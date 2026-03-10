"""
Overlay Strategy Demo: LLM-Driven Agent

Replaces hardcoded overlay rules with LLM decision-making.
Each rebalance day (weekly), feeds market state + holdings + option chain
to DeepSeek API and executes the returned JSON action via PMB.

Tracks three key metrics:
  1. Latency — per-call and total wall time
  2. Token consumption — prompt/completion tokens, estimated cost
  3. Equity curve — LLM agent vs rule-based vs buy-and-hold

Prerequisites:
  - UPQ running on http://127.0.0.1:19703
  - PMB running on http://127.0.0.1:19701
  - DeepSeek API key in eval/models.yaml

Usage:
  python demos/overlay_llm_agent.py --ticker QQQ --strategy profit
  python demos/overlay_llm_agent.py --ticker QQQ --strategy hedge
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import json
import time
import httpx
import yaml
from datetime import datetime
from demos.overlay_helpers import (
    create_account, create_session,
    place_order, step_session, get_summary, get_export,
    get_positions, get_account, print_section, query_stock_price,
    query_option_chain, select_contract, compute_initial_cash,
    get_etf_daily_prices, UPQ_CHAIN,
    query_option_greeks, compute_effective_delta,
    load_macro_context, load_semi_earnings,
)
from demos.result_saver import ResultSaver


# --- Config ---
START_DATE = "2025-01-02"
END_DATE = "2025-12-31"
STOCK_QTY = 10_000
CASH_BUFFER_PCT = 0.20
OTM_PCT = 0.05

STRATEGY_CONFIG = {
    "profit": {
        "name": "Profit Increase (Covered Call)",
        "option_type": "C",
        "dte_min": 7,
        "dte_max": 45,
        "tickers": ["QQQ", "NVDA", "USO"],
        "etf_benchmarks": {"QQQ": "JEPQ", "NVDA": "NVDY", "USO": "USOY"},
    },
    "hedge": {
        "name": "Hedging (Protective Put)",
        "option_type": "P",
        "dte_min": 7,
        "dte_max": 60,
        "tickers": ["QQQ", "NVDA"],
        "etf_benchmarks": {},
    },
}


# --- LLM Integration ---

def load_deepseek_config() -> dict:
    """Load DeepSeek model config from eval/models.yaml."""
    yaml_path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "eval", "models.yaml")
    yaml_path = os.path.abspath(yaml_path)
    with open(yaml_path) as f:
        models = yaml.safe_load(f)["models"]
    return next(m for m in models if m["model_name"] == "deepseek-chat")


def call_llm(client: httpx.Client, model_cfg: dict,
             system_prompt: str, user_prompt: str,
             timeout: int = 90) -> tuple[str, float, dict]:
    """Call DeepSeek API. Returns (content, latency_s, usage_dict)."""
    base_url = model_cfg["base_url"].rstrip("/")
    url = f"{base_url}/chat/completions"

    headers = {"Content-Type": "application/json"}
    if model_cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {model_cfg['api_key']}"

    payload = {
        "model": model_cfg["model_name"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 500,
        "response_format": {"type": "json_object"},
    }

    t0 = time.monotonic()
    resp = client.post(url, json=payload, headers=headers, timeout=timeout)
    latency = time.monotonic() - t0
    resp.raise_for_status()

    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return content, latency, usage


def parse_llm_action(content: str) -> dict | None:
    """Parse JSON action from LLM response."""
    try:
        action = json.loads(content)
        if isinstance(action, dict) and "action" in action:
            return action
    except json.JSONDecodeError:
        pass
    return None


# --- Prompts ---

PROFIT_SYSTEM_PROMPT = """You are an options overlay trading agent. Your objective is to enhance portfolio income via covered calls on a stock position.

Rules:
- You manage a portfolio of {qty:,} shares of {underlying}
- You may SELL covered calls (short call) to collect premium
- Each call contract covers 100 shares
- Only sell calls with strikes above the current price (OTM)
- Option maturities must be between {dte_min} and {dte_max} days to expiry
- Maximum 1 active call position at a time
- You MUST respond with valid JSON only

Available actions:
- "sell_call": sell a call contract from the available chain
- "hold": take no action this period
- "close_position": buy back existing short call (if any)"""

HEDGE_SYSTEM_PROMPT = """You are a risk management agent. Your objective is to protect a stock portfolio from downside risk using put options while controlling hedging cost.

