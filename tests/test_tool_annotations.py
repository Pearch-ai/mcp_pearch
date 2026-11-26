"""Client-visible tool metadata must not hide saved jobs, refreshes or charges."""

import pytest
from fastmcp import Client

import pearch_mcp


@pytest.mark.parametrize(
    "name,title,read_only,open_world",
    [
        ("search_people", "Search People", False, True),
        ("search_company_leads", "Search Company Leads", False, True),
        ("get_profile", "Get Person Profile", False, True),
        ("get_search_status", "Get Search Status", True, True),
        ("list_searches", "List Searches", True, False),
        ("get_user_info", "Get Account Info", True, False),
    ],
)
async def test_list_tools_discloses_operation_effects(name, title, read_only, open_world):
    # Exercise tools/list as consumed by clients, not decorator source text.
    async with Client(pearch_mcp.mcp) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
    tool = tools[name]
    assert tool.title == title
    assert tool.annotations.title == title
    assert tool.annotations.readOnlyHint is read_only
    assert tool.annotations.openWorldHint is open_world
    if not read_only:
        # Refresh/enrichment and charges are not guaranteed to be additive or
        # side-effect-free on repetition, even when some thread reads are free.
        assert tool.annotations.idempotentHint is False
        assert tool.annotations.destructiveHint is True
