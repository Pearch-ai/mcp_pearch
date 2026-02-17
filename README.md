# Pearch.ai MCP

[![smithery badge](https://smithery.ai/badge/@Pearch-ai/mcp_pearch)](https://smithery.ai/server/@Pearch-ai/mcp_pearch)

MCP server for [Pearch.AI](https://pearch.ai): natural-language search over **people** and **companies/leads** (B2B). Use it from Cursor, Claude Desktop, VS Code, or any MCP-compatible client.

[Evaluating AI Recruitment Sourcing Tools by Human Preference](https://arxiv.org/abs/2504.02463v1)

## Features

- **search_people** — natural-language search for people (e.g. “software engineers in California with 5+ years Python”); returns candidates with optional insights and profile scoring.
- **search_company_leads** — find companies and leads/contacts within them (B2B); e.g. “AI startups in SF, 50–200 employees” + “CTOs and engineering managers”.
- **Test key by default** — works out of the box with `test_mcp_key` (masked/sample results); set your own key for full results.

## Prerequisites

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- [FastMCP](https://gofastmcp.com/) — install with `pip install fastmcp` or `uv add fastmcp`

## API key

In the config below we use **`test_mcp_key`** — you get **masked** (sample) results, no sign-up.  
For **full, unmasked** results: get a key at [Pearch.ai Dashboard](https://platform.pearch.ai/dashboard) and put it in `PEARCH_API_KEY` instead of `test_mcp_key` in the same place in your config.

## Installation

### Via npx (Smithery, Claude Desktop — one-click, no Python)

```bash
npx -y @smithery/cli install @Pearch-ai/mcp_pearch --client claude
```

Then in Smithery set `pearchApiKey` to `test_mcp_key` (masked results) or your dashboard key (full results). Requires only Node.js.

### Cursor

**Automatic (recommended):**

```bash
cd /path/to/mcp_pearch
fastmcp install cursor pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Replace `test_mcp_key` with your dashboard key for full results.

**Manual:** add the server to `~/.cursor/mcp.json` (or project `.cursor/mcp.json`). Use `test_mcp_key` for masked results; replace with your dashboard key for full results:

```json
{
  "mcpServers": {
    "Pearch.ai": {
      "command": "uv",
      "args": ["run", "--with", "fastmcp", "fastmcp", "run", "/absolute/path/to/pearch_mcp.py"],
      "env": { "PEARCH_API_KEY": "test_mcp_key" }
    }
  }
}
```

Generate a ready snippet:

```bash
fastmcp install mcp-json pearch_mcp.py --name "Pearch.ai"
```

Then paste the output into `mcpServers` in `~/.cursor/mcp.json`.

### Claude Desktop

**Via npx (no Python):** run once, then set the API key in Smithery:

```bash
npx -y @smithery/cli install @Pearch-ai/mcp_pearch --client claude
```

**Without npx/Smithery (local install):** need Python 3.10+ and [uv](https://docs.astral.sh/uv/) or pip + `pip install fastmcp`.

**Automatic:**

```bash
cd /path/to/mcp_pearch
fastmcp install claude-desktop pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Replace `test_mcp_key` with your dashboard key for full results.

If you get `bad interpreter: No such file or directory` (e.g. in conda), reinstall in the current env and retry: `pip install --force-reinstall fastmcp`, or run: `python -m fastmcp install claude-desktop pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key`.

**Manual:** edit `~/.claude/claude_desktop_config.json` and add under `mcpServers`. Replace `/path/to/mcp_pearch` with the real path. Use `test_mcp_key` for masked results; replace with your dashboard key for full results.

With **uv**:
```json
"Pearch.ai": {
  "command": "uv",
  "args": ["run", "--with", "fastmcp", "fastmcp", "run", "/path/to/mcp_pearch/pearch_mcp.py"],
  "env": { "PEARCH_API_KEY": "test_mcp_key" }
}
```

With **pip/conda** (no uv):
```json
"Pearch.ai": {
  "command": "python",
  "args": ["/path/to/mcp_pearch/pearch_mcp.py"],
  "env": { "PEARCH_API_KEY": "test_mcp_key" }
}
```
Ensure `fastmcp` is installed in that Python env (`pip install fastmcp`).

### Other clients (VS Code, custom)

Use the same `mcpServers` format:

- **VS Code:** `.vscode/mcp.json` in the workspace.
- **Any MCP client:** add the same `command` / `args` / `env` block to the client’s MCP config.

Generate config (uses `test_mcp_key` by default; add `--env PEARCH_API_KEY=your-key` for full results):

```bash
fastmcp install mcp-json pearch_mcp.py --name "Pearch.ai"
```

Paste the generated object into your client’s `mcpServers`.

## Tools

| Tool | Description |
|------|-------------|
| **search_people** | Natural-language search for people or follow-up on a thread. Example: *"software engineers in California with 5+ years Python"*, *"senior ML researchers in Berlin"*. |
| **search_company_leads** | Find companies and leads/contacts (B2B). Example: company *"AI startups in SF, 50–200 employees"* + leads *"CTOs and engineering managers"*. |

Base URL: `PEARCH_API_URL` or per-call `base_url` (default `https://api.pearch.ai`).

## Development

```bash
# test key (masked results); or set your key for full results
export PEARCH_API_KEY='test_mcp_key'

fastmcp dev inspector pearch_mcp.py
```

## Support

- [Open an issue](https://github.com/Pearch-ai/mcp_pearch/issues)
- [f@pearch.ai](mailto:f@pearch.ai)

## License

MIT — see [LICENSE](LICENSE).
