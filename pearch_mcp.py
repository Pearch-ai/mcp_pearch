from fastmcp import FastMCP
import os
import urllib.request
import urllib.parse
import json
from typing import List, Dict, Any

mcp = FastMCP("Pearch_MCP")

@mcp.tool()
def search_people(
    query: str,
    search_type: str = "fast",
    limit: int = 5,
    timeout: int = 1800
) -> List[Dict[str, Any]]:
    api_key = os.environ.get("PEARCH_API_KEY")
    if not api_key:
        raise ValueError("PEARCH_API_KEY environment variable is not set")
        
    base_url = "https://api.pearch.ai/v1/search"
    params = {
        "query": query,
        "type": search_type,
        "limit": limit,
        "timeout": timeout
    }
    url = base_url + "?" + urllib.parse.urlencode(params)
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        if resp.getcode() != 200:
            raise RuntimeError(f"HTTP {resp.getcode()}")
        return json.load(resp)

if __name__ == "__main__":
    mcp.run()