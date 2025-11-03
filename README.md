# Pearch.ai MCP

[![smithery badge](https://smithery.ai/badge/@Pearch-ai/mcp_pearch)](https://smithery.ai/server/@Pearch-ai/mcp_pearch)

Our people search API and MCP deliver the most precise results on the market. You simply ask in natural language, and we provide top-quality candidates. Designed for seamless integration with any ATS or hiring platform, our solution is backed by scientific methods, trusted by recruiters, and consistently rated the highest-quality sourcing tool.

[Evaluating AI Recruitment Sourcing Tools by Human Preference](https://arxiv.org/abs/2504.02463v1)


## Prerequisites

- Python 3.7 or newer
- Pearch.ai API key
- FastMCP package

## API Key Setup

1. Visit [Pearch.ai Dashboard](https://platform.pearch.ai/dashboard) to obtain your API key
2. Set your API key as an environment variable:
   ```bash
   export PEARCH_API_KEY='your-api-key-here'
   ```

## Installation

### Installing via Smithery

To install mcp_pearch for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@Pearch-ai/mcp_pearch):

```bash
npx -y @smithery/cli install @Pearch-ai/mcp_pearch --client claude
```

### Option 1: macOS[uv] 

```bash
# Install Python and uv
brew install python
brew install uv

# Create and activate virtual environment
uv venv
source .venv/bin/activate

# Install FastMCP
uv pip install fastmcp
```

### Option 2: Linux[pip] 

```bash
# Install system dependencies
sudo apt update
sudo apt install python3 python3-venv python3-pip

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install FastMCP
pip install fastmcp
```

## Usage

### Standard Installation

```bash
fastmcp install pearch_mcp.py --name "Pearch.ai" --env-var PEARCH_API_KEY=pearch_mcp_key
```

### Development Mode

For local development and testing:

```bash
# Set your API key
export PEARCH_API_KEY='your-api-key-here'

# Start development server
fastmcp dev pearch_mcp.py
```

## Support

If you encounter any issues or have questions:
- Open an issue in the repository
- Contact support at [f@pearch.ai](mailto:f@pearch.ai)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
