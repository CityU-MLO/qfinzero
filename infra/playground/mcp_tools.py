"""Load QFinZero MCP tools via stdio connection to mcp/server.py."""

import sys
from langchain_mcp_adapters.tools import MCPToolkit
from mcp import StdioServerParameters
from config import MCP_SERVER_PATH, UPQ_URL, NPP_URL, PMB_URL


def get_mcp_server_params() -> StdioServerParameters:
    """Build stdio params to launch mcp/server.py as a subprocess."""
    return StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env={
            "QFINZERO_UPQ_URL": UPQ_URL,
            "QFINZERO_NPP_URL": NPP_URL,
            "QFINZERO_PMB_URL": PMB_URL,
        },
    )


async def load_tools() -> list:
    """Connect to mcp/server.py and return all tools as LangChain tools."""
    params = get_mcp_server_params()
    toolkit = MCPToolkit(server_params=params)
    await toolkit.initialize()
    return toolkit.get_tools()
