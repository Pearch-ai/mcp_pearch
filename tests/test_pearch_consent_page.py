import re

import pytest
from fastmcp.server.auth import oauth_proxy

import pearch_mcp

ARGS = dict(
    client_id="c9d04a92-8b5c-4cac-aef3-3b25e7b65bd7",
    redirect_uri="http://localhost:49914/callback",
    scopes=["email", "profile", "offline_access"],
    txn_id="txn-123",
    csrf_token="csrf-456",
    client_name="Claude Code (pearch)",
    server_name="Pearch_MCP",
)


def page(**overrides):
    return pearch_mcp.create_pearch_consent_html(**{**ARGS, **overrides})


def test_the_default_fastmcp_page_is_replaced_with_the_pearch_one():
    assert oauth_proxy.create_consent_html is pearch_mcp.create_pearch_consent_html


def test_the_page_is_branded_and_says_who_asks_for_what():
    html = page()
    assert "Claude Code (pearch)" in html
    assert "wants to access your Pearch account" in html
    assert "Search people and companies on your behalf and use your Pearch credits" in html
    assert 'src="https://platform.pearch.ai/pearch.png"' in html
    assert "FastMCP" not in html and "gofastmcp.com" not in html


def test_the_page_shows_where_access_will_be_sent_back_to():
    assert "http://localhost:49914/callback" in page()


def test_the_form_keeps_what_the_consent_handler_expects():
    html = page()
    assert re.search(r'<form[^>]*method="POST"', html)
    assert 'name="txn_id" value="txn-123"' in html
    assert 'name="csrf_token" value="csrf-456"' in html
    assert re.search(r'name="action" value="approve"', html)
    assert re.search(r'name="action" value="deny"', html)


def test_offline_access_is_not_shown_to_the_user():
    html = page()
    assert "offline_access" not in html
    assert "email" in html


@pytest.mark.parametrize(
    "field,value",
    [
        ("client_name", '<img src=x onerror="alert(1)">'),
        ("redirect_uri", 'http://localhost:1/cb"><script>alert(1)</script>'),
        ("client_id", '"><script>alert(1)</script>'),
    ],
)
def test_untrusted_values_are_escaped(field, value):
    html = page(**{field: value})
    assert "<script>alert(1)" not in html
    assert 'onerror="alert(1)"' not in html


def test_the_content_security_policy_lets_the_form_return_to_a_custom_scheme():
    html = page(redirect_uri="cursor://anysphere.cursor-retrieval/oauth/callback")
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', html).group(1)
    assert "form-action https: http: cursor:" in policy
    assert "default-src &#x27;none&#x27;" in policy or "default-src 'none'" in policy
