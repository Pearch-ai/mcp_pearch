# Pearch.ai MCP

Pearch.ai MCP is a FastMCP service that enables powerful people search capabilities through the Pearch.ai. This service allows you to integrate advanced people search functionality into your applications.


## Prerequisites

- Python 3.7 or newer
- Pearch.ai API key
- FastMCP package

## API Key Setup

1. Visit [Pearch.ai Dashboard](https://s.pearch.ai/) to obtain your API key
2. For testing purposes, you can use the test key: `pearch_mcp_key`
3. Set your API key as an environment variable:
   ```bash
   export PEARCH_API_KEY='your-api-key-here'
   ```

## Installation

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

## Contributing

We welcome contributions! Here's how you can help:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

Please ensure your code follows our coding standards and includes appropriate tests.

## Support

If you encounter any issues or have questions:
- Open an issue in the repository
- Contact support at [support@pearch.ai](mailto:support@pearch.ai)

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.