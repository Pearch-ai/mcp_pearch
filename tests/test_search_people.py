import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from queue import Queue

from fastmcp import Client

import pearch_mcp


REQUIREMENTS = [
    {"search_requirement": "Software engineer with Python experience", "must_have": True},
    {"search_requirement": "Experience at a fintech company", "must_have": False},
]
RESPONSE = {
    "thread_id": "b5bc831d-b27f-4ee7-b8a8-dbc320d386e1",
    "search_results": [],
    "total_estimate": 0,
    "credits_used": 0,
    "credits_remaining": 100,
    "status": "Done",
}


class SearchPeopleTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.requests = Queue()

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                cls.requests.put({
                    "path": self.path,
                    "body": body,
                    "authorization": self.headers.get("Authorization"),
                    "content_type": self.headers.get("Content-Type"),
                })
                response = json.dumps(RESPONSE).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)

            def log_message(self, format, *args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join()

    async def asyncSetUp(self):
        self.assertTrue(self.requests.empty())
        self.client = Client(pearch_mcp.mcp)
        await self.client.__aenter__()

    async def asyncTearDown(self):
        await self.client.__aexit__(None, None, None)

    async def call_search(self, **arguments):
        arguments = {
            "base_url": self.base_url,
            "api_key": "contract-test-key",
            **arguments,
        }
        result = await self.client.call_tool("search_people", arguments)
        self.assertEqual(result.data, RESPONSE)
        request = self.requests.get_nowait()
        self.assertEqual(request["path"], "/v2/search")
        self.assertEqual(request["authorization"], f"Bearer {arguments['api_key']}")
        self.assertEqual(request["content_type"], "application/json")
        self.assertTrue(self.requests.empty())
        return request["body"]

    async def test_schema_exposes_optional_typed_requirements(self):
        tool = next(tool for tool in await self.client.list_tools() if tool.name == "search_people")
        schema = tool.inputSchema
        self.assertEqual(schema.get("required", []), [])
        requirements = schema["properties"]["search_requirements"]
        self.assertIsNone(requirements["default"])
        array = next(option for option in requirements["anyOf"] if option["type"] == "array")
        item = schema["$defs"][array["items"]["$ref"].rsplit("/", 1)[1]]
        self.assertEqual(item["required"], ["search_requirement"])
        self.assertEqual(set(item["properties"]), {"search_requirement", "must_have"})
        self.assertEqual(item["properties"]["search_requirement"]["type"], "string")
        self.assertEqual(item["properties"]["must_have"]["type"], "boolean")
        self.assertIs(item["properties"]["must_have"]["default"], False)

    async def test_legacy_query_payload_is_unchanged(self):
        expected = {
            "query": "Python engineers",
            "type": "fast",
            "limit": 5,
            "offset": 0,
            "short_response": True,
        }
        self.assertEqual(await self.call_search(query="Python engineers"), expected)
        self.assertEqual(
            await self.call_search(query="Python engineers", search_requirements=None),
            expected,
        )

    async def test_legacy_empty_input_is_still_forwarded(self):
        self.assertEqual(await self.call_search(), {
            "type": "fast", "limit": 5, "offset": 0, "short_response": True,
        })

    async def test_requirements_work_without_query(self):
        body = await self.call_search(search_requirements=REQUIREMENTS)
        self.assertEqual(body, {
            "search_requirements": REQUIREMENTS,
            "type": "fast",
            "limit": 5,
            "offset": 0,
            "short_response": True,
        })

    async def test_requirement_defaults_and_whitespace_match_api(self):
        body = await self.call_search(search_requirements=[{
            "search_requirement": "  Engineer based in São Paulo  ",
        }])
        self.assertEqual(body["search_requirements"], [{
            "search_requirement": "Engineer based in São Paulo",
            "must_have": False,
        }])

    async def test_both_inputs_are_forwarded_for_api_precedence(self):
        body = await self.call_search(query="Original query", search_requirements=REQUIREMENTS)
        self.assertEqual(body["query"], "Original query")
        self.assertEqual(body["search_requirements"], REQUIREMENTS)

    async def test_search_types_accept_either_input(self):
        for search_type in ("fast", "pro", "superfast"):
            with self.subTest(search_type=search_type):
                query_body = await self.call_search(query="Python engineers", search_type=search_type)
                requirements_body = await self.call_search(
                    search_requirements=REQUIREMENTS, search_type=search_type,
                )
                self.assertEqual(query_body.pop("query"), "Python engineers")
                self.assertEqual(requirements_body.pop("search_requirements"), REQUIREMENTS)
                self.assertEqual(query_body["type"], search_type)
                self.assertEqual(requirements_body, query_body)

    async def test_all_search_options_are_forwarded_with_either_input(self):
        options = {
            "search_type": "pro",
            "limit": 10,
            "offset": 2,
            "insights": True,
            "insights_items": ["overall_summary", "short_quotes"],
            "profile_scoring": True,
            "high_freshness": True,
            "reveal_emails": True,
            "reveal_phones": True,
            "filter_out_no_emails": True,
            "filter_out_no_phones": False,
            "filter_out_no_phones_or_emails": False,
            "strict_filters": True,
            "fill_with_low_confidence_results": True,
            "time_budget": 30,
            "short_response": False,
            "omit_fields": ["education"],
            "docid_blacklist": ["already-seen-profile"],
            "docid_whitelist": ["selected-profile"],
            "free": False,
        }
        expected = {key: value for key, value in options.items() if key != "search_type"}
        expected["type"] = "pro"
        for criteria in ({"query": "Python engineers"}, {"search_requirements": REQUIREMENTS}):
            with self.subTest(criteria=criteria):
                self.assertEqual(await self.call_search(**criteria, **options), {**expected, **criteria})

    async def test_pagination_and_thread_followups_keep_existing_behavior(self):
        pagination = {"thread_id": RESPONSE["thread_id"], "limit": 10, "offset": 5}
        for criteria in ({}, {"query": "Updated query"}, {"search_requirements": REQUIREMENTS}):
            with self.subTest(criteria=criteria):
                body = await self.call_search(**pagination, **criteria)
                self.assertEqual(body, {**pagination, **criteria, "short_response": True})

    async def test_demo_mode_and_explicit_free_option_work_with_either_input(self):
        for criteria in ({"query": "Python engineers"}, {"search_requirements": REQUIREMENTS}):
            for free_options in ({}, {"free": True}, {"free": False}):
                with self.subTest(criteria=criteria, free_options=free_options):
                    body = await self.call_search(
                        **criteria, **free_options, api_key="test_mcp_key",
                    )
                    self.assertIs(body["free"], free_options.get("free", True))
                    for key, value in criteria.items():
                        self.assertEqual(body[key], value)

    async def test_pagination_bounds_work_with_either_input(self):
        for criteria in ({"query": "Python engineers"}, {"search_requirements": REQUIREMENTS}):
            for limit, offset, expected_limit, expected_offset in ((0, -1, 1, 0), (10, 998, 2, 998)):
                with self.subTest(criteria=criteria, limit=limit, offset=offset):
                    body = await self.call_search(**criteria, limit=limit, offset=offset)
                    self.assertEqual((body["limit"], body["offset"]), (expected_limit, expected_offset))

    async def test_invalid_requirements_are_rejected_before_http(self):
        invalid_inputs = (
            [],
            ["Python experience"],
            [{}],
            [{"search_requirement": ""}],
            [{"search_requirement": " \t "}],
            [{"search_requirement": None}],
            [{"search_requirement": 42}],
            [{"search_requirement": "Python", "must_have": "not-a-boolean"}],
            [{"search_requirement": "Python", "sql_filter": "unexpected"}],
        )
        for requirements in invalid_inputs:
            with self.subTest(requirements=requirements):
                result = await self.client.call_tool("search_people", {
                    "search_requirements": requirements,
                    "api_key": "contract-test-key",
                    "base_url": self.base_url,
                }, raise_on_error=False)
                self.assertTrue(result.is_error)
                self.assertTrue(self.requests.empty())


if __name__ == "__main__":
    unittest.main()
