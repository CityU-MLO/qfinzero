"""Run the QFinZero hub:  python -m qfinzero.server   (or the ``qfz-server`` script)."""

from __future__ import annotations

import logging

import uvicorn

from qfinzero import config
from .app import app


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
    )
    log = logging.getLogger("qfz.server")
    log.info("QFinZero hub on http://%s:%s  (UI /, REST /api/*, MCP /mcp)",
             config.SERVER_HOST, config.SERVER_PORT)
    uvicorn.run(app, host=config.SERVER_HOST, port=config.SERVER_PORT, access_log=False)


if __name__ == "__main__":
    main()
