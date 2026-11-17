import asyncio
import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import pearch_mcp

KEY = "pearch-test-key"


class FakePearchApi:
    """A Pearch API stand-in with the documented async contract of /v2/search."""

    def __init__(self, polls_until_done=1, submit_delay=0.0):
        self.polls_until_done = polls_until_done
        self.submit_delay = submit_delay
        self.requests = []
        self.threads = {}
        self.history = []
        self.lock = threading.Lock()

    def result(self, thread_id, limit, offset, credits_used=0):
        return {
            "thread_id": thread_id,
            "status": "Done",
            "search_results": [{"docid": f"person-{i}"} for i in range(offset, offset + limit)],
            "credits_used": credits_used,
            "credits_used_total": self.threads[thread_id]["cost"],
        }

    def search(self, body):
        if self.submit_delay and "thread_id" not in body:
            time.sleep(self.submit_delay)
        with self.lock:
            thread_id = body.get("thread_id")
            if thread_id is None:
                thread_id, task_id = str(uuid.uuid4()), str(uuid.uuid4())
                self.threads[thread_id] = {
                    "task_id": task_id,
                    "polls_left": self.polls_until_done,
                    "limit": body.get("limit", 5),
                    "offset": body.get("offset", 0),
                    "cost": 2 * body.get("limit", 5),
                }
                if body.get("async"):
                    return 202, {"task_id": task_id, "thread_id": thread_id, "status": "pending"}
                self.threads[thread_id]["polls_left"] = 0
                return 200, self.result(
                    thread_id, body.get("limit", 5), body.get("offset", 0), self.threads[thread_id]["cost"]
                )
            thread = self.threads.get(thread_id)
            if thread is None:
                return 409, {"error": f"Thread has no reusable search state: {thread_id}"}
            if thread["polls_left"] > 0:
                if set(body) <= {"thread_id", "short_response"}:
                    thread["polls_left"] -= 1
                return 202, {"task_id": thread["task_id"], "thread_id": thread_id, "status": "running"}
            return 200, self.result(
                thread_id,
                body.get("limit", thread["limit"]),
                body.get("offset", thread["offset"]),
            )

    def finish(self, thread_id):
        with self.lock:
            self.threads[thread_id]["polls_left"] = 0

    def search_calls(self):
        return [body for method, path, body in self.requests if path == "/v2/search"]


