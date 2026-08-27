"""Pearch.ai MCP server.

Natural-language people/company-leads search over the Pearch API.

Auth modes (PEARCH_MCP_AUTH):
  oauth   — Google OAuth via FastMCP's OAuthProxy: the MCP client does DCR + the
            authorization-code flow against THIS server, which proxies to Google;
            the verified Google email is mapped to the user's Pearch API key
            through an internal Pearch API endpoint. Raw Pearch API keys sent as
            a plain bearer keep working in this mode too (dual auth).
  api_key — Authorization: Bearer <pearch api key>, validated against the Pearch
            API (the historical scheme, default).
  none    — no auth (local dev only; MCP_DISABLE_AUTH=1 is equivalent).
"""

import asyncio
import hashlib
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.auth.oauth_proxy import OAuthProxy
from fastmcp.server.auth.providers.google import GoogleTokenVerifier
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.event_store import EventStore
from starlette.responses import JSONResponse

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("pearch_mcp")

_DEFAULT_BASE_URL = "https://api.pearch.ai"
_TIMEOUT = 1800
_AUTH_TIMEOUT = 30

_DEFAULT_API_KEY = "test_mcp_key"

_AUTH_MODE = os.environ.get("PEARCH_MCP_AUTH", "api_key").lower()
if os.environ.get("MCP_DISABLE_AUTH") == "1":
    _AUTH_MODE = "none"

# Public URL of this server. OAuth metadata, the fixed upstream redirect URI
# (<base>/auth/callback) and the token audience are all derived from it, so it
# MUST match the host clients actually connect to.
_BASE_URL = os.environ.get("PEARCH_MCP_BASE_URL", "http://localhost:8000").rstrip("/")

# The upstream identity is re-validated on EVERY MCP request (FastMCP swaps its
# JWT for the upstream token per request), so cache verified identities.
_TOKEN_CACHE_TTL_S = int(os.environ.get("PEARCH_MCP_TOKEN_CACHE_TTL_S", "300"))
_TOKEN_CACHE_MAX = 512

# Redirect-URI patterns (fnmatch) for MCP clients. A URI the client listed at
# DCR time is always accepted by FastMCP's ProxyDCRClient, so this list cannot
# lock a new client out — the consent screen is the real confused-deputy
# defence. Override with PEARCH_MCP_ALLOWED_CLIENT_REDIRECT_URIS
# (comma-separated, or `*` for any).
_DEFAULT_CLIENT_REDIRECT_URIS = [
    "http://localhost:*",
    "http://127.0.0.1:*",
    "https://claude.ai/api/mcp/auth_callback",
    "https://claude.com/api/mcp/auth_callback",
    "https://*.pearch.ai/*",
    "cursor://*",
    "vscode://*",
    "vscode-insiders://*",
]


def _api_root(base_url: str | None = None) -> str:
    return (base_url or os.environ.get("PEARCH_API_URL") or _DEFAULT_BASE_URL).rstrip("/")


def _client_redirect_uris() -> list[str] | None:
    raw = os.environ.get("PEARCH_MCP_ALLOWED_CLIENT_REDIRECT_URIS")
    if raw is None:
        return list(_DEFAULT_CLIENT_REDIRECT_URIS)
    if raw.strip() == "*":
        return None
    return [p.strip() for p in raw.split(",") if p.strip()]


class _IdentityCache:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[float, AccessToken]] = {}

    def get(self, token: str) -> AccessToken | None:
        hit = self._cache.get(self._key(token))
        if hit and hit[0] > time.monotonic():
            return hit[1]
        return None

    def put(self, token: str, access: AccessToken) -> None:
        now = time.monotonic()
        if len(self._cache) >= _TOKEN_CACHE_MAX:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            if len(self._cache) >= _TOKEN_CACHE_MAX:
                self._cache.clear()
        self._cache[self._key(token)] = (now + _TOKEN_CACHE_TTL_S, access)

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()


