from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.event_store import EventStore
from fastmcp.server.dependencies import get_access_token
import os
import urllib.request
import urllib.error
import json
from typing import Any

from starlette.responses import JSONResponse

_DEFAULT_BASE_URL = "https://api.pearch.ai"
_TIMEOUT = 1800
_AUTH_TIMEOUT = 30

_DEFAULT_API_KEY = "test_mcp_key"


class PearchApiKeyVerifier(TokenVerifier):
    def __init__(self, base_url: str | None = None):
        super().__init__()
        self._base_url = (base_url or os.environ.get("PEARCH_API_URL") or _DEFAULT_BASE_URL).rstrip("/")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not token:
            return None
        if token == _DEFAULT_API_KEY:
            return AccessToken(
                token=token,
                client_id="test_mcp",
                scopes=[],
                claims={"api_key": token},
            )
        req = urllib.request.Request(
            f"{self._base_url}/v1/user",
            headers={
                "Authorization": f"Bearer {token}",
                "accept": "application/json",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=_AUTH_TIMEOUT) as resp:
                if resp.getcode() == 200:
                    return AccessToken(
                        token=token,
                        client_id="pearch-api",
                        scopes=[],
                        claims={"api_key": token},
                    )
        except urllib.error.HTTPError:
            return None
        except urllib.error.URLError:
            return None
        return None


def _build_auth() -> PearchApiKeyVerifier | None:
    if os.environ.get("MCP_DISABLE_AUTH") == "1":
        return None
    return PearchApiKeyVerifier()


def _resolve_api_key(api_key: str | None) -> str:
    if api_key:
        return api_key
    access = get_access_token()
    if access and access.token:
        return access.token
    return os.environ.get("PEARCH_API_KEY") or _DEFAULT_API_KEY


mcp = FastMCP(
    "Pearch_MCP",
    instructions="Natural-language search over people and companies/leads (B2B) via Pearch.AI. Use search_people for people search; use search_company_leads to find companies and leads within them (B2B). Authenticate with the same Pearch API key as api.pearch.ai (Authorization: Bearer). Use test_mcp_key for masked sample results.",
    auth=_build_auth(),
)


def _request(
    path: str,
    body: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    key = _resolve_api_key(api_key)
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


@mcp.custom_route("/health", methods=["GET"])
@mcp.custom_route("/healthcheck", methods=["GET"])
async def health_check(request):
    return JSONResponse({"status": "healthy", "service": "pearch-mcp"})


_event_store = EventStore()
app = mcp.http_app(event_store=_event_store, retry_interval=2000)

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
