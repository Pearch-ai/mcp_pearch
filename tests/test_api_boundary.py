"""Exercise the public MCP boundary against real, local HTTP upstreams."""

import asyncio
import hashlib
import hmac
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlsplit

import httpx
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import pearch_mcp


@contextmanager
def serve(reply=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            request = {"method": self.command, "path": self.path,
                       "headers": self.headers, "body": body}
            requests.append(request)
            status, headers, payload = reply(request) if reply else (
                200, {}, {"user": {"email": "test@example.com"}, "api_key": "mapped-key"}
            )
            data = json.dumps(payload).encode()
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = handle_request

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


TOOLS = {
    "search_people": {"query": "engineers", "wait_seconds": 0},
    "get_search_status": {"thread_id": "existing-thread", "wait_seconds": 0},
    "list_searches": {},
    "search_company_leads": {"company_query": "startups"},
    "get_profile": {"docid": "test-person"},
    "get_user_info": {},
}


async def test_tools_do_not_advertise_connection_secrets_or_destinations():
    async with Client(pearch_mcp.mcp) as client:
        tools = await client.list_tools()
    assert {tool.name for tool in tools} == set(TOOLS)
    for tool in tools:
        assert {"api_key", "base_url"}.isdisjoint(tool.inputSchema["properties"]), tool.name


async def test_tools_do_not_advertise_webhook_destinations():
    async with Client(pearch_mcp.mcp) as client:
        tools = await client.list_tools()
    for tool in tools:
        assert "webhook_url" not in tool.inputSchema["properties"], tool.name


@pytest.mark.parametrize("value", [None, "", "https://hooks.example.com/private-receiver-secret"])
@pytest.mark.parametrize("followup", [False, True])
async def test_retired_webhook_argument_fails_before_search(monkeypatch, value, followup):
    with serve() as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url)
        monkeypatch.setenv("PEARCH_API_KEY", "local-account")
        arguments = {"thread_id": "existing-thread"} if followup else {"query": "engineers"}
        async with Client(pearch_mcp.mcp) as client:
            with pytest.raises(ToolError, match="webhook_url is no longer supported in MCP") as error:
                await client.call_tool("search_people", {**arguments, "webhook_url": value})
        assert "get_search_status" in str(error.value)
        assert "thread_id" in str(error.value)
        assert "private-receiver-secret" not in str(error.value)
        assert requests == []


async def test_http_client_can_retry_without_the_retired_webhook(monkeypatch):
    with serve() as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url)
        monkeypatch.setattr(pearch_mcp.mcp, "auth", pearch_mcp.PearchApiKeyVerifier())
        app = pearch_mcp.mcp.http_app(stateless_http=True, json_response=True)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test") as client:
                rejected = await rpc(client, "tools/call", {"name": "search_people", "arguments": {
                    "query": "engineers", "webhook_url": "https://hooks.example.com/private-receiver-secret",
                }}, "account-a")
                assert rejected.status_code == 200
                assert rejected.json()["result"]["isError"] is True
                assert "get_search_status" in rejected.text
                assert "private-receiver-secret" not in rejected.text
                assert [r["path"] for r in requests] == ["/v1/user"]
                accepted = await rpc(client, "tools/call", {"name": "search_people", "arguments": {
                    "query": "engineers", "wait_seconds": 0,
                }}, "account-a")
                assert accepted.status_code == 200
                assert not accepted.json()["result"].get("isError")
        searches = [r for r in requests if r["method"] == "POST"]
        assert len(searches) == 1
        body = json.loads(searches[0]["body"])
        assert body["async"] is True and "webhook_url" not in body


@pytest.mark.parametrize("tool", TOOLS)
async def test_each_tool_uses_the_server_url_and_local_credential(monkeypatch, tool):
    def reply(request):
        return 200, {}, {"thread_id": "existing-thread", "search_results": [],
                         "api_call_history": [], "total_count": 0, "status": "Done"}

    with serve(reply) as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url + "/")
        monkeypatch.setenv("PEARCH_API_KEY", "local-account")
        async with Client(pearch_mcp.mcp) as client:
            result = await client.call_tool(tool, TOOLS[tool])
            assert not result.is_error
        assert requests
        assert all(r["headers"]["Authorization"] == "Bearer local-account" for r in requests)
        assert all(r["headers"]["X-Pearch-Source"] == "mcp" for r in requests)


async def test_local_demo_searches_keep_masking_and_cached_company_replays(monkeypatch):
    with serve() as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url)
        monkeypatch.delenv("PEARCH_API_KEY", raising=False)
        async with Client(pearch_mcp.mcp) as client:
            await client.call_tool("search_people", {"query": "engineers"})
            await client.call_tool("search_company_leads", {"company_query": "startups"})
            await client.call_tool("search_company_leads", {"thread_id": "existing-thread"})
        assert all(r["headers"]["Authorization"] == "Bearer test_mcp_key" for r in requests)
        people, companies, replay = [json.loads(r["body"]) for r in requests]
        assert people["free"] is True and companies["free"] is True
        assert "free" not in replay


