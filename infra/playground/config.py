import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from qfinzero.config import (
    PLAYGROUND_PORT,
    LLM_PROXY as DEFAULT_LLM_PROXY,
    PMB_URL as DEFAULT_PMB_URL,
    ESP_URL as DEFAULT_ESP_URL,
    UPQ_URL as DEFAULT_UPQ_URL,
)

PORT = int(os.environ.get("PLAYGROUND_PORT", str(PLAYGROUND_PORT)))
HOST = os.environ.get("PLAYGROUND_HOST", "0.0.0.0")

# Outbound proxy for LLM API calls (see qfinzero.config.LLM_PROXY). A per-request
# `proxy` field, when present, overrides this server default.
LLM_PROXY = os.environ.get("LLM_PROXY", DEFAULT_LLM_PROXY)

# Path to mcp/server.py relative to project root
MCP_SERVER_PATH = str(PROJECT_ROOT / "mcp" / "server.py")

UPQ_URL = os.environ.get("QFINZERO_UPQ_URL", DEFAULT_UPQ_URL)
ESP_URL = os.environ.get("QFINZERO_ESP_URL", DEFAULT_ESP_URL)
PMB_URL = os.environ.get("QFINZERO_PMB_URL", DEFAULT_PMB_URL)

REQUEST_TIMEOUT_S = int(os.environ.get("PLAYGROUND_TIMEOUT_S", "120"))
