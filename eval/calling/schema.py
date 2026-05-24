"""
QFinZero Tool Calling Evaluation — Output Schema & System Prompt
=================================================================

Defines:
1. The strict JSON schema that models must output.
2. The system prompt template used to instruct models.
3. Parsing / validation utilities.
"""

from __future__ import annotations

import json
import re
from typing import Any

# ---------------------------------------------------------------------------
# Output Schema (for reference & validation)
# ---------------------------------------------------------------------------
# Models must return EXACTLY this structure. No markdown fences, no extra text.
#
# {
#   "tool_plan": [
#     {
#       "tool_name": "UPQ.stock.daily",
#       "method": "GET",
#       "endpoint": "/stock/daily",
#       "params": {
#         "tickers": "AAPL",
#         "start": "2025-01-06",
#         "end": "2025-01-31"
#       }
#     }
#   ],
#   "final_answer": {
#     "summary": "Short summary of what the tool calls achieve.",
#     "citations": [],
#     "assumptions": ["Assumed regular trading hours 09:30-16:00 ET."]
#   }
# }

OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["tool_plan", "final_answer"],
    "properties": {
        "tool_plan": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["tool_name", "method", "endpoint", "params"],
                "properties": {
                    "tool_name": {"type": "string"},
                    "method": {"type": "string", "enum": ["GET", "POST"]},
                    "endpoint": {"type": "string"},
                    "params": {"type": "object"},
                },
            },
        },
        "final_answer": {
            "type": "object",
            "required": ["summary"],
            "properties": {
                "summary": {"type": "string"},
                "citations": {"type": "array", "items": {"type": "string"}},
                "assumptions": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Tool registry (available tools description for the system prompt)
# ---------------------------------------------------------------------------
TOOL_REGISTRY = """\
Available QFinZero tools:

=== UPQ (Unified Price Query) ===
1. UPQ.stock.minute
   GET /stock
   Params: tickers (str, comma-sep), start (ISO datetime), end (ISO datetime)
   Optional: fields (str, comma-sep), limit (int)
   Returns: minute OHLCV bars.

2. UPQ.stock.daily
   GET /stock/daily
   Params: tickers (str, comma-sep), start (date YYYY-MM-DD), end (date YYYY-MM-DD)
   Optional: fields (str, comma-sep)
   Returns: daily OHLCV bars.

3. UPQ.option.chain_query
   GET /option/chain_query
   Params: underlying (str), date (date YYYY-MM-DD)
   Optional: expiry_min (date), expiry_max (date), strike_min (float), strike_max (float), type ("C"|"P"), fields (str)
   Returns: option chain snapshot.

4. UPQ.option.ticker_query
   GET /option/ticker_query
   Params: contract (OPRA str, e.g. "O:NVDA250117C00136000"), start (date or datetime), end (date or datetime)
   Optional: resolution ("day"|"minute"), fields (str)
   Returns: price history for a single option contract.

5. UPQ.rates.query
   GET /rates/query
   Params: start (date), end (date)
   Optional: tenors (str, comma-sep from: 1M,3M,1Y,2Y,5Y,10Y,30Y; default=all)
   Returns: Treasury yield curve data.

=== ESP (News Pushing Pipeline) ===
6. ESP.events.query
   POST /esp/events/query
   Body: mode ("upcoming"|"just_happened"|"window"), event_types (list from: macro_calendar, earnings, breaking_news, daily_news)
   Optional: start_utc (ISO-UTC), end_utc (ISO-UTC), horizon_minutes (int), tickers (list), min_importance ("low"|"medium"|"high"), limit (int), cursor (str), view ("compact"|"full"), now_utc (ISO-UTC)
   Returns: list of events with pagination.

7. ESP.events.get
   GET /esp/events/{event_id}
   Returns: single event by ID.

8. ESP.events.stream
   POST /esp/events/stream
   Body: cursor (str), event_types (list), tickers (list), limit (int), now_utc (ISO-UTC)
   Returns: incremental event updates from cursor.

9. ESP.triggers.next
   POST /esp/triggers/next
   Body: tickers (list), min_importance (str), horizon_minutes (int), limit (int), now_utc (ISO-UTC)
   Returns: next trigger events for agent wakeup.

10. ESP.timeline
    POST /esp/timeline
    Body: tickers (list), start_utc (ISO-UTC), end_utc (ISO-UTC), bucket_minutes (int), now_utc (ISO-UTC)
    Returns: events bucketed by time interval.

11. ESP.calendar.econ
    POST /esp/calendar/econ
    Body: start_date (date), end_date (date), min_importance ("low"|"medium"|"high")
    Optional: limit (int), cursor (str), now_utc (ISO-UTC)
    Returns: economic calendar events.

12. ESP.calendar.earnings
    POST /esp/calendar/earnings
    Body: start_date (date), end_date (date)
    Optional: tickers (list), min_importance (int), limit (int), cursor (str), now_utc (ISO-UTC)
    Returns: earnings calendar events.

13. ESP.news.body
    GET /esp/news/{news_id}/body
    Returns: full news article body.

=== PMB (Paper Money Broker) ===
14. PMB.account.create
    POST /v1/accounts
    Body: base_currency (str), account_type ("MARGIN"|"CASH"), initial_cash (float), timezone (IANA str), start_date (date)
    Optional: constraints (obj), margin_config (obj)
    Returns: new account with account_id.

15. PMB.account.positions
    GET /v1/accounts/{account_id}/positions
    Returns: current positions.

16. PMB.account.orders
    GET /v1/accounts/{account_id}/orders
    Optional query: session_id (str), status_in (str, comma-sep), limit (int)
    Returns: list of orders.

17. PMB.account.trades
    GET /v1/accounts/{account_id}/trades
    Optional query: session_id (str), limit (int)
    Returns: list of executed trades.

18. PMB.session.create
    POST /v1/sessions
    Body: account_id (str), frequency ("1m"|"1d"), start_ts (str), end_ts (str), universe ({stocks: list, options: list})
    Optional: upq (obj), execution_config (obj), reproducibility (obj)
    Returns: new session with session_id.

19. PMB.session.step
    POST /v1/sessions/{session_id}/step
    Body: step (int)
    Optional: target_ts (str)
    Returns: clock state + events.

20. PMB.session.stop
    POST /v1/sessions/{session_id}/stop
    Returns: confirmation.

21. PMB.session.summary
    GET /v1/sessions/{session_id}/summary
    Returns: performance summary.

22. PMB.session.export
    GET /v1/sessions/{session_id}/export
    Optional query: format ("json"|"csv")
    Returns: full session history.

23. PMB.session.market
    GET /v1/sessions/{session_id}/market
    Returns: current market snapshot.

24. PMB.order.place
    POST /v1/orders
    Body: session_id (str), account_id (str), order ({instrument: {type, symbol|contract}, side ("BUY"|"SELL"), order_type ("MARKET"|"LIMIT"|"STOP"|"STOP_LIMIT"), qty (int), limit_price (float, if LIMIT/STOP_LIMIT), stop_price (float, if STOP/STOP_LIMIT), time_in_force ("DAY"|"GTC"|"GTD")})
    Optional: client_order_id (str), expire_ts (str, if GTD)
    Returns: order confirmation.

25. PMB.order.cancel
    POST /v1/orders/{order_id}/cancel
    Body: session_id (str), account_id (str)
    Returns: confirmation.

26. PMB.order.modify
    POST /v1/orders/{order_id}/modify
    Body: session_id (str), account_id (str), updates ({limit_price, qty, ...})
    Returns: updated order.

=== Special ===
- If the user request is impossible or unsupported, return tool_plan as an empty list and explain in final_answer.summary.
"""


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = f"""\
You are a financial tool-calling agent for QFinZero. Your job is to select \
the correct API tools and parameters to fulfill user requests.

RULES:
1. Output ONLY valid JSON. No markdown, no code fences, no explanation outside JSON.
2. Use the exact schema below. Do not add extra fields.
3. Do not include chain-of-thought reasoning. Only output the tool plan.
4. If the request is impossible or unsupported, return an empty tool_plan and explain in final_answer.summary.
5. Use correct date/time formats: dates as YYYY-MM-DD, datetimes as YYYY-MM-DDTHH:MM:SS, UTC datetimes with Z suffix.
6. For multi-step tasks, list tool calls in dependency order (calls that depend on prior results come later).

OUTPUT SCHEMA:
{{
  "tool_plan": [
    {{
      "tool_name": "<tool_name from registry>",
      "method": "GET|POST",
      "endpoint": "<endpoint path>",
      "params": {{<key-value parameters>}}
    }}
  ],
  "final_answer": {{
    "summary": "<short description of what the plan achieves>",
    "citations": [],
    "assumptions": ["<any assumptions made>"]
  }}
}}

{TOOL_REGISTRY}
"""


# ---------------------------------------------------------------------------
# Parsing utilities
# ---------------------------------------------------------------------------

def parse_model_output(raw: str) -> tuple[dict[str, Any] | None, bool, str]:
    """
    Parse raw model output string into structured dict.

    Returns
    -------
    (parsed_dict, json_valid, error_message)
    """
    # Strip common wrapper artifacts
    cleaned = raw.strip()

    # Remove markdown code fences if present
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    # Try direct parse
    try:
        obj = json.loads(cleaned)
        return obj, True, ""
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    brace_start = cleaned.find("{")
    brace_end = cleaned.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        candidate = cleaned[brace_start : brace_end + 1]
        try:
            obj = json.loads(candidate)
            return obj, False, "JSON extracted from surrounding text"
        except json.JSONDecodeError:
            pass

    # Try fixing common issues: trailing commas
    try:
        fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
        obj = json.loads(fixed)
        return obj, False, "Fixed trailing commas"
    except json.JSONDecodeError:
        pass

    return None, False, f"Could not parse JSON from output (length={len(raw)})"


def extract_tool_calls(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract tool_plan list from parsed model output."""
    # Support both "tool_plan" and "thoughtless_plan" keys
    plan = parsed.get("tool_plan") or parsed.get("thoughtless_plan") or []
    if not isinstance(plan, list):
        return []
    return plan


def extract_final_answer(parsed: dict[str, Any]) -> dict[str, Any] | None:
    """Extract final_answer dict from parsed model output."""
    fa = parsed.get("final_answer")
    if isinstance(fa, dict):
        return fa
    return None


def validate_schema(parsed: dict[str, Any]) -> list[str]:
    """
    Light schema validation. Returns list of violation descriptions.
    (Not a full JSON Schema validator — just checks required structure.)
    """
    violations: list[str] = []

    if not isinstance(parsed, dict):
        return ["Root is not an object"]

    if "tool_plan" not in parsed and "thoughtless_plan" not in parsed:
        violations.append("Missing 'tool_plan' field")

    plan = parsed.get("tool_plan") or parsed.get("thoughtless_plan") or []
    if not isinstance(plan, list):
        violations.append("'tool_plan' is not an array")
    else:
        for i, call in enumerate(plan):
            if not isinstance(call, dict):
                violations.append(f"tool_plan[{i}] is not an object")
                continue
            for field in ("tool_name", "method", "endpoint", "params"):
                if field not in call:
                    violations.append(f"tool_plan[{i}] missing '{field}'")
            if "method" in call and call["method"] not in ("GET", "POST"):
                violations.append(
                    f"tool_plan[{i}].method = '{call['method']}' (expected GET|POST)"
                )

    fa = parsed.get("final_answer")
    if fa is None:
        violations.append("Missing 'final_answer' field")
    elif not isinstance(fa, dict):
        violations.append("'final_answer' is not an object")
    elif "summary" not in fa:
        violations.append("'final_answer' missing 'summary'")

    return violations
