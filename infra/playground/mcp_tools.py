"""Load QFinZero MCP tools via stdio connection to mcp/server.py."""

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config import MCP_SERVER_PATH, UPQ_URL, NPP_URL, PMB_URL


def get_mcp_server_params() -> StdioServerParameters:
    """Build stdio params to launch mcp/server.py as a subprocess."""
    return StdioServerParameters(
        command=sys.executable,
        args=[MCP_SERVER_PATH],
        env={
            **os.environ,
            "QFINZERO_UPQ_URL": UPQ_URL,
            "QFINZERO_NPP_URL": NPP_URL,
            "QFINZERO_PMB_URL": PMB_URL,
        },
    )


@asynccontextmanager
async def get_tools() -> AsyncIterator[list]:
    """Connect to mcp/server.py, yield tools, then close the session."""
    params = get_mcp_server_params()
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            yield tools
