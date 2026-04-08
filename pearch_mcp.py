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
    custom_filters: dict[str, Any] | None = None,
    custom_filters_mode: str | None = None,
    strict_filters: bool | None = None,
    docid_blacklist: list[str] | None = None,
    high_freshness: bool = False,
    filter_out_no_emails: bool = False,
    filter_out_no_phones: bool = False,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Search for people and professional profiles using natural language.

    Pass a natural-language query (e.g. "software engineers in California with 5+ years Python").
    search_type: "fast" (1 credit/candidate) or "pro" (5 credits/candidate, higher quality).
    Optionally pass thread_id from a previous response for follow-up.

    custom_filters: structured filters applied on top of the NL query. Searches across ALL experience, not just current role. Example:
      {"companies": ["Mollie", "Adyen"], "locations": ["Netherlands"], "min_total_experience_years": 5}
    Available filter fields:
      - Array (include): locations, languages, titles, industries, companies, universities, keywords, degrees, specialization_categories
      - Array (exclude): not_locations, not_languages, not_titles, not_current_titles, not_industries, not_companies, not_current_experience_companies, not_universities
      - Current-only: current_titles, current_experience_companies
      - Numeric: min/max_linkedin_followers, min/max_total_experience_years, min/max_estimated_age, min/max_current_experience_years
      - Boolean: studied_at_top_universities, has_startup_experience, has_saas_experience, has_b2b_experience, has_b2c_experience
      - Exact: first_name, middle_name, last_name, gender ("male"/"female")
    custom_filters_mode: "exact" (only use passed filters) or "smart" (merge with LLM-generated filters from query). Default: smart.
    strict_filters: enforce exact title matching.
    docid_blacklist: list of profile IDs to exclude from results.
    high_freshness: real-time profile updates (+2 credits/candidate).
    filter_out_no_emails: only return profiles with email addresses (+1 credit/candidate).
    filter_out_no_phones: only return profiles with phone numbers (+1 credit/candidate).

    Returns thread_id, search_results, credits_remaining, total_estimate, status.
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
    if custom_filters:
        body["custom_filters"] = custom_filters
    if custom_filters_mode:
        body["custom_filters_mode"] = custom_filters_mode
    if strict_filters is not None:
        body["strict_filters"] = strict_filters
    if docid_blacklist:
        body["docid_blacklist"] = docid_blacklist
    if high_freshness:
        body["high_freshness"] = high_freshness
    if filter_out_no_emails:
        body["filter_out_no_emails"] = filter_out_no_emails
    if filter_out_no_phones:
        body["filter_out_no_phones"] = filter_out_no_phones
    return _request("v2/search", body, api_key=api_key, base_url=base_url)


@mcp.tool()
def search_company_leads(
    company_query: str,
    lead_query: str | None = None,
    limit: int = 5,
    leads_limit: int = 3,
    reveal_emails: bool = False,
    reveal_phones: bool = False,
    filter_out_no_emails: bool = False,
    filter_out_no_phones: bool = False,
    high_freshness: bool = False,
    select_top_leads: bool = True,
    outreach_message_instruction: str | None = None,
    thread_id: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Find companies and leads (contacts) within those companies. For B2B sales or headhunting.

    company_query: natural-language description of companies (e.g. "AI startups in San Francisco with 50-200 employees").
    lead_query: optional, who to find at those companies (e.g. "CTOs and engineering managers"). Do not put company criteria here.
    limit: max companies to return. leads_limit: leads per company.
    filter_out_no_emails: only return leads with email addresses.
    filter_out_no_phones: only return leads with phone numbers.
    high_freshness: real-time profile updates for leads.
    select_top_leads: AI-select best matching leads per company (default: true).
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
    if filter_out_no_emails:
        body["filter_out_no_emails"] = filter_out_no_emails
    if filter_out_no_phones:
        body["filter_out_no_phones"] = filter_out_no_phones
    if high_freshness:
        body["high_freshness"] = high_freshness
    if not select_top_leads:
        body["select_top_leads"] = select_top_leads
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
