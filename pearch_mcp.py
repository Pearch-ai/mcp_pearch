from fastmcp import FastMCP
import os
import urllib.request
import urllib.error
import json
from typing import Any

_DEFAULT_BASE_URL = "https://api.pearch.ai"
_TIMEOUT = 1800

mcp = FastMCP(
    "Pearch_MCP",
    instructions="Natural-language search over people and companies/leads (B2B) via Pearch.AI. Use search_people for people search; use search_company_leads to find companies and leads within them (B2B). By default uses test_mcp_key (masked results). For full results set PEARCH_API_KEY or pass api_key; base URL via PEARCH_API_URL or base_url.",
)


_DEFAULT_API_KEY = "test_mcp_key"


def _request(
    path: str,
    body: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    key = api_key or os.environ.get("PEARCH_API_KEY") or _DEFAULT_API_KEY
    root = (base_url or os.environ.get("PEARCH_API_URL") or _DEFAULT_BASE_URL).rstrip("/")
    url = f"{root}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    headers = {
        "accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.getcode() != 200:
                raise RuntimeError(f"HTTP {resp.getcode()}")
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode()
            detail = json.loads(err_body) if err_body.strip() else {}
        except Exception:
            detail = {"message": str(e)}
        raise RuntimeError(f"Pearch API error {e.code}: {detail}") from e


@mcp.tool()
def search_people(
    query: str,
    search_type: str = "fast",
    limit: int = 5,
    insights: bool = True,
    profile_scoring: bool = True,
    reveal_emails: bool = False,
    reveal_phones: bool = False,
    thread_id: str | None = None,
    offset: int = 0,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Search for people and professional profiles using natural language.

    Pass a natural-language query (e.g. "software engineers in California with 5+ years Python").
    search_type: "fast" (1 credit/candidate) or "pro" (5 credits/candidate, higher quality).
    Optionally pass thread_id from a previous response for follow-up. Returns thread_id, search_results, credits_remaining, total_estimate, status.
    """
    body: dict[str, Any] = {
        "query": query,
        "type": search_type,
        "limit": min(max(limit, 1), 1000),
        "insights": insights,
        "profile_scoring": profile_scoring,
        "reveal_emails": reveal_emails,
        "reveal_phones": reveal_phones,
        "offset": offset,
    }
    if thread_id:
        body["thread_id"] = thread_id
    return _request("v2/search", body, api_key=api_key, base_url=base_url)


@mcp.tool()
def search_company_leads(
    company_query: str,
    lead_query: str | None = None,
    limit: int = 5,
    leads_limit: int = 3,
    reveal_emails: bool = False,
    reveal_phones: bool = False,
    outreach_message_instruction: str | None = None,
    thread_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Find companies and leads (contacts) within those companies. For B2B sales or headhunting.

    company_query: natural-language description of companies (e.g. "AI startups in San Francisco with 50-200 employees").
    lead_query: optional, who to find at those companies (e.g. "CTOs and engineering managers"). Do not put company criteria here.
    limit: max companies to return. leads_limit: leads per company.
    Optionally pass outreach_message_instruction to generate personalized outreach text per lead.
    Returns thread_id, search_results (companies with leads), query, duration.
    """
    body: dict[str, Any] = {
        "company_query": company_query,
        "limit": min(max(limit, 1), 1000),
        "leads_limit": min(max(leads_limit, 1), 10),
        "reveal_emails": reveal_emails,
        "reveal_phones": reveal_phones,
    }
    if lead_query:
        body["lead_query"] = lead_query
    if outreach_message_instruction:
        body["outreach_message_instruction"] = outreach_message_instruction
    if thread_id:
        body["thread_id"] = thread_id
    return _request("v2/search_company_leads", body, api_key=api_key, base_url=base_url)


app = mcp.http_app()

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Pearch MCP server")
    p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--path", default="/mcp")
    args = p.parse_args()
    if args.transport == "http":
        mcp.run(
            transport="http",
            host=args.host,
            port=args.port,
            path=args.path.rstrip("/") or "/mcp",
        )
    else:
        mcp.run()
