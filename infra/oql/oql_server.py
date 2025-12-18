"""
OQL Query Server

A Flask-based HTTP service that executes OQL queries and returns:
- JSONL-encoded table output
- Metadata including runtime, as-of date, server time, and original query

Endpoints:
  GET  /health
  POST /query
  POST /valid
"""

import os
import time
import json
import logging
from datetime import datetime
from typing import Any, Optional, Tuple

import pandas as pd
from flask import Flask, request, jsonify

from executor.data_client import OptionDataClient
from executor.executor import OQLEngine
from parsing.parser import parse_query  # adjust to your real parser import
from executor.executor import STRATEGY_REGISTRY


# ---------------------- Logging Setup ----------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("oql_server")


# ---------------------- Config ----------------------
DATA_HOST = os.getenv("OQL_DATA_HOST", "127.0.0.1")
DATA_PORT = int(os.getenv("OQL_DATA_PORT", "19787"))
ENGINE_VERSION = "v1"

# Hard timeout: if query runs longer, kill it (prevents client-cancel runaway)
QUERY_TIMEOUT_S = float(os.getenv("OQL_QUERY_TIMEOUT_S", "60"))

# Optional: limit response rows to avoid returning huge payloads
MAX_ROWS = int(os.getenv("OQL_MAX_ROWS", "5000"))

# Optional: child process memory cap (Linux). If unset/0 => disabled.
# Example: export OQL_QUERY_MAX_MEM_MB=4096
MAX_MEM_MB = int(os.getenv("OQL_QUERY_MAX_MEM_MB", "80960"))

# Multiprocessing start method: "spawn" is safest with libs/sockets/threads.
MP_START_METHOD = os.getenv("OQL_MP_START_METHOD", "spawn")


# ---------------------- Flask App ----------------------
app = Flask(__name__)


def _now_utc_iso() -> str:
    """Return current UTC time in ISO-8601 format with Z suffix."""
    return datetime.utcnow().isoformat() + "Z"


def _default_as_of_date() -> str:
    """Return default as-of date (today, in UTC)."""
    return datetime.utcnow().strftime("%Y-%m-%d")


def dataframe_to_jsonl(df: pd.DataFrame) -> str:
    """
    Convert a DataFrame into JSON Lines format.

    NOTE:
    - pandas.to_json handles numpy dtypes and missing values much better than json.dumps(df.to_dict()).
    """
    return df.to_json(
        orient="records",
        lines=True,
        force_ascii=False,
        date_format="iso",
    )


def _validate_ast_semantics(ast) -> None:
    # 1) strategy exists
    if ast.strategy not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy: {ast.strategy}. Supported={sorted(STRATEGY_REGISTRY.keys())}"
        )

    # 2) basic FROM underlying check
    if not getattr(ast, "underlying", None):
        raise ValueError("Missing FROM <UNDERLYING>")


# ---------------------- Hard-timeout Execution (Process Kill) ----------------------
def _maybe_set_mem_limit(max_mem_mb: int) -> None:
    """
    Best-effort memory cap for the child process (Linux only).
    If not supported, it silently does nothing.
    """
    if max_mem_mb <= 0:
        return
    try:
        import resource  # Linux/Unix
        limit = max_mem_mb * 1024 * 1024
        # Address space limit (virtual memory). Helps prevent worst-case RAM blowups.
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        # Don't crash worker just because limits can't be set
        print("Warning: unable to set memory limit for worker process")
        pass


def _exec_worker(query: str, as_of_date: str, out_q) -> None:
    """
    Runs in a child process.
    IMPORTANT: create OptionDataClient/OQLEngine inside child so killing the child truly stops work.
    """
    _maybe_set_mem_limit(MAX_MEM_MB)

    try:
        data_client = OptionDataClient(host=DATA_HOST, port=DATA_PORT)
        engine = OQLEngine(data_client=data_client)

        result = engine.execute(query, as_of_date=as_of_date)

        if isinstance(result, pd.DataFrame):
            df = result
            if MAX_ROWS > 0 and len(df) > MAX_ROWS:
                df = df.head(MAX_ROWS)

            jsonl = dataframe_to_jsonl(df)
            out_q.put(("ok_df", jsonl, int(len(df)), None))

        elif isinstance(result, str):
            out_q.put(("ok_msg", "", 0, result))

        else:
            out_q.put(("err", "", 0, f"Unexpected return type: {type(result).__name__}"))

    except Exception as e:
        out_q.put(("err", "", 0, str(e)))


def run_with_hard_timeout(
    query: str, as_of_date: str, timeout_s: float
) -> Tuple[bool, str, int, Optional[str], bool]:
    """
    Returns:
      ok, data_jsonl, rows, message_or_error, is_timeout

    If timeout happens, the child process is terminated.
    This is the key fix for "client cancels but backend still runs + eats memory".
    """
    import multiprocessing as mp

    ctx = mp.get_context(MP_START_METHOD)
    out_q = ctx.Queue(maxsize=1)
    p = ctx.Process(target=_exec_worker, args=(query, as_of_date, out_q), daemon=True)

    p.start()
    p.join(timeout_s)

    if p.is_alive():
        # Hard kill
        p.terminate()
        p.join(1)
        return False, "", 0, f"Query timeout after {timeout_s:.1f}s (killed worker process)", True

    try:
        tag, jsonl, rows, msg = out_q.get_nowait()
    except Exception:
        return False, "", 0, "Worker exited without returning result", False

    if tag == "ok_df":
        return True, jsonl, rows, None, False
    if tag == "ok_msg":
        return True, "", 0, msg, False

    return False, "", 0, msg, False


