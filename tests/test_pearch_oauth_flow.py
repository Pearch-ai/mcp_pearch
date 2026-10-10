import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp import FastMCP
from key_value.aio.stores.memory import MemoryStore

import pearch_mcp

BASE = "https://mcp.example.test"
SUPABASE = "https://project.supabase.co"
CLIENT_REDIRECT = "http://localhost:9999/cb"
UPSTREAM_ACCESS = "supabase-access-token-0123456789"
UPSTREAM_REFRESH = "supabase-refresh-token"


def pkce():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def query_of(location):
    return {key: values[0] for key, values in parse_qs(urlparse(location).query).items()}


@pytest.fixture
def proxy(monkeypatch):
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_URL", SUPABASE)
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_CLIENT_ID", "pearch-mcp-app")
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_CLIENT_SECRET", "pearch-mcp-secret")
    monkeypatch.setattr(pearch_mcp, "_BASE_URL", BASE)
    monkeypatch.setattr(pearch_mcp, "_oauth_client_storage", lambda secret: MemoryStore())
    return pearch_mcp._build_pearch_oauth_auth()


@pytest.fixture
def pearch_api(monkeypatch):
    calls = []

    def fetch_user(self, token):
        calls.append(token)
        return {"user": {"email": "person@example.com"}} if token == UPSTREAM_ACCESS else None

    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", fetch_user)
    return calls


@pytest.fixture
async def mcp_client(proxy):
    app = FastMCP("flow-test", auth=proxy).http_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE) as client:
        yield client


async def sign_in(mcp_client, supabase, client_scopes="email profile"):
    registration = await mcp_client.post(
        "/register",
        json={
            "client_name": "Claude",
            "redirect_uris": [CLIENT_REDIRECT],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registration.status_code == 201, registration.text
    client_id = registration.json()["client_id"]
    verifier, challenge = pkce()

    authorize = await mcp_client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": CLIENT_REDIRECT,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "client-state",
            "scope": client_scopes,
        },
    )
    assert authorize.status_code == 302, authorize.text
    consent_url = authorize.headers["location"]
    assert "error" not in query_of(consent_url), consent_url
    assert urlparse(consent_url).path == "/consent"

    page = await mcp_client.get(consent_url)
    assert page.status_code == 200
    assert "Claude" in page.text and CLIENT_REDIRECT in page.text
    txn_id = re.search(r'name="txn_id" value="([^"]+)"', page.text).group(1)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', page.text).group(1)

    approved = await mcp_client.post("/consent", data={"action": "approve", "txn_id": txn_id, "csrf_token": csrf})
    assert approved.status_code in (302, 303), approved.text
    upstream_authorize = approved.headers["location"]

    supabase.post(f"{SUPABASE}/auth/v1/oauth/token").respond(
        json={
            "access_token": UPSTREAM_ACCESS,
            "refresh_token": UPSTREAM_REFRESH,
            "token_type": "bearer",
            "expires_in": 604800,
        }
    )
    upstream_state = query_of(upstream_authorize)["state"]
    callback = await mcp_client.get("/auth/callback", params={"code": "upstream-code", "state": upstream_state})
    assert callback.status_code == 302, callback.text
    returned = query_of(callback.headers["location"])
    assert callback.headers["location"].startswith(CLIENT_REDIRECT)
    assert returned["state"] == "client-state"

    token = await mcp_client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": returned["code"],
            "redirect_uri": CLIENT_REDIRECT,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert token.status_code == 200, token.text
    return upstream_authorize, token, client_id


@respx.mock(assert_all_called=False)
async def test_the_user_is_sent_to_supabase_with_pinned_scopes(mcp_client, pearch_api, respx_mock):
    upstream_authorize, _, _ = await sign_in(mcp_client, respx_mock)
    parsed = urlparse(upstream_authorize)
    query = query_of(upstream_authorize)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == f"{SUPABASE}/auth/v1/oauth/authorize"
    assert query["client_id"] == "pearch-mcp-app"
    assert query["redirect_uri"] == f"{BASE}/auth/callback"
    assert query["scope"] == "email profile offline_access"
    assert "openid" not in query["scope"].split()
    assert query["code_challenge_method"] == "S256"


