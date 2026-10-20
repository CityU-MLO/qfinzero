"""Build the API reference of the documentation hub (``docs/api/reference.json``).

The web hub (``/docs/api/…``, ``/docs/mcp/…``) renders endpoint and tool pages
from one JSON file generated from the sources of truth:

* UPQ (Rust): ``docs/upq/openapi.yaml``, kept by hand next to the handlers;
* ESP and PMB (FastAPI): ``app.openapi()`` of each service, each loaded in its
  own interpreter because both are a top-level ``main`` module;
* MCP: the tools registered on ``mcp/server.py`` with their input schemas,
  argument descriptions taken from the docstrings.

Schemas are flattened for display: parameters and top-level body fields with
type, required flag, default, enum and description, plus a generated example.

    python -m qfinzero.docsgen            # rewrite docs/api/reference.json
    python -m qfinzero.docsgen --check    # exit 1 if it is out of date
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "docs" / "api" / "reference.json"

# service -> (title, hub base path, grouping of paths, intro)
SERVICES: dict[str, dict[str, Any]] = {
    "upq": {
        "title": {"en": "Market data (UPQ)", "zh": "行情数据（UPQ）"},
        "base": "/svc/upq", "scope": "market-data",
        "summary": {"en": "Bars, quotes, option chains, futures, crypto, FX, rates and dividends from the QFZ store.",
                    "zh": "来自 QFZ 存储的 K 线、报价、期权链、期货、加密货币、外汇、利率和分红。"},
        "groups": [("Stocks", ("/stock",)), ("Options", ("/option",)), ("Futures", ("/future",)),
                   ("Crypto", ("/crypto",)), ("FX", ("/fx",)),
                   ("Rates and dividends", ("/rates", "/dividends")), ("Service", ("/health",))],
    },
    "esp": {
        "title": {"en": "Events and news (ESP)", "zh": "事件与新闻（ESP）"},
        "base": "/svc/esp", "scope": "events",
        "summary": {"en": "Point-in-time news, earnings and macro calendars, event streams and timelines.",
                    "zh": "按时点可见的新闻、财报与宏观日历、事件流和时间线。"},
        "groups": [("Events", ("/esp/events", "/esp/timeline", "/esp/triggers")), ("News", ("/esp/news",)),
                   ("Calendars", ("/esp/calendar",)), ("Service", ("/esp/health", "/esp/admin"))],
    },
    "pmb": {
        "title": {"en": "Paper broker (PMB)", "zh": "模拟券商（PMB）"},
        "base": "/svc/pmb", "scope": "trading",
        "summary": {"en": "Accounts, orders, positions, trading sessions with a simulated clock, margin.",
                    "zh": "账户、订单、持仓、带模拟时钟的交易会话以及保证金。"},
        "groups": [("Accounts", ("/v1/accounts",)), ("Orders", ("/v1/orders",)),
                   ("Sessions", ("/v1/sessions",)), ("Service", ("/v1/health", "/v1/config", "/"))],
    },
}

MCP_GROUPS = [("upq_crypto", "Crypto"), ("upq_fx", "FX"), ("upq_", "Market data"), ("data_", "Data coverage"),
              ("market_", "Calendar"), ("research_", "Research"), ("esp_", "Events and news"), ("pmb_", "Paper broker"),
              ("admin_", "Data administration")]

METHODS = ("get", "post", "put", "patch", "delete")


# ── schema helpers ────────────────────────────────────────────────────────

def _resolve(spec: dict, node: Any, depth: int = 0) -> Any:
    if not isinstance(node, dict) or depth > 12:
        return node
    if "$ref" in node:
        ref = node["$ref"]
        target: Any = spec
        for part in ref.lstrip("#/").split("/"):
            target = target.get(part, {}) if isinstance(target, dict) else {}
        return _resolve(spec, {**target, **{k: v for k, v in node.items() if k != "$ref"}}, depth + 1)
    for key in ("anyOf", "oneOf", "allOf"):
        if key in node:
            options = [_resolve(spec, x, depth + 1) for x in node[key]]
            real = [o for o in options if o.get("type") != "null"]
            if key == "allOf":
                merged: dict = {}
                for o in options:
                    merged.update({k: v for k, v in o.items() if k != "properties"})
                    merged.setdefault("properties", {}).update(o.get("properties", {}))
                    merged["required"] = sorted({*merged.get("required", []), *o.get("required", [])})
                rest = {k: v for k, v in node.items() if k != key}
                return {**merged, **rest}
            base = {k: v for k, v in node.items() if k != key}
            if len(real) == 1:
                return {**real[0], **base, "nullable": len(real) < len(options)}
            return {**base, "type": " | ".join(_type(o) for o in real) or "any",
                    "nullable": len(real) < len(options), "_variants": real}
    return node


def _type(s: dict) -> str:
    t = s.get("type")
    if isinstance(t, list):
        t = " | ".join(x for x in t if x != "null")
    if t == "array":
        return f"{_type(s.get('items') or {})}[]"
    if s.get("enum") and not t:
        t = "string"
    if s.get("format") in ("date", "date-time"):
        return f"string ({s['format']})"
    return str(t or ("object" if "properties" in s else "any"))


# example values by field name, for schemas that carry none
GUESS = [(r"^tickers$", "AAPL,MSFT"), (r"^(ticker|symbol|underlying)$", "AAPL"), (r"session_id$", "sess_1"),
         (r"account_id$", "acc_1"), (r"order_id$", "ord_1"), (r"(^|_)start", "2025-01-02"), (r"(^|_)end", "2025-01-10"),
         (r"date$", "2025-01-02"), (r"^(qty|quantity)$", 10), (r"^limit$", 100), (r"^(q|query|text)$", "earnings")]


def _guess(name: Optional[str]) -> Any:
    for pat, v in GUESS:
        if name and re.search(pat, name):
            return v
    return None


def _example(spec: dict, s: Any, depth: int = 0, name: Optional[str] = None) -> Any:
    """An example value: the schema's own, else a guess from the field name.
    Objects keep required fields and fields with an example or default."""
    s = _resolve(spec, s)
    if not isinstance(s, dict) or depth > 5:
        return None
    for k in ("example", "default"):
        if s.get(k) is not None:
            return s[k]
    if s.get("examples"):
        ex = s["examples"]
        return ex[0] if isinstance(ex, list) else next(iter(ex.values()), {}).get("value")
    if s.get("enum"):
        return s["enum"][0]
    if "_variants" in s:
        return _example(spec, s["_variants"][0], depth + 1, name)
    t = s.get("type")
    if t == "object" or "properties" in s:
        req = set(s.get("required") or [])
        out = {}
        for k, v in (s.get("properties") or {}).items():
            r = _resolve(spec, v)
            if (k in req or any(r.get(x) is not None for x in ("example", "default"))
                    or (depth > 0 and k in ("symbol", "ticker"))):
                out[k] = _example(spec, r, depth + 1, k)
        return out
    if t == "array":
        item = _example(spec, s.get("items") or {}, depth + 1, name)
        return [item] if item is not None else []
    g = _guess(name)
    if g is not None:
        return g
    if s.get("format") == "date":
        return "2025-01-02"
    if s.get("format") == "date-time":
        return "2025-01-02T14:30:00Z"
    return {"string": "string", "integer": 0, "number": 0.0, "boolean": False}.get(t)


def _fields(spec: dict, schema: Any, depth: int = 0) -> list[dict]:
    """Top-level fields, with one nested level for object fields (``children``)."""
    s = _resolve(spec, schema or {})
    req = set(s.get("required") or [])
    out = []
    for name, sub in (s.get("properties") or {}).items():
        r = _resolve(spec, sub)
        f = _field(name, r, name in req)
        if depth < 2 and r.get("properties"):
            f["children"] = _fields(spec, r, depth + 1)
            f["type"] = "object"
        out.append(f)
    return out


def _noise(name: str, text: str) -> bool:
    """FastAPI titles that only repeat the field or schema name."""
    t = text.strip()
    return not t or t.lower() == name.replace("_", " ").lower() or bool(re.fullmatch(r"[A-Z][A-Za-z0-9]+", t))


def _field(name: str, r: dict, required: bool, where: Optional[str] = None) -> dict:
    desc = (r.get("description") or "").strip()
    if not desc and not _noise(name, r.get("title") or ""):
        desc = r["title"].strip()
    f = {"name": name, "type": _type(r), "required": required, "description": desc}
    if where:
        f["in"] = where
    for k in ("default", "enum", "example"):
        if r.get(k) is not None:
            f[k] = r[k]
    if r.get("nullable"):
        f["nullable"] = True
    if r.get("minimum") is not None or r.get("maximum") is not None:
        f["range"] = [r.get("minimum"), r.get("maximum")]
    return f


def _slug(method: str, path: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", f"{method}-{path}".lower())).strip("-")


def endpoints(service: str, spec: dict) -> list[dict]:
    conf = SERVICES[service]
    out = []
    for path, item in sorted((spec.get("paths") or {}).items()):
        for method in METHODS:
            op = item.get(method)
            if not op:
                continue
            params = [_field(p["name"], _resolve(spec, p.get("schema") or {}) | (
                {"description": p["description"]} if p.get("description") else {}) | (
                {"example": p["example"]} if p.get("example") is not None else {}),
                bool(p.get("required")), p.get("in"))
                for p in (_resolve(spec, x) for x in (item.get("parameters", []) + op.get("parameters", [])))]
            body = None
            rb = _resolve(spec, op.get("requestBody") or {})
            js = (rb.get("content") or {}).get("application/json")
            if js:
                fields = _fields(spec, js.get("schema"))
                example = js.get("example")
                if example is None:
                    example = _example(spec, js.get("schema"))
                body = {"fields": fields, "required": bool(rb.get("required")), "example": example}
            responses = []
            for status, r in (op.get("responses") or {}).items():
                r = _resolve(spec, r)
                c = (r.get("content") or {}).get("application/json") or {}
                ex = c.get("example")
                if ex is None and c.get("schema") and str(status).startswith("2"):
                    ex = _example(spec, c["schema"])
                responses.append({"status": str(status), "description": (r.get("description") or "").strip(),
                                  **({"example": ex} if ex is not None else {})})
            group = next((g for g, prefixes in conf["groups"] if any(
                path == p or path.startswith(p.rstrip("/") + "/") or (p == "/" and path == "/") for p in prefixes)),
                (op.get("tags") or ["Other"])[0].replace("_", " ").title())
            desc = (op.get("description") or "").strip()
            summary = (op.get("summary") or "").strip() or desc.split("\n")[0][:80] or f"{method.upper()} {path}"
            out.append({"id": _slug(method, path), "method": method.upper(), "path": path, "group": group,
                        "summary": summary, "description": desc if desc != summary else "",
                        "params": params, "body": body, "responses": responses,
                        "deprecated": bool(op.get("deprecated"))})
    order = [g for g, _ in conf["groups"]]
    out.sort(key=lambda e: (order.index(e["group"]) if e["group"] in order else len(order), e["path"], e["method"]))
    return out


# ── loading the specs ─────────────────────────────────────────────────────

def _fastapi_spec(service_dir: Path) -> dict:
    code = ("import json, sys; sys.path.insert(0, '.'); from main import app; "
            "sys.stdout.write(json.dumps(app.openapi()))")
    r = subprocess.run([sys.executable, "-c", code], cwd=service_dir, capture_output=True, text=True, timeout=180,
                       env={**__import__("os").environ, "PYTHONPATH": str(REPO)})
    if r.returncode != 0:
        raise RuntimeError(f"{service_dir.name}: {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout[r.stdout.index("{"):])


def _mcp_tools() -> list[dict]:
    code = r"""