# ---------------------- API Endpoints ----------------------
@app.post("/valid")
def valid():
    t0 = time.time()
    payload = request.get_json(silent=True) or {}

    query = payload.get("query", "")
    as_of_date = payload.get("as_of_date", None)

    meta = {
        "ok": False,
        "engine_version": ENGINE_VERSION,
        "elapsed_ms": 0.0,
        "error": None,
    }

    if not isinstance(query, str) or not query.strip():
        meta["error"] = "Missing or invalid 'query'"
        meta["elapsed_ms"] = (time.time() - t0) * 1000
        return jsonify({"data": "", "meta": meta}), 400

    if as_of_date is not None:
        if not isinstance(as_of_date, str):
            meta["error"] = "Invalid 'as_of_date' (expected string YYYY-MM-DD)"
            meta["elapsed_ms"] = (time.time() - t0) * 1000
            return jsonify({"data": "", "meta": meta}), 400
        try:
            datetime.strptime(as_of_date, "%Y-%m-%d")
        except ValueError:
            meta["error"] = "Invalid 'as_of_date' (expected YYYY-MM-DD)"
            meta["elapsed_ms"] = (time.time() - t0) * 1000
            return jsonify({"data": "", "meta": meta}), 400

    try:
        ast = parse_query(query)  # parse only
        # _validate_ast_semantics(ast)  # optional semantic checks

        meta["ok"] = True
        meta["elapsed_ms"] = (time.time() - t0) * 1000
        return jsonify({"meta": meta}), 200

    except Exception as e:
        meta["error"] = str(e)
        meta["elapsed_ms"] = (time.time() - t0) * 1000
        # keep 200 so client always reads meta.ok
        return jsonify({"data": "", "meta": meta}), 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "server_time": _now_utc_iso()}), 200


@app.route("/query", methods=["POST"])
def run_query():
    t0 = time.time()
    server_time = _now_utc_iso()

    payload = request.get_json(silent=True) or {}
    query = payload.get("query")
    as_of_date = payload.get("as_of_date") or _default_as_of_date()

    # Optional per-request timeout override (still capped by server env if you want)
    timeout_s = payload.get("timeout_s")
    if timeout_s is None:
        timeout_s = QUERY_TIMEOUT_S
    else:
        try:
            timeout_s = float(timeout_s)
        except Exception:
            timeout_s = QUERY_TIMEOUT_S

    if not query or not isinstance(query, str):
        meta = {
            "ok": False,
            "error": "Missing or invalid 'query'",
            "rows": 0,
            "elapsed_ms": (time.time() - t0) * 1000.0,
            "as_of_date": as_of_date,
            "server_time": server_time,
            "origin_query": query,
            "engine_version": ENGINE_VERSION,
        }
        return jsonify({"meta": meta, "data": ""}), 400

    logger.info(f"Received query (as_of_date={as_of_date}, timeout_s={timeout_s}): {query!r}")

    # Execute with HARD timeout + process kill (prevents runaway after client timeout/cancel)
    ok, jsonl_str, rows, msg_or_err, is_timeout = run_with_hard_timeout(
        query=query,
        as_of_date=as_of_date,
        timeout_s=timeout_s,
    )
    elapsed_ms = (time.time() - t0) * 1000.0

    if ok:
        meta: dict[str, Any] = {
            "ok": True,
            "error": None,
            "rows": int(rows),
            "elapsed_ms": elapsed_ms,
            "as_of_date": as_of_date,
            "server_time": server_time,
            "origin_query": query,
            "engine_version": ENGINE_VERSION,
        }
        if msg_or_err is not None and rows == 0 and jsonl_str == "":
            meta["message"] = msg_or_err
        return jsonify({"meta": meta, "data": jsonl_str}), 200

    meta = {
        "ok": False,
        "error": msg_or_err,
        "rows": 0,
        "elapsed_ms": elapsed_ms,
        "as_of_date": as_of_date,
        "server_time": server_time,
        "origin_query": query,
        "engine_version": ENGINE_VERSION,
    }
    # 504 for timeout, 500 otherwise
    status = 504 if is_timeout else 500
    return jsonify({"meta": meta, "data": ""}), status


# ---------------------- Local Development Entry ----------------------
if __name__ == "__main__":
    """
    For development:
        python oql_server.py

    For production (recommended):
        gunicorn -w 4 -k gthread --threads 8 -b 0.0.0.0:19777 --timeout 120 oql_server:app
    """
    port = int(os.getenv("OQL_SERVER_PORT", "19777"))
    app.run(host="0.0.0.0", port=port, threaded=True)
