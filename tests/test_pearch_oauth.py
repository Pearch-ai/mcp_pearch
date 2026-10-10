import json

import pytest
from fastmcp.server.auth import AccessToken
from key_value.aio.stores.memory import MemoryStore

import pearch_mcp

SUPABASE_URL = "https://project.supabase.co"
PEARCH_SCOPES = ["email", "profile", "offline_access"]


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_URL", SUPABASE_URL + "/")
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_CLIENT_ID", "client-id-1")
    monkeypatch.setenv("PEARCH_MCP_SUPABASE_CLIENT_SECRET", "secret-1")
    monkeypatch.setattr(pearch_mcp, "_BASE_URL", "https://mcp.example.test")
    monkeypatch.setattr(pearch_mcp, "_oauth_client_storage", lambda secret: MemoryStore())


def test_builds_a_proxy_in_front_of_supabase(supabase_env):
    proxy = pearch_mcp._build_pearch_oauth_auth()
    assert isinstance(proxy, pearch_mcp.DualAuthOAuthProxy)
    assert proxy._upstream_authorization_endpoint == f"{SUPABASE_URL}/auth/v1/oauth/authorize"
    assert proxy._upstream_token_endpoint == f"{SUPABASE_URL}/auth/v1/oauth/token"
    assert proxy._upstream_client_id == "client-id-1"
    assert proxy._upstream_client_secret.get_secret_value() == "secret-1"
    assert proxy._token_endpoint_auth_method == "client_secret_basic"
    assert proxy._redirect_path == "/auth/callback"


def test_scopes_asked_from_supabase_are_pinned_and_never_include_openid(supabase_env):
    proxy = pearch_mcp._build_pearch_oauth_auth()
    assert proxy.required_scopes == PEARCH_SCOPES
    assert "openid" not in proxy.required_scopes


def test_raw_api_keys_keep_working_next_to_oauth(supabase_env):
    proxy = pearch_mcp._build_pearch_oauth_auth()
    assert isinstance(proxy._api_key_verifier, pearch_mcp.PearchApiKeyVerifier)


@pytest.mark.parametrize("missing", ["PEARCH_MCP_SUPABASE_URL", "PEARCH_MCP_SUPABASE_CLIENT_ID", "PEARCH_MCP_SUPABASE_CLIENT_SECRET"])
def test_refuses_to_start_without_the_supabase_settings(supabase_env, monkeypatch, missing):
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError) as error:
        pearch_mcp._build_pearch_oauth_auth()
    assert "PEARCH_MCP_AUTH=pearch_oauth" in str(error.value)
    assert missing in str(error.value) or "PEARCH_MCP_SUPABASE_" in str(error.value)


def test_the_auth_mode_selects_the_proxy(supabase_env, monkeypatch):
    monkeypatch.setattr(pearch_mcp, "_AUTH_MODE", "pearch_oauth")
    assert isinstance(pearch_mcp._build_auth(), pearch_mcp.DualAuthOAuthProxy)


def test_unknown_modes_list_the_new_one(monkeypatch):
    monkeypatch.setattr(pearch_mcp, "_AUTH_MODE", "nonsense")
    with pytest.raises(RuntimeError) as error:
        pearch_mcp._build_auth()
    assert "pearch_oauth" in str(error.value)


async def test_health_reports_the_public_url_in_both_oauth_modes(monkeypatch):
    monkeypatch.setattr(pearch_mcp, "_BASE_URL", "https://mcp.example.test")
    monkeypatch.setattr(pearch_mcp, "_AUTH_MODE", "pearch_oauth")
    response = await pearch_mcp.health_check(None)
    assert json.loads(response.body) == {
        "status": "healthy",
        "service": "pearch-mcp",
        "auth": "pearch_oauth",
        "base_url": "https://mcp.example.test",
    }


class FakeUserLookup:
    def __init__(self, user):
        self.user = user
        self.calls = []

    def __call__(self, verifier, token):
        self.calls.append(token)
        return self.user


async def test_verifier_accepts_a_token_the_api_accepts_and_grants_the_configured_scopes(monkeypatch):
    lookup = FakeUserLookup({"user": {"email": "User@Example.com"}})
    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", lambda self, token: lookup(self, token))
    verifier = pearch_mcp.PearchApiKeyVerifier(scopes=PEARCH_SCOPES)

    access = await verifier.verify_token("upstream-token")
    assert access.claims == {"api_key": "upstream-token", "email": "user@example.com"}
    assert access.scopes == PEARCH_SCOPES
    assert verifier.required_scopes == PEARCH_SCOPES

    await verifier.verify_token("upstream-token")
    assert lookup.calls == ["upstream-token"]


async def test_verifier_rejects_a_token_the_api_rejects(monkeypatch):
    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", lambda self, token: None)
    assert await pearch_mcp.PearchApiKeyVerifier(scopes=PEARCH_SCOPES).verify_token("nope") is None


async def test_api_key_verification_is_unchanged_without_scopes(monkeypatch):
    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", lambda self, token: {"user": {"email": "a@b.c"}})
    access = await pearch_mcp.PearchApiKeyVerifier().verify_token("pk_key")
    assert access.scopes == []


def test_tool_calls_forward_the_stored_upstream_token(monkeypatch):
    access = AccessToken(token="mcp-jwt", client_id="x", scopes=[], claims={"api_key": "upstream-token"})
    monkeypatch.setattr(pearch_mcp, "get_access_token", lambda: access)
    assert pearch_mcp._resolve_api_key(None) == "upstream-token"


@pytest.mark.parametrize("mode_env", ["pearch_oauth", "api_key"])
async def test_a_raw_api_key_is_accepted_in_both_modes(supabase_env, monkeypatch, mode_env):
    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", lambda self, token: {"user": {"email": "a@b.c"}} if token == "pk_valid" else None)
    monkeypatch.setattr(pearch_mcp, "_AUTH_MODE", mode_env)
    auth = pearch_mcp._build_auth()
    if mode_env == "pearch_oauth":
        accepted = await auth.load_access_token("pk_valid")
        rejected = await auth.load_access_token("pk_invalid")
        assert accepted.scopes == PEARCH_SCOPES
    else:
        accepted = await auth.verify_token("pk_valid")
        rejected = await auth.verify_token("pk_invalid")
        assert accepted.scopes == []
    assert accepted.claims["api_key"] == "pk_valid"
    assert rejected is None


async def test_the_public_demo_key_still_works_without_a_lookup(monkeypatch):
    def forbidden(self, token):
        raise AssertionError("the demo key must not hit the API")

    monkeypatch.setattr(pearch_mcp.PearchApiKeyVerifier, "_fetch_user", forbidden)
    access = await pearch_mcp.PearchApiKeyVerifier().verify_token("test_mcp_key")
    assert access.claims == {"api_key": "test_mcp_key"}