import asyncio, importlib.util, json, sys
spec = importlib.util.spec_from_file_location("_qfz_mcp_docs", "mcp/server.py")
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
tools = asyncio.run(mod.mcp.list_tools())
sys.stdout.write("\n@@JSON@@" + json.dumps([{"name": t.name, "description": t.description or "",
    "schema": t.inputSchema} for t in tools]))
"""
    r = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or "@@JSON@@" not in r.stdout:
        raise RuntimeError(f"mcp: {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout.split("@@JSON@@", 1)[1])


def _docstring(doc: str) -> tuple[str, dict[str, str], str]:
    """(summary, {arg: description}, returns) from a Google-style docstring."""
    lines = doc.strip("\n").split("\n")
    body, args, ret, mode, cur = [], {}, [], "body", None
    for raw in lines:
        line = raw.rstrip()
        if line.strip() in ("Args:", "Arguments:", "Parameters:"):
            mode = "args"
            continue
        if line.strip() in ("Returns:", "Return:"):
            mode = "ret"
            continue
        if mode == "args":
            m = re.match(r"^\s{2,}(\w+)\s*(?:\([^)]*\))?:\s*(.*)$", line)
            if m and len(raw) - len(raw.lstrip()) <= 8:
                cur = m.group(1)
                args[cur] = m.group(2).strip()
            elif cur and line.strip():
                args[cur] += " " + line.strip()
            elif not line.strip():
                cur = None
            continue
        if mode == "ret":
            if line.strip():
                ret.append(line.strip())
            continue
        body.append(line)
    return "\n".join(body).strip(), args, " ".join(ret)


def mcp_reference(tools: list[dict]) -> list[dict]:
    out = []
    for t in tools:
        summary, args, ret = _docstring(t["description"])
        schema = t["schema"] or {}
        req = set(schema.get("required") or [])
        params = []
        for name, sub in (schema.get("properties") or {}).items():
            r = _resolve(schema, sub)
            f = _field(name, r, name in req)
            f["description"] = args.get(name, f["description"])
            if f["description"] == r.get("title"):
                f["description"] = ""
            params.append(f)
        example = {p["name"]: p.get("example", p.get("default", _example(schema, (schema.get("properties") or {})[p["name"]],
                                                                          name=p["name"])))
                   for p in params if p["required"]}
        group = next((g for pre, g in MCP_GROUPS if t["name"].startswith(pre)), "Other")
        first, _, rest = summary.partition("\n\n")
        out.append({"name": t["name"], "group": group, "summary": first.replace("\n", " ").strip(),
                    "description": rest.strip(), "params": params, "returns": ret, "example": example})
    order = [g for _, g in MCP_GROUPS]
    out.sort(key=lambda x: (order.index(x["group"]) if x["group"] in order else 9, x["name"]))
    return out


def build() -> dict:
    import yaml

    specs = {"upq": yaml.safe_load((REPO / "docs/upq/openapi.yaml").read_text()),
             "esp": _fastapi_spec(REPO / "infra/esp"),
             "pmb": _fastapi_spec(REPO / "infra/pmb")}
    services = []
    for sid, conf in SERVICES.items():
        spec = specs[sid]
        info = spec.get("info") or {}
        version = str(info.get("version", ""))
        if version.startswith("qfinzero:"):      # git-derived: changes with every commit
            version = ""
        services.append({"id": sid, "title": conf["title"], "summary": conf["summary"], "base": conf["base"],
                         "scope": conf["scope"], "version": version,
                         "intro": (info.get("description") or "").strip(),
                         "endpoints": endpoints(sid, spec)})
    return {"_comment": "Generated by `python -m qfinzero.docsgen`; do not edit.",
            "services": services, "mcp": mcp_reference(_mcp_tools())}


def render(ref: dict) -> str:
    return json.dumps(ref, indent=1, ensure_ascii=False, sort_keys=False) + "\n"


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="qfz-docs", description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="fail if docs/api/reference.json is out of date")
    args = ap.parse_args(argv)
    text = render(build())
    if args.check:
        same = OUT.is_file() and OUT.read_text() == text
        print("up to date" if same else f"{OUT.relative_to(REPO)} is out of date; run python -m qfinzero.docsgen")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    ref = json.loads(text)
    print(f"wrote {OUT.relative_to(REPO)}: " + ", ".join(f"{s['id']} {len(s['endpoints'])}" for s in ref["services"])
          + f", mcp {len(ref['mcp'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