@pytest.mark.parametrize("tool", TOOLS)
@pytest.mark.parametrize("argument", ["api_key", "base_url"])
@pytest.mark.parametrize("value", [None, "", "legacy-secret"])
async def test_old_arguments_fail_before_any_upstream_request(monkeypatch, tool, argument, value):
    with serve() as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url)
        monkeypatch.setenv("PEARCH_API_KEY", "local-key")
        async with Client(pearch_mcp.mcp) as client:
            with pytest.raises(ToolError, match="connection settings") as error:
                await client.call_tool(tool, {**TOOLS[tool], argument: value})
        assert "legacy-secret" not in str(error.value)
        assert requests == []


@pytest.mark.parametrize("status", [300, 301, 302, 303, 304, 305, 307, 308])
@pytest.mark.parametrize("operation", ["get_user_info", "search_people", "verify", "map_email"])
async def test_api_redirects_never_forward_credentials(monkeypatch, status, operation):
    with serve() as (destination, leaked):
        def redirect(request):
            return status, {"Location": destination + "/capture"}, {}

        with serve(redirect) as (origin, requests):
            monkeypatch.setenv("PEARCH_API_URL", origin)
            monkeypatch.setenv("PEARCH_API_KEY", "synthetic-private-key")
            monkeypatch.setenv("PEARCH_MCP_INTERNAL_TOKEN", "synthetic-internal-secret")
            if operation == "verify":
                assert await pearch_mcp.PearchApiKeyVerifier().verify_token("synthetic-private-key") is None
            elif operation == "map_email":
                assert await asyncio.to_thread(pearch_mcp._fetch_api_key_for_email, "test@example.com") is None
            else:
                async with Client(pearch_mcp.mcp) as client:
                    with pytest.raises(ToolError, match="redirects are disabled"):
                        await client.call_tool(operation, TOOLS[operation])
            assert len(requests) == 1
            assert leaked == []


async def rpc(client, method, params, token=None):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return await client.post("/mcp", headers=headers, json={
        "jsonrpc": "2.0", "id": 1, "method": method, "params": params,
    })


async def test_http_bearers_remain_isolated_and_requests_are_signed(monkeypatch):
    def reply(request):
        bearer = request["headers"]["Authorization"]
        if bearer not in ("Bearer account-a", "Bearer account-b"):
            return 403, {}, {"error": "invalid token"}
        return 200, {}, {"user": {"email": bearer.removeprefix("Bearer ") + "@example.com"}}

    with serve(reply) as (url, requests):
        monkeypatch.setenv("PEARCH_API_URL", url)
        monkeypatch.setenv("PEARCH_API_KEY", "must-not-use-local-fallback")
        monkeypatch.setenv("PEARCH_MCP_INTERNAL_TOKEN", "signing-secret")
        monkeypatch.setattr(pearch_mcp.mcp, "auth", pearch_mcp.PearchApiKeyVerifier())
        app = pearch_mcp.mcp.http_app(stateless_http=True, json_response=True)
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp.test") as client:
                results = await asyncio.gather(*[
                    rpc(client, "tools/call", {"name": "get_user_info", "arguments": {}}, token)
                    for token in ("account-a", "account-b")
                ])
                for account, response in zip(("account-a", "account-b"), results):
                    assert response.status_code == 200, response.text
                    assert response.json()["result"]["structuredContent"]["user"]["email"] == account + "@example.com"
                for token in (None, "invalid-key"):
                    response = await rpc(client, "tools/call", {"name": "get_user_info", "arguments": {}}, token)
                    assert response.status_code == 401

        tool_calls = [r for r in requests if r["headers"].get("X-Pearch-Source") == "mcp"]
        assert len(tool_calls) == 2
        for request in tool_calls:
            version, timestamp, signature = request["headers"]["X-Pearch-Source-Signature"].split(":")
            key = request["headers"]["Authorization"].removeprefix("Bearer ")
            parsed = urlsplit(request["path"])
            target = unquote(parsed.path) + ("?" + parsed.query if parsed.query else "")
            payload = json.dumps([
                "pearch-mcp-source-v1", timestamp, request["method"], target,
                hashlib.sha256(key.encode()).hexdigest(), hashlib.sha256(request["body"]).hexdigest(),
            ], separators=(",", ":")).encode()
            assert version == "v1"
            assert signature == hmac.new(b"signing-secret", payload, hashlib.sha256).hexdigest()
