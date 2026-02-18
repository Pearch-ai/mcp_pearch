# Pearch.ai MCP
[![Trust Score](https://archestra.ai/mcp-catalog/api/badge/quality/Pearch-ai/mcp_pearch)](https://archestra.ai/mcp-catalog/pearch-ai__mcp_pearch)

MCP server for [Pearch.AI](https://pearch.ai): natural-language search over **people** and **companies/leads** (B2B). Use it from Cursor, Claude Desktop, VS Code, or any MCP-compatible client.

> [Evaluating AI Recruitment Sourcing Tools by Human Preference](https://arxiv.org/abs/2504.02463v1)

## Features

- **search_people** — natural-language search for people (e.g. “software engineers in California with 5+ years Python”); returns candidates with optional insights and profile scoring.
- **search_company_leads** — find companies and leads/contacts within them (B2B); e.g. “AI startups in SF, 50–200 employees” + “CTOs and engineering managers”.
- **Test key by default** — works out of the box with `test_mcp_key` (masked/sample results); set your own key for full results.

## Prerequisites

- **Python 3.10+**
- **[uv](https://docs.astral.sh/uv/)** (recommended; Linux/macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`) or pip
- **FastMCP** — install with `pip install fastmcp` or `uv add fastmcp`

## API key

Use **`test_mcp_key`** for **masked (sample) results** — no sign-up required.

For **full, unmasked results**, get an API key from the [Pearch.ai Dashboard](https://platform.pearch.ai/dashboard) and set it as `PEARCH_API_KEY` in your MCP config (see Installation below).

## Installation

Clone the repo, then follow the steps for your client:

```bash
git clone https://github.com/Pearch-ai/mcp_pearch
cd mcp_pearch
```

### Claude Desktop

**Automatic:**

```bash
fastmcp install claude-desktop pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Replace `test_mcp_key` with your dashboard key for full results.

If you see `bad interpreter: No such file or directory` (e.g. with conda), run:

```bash
pip install --force-reinstall fastmcp
```

or:

```bash
python -m fastmcp install claude-desktop pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

**Manual:** edit `~/.claude/claude_desktop_config.json` and add under `mcpServers`. Replace `/path/to/mcp_pearch` with your actual path.

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

Ensure `fastmcp` is installed: `pip install fastmcp`.

### Cursor

**Recommended (automatic):**

```bash
fastmcp install cursor pearch_mcp.py --env PEARCH_API_KEY=test_mcp_key
```

Replace `test_mcp_key` with your dashboard key for full results.

**Manual:** add to `~/.cursor/mcp.json` (or project `.cursor/mcp.json`):

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

Replace `/absolute/path/to/pearch_mcp.py` with the real path. Use `test_mcp_key` for masked results, or your dashboard key for full results.

To generate a ready snippet:

```bash
fastmcp install mcp-json pearch_mcp.py --name "Pearch.ai"
```

Then paste the output into `mcpServers` in `~/.cursor/mcp.json`.

### VS Code and other clients

- **VS Code:** add the same `mcpServers` block to `.vscode/mcp.json` in your workspace.
- **Other MCP clients:** use the same `command` / `args` / `env` format in the client’s MCP config.

Generate a config snippet (defaults to `test_mcp_key`; add `--env PEARCH_API_KEY=your-key` for full results):

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
export PEARCH_API_KEY='test_mcp_key'   # or your key for full results
fastmcp dev inspector pearch_mcp.py
```

## Support

- [Open an issue](https://github.com/Pearch-ai/mcp_pearch/issues)
- [f@pearch.ai](mailto:f@pearch.ai)

## License

MIT — see [LICENSE](LICENSE).
