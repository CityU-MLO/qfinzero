"""Load QFinZero MCP tools via stdio connection to mcp/server.py.

A thread's cutoff becomes the MCP server's fixed time lock (QFZ_TIME_LOCK_AS_OF),
so every data tool is capped at it whatever the model asks for.
"""

import os
import sys
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langchain_mcp_adapters.tools import load_mcp_tools
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from config import MCP_SERVER_PATH, UPQ_URL, ESP_URL, PMB_URL


def get_mcp_server_params(as_of: str | None = None) -> StdioServerParameters:
    """Build stdio params to launch mcp/server.py as a subprocess, time-locked at ``as_of``."""
    env = {k: v for k, v in os.environ.items() if k != "QFZ_TIME_LOCK_AS_OF"}
    env.update({"QFINZERO_UPQ_URL": UPQ_URL, "QFINZERO_ESP_URL": ESP_URL, "QFINZERO_PMB_URL": PMB_URL})
    if as_of:
        env["QFZ_TIME_LOCK_AS_OF"] = as_of
    return StdioServerParameters(command=sys.executable, args=[MCP_SERVER_PATH], env=env)


@asynccontextmanager
async def get_tools(as_of: str | None = None) -> AsyncIterator[list]:
    """Connect to mcp/server.py (locked at ``as_of``), yield tools, then close the session."""
    params = get_mcp_server_params(as_of)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await load_mcp_tools(session)
            yield tools