class PearchApiKeyVerifier(TokenVerifier):
    """Validate a raw Pearch API key against GET /v1/user."""

    def __init__(self, base_url: str | None = None):
        super().__init__()
        self._base_url = _api_root(base_url)
        self._cache = _IdentityCache()

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
        cached = self._cache.get(token)
        if cached is not None:
            return cached
        user = await asyncio.to_thread(self._fetch_user, token)
        if user is None:
            return None
        # /v1/user nests identity under "user": {"email": ...}; fall back to top level.
        info = user.get("user") if isinstance(user.get("user"), dict) else user
        email = ((info or {}).get("email") or "").lower()
        access = AccessToken(
            token=token,
            client_id="pearch-api",
            scopes=[],
            claims={"api_key": token, "email": email},
        )
        self._cache.put(token, access)
        return access

    def _fetch_user(self, token: str) -> dict[str, Any] | None:
        req = urllib.request.Request(
            f"{self._base_url}/v1/user",
            headers={"Authorization": f"Bearer {token}", "accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=_AUTH_TIMEOUT) as resp:
                if resp.getcode() != 200:
                    return None
                return json.load(resp)
        except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
            return None


def _fetch_api_key_for_email(email: str) -> str | None:
    internal_token = os.environ.get("PEARCH_MCP_INTERNAL_TOKEN", "")
    if not internal_token:
        log.error("pearch-mcp: PEARCH_MCP_INTERNAL_TOKEN is not set; cannot map OAuth identity to an API key")
        return None
    qs = urllib.parse.urlencode({"email": email})
    req = urllib.request.Request(
        f"{_api_root()}/v1/internal/mcp/api_key?{qs}",
        headers={"X-Internal-Token": internal_token, "accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=_AUTH_TIMEOUT) as resp:
            if resp.getcode() != 200:
                return None
            return (json.load(resp) or {}).get("api_key") or None
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return None


class PearchGoogleVerifier(GoogleTokenVerifier):
    """Google token verification (tokeninfo/userinfo) + Pearch account mapping.

    A valid Google identity that has no Pearch account (or no API key) is
    rejected: tool calls bill credits against the caller's own key.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cache = _IdentityCache()

    async def verify_token(self, token: str) -> AccessToken | None:
        cached = self._cache.get(token)
        if cached is not None:
            return cached

        access = await super().verify_token(token)
        if access is None:
            return None

        email = (access.claims.get("email") or "").lower() if access.claims else ""
        user_data = (access.claims or {}).get("google_user_data") or {}
        if not email or user_data.get("verified_email") is False:
            log.warning("pearch-mcp: rejecting unverified Google email (%s)", email or "?")
            return None

        api_key = await asyncio.to_thread(_fetch_api_key_for_email, email)
        if not api_key:
            log.warning(
                "pearch-mcp: no Pearch API key for %s — sign up and create a key at platform.pearch.ai",
                email,
            )
            return None
        access.claims["api_key"] = api_key

        self._cache.put(token, access)
        return access


class DualAuthOAuthProxy(OAuthProxy):
    """OAuthProxy that also accepts raw Pearch API keys and pins upstream scopes.

    - load_access_token: FastMCP-issued tokens are JWTs (3 dot-separated
      segments); anything else is treated as a Pearch API key so header-based
      clients keep working in oauth mode.
    - authorize: FastMCP forwards whatever scopes the MCP client requested to
      Google. A client asking for less than openid+email would get a token with
      no email, and the account mapping would reject every request with an
      opaque 401. Pinning the scopes fixes it at the source.
    """

    def __init__(self, *, api_key_verifier: PearchApiKeyVerifier, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._api_key_verifier = api_key_verifier

    async def authorize(self, client: Any, params: Any) -> str:
        if self.required_scopes:
            params.scopes = list(self.required_scopes)
        return await super().authorize(client, params)

    async def load_access_token(self, token: str) -> AccessToken | None:
        if token.count(".") == 2:
            return await super().load_access_token(token)
        access = await self._api_key_verifier.verify_token(token)
        if access is None:
            return None
        # API-key identities carry no OAuth scopes; grant the proxy's required
        # scopes so FastMCP's scope gate does not 403 a valid key.
        return access.model_copy(update={"scopes": list(self.required_scopes or [])})


def _oauth_client_storage(client_secret: str) -> Any:
    """Back OAuth state (DCR registrations, transactions, codes, upstream Google tokens).

    Returning None keeps FastMCP's default encrypted DiskStore — fine locally,
    but it dies with the pod, forcing every client to re-authenticate on each
    rollout and blocking >1 replica. The deployment sets
    PEARCH_MCP_OAUTH_STORE=redis. FastMCP only encrypts the store it creates
    itself, so a custom store must be wrapped in Fernet here — upstream Google
    tokens must not sit in shared Redis in plaintext.
    """
    if os.environ.get("PEARCH_MCP_OAUTH_STORE", "disk").lower() != "redis":
        return None

    from cryptography.fernet import Fernet
    from fastmcp.server.auth.jwt_issuer import derive_jwt_key
    from key_value.aio.stores.redis import RedisStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    host = os.environ.get("PEARCH_MCP_OAUTH_REDIS_HOST") or os.environ.get("REDIS_ENDPOINT", "")
    if not host:
        raise RuntimeError("PEARCH_MCP_OAUTH_STORE=redis requires PEARCH_MCP_OAUTH_REDIS_HOST or REDIS_ENDPOINT")
    port = int(os.environ.get("REDIS_PORT", "6379"))
    db = int(os.environ.get("PEARCH_MCP_OAUTH_REDIS_DB", "4"))
    log.info("pearch-mcp: OAuth state store = redis %s:%s/%s (encrypted)", host, port, db)
    return FernetEncryptionWrapper(
        key_value=RedisStore(
            host=host,
            port=port,
            db=db,
            password=os.environ.get("REDIS_PASSWORD") or None,
        ),
        fernet=Fernet(
            key=derive_jwt_key(
                high_entropy_material=client_secret,
                salt="pearchmcp-oauth-store-encryption-key",
            )
        ),
    )


def _build_oauth_auth() -> OAuthProxy:
    client_id = os.environ.get("PEARCH_MCP_GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("PEARCH_MCP_GOOGLE_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        raise RuntimeError(
            "PEARCH_MCP_AUTH=oauth requires PEARCH_MCP_GOOGLE_CLIENT_ID and "
            "PEARCH_MCP_GOOGLE_CLIENT_SECRET (Google OAuth 2.0 Web application "
            f"client with redirect URI {_BASE_URL}/auth/callback)"
        )

    scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
    verifier = PearchGoogleVerifier(required_scopes=scopes, timeout_seconds=_AUTH_TIMEOUT)

    log.info("pearch-mcp: Google OAuth base_url=%s callback=%s/auth/callback", _BASE_URL, _BASE_URL)
    return DualAuthOAuthProxy(
        api_key_verifier=PearchApiKeyVerifier(),
        upstream_authorization_endpoint="https://accounts.google.com/o/oauth2/v2/auth",
        upstream_token_endpoint="https://oauth2.googleapis.com/token",
        upstream_revocation_endpoint="https://oauth2.googleapis.com/revoke",
        upstream_client_id=client_id,
        upstream_client_secret=client_secret,
        token_verifier=verifier,
        base_url=_BASE_URL,
        redirect_path="/auth/callback",
        allowed_client_redirect_uris=_client_redirect_uris(),
        client_storage=_oauth_client_storage(client_secret),
        extra_authorize_params={"access_type": "offline", "prompt": "consent"},
        require_authorization_consent=True,
    )


def _build_auth() -> Any:
    if _AUTH_MODE == "none":
        log.warning("pearch-mcp: AUTH DISABLED (PEARCH_MCP_AUTH=none) — local dev only")
        return None
    if _AUTH_MODE == "api_key":
        log.info("pearch-mcp: auth = Pearch API key")
        return PearchApiKeyVerifier()
    if _AUTH_MODE != "oauth":
        raise RuntimeError(f"unknown PEARCH_MCP_AUTH={_AUTH_MODE!r} (expected oauth|api_key|none)")
    return _build_oauth_auth()


def _resolve_api_key(api_key: str | None) -> str:
    if api_key:
        return api_key
    try:
        access = get_access_token()
    except Exception:
        access = None
    if access:
        claimed = (access.claims or {}).get("api_key")
        if claimed:
            return claimed
        if access.token:
            return access.token
    return os.environ.get("PEARCH_API_KEY") or _DEFAULT_API_KEY


mcp = FastMCP(
    "Pearch_MCP",
    instructions=(
        "Natural-language search over people and companies/leads (B2B) via Pearch.AI. "
        "Use search_people for people search, search_company_leads for B2B company+lead "
        "discovery, get_profile to enrich a single person, get_user_info for credits/plan. "
        "Authenticate via OAuth (sign in with the Google account of your Pearch user) or "
        "with a Pearch API key (Authorization: Bearer, same key as api.pearch.ai). "
        "Use test_mcp_key for masked sample results."
    ),
    auth=_build_auth(),
)


def _headers(key: str) -> dict[str, str]:
    return {
        "accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
    }


def _read_error(e: urllib.error.HTTPError) -> RuntimeError:
    try:
        err_body = e.read().decode()
        detail = json.loads(err_body) if err_body.strip() else {}
    except Exception:
        detail = {"message": str(e)}
    return RuntimeError(f"Pearch API error {e.code}: {detail}")


def _request(
    path: str,
    body: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    key = _resolve_api_key(api_key)
    # The demo key has no credits: force the masked free mode for it. Company-leads
    # thread replays reject the free param, and their credit check is skipped on
    # the cached path anyway.
    if (
        key == _DEFAULT_API_KEY
        and "free" not in body
        and not (path.endswith("search_company_leads") and "thread_id" in body)
    ):
        body["free"] = True
    url = f"{_api_root(base_url)}/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=_headers(key), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.getcode() not in (200, 202):
                raise RuntimeError(f"HTTP {resp.getcode()}")
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise _read_error(e) from e


def _get_request(
    path: str,
    params: dict[str, Any],
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    key = _resolve_api_key(api_key)
    clean = {
        k: ("true" if v is True else "false" if v is False else v)
        for k, v in params.items()
        if v is not None
    }
    url = f"{_api_root(base_url)}/{path.lstrip('/')}"
    if clean:
        url += "?" + urllib.parse.urlencode(clean)
    req = urllib.request.Request(url, headers=_headers(key), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if resp.getcode() != 200:
                raise RuntimeError(f"HTTP {resp.getcode()}")
            return json.load(resp)
    except urllib.error.HTTPError as e:
        raise _read_error(e) from e


def _body(**kwargs: Any) -> dict[str, Any]:
    return {k: v for k, v in kwargs.items() if v is not None}


@mcp.tool(
    title="Search People",
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
def search_people(
    query: str | None = None,
    search_type: str | None = None,
    limit: int = 5,
    offset: int = 0,
    thread_id: str | None = None,
    insights: bool | None = None,
    insights_items: list[str] | None = None,
    profile_scoring: bool | None = None,
    high_freshness: bool | None = None,
    reveal_emails: bool | None = None,
    reveal_phones: bool | None = None,
    filter_out_no_emails: bool | None = None,
    filter_out_no_phones: bool | None = None,
    filter_out_no_phones_or_emails: bool | None = None,
    strict_filters: bool | None = None,
    fill_with_low_confidence_results: bool | None = None,
    time_budget: int | None = None,
    short_response: bool = True,
    omit_fields: list[str] | None = None,
    docid_blacklist: list[str] | None = None,
    docid_whitelist: list[str] | None = None,
    free: bool | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Search for people and professional profiles using natural language.

    Pass a natural-language query (e.g. "software engineers in California with 5+ years
    Python"). search_type: "fast" (1 credit/candidate, ~30s; the default for new
    searches), "pro" (5 credits/candidate, higher quality, can take a few minutes), or
    "superfast" (1 credit/candidate, cheapest and quickest; incompatible with
    insights/profile_scoring/high_freshness). Leave search_type unset on thread_id
    follow-ups to keep the thread's original type.

    Credits per returned candidate: type cost + insights +1 + high_freshness +2 +
    reveal_emails +6 (only when found) + reveal_phones +6 (only when found); any
    filter_out_no_* contact filter +1.

    Pagination and follow-ups: reuse thread_id from a previous response. Changing only
    limit/offset pages through cached results (cheap); changing the query or any other
    parameter re-runs the search. offset + limit must not exceed 1000.

    Options: insights_items subset of ["overall_summary", "short_quotes", "rationale",
    "short_rationale"]; filter_out_no_emails / filter_out_no_phones /
    filter_out_no_phones_or_emails return only candidates with that contact info;
    high_freshness refreshes profiles in real time; strict_filters disables filter
    relaxation when too few candidates match; fill_with_low_confidence_results pads
    underfilled results with low-confidence matches; time_budget (seconds) caps search
    time; short_response returns compact profiles (recommended for MCP);
    docid_blacklist/docid_whitelist exclude/pin LinkedIn slugs; free=true returns
    masked trial results without spending credits (limit capped at 25; automatic for
    test_mcp_key).

    Returns thread_id, search_results (each: docid, profile, score, insights),
    total_estimate, credits_used, credits_remaining, status.
    """
    if limit < 1:
        limit = 1
    if offset < 0:
        offset = 0
    if offset + limit > 1000:
        if offset >= 1000:
            raise ValueError("offset must be below 1000 (the API serves at most the top 1000 results)")
        limit = 1000 - offset
    if search_type is None and thread_id is None:
        search_type = "fast"
    body = _body(
        query=query,
        type=search_type,
        limit=limit,
        offset=offset,
        thread_id=thread_id,
        insights=insights,
        insights_items=insights_items,
        profile_scoring=profile_scoring,
        high_freshness=high_freshness,
        reveal_emails=reveal_emails,
        reveal_phones=reveal_phones,
        filter_out_no_emails=filter_out_no_emails,
        filter_out_no_phones=filter_out_no_phones,
        filter_out_no_phones_or_emails=filter_out_no_phones_or_emails,
        strict_filters=strict_filters,
        fill_with_low_confidence_results=fill_with_low_confidence_results,
        time_budget=time_budget,
        omit_fields=omit_fields,
        docid_blacklist=docid_blacklist,
        docid_whitelist=docid_whitelist,
        free=free,
    )
    body["short_response"] = short_response
    return _request("v2/search", body, api_key=api_key, base_url=base_url)


@mcp.tool(
    title="Search Company Leads",
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
def search_company_leads(
    company_query: str | None = None,
    lead_query: str | None = None,
    limit: int = 5,
    leads_limit: int = 3,
    reveal_emails: bool | None = None,
    reveal_phones: bool | None = None,
    filter_out_no_emails: bool | None = None,
    filter_out_no_phones: bool | None = None,
    filter_out_no_phones_or_emails: bool | None = None,
    high_freshness: bool | None = None,
    company_high_freshness: bool | None = None,
    outreach_message_instruction: str | None = None,
    short_response: bool = True,
    omit_fields: list[str] | None = None,
    thread_id: str | None = None,
    free: bool | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Find companies and leads (contacts) within those companies. For B2B sales or headhunting.

    company_query: natural-language description of companies (e.g. "AI startups in San
    Francisco with 50-200 employees"). lead_query: optional, who to find at those companies
    (e.g. "CTOs and engineering managers") — do not put company criteria here.
    limit: max companies (up to 10000). leads_limit: leads per company (up to 10).
    outreach_message_instruction generates personalized outreach text per lead.
    company_high_freshness looks companies up on the internet in real time;
    high_freshness refreshes lead profiles.

    Credits: 5 per company; per lead 2 + outreach message 3 + reveal_emails 3 +
    reveal_phones 8 + high_freshness 1; contact filters +1 per lead.

    thread_id replays a previous search from cache: with thread_id only limit,
    leads_limit, short_response and omit_fields may be changed — any other parameter is
    rejected. To change the query or options, start a new search without thread_id.

    Returns thread_id, search_results (companies, each with leads), query, duration.
    """
    limit = min(max(limit, 1), 10000)
    leads_limit = min(max(leads_limit, 1), 10)
    if thread_id:
        disallowed = {
            "company_query": company_query,
            "lead_query": lead_query,
            "outreach_message_instruction": outreach_message_instruction,
            "reveal_emails": reveal_emails,
            "reveal_phones": reveal_phones,
            "filter_out_no_emails": filter_out_no_emails,
            "filter_out_no_phones": filter_out_no_phones,
            "filter_out_no_phones_or_emails": filter_out_no_phones_or_emails,
            "high_freshness": high_freshness,
            "company_high_freshness": company_high_freshness,
            "free": free,
        }
        given = [name for name, value in disallowed.items() if value is not None]
        if given:
            raise ValueError(
                "with thread_id only limit, leads_limit, short_response and omit_fields may be "
                f"changed; drop thread_id to start a new search with: {', '.join(given)}"
            )
        body = _body(
            thread_id=thread_id,
            limit=limit,
            leads_limit=leads_limit,
            omit_fields=omit_fields,
        )
    else:
        if not company_query:
            raise ValueError("company_query is required when thread_id is not provided")
        body = _body(
            company_query=company_query,
            lead_query=lead_query,
            limit=limit,
            leads_limit=leads_limit,
            reveal_emails=reveal_emails,
            reveal_phones=reveal_phones,
            filter_out_no_emails=filter_out_no_emails,
            filter_out_no_phones=filter_out_no_phones,
            filter_out_no_phones_or_emails=filter_out_no_phones_or_emails,
            high_freshness=high_freshness,
            company_high_freshness=company_high_freshness,
            outreach_message_instruction=outreach_message_instruction,
            omit_fields=omit_fields,
            free=free,
        )
    body["short_response"] = short_response
    return _request("v2/search_company_leads", body, api_key=api_key, base_url=base_url)


@mcp.tool(
    title="Get Person Profile",
    annotations={"readOnlyHint": True, "openWorldHint": True},
)
def get_profile(
    docid: str | None = None,
    uuid: str | None = None,
    email: str | None = None,
    reveal_emails: bool | None = None,
    reveal_phones: bool | None = None,
    high_freshness: bool | None = None,
    with_profile: bool | None = None,
    github_enrich: bool | None = None,
    short_response: bool = True,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Look up and enrich a single person's profile.

    Identify the person by exactly one of: docid (LinkedIn slug, e.g. "john-doe-123"),
    uuid (masked profile UUID from free/masked search results — unmasks it, flat 25
    credits), or email (resolves the email to a LinkedIn profile first).

    Credits: with_profile 1, high_freshness (real-time refresh) 2, reveal_emails 6,
    reveal_phones 6, github_enrich 8, email-to-LinkedIn resolution 6.

    Returns profile, credits_used, credits_remaining.
    """
    if sum(1 for v in (docid, uuid, email) if v) != 1:
        raise ValueError("pass exactly one of docid, uuid or email")
    params = _body(
        docid=docid,
        uuid=uuid,
        email=email,
        reveal_emails=reveal_emails,
        reveal_phones=reveal_phones,
        high_freshness=high_freshness,
        with_profile=with_profile,
        github_enrich=github_enrich,
        short_response=short_response,
    )
    return _get_request("v1/profile", params, api_key=api_key, base_url=base_url)


@mcp.tool(
    title="Get Account Info",
    annotations={"readOnlyHint": True, "openWorldHint": False},
)
def get_user_info(
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    """Get the authenticated Pearch user: email, remaining credits, pricing plan.

    Free (0 credits). Use it to check the credit balance before expensive searches.
    """
    return _get_request("v1/user", {}, api_key=api_key, base_url=base_url)


@mcp.custom_route("/health", methods=["GET"])
@mcp.custom_route("/healthcheck", methods=["GET"])
async def health_check(request):
    return JSONResponse(
        {
            "status": "healthy",
            "service": "pearch-mcp",
            "auth": _AUTH_MODE,
            "base_url": _BASE_URL if _AUTH_MODE == "oauth" else None,
        }
    )


class _ApiKeyOnly401:
    """API-key mode only: strip the OAuth `WWW-Authenticate: Bearer` challenge on 401.

    Without this, OAuth-capable MCP clients (Claude,
    Cursor) treat the challenge as a signal to run OAuth discovery against
    /.well-known/oauth-* — which the API-key configuration does not serve — and
    hang until their connect timeout. In oauth mode the challenge is exactly
    what clients need, so this wrapper is NOT applied.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def send_no_challenge(message: Any) -> None:
            if message["type"] == "http.response.start" and message.get("status") == 401:
                message["headers"] = [
                    (k, v)
                    for (k, v) in message.get("headers", [])
                    if k.lower() != b"www-authenticate"
                ]
            await send(message)

        await self.app(scope, receive, send_no_challenge)


_event_store = EventStore()
app = mcp.http_app(event_store=_event_store, retry_interval=2000)
if _AUTH_MODE == "api_key":
    app = _ApiKeyOnly401(app)

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
