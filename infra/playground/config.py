import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from this directory (ignored by git, machine-specific overrides)
load_dotenv(Path(__file__).parent / ".env")

PORT = int(os.environ.get("PLAYGROUND_PORT", "19310"))
HOST = os.environ.get("PLAYGROUND_HOST", "0.0.0.0")

# Path to mcp/server.py relative to project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
MCP_SERVER_PATH = str(PROJECT_ROOT / "mcp" / "server.py")

# Backend service URLs — defaults are production ports (19350/19330/19320).
# Override in infra/playground/.env for dev (e.g. QFINZERO_NPP_URL=http://127.0.0.1:19702).
UPQ_URL = os.environ.get("QFINZERO_UPQ_URL", "http://127.0.0.1:19350")
NPP_URL = os.environ.get("QFINZERO_NPP_URL", "http://127.0.0.1:19330")
PMB_URL = os.environ.get("QFINZERO_PMB_URL", "http://127.0.0.1:19320")

REQUEST_TIMEOUT_S = int(os.environ.get("PLAYGROUND_TIMEOUT_S", "120"))