Rules:
- You manage a portfolio of {qty:,} shares of {underlying}
- You may BUY protective puts to hedge downside
- Each put contract covers 100 shares
- Only buy puts with strikes below the current price (OTM)
- Option maturities must be between {dte_min} and {dte_max} days to expiry
- Maximum 1 active put position at a time
- You MUST respond with valid JSON only

Available actions:
- "buy_put": buy a put contract from the available chain
- "hold": take no action this period
- "close_position": sell existing put (if any)"""


def build_user_prompt(strategy: str, underlying: str, date: str,
                      price: float, cash: float, equity: float,
                      active_options: list, chain: list[dict],
                      effective_delta: float | None = None,
                      context: str = "") -> str:
    """Build the user prompt with current market state."""
    chain_summary = []
    for c in chain[:10]:  # Limit to 10 contracts to keep prompt short
        chain_summary.append(
            f"  {c['ticker']} strike=${c['strike']:.2f} "
            f"expiry={c.get('expiry', 'N/A')} premium=${c.get('close', 0):.2f}"
        )

    options_str = ", ".join(active_options) if active_options else "None"
    chain_str = "\n".join(chain_summary) if chain_summary else "  No contracts available"

    delta_line = ""
    if effective_delta is not None:
        delta_line = f"\n- Current effective delta: {effective_delta:.0f} (target <= {STOCK_QTY:,})"

    context_section = ""
    if context:
        context_section = f"\n\nMarket Context:\n{context}"

    return f"""Current state:
- Date: {date}
- {underlying} price: ${price:.2f}
- Cash available: ${cash:,.2f}
- Portfolio equity: ${equity:,.2f}
- Active option positions: {options_str}{delta_line}

Available option contracts:
{chain_str}

What action should I take? Respond with JSON:
{{"action": "sell_call"|"buy_put"|"hold"|"close_position", "contract": "O:...", "reason": "..."}}

If action is "hold" or "close_position", omit the "contract" field.
Constraint: effective delta must stay <= {STOCK_QTY:,} shares.{context_section}"""


def is_rebalance_day(date_str: str) -> bool:
    """Check if date is a Monday (weekly rebalance)."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return dt.weekday() == 0  # 0 = Monday


def _date_offset(date_str: str, days: int) -> str:
    """Return date_str offset by N days."""
    from datetime import timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=days)
    return dt.strftime("%Y-%m-%d")