@pytest.fixture
def api():
    fake = FakePearchApi()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or b"{}")
            fake.requests.append(("POST", self.path, body))
            assert self.headers["Authorization"] == f"Bearer {KEY}"
            self.reply(*fake.search(body))

        def do_GET(self):
            url = urlparse(self.path)
            query = {k: v[0] for k, v in parse_qs(url.query).items()}
            fake.requests.append(("GET", url.path, query))
            if url.path == "/v1/user":
                self.reply(200, {"user": {"email": "person@example.com"}})
            elif url.path == "/v1/api_call_history":
                offset = int(query.get("offset", 0))
                rows = fake.history[offset:offset + int(query.get("limit", 10))]
                self.reply(200, {"api_call_history": rows, "total_count": len(fake.history)})
            else:
                self.reply(404, {"error": "not found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fake.base_url = f"http://127.0.0.1:{server.server_port}"
    yield fake
    server.shutdown()


async def call(tool, api, **arguments):
    async with Client(pearch_mcp.mcp) as client:
        result = await client.call_tool(tool, {"api_key": KEY, "base_url": api.base_url, **arguments})
        return result.structured_content


async def test_new_search_runs_in_background_and_returns_results_when_done(api):
    api.polls_until_done = 2

    result = await call("search_people", api, query="python engineers in Berlin", limit=3)

    assert result["status"] == "Done"
    assert [r["docid"] for r in result["search_results"]] == ["person-0", "person-1", "person-2"]
    assert result["credits_used"] == 6
    submit, *polls = api.search_calls()
    assert submit["async"] is True and submit["type"] == "fast" and submit["limit"] == 3
    assert polls == [{"thread_id": result["thread_id"], "short_response": True}] * 3


async def test_search_still_running_is_handed_back_with_thread_and_task_ids(api):
    api.polls_until_done = 10**6

    started = time.monotonic()
    running = await call("search_people", api, query="staff ML engineers", search_type="pro", wait_seconds=1)

    assert 0.9 < time.monotonic() - started < 3
    assert running["status"] == "running"
    thread = api.threads[running["thread_id"]]
    assert running["task_id"] == thread["task_id"]
    assert "get_search_status" in running["next_step"]

    still = await call("get_search_status", api, thread_id=running["thread_id"], wait_seconds=0)
    assert still["status"] == "running" and still["thread_id"] == running["thread_id"]

    api.finish(running["thread_id"])
    done = await call("get_search_status", api, thread_id=running["thread_id"], wait_seconds=5)
    assert done["status"] == "Done" and len(done["search_results"]) == 5
    assert done["credits_used"] == 10


async def test_wait_seconds_zero_submits_and_returns_at_once(api):
    pending = await call("search_people", api, query="CFOs in Austin", wait_seconds=0, webhook_url="https://hooks.example.com/x")

    assert pending["status"] == "pending"
    assert pending["thread_id"] in api.threads
    assert pending["task_id"] == api.threads[pending["thread_id"]]["task_id"]
    (submit,) = api.search_calls()
    assert submit["async"] is True and submit["webhook_url"] == "https://hooks.example.com/x"


async def test_thread_pages_stay_synchronous(api):
    api.polls_until_done = 0
    first = await call("search_people", api, query="data engineers", limit=2)
    api.requests.clear()

    page = await call("search_people", api, thread_id=first["thread_id"], limit=2, offset=2)

    assert [r["docid"] for r in page["search_results"]] == ["person-2", "person-3"]
    assert page["credits_used"] == 0 and page["credits_used_total"] == 4
    (request,) = api.search_calls()
    assert "async" not in request and request["offset"] == 2


async def test_page_of_a_thread_still_running_waits_then_returns_that_page(api):
    api.polls_until_done = 10**6
    running = await call("search_people", api, query="designers", wait_seconds=0)
    api.requests.clear()
    api.threads[running["thread_id"]]["polls_left"] = 1

    page = await call("search_people", api, thread_id=running["thread_id"], limit=2, offset=4)

    assert [r["docid"] for r in page["search_results"]] == ["person-4", "person-5"]
    asked, *polls, again = api.search_calls()
    assert asked == again and asked["offset"] == 4
    assert polls == [{"thread_id": running["thread_id"], "short_response": True}] * 2


async def test_webhook_url_is_refused_on_thread_follow_ups(api):
    with pytest.raises(ToolError, match="webhook_url applies to new searches only"):
        await call("search_people", api, thread_id=str(uuid.uuid4()), webhook_url="https://hooks.example.com/x")
    assert api.requests == []


async def test_failed_search_surfaces_the_api_error(api):
    with pytest.raises(ToolError, match="409"):
        await call("get_search_status", api, thread_id=str(uuid.uuid4()))


async def test_list_searches_returns_new_searches_with_their_thread_ids(api):
    thread_a, thread_b = str(uuid.uuid4()), str(uuid.uuid4())
    api.history = [
        {"uuid": "t-3", "thread_id": thread_b, "path": "/v2/search", "parameters": {"thread_id": thread_b, "short_response": True},
         "items_count": 5, "credits_used": 0, "task_status": "completed", "response_status": 200, "created_at": "2026-11-17T10:03:00"},
        {"uuid": "t-2", "thread_id": thread_b, "path": "/v2/search", "api_key": "secret-key",
         "parameters": {"search_requirements": [{"search_requirement": "CTO", "must_have": True}, {"search_requirement": "fintech"}], "type": "pro", "limit": 5},
         "items_count": 5, "credits_used": 25, "task_status": "completed", "response_status": 200, "response_time": 151.2, "created_at": "2026-11-17T10:00:00"},
        {"uuid": "t-1", "thread_id": thread_a, "path": "/v2/search_company_leads",
         "parameters": {"company_query": "AI startups in Paris", "lead_query": "founders", "limit": 3},
         "items_count": 3, "credits_used": 21, "task_status": "completed", "response_status": 200, "created_at": "2026-11-16T09:00:00"},
    ]

    listed = await call("list_searches", api, limit=1)

    assert listed == {
        "searches": [{
            "thread_id": thread_b, "task_id": "t-2", "kind": "people", "query": "CTO\nfintech", "search_type": "pro",
            "limit": 5, "created_at": "2026-11-17T10:00:00", "status": "completed", "http_status": 200,
            "results": 5, "credits_used": 25, "duration_seconds": 151.2,
        }],
        "next_offset": 2,
    }
    method, path, query = api.requests[-1]
    assert (method, path) == ("GET", "/v1/api_call_history")
    assert query == {"limit": "100", "offset": "0", "paths": "/v2/search,/v2/search/submit,/v2/search_company_leads"}

    rest = await call("list_searches", api, offset=listed["next_offset"], include_organization=True)

    assert rest["next_offset"] is None
    assert rest["searches"][0]["kind"] == "company_leads"
    assert rest["searches"][0]["query"] == "AI startups in Paris" and rest["searches"][0]["lead_query"] == "founders"
    assert api.requests[-1][2]["org_history"] == "true"


async def test_a_long_search_does_not_block_other_tool_calls(api):
    api.submit_delay = 2
    api.polls_until_done = 0

    async with Client(pearch_mcp.mcp) as first, Client(pearch_mcp.mcp) as second:
        started = time.monotonic()

        async def account():
            await asyncio.sleep(0.2)
            await second.call_tool("get_user_info", {"api_key": KEY, "base_url": api.base_url})
            return time.monotonic() - started

        search = first.call_tool("search_people", {"query": "slow", "api_key": KEY, "base_url": api.base_url})
        _, account_done_at = await asyncio.gather(search, account())

    assert account_done_at < 1