@respx.mock(assert_all_called=False)
async def test_the_client_never_receives_the_supabase_tokens(mcp_client, pearch_api, respx_mock):
    _, token, _ = await sign_in(mcp_client, respx_mock)
    body = token.json()
    assert UPSTREAM_ACCESS not in token.text
    assert UPSTREAM_REFRESH not in token.text
    assert body["access_token"].count(".") == 2
    assert body["access_token"] != UPSTREAM_ACCESS
    assert body.get("refresh_token") and body["refresh_token"] != UPSTREAM_REFRESH


@respx.mock(assert_all_called=False)
async def test_the_proxy_authenticates_to_supabase_as_the_registered_app(mcp_client, pearch_api, respx_mock):
    await sign_in(mcp_client, respx_mock)
    exchange = respx_mock.calls.last.request if respx_mock.calls else None
    token_calls = [call.request for call in respx_mock.calls if str(call.request.url).endswith("/auth/v1/oauth/token")]
    assert token_calls, "the proxy never exchanged the upstream code"
    request = token_calls[0]
    expected = "Basic " + base64.b64encode(b"pearch-mcp-app:pearch-mcp-secret").decode()
    assert request.headers["authorization"] == expected
    form = parse_qs(request.content.decode())
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["upstream-code"]
    assert form["redirect_uri"] == [f"{BASE}/auth/callback"]
    assert "code_verifier" in form


@respx.mock(assert_all_called=False)
async def test_a_client_token_is_swapped_for_the_supabase_token_that_goes_to_the_api(mcp_client, proxy, pearch_api, respx_mock):
    _, token, _ = await sign_in(mcp_client, respx_mock)
    client_token = token.json()["access_token"]

    access = await proxy.load_access_token(client_token)

    assert access is not None
    assert access.claims["api_key"] == UPSTREAM_ACCESS
    assert access.claims["email"] == "person@example.com"
    assert access.scopes == ["email", "profile", "offline_access"]
    assert pearch_api == [UPSTREAM_ACCESS]


@respx.mock(assert_all_called=False)
async def test_a_forged_client_token_is_rejected_without_calling_the_api(mcp_client, proxy, pearch_api, respx_mock):
    await sign_in(mcp_client, respx_mock)
    header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps({"jti": "nope"}).encode()).rstrip(b"=").decode()
    assert await proxy.load_access_token(f"{header}.{body}.forged") is None
    assert pearch_api == []


@respx.mock(assert_all_called=False)
async def test_refresh_follows_the_rotation_of_the_supabase_refresh_token(mcp_client, pearch_api, respx_mock):
    _, token, client_id = await sign_in(mcp_client, respx_mock)
    rotations = [("supabase-access-2", "supabase-refresh-2"), ("supabase-access-3", "supabase-refresh-3")]
    respx_mock.clear()
    route = respx_mock.post(f"{SUPABASE}/auth/v1/oauth/token")
    route.side_effect = [
        httpx.Response(200, json={"access_token": access, "refresh_token": refresh, "token_type": "bearer", "expires_in": 604800})
        for access, refresh in rotations
    ]
    client_refresh = token.json()["refresh_token"]

    for sent_upstream_refresh, (new_access, _) in zip([UPSTREAM_REFRESH, "supabase-refresh-2"], rotations):
        response = await mcp_client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": client_refresh, "client_id": client_id},
        )
        assert response.status_code == 200, response.text
        assert new_access not in response.text
        client_refresh = response.json()["refresh_token"]
        sent = parse_qs(route.calls.last.request.content.decode())
        assert sent["grant_type"] == ["refresh_token"]
        assert sent["refresh_token"] == [sent_upstream_refresh]
