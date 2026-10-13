import base64
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


def icon_of(html):
    found = re.search(r'class="pm-icon"[^>]*><img src="(data:image/svg\+xml;base64,[A-Za-z0-9+/=]+)"', html)
    return found.group(1) if found else None


def test_a_vendor_domain_in_the_return_address_shows_that_vendors_icon_and_domain():
    html = page(client_name="Totally Something Else", redirect_uri="https://claude.ai/api/mcp/auth_callback")
    assert icon_of(html) == pearch_mcp.client_icon_uri("claude")
    assert "claude.ai" in html


def test_openai_domains_show_the_openai_icon():
    html = page(client_name="x", redirect_uri="https://chatgpt.com/connector_platform_oauth_redirect")
    assert icon_of(html) == pearch_mcp.client_icon_uri("openai")


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://claude.ai.evil.example/cb",
        "https://evil.example/claude.ai/api/mcp/auth_callback",
        "https://notclaude.ai/cb",
        "https://evil.example/cb?next=https://claude.ai",
        "http://claude.ai/api/mcp/auth_callback",
    ],
)
def test_a_lookalike_address_does_not_borrow_an_icon_even_if_the_name_says_claude(redirect_uri):
    html = page(client_name="Claude", redirect_uri=redirect_uri)
    assert icon_of(html) is None
    assert 'class="pm-icon pm-initial"' in html


def test_an_app_on_this_computer_is_recognised_by_its_declared_name_and_labelled_unverified():
    html = page(client_name="Claude Code (pearch)")
    assert icon_of(html) == pearch_mcp.client_icon_uri("claude")
    assert "App on this computer" in html


def test_an_unknown_app_on_this_computer_gets_an_initial_not_an_icon():
    html = page(client_name="my-script")
    assert icon_of(html) is None
    assert re.search(r'class="pm-icon pm-initial"[^>]*>M<', html)
    assert "App on this computer" in html


@pytest.mark.parametrize(
    "scheme,brand", [("cursor://anysphere.cursor-retrieval/oauth/callback", "cursor"), ("vscode://ms-vscode.mcp/cb", "visualstudiocode")]
)
def test_editor_deep_links_show_the_editor_icon(scheme, brand):
    assert icon_of(page(client_name="x", redirect_uri=scheme)) == pearch_mcp.client_icon_uri(brand)


def test_the_icons_are_plain_images_that_cannot_run_anything():
    for brand in ("claude", "openai", "cursor", "visualstudiocode"):
        svg = base64.b64decode(pearch_mcp.client_icon_uri(brand).split(",", 1)[1]).decode()
        assert svg.startswith("<svg") and "<script" not in svg and "onload" not in svg.lower() and "href" not in svg


def test_a_name_with_markup_never_reaches_the_page_as_markup():
    html = page(client_name="<b>bold</b>", redirect_uri="https://evil.example/cb")
    assert "<b>bold</b>" not in html