def run_llm_strategy(underlying: str, strategy: str):
    """Run LLM-driven overlay strategy for a single underlying."""

    cfg = STRATEGY_CONFIG[strategy]
    etf_ticker = cfg["etf_benchmarks"].get(underlying)

    print_section(f"LLM Agent: {cfg['name']} — {underlying}")
    print(f"  Period: {START_DATE} to {END_DATE}")
    print(f"  Stock Position: {STOCK_QTY:,} shares")
    print(f"  DTE Window: {cfg['dte_min']}-{cfg['dte_max']} days")
    print(f"  Rebalance: Weekly (Monday)")
    print(f"  LLM: DeepSeek Chat")

    # Load LLM config
    model_cfg = load_deepseek_config()
    call_latency = model_cfg.get("call_latency_s", 1.0)

    # Load context data
    semi_earnings = load_semi_earnings()
    if semi_earnings:
        print(f"  Loaded semiconductor earnings: {len(semi_earnings['earnings'])} records")
    else:
        print("  [WARN] Could not load semiconductor earnings context")
        semi_earnings = {"tickers": [], "earnings": []}

    # 1. Get reference price and compute initial cash
    print_section("Phase 1: Setup")
    ref_price = query_stock_price(underlying, START_DATE)
    if ref_price is None:
        print(f"  ERROR: Cannot get {underlying} price. Skipping.")
        return
    print(f"  Reference price: ${ref_price:.2f}")

    initial_cash = compute_initial_cash(ref_price, STOCK_QTY, CASH_BUFFER_PCT)
    print(f"  Initial capital: ${initial_cash:,.2f}")

    # We can't pre-discover contracts for LLM mode — the LLM decides.
    # Instead, we'll query the chain dynamically each rebalance day.
    # But PMB needs contracts in the universe upfront. So we pre-discover
    # a broad set of contracts to include in the universe.
    print("\n  Pre-discovering broad contract universe...")
    from demos.overlay_helpers import discover_contracts_weekly
    all_contracts = discover_contracts_weekly(
        underlying=underlying,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type=cfg["option_type"],
        otm_pct=OTM_PCT,
        ref_price=ref_price,
        dte_min=cfg["dte_min"],
        dte_max=cfg["dte_max"],
    )

    if not all_contracts:
        print(f"  ERROR: No contracts found for {underlying}.")
        return

    option_tickers = [c["ticker"] for c in all_contracts]
    contract_lookup = {c["ticker"]: c for c in all_contracts}
    print(f"  Universe: {len(all_contracts)} contracts")

    # ETF benchmark
    etf_prices = {}
    if etf_ticker:
        etf_data = get_etf_daily_prices(etf_ticker, START_DATE, END_DATE)
        etf_prices = {r["date"]: r["close"] for r in etf_data}

    # 2. Create session
    print_section("Phase 2: Session")
    acct = create_account(initial_cash=initial_cash, start_date=START_DATE)
    account_id = acct["account_id"]
    sess = create_session(
        account_id=account_id,
        start_ts=START_DATE,
        end_ts=END_DATE,
        stocks=[underlying],
        options=option_tickers,
        seed=701,
        run_id=f"overlay_llm_{strategy}_{underlying.lower()}_2025",
    )
    session_id = sess["session_id"]
    print(f"  Account: {account_id}")
    print(f"  Session: {session_id}")

    # 3. Buy stock
    step_data = step_session(session_id)
    events = step_data.get("events", [])
    market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
    initial_price = 0
    if market_tick and market_tick["payload"]["stocks"]:
        initial_price = market_tick["payload"]["stocks"][0]["close"]

    print(f"  Buying {STOCK_QTY:,} shares at ${initial_price:.2f}...")
    place_order(session_id, account_id, "initial_stock_buy",
                {"type": "STOCK", "symbol": underlying}, "BUY", STOCK_QTY)
    step_session(session_id)

    # System prompt
    if strategy == "profit":
        sys_prompt = PROFIT_SYSTEM_PROMPT.format(
            qty=STOCK_QTY, underlying=underlying,
            dte_min=cfg["dte_min"], dte_max=cfg["dte_max"])
    else:
        sys_prompt = HEDGE_SYSTEM_PROMPT.format(
            qty=STOCK_QTY, underlying=underlying,
            dte_min=cfg["dte_min"], dte_max=cfg["dte_max"])

    # 4. Trading loop
    print_section(f"Phase 3: LLM Trading — {underlying}")

    active_option = None
    options_log = []
    llm_calls = []  # Track latency + tokens
    day_count = 2
    order_seq = 0
    benchmark_initial_price = initial_price
    total_wall_time = 0.0

    print(f"\n  {'Day':>4} | {'Date':^10} | {underlying:>8} | {'LLM Action':^45} | {'Equity':>14}")
    print("  " + "-" * 100)

    http_client = httpx.Client()
    current_macro_month = ""
    macro_context = {}

    try:
        while True:
            step_data = step_session(session_id)
            if not step_data.get("ok"):
                break
            clock = step_data.get("clock", {})
            if clock.get("status") != "RUNNING":
                break

            events = step_data.get("events", [])
            day_count += 1
            current_date = clock.get("current_ts", "")[:10]

            # Extract market data
            market_tick = next((e for e in events if e["type"] == "MARKET_TICK"), None)
            current_price = 0
            if market_tick and market_tick["payload"]["stocks"]:
                current_price = market_tick["payload"]["stocks"][0]["close"]

            # Extract equity + positions
            account_snap = next((e for e in events if e["type"] == "ACCOUNT_SNAPSHOT"), None)
            equity = 0
            cash = 0
            stock_pos = 0
            if account_snap:
                snap = account_snap["payload"]
                equity = snap["equity"]
                cash = snap.get("cash", 0)
                for pos in snap.get("positions", []):
                    if pos.get("instrument_id", "").startswith("STOCK:"):
                        stock_pos = pos["qty"]

            # Handle option expiry
            for evt in events:
                if evt.get("type") == "OPTION_EXPIRY_EVENT":
                    payload = evt.get("payload", {})
                    contract = payload.get("contract", "")
                    is_itm = payload.get("is_itm", False)
                    assignment = payload.get("assignment")

                    outcome = "ITM" if is_itm else "OTM"
                    action_str = f"EXPIRY {outcome}: {contract[-21:]}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^45} | ${equity:13,.2f}")

                    options_log.append({
                        "date": current_date, "action": f"EXPIRY_{outcome}",
                        "contract": contract, "source": "expiry",
                    })
                    active_option = None

            # Re-buy stock if called away (profit strategy)
            if strategy == "profit" and stock_pos < STOCK_QTY and current_price > 0:
                rebuy_qty = STOCK_QTY - stock_pos
                order_seq += 1
                place_order(session_id, account_id, f"rebuy_{order_seq}",
                            {"type": "STOCK", "symbol": underlying}, "BUY", rebuy_qty)
                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{'RE-BUY ' + str(rebuy_qty) + ' shares':^45} | ${equity:13,.2f}")

            # LLM rebalance on Mondays (or first day) when no active option
            if not is_rebalance_day(current_date):
                continue
            if active_option is not None:
                continue
            if current_price <= 0:
                continue

            # Load macro context when month changes
            month_str = current_date[:7]
            if month_str != current_macro_month:
                current_macro_month = month_str
                macro_context = load_macro_context(month_str)
                if macro_context.get("last_month_review"):
                    n = len(macro_context["last_month_review"].get("events", []))
                    print(f"  [CTX] Loaded macro context for {month_str}: {n} review events")

            # Query option chain for LLM to choose from
            from datetime import timedelta
            dt = datetime.strptime(current_date, "%Y-%m-%d")
            expiry_min = (dt + timedelta(days=cfg["dte_min"])).strftime("%Y-%m-%d")
            expiry_max = (dt + timedelta(days=cfg["dte_max"])).strftime("%Y-%m-%d")

            if cfg["option_type"] == "C":
                s_min = current_price * (1 + OTM_PCT * 0.5)
                s_max = current_price * (1 + OTM_PCT * 2.0)
            else:
                s_min = current_price * (1 - OTM_PCT * 2.0)
                s_max = current_price * (1 - OTM_PCT * 0.5)

            chain = query_option_chain(
                underlying=underlying, date=current_date,
                option_type=cfg["option_type"],
                strike_min=s_min, strike_max=s_max,
                expiry_min=expiry_min, expiry_max=expiry_max,
            )

            # Filter chain to only contracts in our universe
            chain = [c for c in chain if c.get("ticker") in contract_lookup]

            active_list = [active_option] if active_option else []

            # Compute effective delta for the prompt
            eff_delta = None
            try:
                option_pos_list = []
                for p in get_positions(account_id):
                    if p.get("instrument_id", "").startswith("OPTION:"):
                        p_greeks = query_option_greeks(
                            p["instrument_id"].split(":", 1)[1], current_date)
                        if p_greeks and p_greeks.get("delta"):
                            option_pos_list.append({
                                "delta": p_greeks["delta"],
                                "qty": p["qty"],
                            })
                eff_delta = compute_effective_delta(STOCK_QTY, option_pos_list)
            except Exception:
                pass

            # Build context string for LLM
            ctx_parts = []

            # Macro: last month review
            review = macro_context.get("last_month_review")
            if review and review.get("events"):
                ctx_parts.append(f"Last month ({review['month']}) key macro events:")
                for ev in review["events"]:
                    line = f"  {ev['date']} {ev['event']}"
                    if ev.get("actual"):
                        line += f": actual={ev['actual']}"
                        if ev.get("consensus"):
                            line += f" vs consensus={ev['consensus']}"
                        if ev.get("previous"):
                            line += f" (prev={ev['previous']})"
                    ctx_parts.append(line)

            # Macro: next month upcoming
            upcoming = macro_context.get("next_month_upcoming")
            if upcoming and upcoming.get("events"):
                ctx_parts.append(f"\nUpcoming macro events next month ({upcoming['month']}):")
                for ev in upcoming["events"]:
                    ctx_parts.append(f"  {ev['date']} {ev['event']}")

            # Semiconductor earnings: recent results + upcoming
            if semi_earnings and semi_earnings.get("earnings"):
                recent = [e for e in semi_earnings["earnings"]
                          if e["date"] >= _date_offset(current_date, -14)
                          and e["date"] < current_date and e.get("actual_eps") is not None]
                upcoming_earn = [e for e in semi_earnings["earnings"]
                                 if e["date"] >= current_date
                                 and e["date"] <= _date_offset(current_date, 14)]

                if recent:
                    ctx_parts.append("\nRecent semiconductor earnings (last 14 days):")
                    for e in recent:
                        surprise = ""
                        if e.get("eps_surprise_percent") is not None:
                            surprise = f" surprise={e['eps_surprise_percent']:.1%}"
                        ctx_parts.append(
                            f"  {e['date']} {e['ticker']} {e['fiscal_period']}/{e['fiscal_year']}: "
                            f"EPS actual={e['actual_eps']} est={e['estimated_eps']}{surprise}"
                        )

                if upcoming_earn:
                    ctx_parts.append("\nUpcoming semiconductor earnings (next 14 days):")
                    for e in upcoming_earn:
                        ctx_parts.append(
                            f"  {e['date']} {e['ticker']} {e['fiscal_period']}/{e['fiscal_year']}: "
                            f"est EPS={e['estimated_eps']}"
                        )

            context_str = "\n".join(ctx_parts)

            user_prompt = build_user_prompt(
                strategy, underlying, current_date,
                current_price, cash, equity,
                active_list, chain,
                effective_delta=eff_delta,
                context=context_str,
            )

            # Call LLM
            try:
                content, latency, usage = call_llm(
                    http_client, model_cfg, sys_prompt, user_prompt)
                total_wall_time += latency
                llm_calls.append({
                    "date": current_date,
                    "latency_s": round(latency, 3),
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                })

                action = parse_llm_action(content)
                if not action:
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{'LLM: invalid JSON, skipping':^45} | ${equity:13,.2f}")
                    time.sleep(call_latency)
                    continue

                action_type = action.get("action", "hold")
                contract_ticker = action.get("contract", "")
                reason = action.get("reason", "")[:40]

                if action_type in ("sell_call", "buy_put") and contract_ticker:
                    # Verify contract is in our universe
                    if contract_ticker not in contract_lookup:
                        print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                              f"{'LLM: contract not in universe':^45} | ${equity:13,.2f}")
                        time.sleep(call_latency)
                        continue

                    side = "SELL" if action_type == "sell_call" else "BUY"
                    order_seq += 1
                    resp = place_order(
                        session_id, account_id, f"llm_{order_seq}",
                        {"type": "OPTION", "contract": contract_ticker},
                        side, 1,
                    )
                    if resp.get("ok"):
                        active_option = contract_ticker
                        c = contract_lookup[contract_ticker]
                        action_str = f"LLM {side} {contract_ticker[-21:]} ({reason})"
                        print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                              f"{action_str:^45} | ${equity:13,.2f}")
                        options_log.append({
                            "date": current_date, "action": action_type,
                            "contract": contract_ticker,
                            "strike": c["strike"], "expiry": c["expiry"],
                            "premium": c["close"], "reason": reason,
                            "source": "llm",
                        })
                    else:
                        print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                              f"{'LLM order rejected':^45} | ${equity:13,.2f}")

                elif action_type == "hold":
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{'LLM: HOLD (' + reason + ')':^45} | ${equity:13,.2f}")

                time.sleep(call_latency)

            except Exception as e:
                print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                      f"{'LLM ERROR: ' + str(e)[:30]:^45} | ${equity:13,.2f}")
                time.sleep(call_latency)
                continue

    finally:
        http_client.close()

    # 5. Results
    print_section(f"Results: LLM Agent — {strategy} — {underlying}")

    summary = get_summary(session_id)
    positions = get_positions(account_id)

    overlay_return = summary["total_return"]
    final_price = current_price if current_price > 0 else initial_price
    stock_cost = benchmark_initial_price * STOCK_QTY
    benchmark_equity = (initial_cash - stock_cost) + final_price * STOCK_QTY
    benchmark_return = (benchmark_equity - initial_cash) / initial_cash

    print(f"\n  {'Metric':<30} {'LLM Agent':>15} {'Buy-Hold':>15}")
    print("  " + "-" * 60)
    print(f"  {'Total Return':<30} {overlay_return*100:>14.2f}% {benchmark_return*100:>14.2f}%")
    print(f"  {'Final Equity':<30} ${summary['final_equity']:>13,.2f} ${benchmark_equity:>13,.2f}")
    print(f"  {'Max Drawdown':<30} {summary['max_drawdown']*100:>14.2f}%")
    print(f"  {'Alpha':<30} {(overlay_return - benchmark_return)*100:>14.2f}%")
    print(f"  {'Fees':<30} ${summary['fees_paid']:>13,.2f}")

    # LLM metrics
    total_prompt_tokens = sum(c["prompt_tokens"] for c in llm_calls)
    total_completion_tokens = sum(c["completion_tokens"] for c in llm_calls)
    total_tokens = sum(c["total_tokens"] for c in llm_calls)
    latencies = [c["latency_s"] for c in llm_calls]
    latencies.sort()

    # DeepSeek pricing: $0.14/M input, $0.28/M output (cache miss)
    est_cost = (total_prompt_tokens * 0.14 + total_completion_tokens * 0.28) / 1_000_000

    print(f"\n  LLM Metrics:")
    print(f"    Total calls: {len(llm_calls)}")
    print(f"    Total wall time: {total_wall_time:.1f}s")
    if latencies:
        p50 = latencies[len(latencies)//2]
        p95 = latencies[int(len(latencies)*0.95)]
        print(f"    Latency P50: {p50:.2f}s, P95: {p95:.2f}s")
    print(f"    Prompt tokens: {total_prompt_tokens:,}")
    print(f"    Completion tokens: {total_completion_tokens:,}")
    print(f"    Total tokens: {total_tokens:,}")
    print(f"    Est. cost: ${est_cost:.4f}")

    # Option activity
    llm_actions = [o for o in options_log if o.get("source") == "llm"]
    print(f"\n  Option Activity:")
    print(f"    LLM trades: {len(llm_actions)}")
    for o in llm_actions:
        print(f"      {o['date']}: {o['action']} {o.get('contract', '')[:30]} "
              f"reason={o.get('reason', '')}")

    # 6. Save results
    print_section("Saving Results")

    export_data = get_export(session_id)
    saver = ResultSaver(f"overlay_llm_{strategy}_{underlying.lower()}")

    saver.add_summary_line(f"Overlay LLM Agent: {cfg['name']}")
    saver.add_summary_line(f"{'='*70}")
    saver.add_summary_line(f"Underlying: {underlying}")
    saver.add_summary_line(f"Period: {START_DATE} to {END_DATE}")
    saver.add_summary_line(f"Position: {STOCK_QTY:,} shares")
    saver.add_summary_line(f"LLM: DeepSeek Chat")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"Performance:")
    saver.add_summary_line(f"  LLM Agent Return: {overlay_return*100:+.2f}%")
    saver.add_summary_line(f"  Buy-and-Hold: {benchmark_return*100:+.2f}%")
    saver.add_summary_line(f"  Alpha: {(overlay_return - benchmark_return)*100:+.2f}%")
    saver.add_summary_line(f"")
    saver.add_summary_line(f"LLM Metrics:")
    saver.add_summary_line(f"  Calls: {len(llm_calls)}")
    saver.add_summary_line(f"  Wall time: {total_wall_time:.1f}s")
    saver.add_summary_line(f"  Tokens: {total_tokens:,}")
    saver.add_summary_line(f"  Est. cost: ${est_cost:.4f}")

    saver.save_summary(summary)
    saver.save_holdings(positions)
    saver.save_operations(export_data.get("orders", []), export_data.get("trades", []))
    saver.save_equity_curve(export_data.get("equity_curve", []))
    saver.save_text_report()

    # Save LLM-specific data
    llm_metrics = {
        "model": model_cfg["model_name"],
        "total_calls": len(llm_calls),
        "total_wall_time_s": round(total_wall_time, 2),
        "total_prompt_tokens": total_prompt_tokens,
        "total_completion_tokens": total_completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost_usd": round(est_cost, 6),
        "latency_p50_s": round(latencies[len(latencies)//2], 3) if latencies else 0,
        "latency_p95_s": round(latencies[int(len(latencies)*0.95)], 3) if latencies else 0,
        "calls": llm_calls,
    }
    metrics_path = os.path.join(saver.output_dir, "llm_metrics.json")
    with open(metrics_path, "w") as f:
        json.dump(llm_metrics, f, indent=2)
    print(f"   Saved LLM metrics: {metrics_path}")

    saver.print_saved_location()

    return {
        "underlying": underlying,
        "strategy": strategy,
        "overlay_return": overlay_return,
        "benchmark_return": benchmark_return,
        "llm_calls": len(llm_calls),
        "total_tokens": total_tokens,
        "est_cost": est_cost,
        "wall_time": total_wall_time,
    }


def main():
    parser = argparse.ArgumentParser(description="LLM-Driven Overlay Agent")
    parser.add_argument("--ticker", type=str, default="QQQ")
    parser.add_argument("--strategy", type=str, choices=["profit", "hedge"],
                        default="profit")
    args = parser.parse_args()

    if args.strategy not in STRATEGY_CONFIG:
        print(f"Unknown strategy: {args.strategy}")
        return

    run_llm_strategy(args.ticker, args.strategy)


if __name__ == "__main__":
    main()
