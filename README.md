# Pearch.ai MCP
[![Trust Score](https://archestra.ai/mcp-catalog/api/badge/quality/Pearch-ai/mcp_pearch)](https://archestra.ai/mcp-catalog/pearch-ai__mcp_pearch)

MCP server for [Pearch.AI](https://pearch.ai): natural-language search over **people** and **companies/leads** (B2B). Use it from Claude, Cursor, VS Code, or any MCP-compatible client.

> [Evaluating AI Recruitment Sourcing Tools by Human Preference](https://arxiv.org/abs/2504.02463v1)

## Tools

| Tool | Description |
|------|-------------|
| **search_people** | Natural-language people search (e.g. *"software engineers in California with 5+ years Python"*). Supports fast/pro/superfast search types, contact reveal & contact filters, real-time profile refresh, insights, and thread-based pagination/follow-ups. |
| **search_company_leads** | Find companies and leads/contacts within them (B2B). Example: company *"AI startups in SF, 50–200 employees"* + leads *"CTOs and engineering managers"*, with optional personalized outreach messages. |
| **get_profile** | Look up and enrich a single person by LinkedIn slug or email (contact reveal, real-time refresh, GitHub enrichment). |
| **get_user_info** | Authenticated user info: email, remaining credits, pricing plan. Free. |

Custom structured filters (`custom_filters` / `search_requirements`) are intentionally not exposed — describe everything in the natural-language query.

## Remote server (recommended)

The hosted server lives at `https://mcp.pearch.ai/mcp` and supports two auth schemes at once:

### OAuth (no key handling)

Add the server without any headers — OAuth-capable clients (Claude, Cursor, VS Code) discover the flow automatically and open a Google sign-in. Sign in with the Google account whose email matches your Pearch account:

```bash
claude mcp add --transport http pearch https://mcp.pearch.ai/mcp
```

Your searches bill credits against your own Pearch account. If your Pearch account has no API key yet, create one first in the [Pearch.ai Dashboard](https://platform.pearch.ai/dashboard).

### API key

Pass the same Pearch API key as `api.pearch.ai`:

```json
{
  "mcpServers": {
    "Pearch.ai": {
      "url": "https://mcp.pearch.ai/mcp",
      "headers": {
        "Authorization": "Bearer ${env:PEARCH_API_KEY}"
      }
    }
  }
}
```

Use **`test_mcp_key`** for **masked (sample) results** — no sign-up required.

## Local (stdio) installation

Requires **Python 3.10+** and `pip install -r requirements.txt` (or `pip install fastmcp`).

### Claude Desktop / Claude Code

```bash
fastmcp install claude-desktop pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Or manually under `mcpServers`:

```json
"Pearch.ai": {
  "command": "python",
  "args": ["/path/to/mcp_pearch/pearch_mcp.py"],
  "env": { "PEARCH_API_KEY": "test_mcp_key" }
}
```

### Cursor

```bash
fastmcp install cursor pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Replace `test_mcp_key` with your dashboard key for full results.

## Running your own HTTP server

```bash
uvicorn pearch_mcp:app --host 0.0.0.0 --port 8000
```

Health: `GET /health` or `/healthcheck` (reports the auth mode).

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `PEARCH_MCP_AUTH` | `api_key` | `oauth` \| `api_key` \| `none`. In `oauth` mode raw API-key bearers are still accepted (dual auth). |
| `PEARCH_MCP_BASE_URL` | `http://localhost:8000` | Public URL of this server. OAuth metadata, token audience, and the `/auth/callback` redirect URI all derive from it. |
| `PEARCH_MCP_GOOGLE_CLIENT_ID` / `PEARCH_MCP_GOOGLE_CLIENT_SECRET` | — | Google OAuth 2.0 Web application client (register `<base_url>/auth/callback` as a redirect URI). Required in `oauth` mode. |
| `PEARCH_MCP_INTERNAL_TOKEN` | — | Shared secret for the Pearch API's internal email→API-key mapping endpoint. Required in `oauth` mode. |
| `PEARCH_MCP_OAUTH_STORE` | `disk` | `redis` keeps OAuth state (client registrations, tokens — encrypted) in Redis so it survives restarts and allows >1 replica. |
| `PEARCH_MCP_OAUTH_REDIS_HOST` / `REDIS_ENDPOINT`, `REDIS_PORT`, `PEARCH_MCP_OAUTH_REDIS_DB`, `REDIS_PASSWORD` | —, `6379`, `4`, — | Redis connection for the OAuth store. |
| `PEARCH_MCP_ALLOWED_CLIENT_REDIRECT_URIS` | built-in list | Comma-separated fnmatch patterns for MCP client redirect URIs (`*` = any). |
| `PEARCH_MCP_TOKEN_CACHE_TTL_S` | `300` | Verified-identity cache TTL; also the revocation lag. |
| `PEARCH_API_URL` | `https://api.pearch.ai` | Pearch API base (per-call `base_url` overrides). |
| `PEARCH_API_KEY` | `test_mcp_key` | Fallback key for stdio/local use. |
| `MCP_DISABLE_AUTH` | — | `1` is equivalent to `PEARCH_MCP_AUTH=none` (local dev only). |

In `oauth` mode the ingress/reverse proxy must route the **whole host** to the server, not just `/mcp`: the flow adds `/.well-known/oauth-*`, `/authorize`, `/token`, `/register`, `/revoke`, `/consent`, and `/auth/callback`.

## Development

```bash
export PEARCH_API_KEY='test_mcp_key'   # or your key for full results
fastmcp dev inspector pearch_mcp.py
```

## Support

- [Open an issue](https://github.com/Pearch-ai/mcp_pearch/issues)
- [f@pearch.ai](mailto:f@pearch.ai)

## License

MIT — see [LICENSE](LICENSE).
