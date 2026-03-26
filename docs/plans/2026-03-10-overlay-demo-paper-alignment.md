# Overlay Demo Paper Alignment — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix all three overlay demo scripts so option contract quantities match the 10,000-share stock position, add cash-secured put selling to the profit strategy, add put spread support to the hedge strategy, and enforce hard delta constraints in the LLM agent.

**Architecture:** Each demo script is modified independently — they share `overlay_helpers.py` for helper functions. The PMB `place_order` API treats option `qty` as contracts (each = 100 shares). With `STOCK_QTY=10_000`, the correct quantity is `STOCK_QTY // 100 = 100` contracts. Put spreads require the existing PMB spread order API (`/v1/orders` with `spread_id` at top level of `CreateOrderRequest`, NOT inside `OrderSpec`).

**Tech Stack:** Python 3.11, PMB backtesting engine, UPQ market data, DeepSeek LLM API

---

### Task 1: Fix Contract Quantity — All Three Demo Scripts

**Context:** All three demo scripts hardcode `qty=1` for option orders. With 10,000 shares, the overlay should trade 100 contracts (`STOCK_QTY // 100`). This is the root cause of all strategies showing ~identical returns — a single contract on a $6M portfolio has negligible impact.

**⚠️ Cash buffer consideration:** 100 contracts of cash-secured puts on QQQ at ~$475 would require $4.75M locked. With `initial_cash = stock_notional × 1.2 ≈ $6M`, this could exhaust available cash. The cash-secured check (`strike × 100 × qty ≤ cash`) in Task 2 will naturally limit put selling when cash is insufficient, so no buffer change is needed for covered calls and protective puts. For cash-secured puts specifically, the OPTION_QTY should NOT be hardcoded — use `min(STOCK_QTY // 100, available_cash // (strike * 100))` instead.

**Files:**
- Modify: `infra/pmb/demos/overlay_profit_increase_v2.py:36,246,257`
- Modify: `infra/pmb/demos/overlay_hedging_v2.py:39,208,219`
- Modify: `infra/pmb/demos/overlay_llm_agent.py:48,554,589`

**Step 1: Add `OPTION_QTY` constant and fix qty in overlay_profit_increase_v2.py**

In `overlay_profit_increase_v2.py`, add constant after line 44 (`DTE_MAX = 45`):

```python
OPTION_QTY = STOCK_QTY // 100  # 100 contracts = 10,000 shares
```

Change line 246 — replace the manual delta formula with `compute_effective_delta`:

Before:
```python
new_delta = eff_delta + (-greeks["delta"]) * 1 * 100  # short call
```

After — simulate adding the proposed short call position to the existing list:
```python
proposed_pos = option_pos_list + [{"delta": greeks["delta"], "qty": -OPTION_QTY}]
new_delta = compute_effective_delta(STOCK_QTY, proposed_pos)
```

This uses the same `delta × qty × 100` logic as `compute_effective_delta` (where `qty` is signed: negative for short). No more manual sign flipping.

Change line 257 from:
```python
"SELL", 1,
```
to:
```python
"SELL", OPTION_QTY,
```

**Step 2: Fix qty in overlay_hedging_v2.py**

Add constant after line 42 (`DTE_MAX = 60`):

```python
OPTION_QTY = STOCK_QTY // 100  # 100 contracts = 10,000 shares
```

Change line 208 — replace manual delta formula with `compute_effective_delta`:

Before:
```python
new_delta = eff_delta + greeks["delta"] * 1 * 100  # long put
```

After:
```python
proposed_pos = option_pos_list + [{"delta": greeks["delta"], "qty": OPTION_QTY}]
new_delta = compute_effective_delta(STOCK_QTY, proposed_pos)
```

Change line 219 from:
```python
"BUY", 1,
```
to:
```python
"BUY", OPTION_QTY,
```

**Step 3: Fix qty in overlay_llm_agent.py**

Add constant after line 50 (`OTM_PCT = 0.05`):

```python
OPTION_QTY = STOCK_QTY // 100  # 100 contracts = 10,000 shares
```

Change line 554 (close position) from:
```python
close_side, 1,
```
to:
```python
close_side, OPTION_QTY,
```

Change line 589 (open position) from:
```python
side, 1,
```
to:
```python
side, OPTION_QTY,
```

**Step 4: Verify changes compile**

Run: `cd infra/pmb && python -c "import demos.overlay_profit_increase_v2; import demos.overlay_hedging_v2; import demos.overlay_llm_agent"`
Expected: No import errors

---

### Task 2: Add Cash-Secured Put Selling to Profit Strategy

**Context:** Per the paper, the profit-increase strategy uses **both** covered calls and cash-secured puts. The current rule-based demo only sells calls. The LLM agent's system prompt also only mentions calls. Cash-secured puts require that `strike × 100 × qty ≤ available_cash` (the cash secures potential assignment).

**⚠️ Delta calculation:** All delta constraint checks must use `compute_effective_delta` with a proposed position list, NOT manual sign-flipped formulas. This ensures consistency with the existing helper.

**⚠️ Dynamic qty for puts:** Because cash-secured puts lock up cash proportional to `strike × 100 × qty`, selling 100 put contracts on QQQ (~$475) would lock $4.75M, which may exceed available cash. Use dynamic sizing: `put_qty = min(OPTION_QTY, int(cash // (strike * 100)))`.

**Files:**
- Modify: `infra/pmb/demos/overlay_profit_increase_v2.py`
- Modify: `infra/pmb/demos/overlay_llm_agent.py` (update system prompt + action handling)

**Step 1: Add put contract discovery to overlay_profit_increase_v2.py**

After the call contract discovery (line 84), add put discovery:

```python
# Pre-discover all weekly put contracts (for cash-secured puts)
put_contracts = discover_contracts_weekly(
    underlying=underlying,
    start_date=START_DATE,
    end_date=END_DATE,
    option_type="P",
    otm_pct=OTM_PCT,
    ref_price=ref_price,
    dte_min=DTE_MIN,
    dte_max=DTE_MAX,
)

if put_contracts:
    print(f"  Discovered {len(put_contracts)} put contracts for the year")
    option_tickers.extend(c["ticker"] for c in put_contracts)
```

**Step 2: Add tracking variables**

Initialize alongside existing tracking vars (~line 138):

```python
active_put_contract = None
put_contract_idx = 0
```

**Step 3: Handle put expiry in the expiry event handler**

In the existing expiry handler block (~line 183-207), detect whether the expired contract is a put by checking the OPRA ticker. OPRA format: `O:AAPL250117P00150000` — the character before the 8-digit strike is `C` or `P`. When a put expires, set `active_put_contract = None`:

```python
# Determine if expired contract is a call or put from OPRA ticker
# Format: O:AAPL250117P00150000 — 'P' or 'C' before the strike digits
opra = contract.split(":")[-1] if ":" in contract else contract
# The type indicator is at position: len(ticker) + 6 (YYMMDD)
# Simpler: check if 'P' appears after the date portion
is_put_contract = "P" in opra[len(opra)-9:]  # last 9 chars: type + 8-digit strike

if is_put_contract:
    active_put_contract = None
else:
    active_call_contract = None
```

**Step 4: Add put selling logic to the trading loop**

After the call selling block (after the `if active_call_contract is None` block ends ~line 269), add:

```python
# Sell cash-secured put if no active put position
if active_put_contract is None and put_contract_idx < len(put_contracts):
    while put_contract_idx < len(put_contracts):
        pc = put_contracts[put_contract_idx]
        if pc["expiry"] >= current_date:
            break
        put_contract_idx += 1

    if put_contract_idx < len(put_contracts):
        pc = put_contracts[put_contract_idx]

        # Dynamic qty: limited by available cash
        put_qty = min(OPTION_QTY, int(cash // (pc["strike"] * 100)))
        if put_qty <= 0:
            pass  # Not enough cash, skip
        else:
            # Delta constraint via compute_effective_delta
            greeks = query_option_greeks(pc["ticker"], current_date)
            skip = False
            if greeks and greeks.get("delta"):
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
                # Simulate adding short put: qty is negative (short)
                proposed = option_pos_list + [{"delta": greeks["delta"], "qty": -put_qty}]
                new_delta = compute_effective_delta(STOCK_QTY, proposed)
                if abs(new_delta) > STOCK_QTY:
                    skip = True

            if not skip:
                order_seq += 1
                resp = place_order(
                    session_id, account_id, f"sell_put_{order_seq}",
                    {"type": "OPTION", "contract": pc["ticker"]},
                    "SELL", put_qty,
                )
                if resp.get("ok"):
                    active_put_contract = pc["ticker"]
                    put_contract_idx += 1
                    action_str = f"SELL PUT {pc['ticker'][-21:]} x{put_qty} @${pc['strike']:.2f}"
                    print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                          f"{action_str:^40} | ${equity:13,.2f}")
                    options_log.append({
                        "date": current_date, "action": "SELL_PUT",
                        "contract": pc["ticker"], "strike": pc["strike"],
                        "expiry": pc["expiry"], "premium": pc["close"],
                        "qty": put_qty,
                    })
```

**Step 5: Update results summary**

Update the premium summary section to include put selling stats:

```python
sell_put_actions = [o for o in options_log if o["action"] == "SELL_PUT"]
total_put_premium = sum(o.get("premium", 0) * o.get("qty", 1) for o in sell_put_actions)
```

**Step 6: Update LLM profit system prompt**

In `overlay_llm_agent.py`, update `PROFIT_SYSTEM_PROMPT` to include puts:

```python
PROFIT_SYSTEM_PROMPT = """You are an options overlay trading agent. Your objective is to enhance portfolio income via covered calls AND cash-secured puts on a stock position.

Rules:
- You manage a portfolio of {qty:,} shares of {underlying}
- You may SELL covered calls (short call) to collect premium
- You may SELL cash-secured puts (short put) to collect premium
- Each option contract covers 100 shares
- Only sell calls with strikes above the current price (OTM)
- Only sell puts with strikes below the current price (OTM)
- Cash-secured put requires: strike × 100 × contracts ≤ available cash
- Option maturities must be between {dte_min} and {dte_max} days to expiry
- Maximum 1 active call + 1 active put position at a time
- You MUST respond with valid JSON only

Available actions:
- "sell_call": sell a call contract from the available chain
- "sell_put": sell a cash-secured put from the available chain
- "hold": take no action this period
- "close_position": buy back existing short option (specify contract in field)"""
```

Update `build_user_prompt` response format to include `"sell_put"`:

```python
{{"action": "sell_call"|"sell_put"|"buy_put"|"hold"|"close_position", "contract": "O:...", "reason": "..."}}
```

**Step 7: Add put contracts to LLM universe discovery**

In `overlay_llm_agent.py` `run_llm_strategy`, when `strategy == "profit"`, discover both call AND put contracts:

```python
# For profit strategy, also discover put contracts
if strategy == "profit":
    put_contracts = discover_contracts_weekly(
        underlying=underlying,
        start_date=START_DATE,
        end_date=END_DATE,
        option_type="P",
        otm_pct=OTM_PCT,
        ref_price=ref_price,
        dte_min=cfg["dte_min"],
        dte_max=cfg["dte_max"],
    )
    if put_contracts:
        option_tickers.extend(c["ticker"] for c in put_contracts)
        contract_lookup.update({c["ticker"]: c for c in put_contracts})
        print(f"  + {len(put_contracts)} put contracts for cash-secured puts")
```

Also query the put chain on rebalance days alongside the call chain, and include both in the LLM prompt.

---

### Task 3: Enforce Hard Delta Constraint in LLM Agent

**Context:** The LLM agent currently computes effective delta and displays it in the prompt, but doesn't enforce it — if the LLM returns an action that would push delta beyond STOCK_QTY, it still executes. The paper requires strict delta constraint enforcement.

**⚠️ Delta calculation:** Use `compute_effective_delta` with proposed position, consistent with Task 1 fixes.

**Files:**
- Modify: `infra/pmb/demos/overlay_llm_agent.py:570-606`

**Step 1: Add delta validation before executing LLM orders**

After the LLM action is parsed and before the order is placed (around line 570), add:

```python
# Hard delta constraint: reject if order would push delta beyond limit
if action_type in ("sell_call", "sell_put", "buy_put") and contract_ticker:
    greeks = query_option_greeks(contract_ticker, current_date)
    if greeks and greeks.get("delta") and eff_delta is not None:
        # Build current option position list
        current_option_pos = []
        for p in get_positions(account_id):
            if p.get("instrument_id", "").startswith("OPTION:"):
                p_greeks = query_option_greeks(
                    p["instrument_id"].split(":", 1)[1], current_date)
                if p_greeks and p_greeks.get("delta"):
                    current_option_pos.append({
                        "delta": p_greeks["delta"],
                        "qty": p["qty"],
                    })

        # Proposed qty: negative for sells, positive for buys
        if action_type in ("sell_call", "sell_put"):
            proposed_qty = -OPTION_QTY
        else:  # buy_put
            proposed_qty = OPTION_QTY

        proposed = current_option_pos + [{"delta": greeks["delta"], "qty": proposed_qty}]
        proposed_delta = compute_effective_delta(STOCK_QTY, proposed)

        if abs(proposed_delta) > STOCK_QTY:
            print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
                  f"{'DELTA REJECT: ' + action_type:^45} | ${equity:13,.2f}")
            time.sleep(call_latency)
            continue
```

---

### Task 4: Add Put Spread Support to Hedge Strategy

**Context:** Per the paper, the hedging strategy uses put **spreads** (buy near-ATM put + sell further-OTM put) to reduce hedging cost. PMB already supports spread orders via `spread_id` in the `CreateOrderRequest` model (top level, NOT inside `OrderSpec`). We need to add a `place_spread` helper and modify the hedge script.

**⚠️ Contract pairing:** Two independent `discover_contracts_weekly` calls with different `otm_pct` values won't guarantee same-expiry pairing. Instead, discover a broad set of put contracts and pair them in code by expiry.

**Files:**
- Modify: `infra/pmb/demos/overlay_helpers.py` (add `place_spread` helper)
- Modify: `infra/pmb/demos/overlay_hedging_v2.py` (replace single put with put spread)
- Modify: `infra/pmb/demos/overlay_llm_agent.py` (add `buy_put_spread` to hedge prompt)

**Step 1: Add place_spread helper to overlay_helpers.py**

After `place_order` function. Note: `spread_id` goes in the top-level request, NOT inside `order`:

```python
def place_spread(session_id: str, account_id: str, client_order_id: str,
                 legs: list[dict], spread_id: str | None = None) -> list[dict]:
    """Place a multi-leg spread order via PMB.

    Each leg is: {"instrument": {...}, "side": str, "qty": int}
    All legs share the same spread_id for atomic execution.

    Note: spread_id is a top-level field on CreateOrderRequest,
    not inside OrderSpec.
    """
    import uuid
    sid = spread_id or str(uuid.uuid4())[:8]
    responses = []
    for i, leg in enumerate(legs):
        resp = requests.post(f"{PMB_BASE}/v1/orders", json={
            "session_id": session_id,
            "account_id": account_id,
            "client_order_id": f"{client_order_id}_leg{i}",
            "spread_id": sid,
            "order": {
                "instrument": leg["instrument"],
                "side": leg["side"],
                "order_type": "MARKET",
                "qty": leg["qty"],
                "time_in_force": "GTC",
            },
        })
        responses.append(resp.json())
    return responses
```

**Step 2: Discover broad put contracts and pair by expiry**

Instead of two separate `discover_contracts_weekly` calls, use a single broad discovery and then pair near/far puts by expiry in code.

Add a helper function in `overlay_hedging_v2.py`:

```python
NEAR_OTM_PCT = 0.03   # Long leg: 3% OTM
FAR_OTM_PCT = 0.08    # Short leg: 8% OTM

def pair_spread_contracts(contracts: list[dict], ref_price: float) -> list[dict]:
    """Pair contracts into spreads by expiry.

    For each expiry, find:
      - near leg: strike closest to ref_price × (1 - NEAR_OTM_PCT)
      - far leg: strike closest to ref_price × (1 - FAR_OTM_PCT)

    Returns list of {"expiry": ..., "near": {...}, "far": {...}} dicts.
    Only includes pairs where both legs exist and near.strike > far.strike.
    """
    from collections import defaultdict
    by_expiry = defaultdict(list)
    for c in contracts:
        by_expiry[c["expiry"]].append(c)

    near_target = ref_price * (1 - NEAR_OTM_PCT)
    far_target = ref_price * (1 - FAR_OTM_PCT)

    pairs = []
    for expiry in sorted(by_expiry.keys()):
        cs = by_expiry[expiry]
        if len(cs) < 2:
            continue
        near = min(cs, key=lambda c: abs(c["strike"] - near_target))
        far = min(cs, key=lambda c: abs(c["strike"] - far_target))
        if near["ticker"] != far["ticker"] and near["strike"] > far["strike"]:
            pairs.append({"expiry": expiry, "near": near, "far": far})
    return pairs
```

Discover contracts with a wide strike range that covers both 3% and 8% OTM:

```python
contracts = discover_contracts_weekly(
    underlying=underlying,
    start_date=START_DATE,
    end_date=END_DATE,
    option_type="P",
    otm_pct=0.05,       # Use middle value for discovery
    ref_price=ref_price,
    dte_min=DTE_MIN,
    dte_max=DTE_MAX,
)
# Note: discover_contracts_weekly searches a strike range — if it uses
# otm_pct to set a range, ensure the range covers both 3% and 8%.
# May need to call query_option_chain directly with wider strike range.
```

Alternative (more reliable): query the chain directly in the trading loop with `strike_min = price * 0.90` and `strike_max = price * 0.99`, then pair in real-time. This avoids pre-discovery pairing issues.

**Step 3: Replace single put buy with spread order in trading loop**

```python
from demos.overlay_helpers import place_spread

# Find next valid spread pair
spread = spread_pairs[spread_idx]

order_seq += 1
responses = place_spread(
    session_id, account_id, f"put_spread_{order_seq}",
    legs=[
        {"instrument": {"type": "OPTION", "contract": spread["near"]["ticker"]},
         "side": "BUY", "qty": OPTION_QTY},
        {"instrument": {"type": "OPTION", "contract": spread["far"]["ticker"]},
         "side": "SELL", "qty": OPTION_QTY},
    ],
)
```

**Step 4: Update LLM hedge prompt**

In `overlay_llm_agent.py`, update `HEDGE_SYSTEM_PROMPT`:

```python
HEDGE_SYSTEM_PROMPT = """You are a risk management agent. Your objective is to protect a stock portfolio from downside risk using put spreads while controlling hedging cost.

Rules:
- You manage a portfolio of {qty:,} shares of {underlying}
- You may BUY put spreads (buy near-ATM put + sell further-OTM put)
- You may also BUY single protective puts for maximum protection
- Each option contract covers 100 shares
- Only use puts with strikes below the current price (OTM)
- Option maturities must be between {dte_min} and {dte_max} days to expiry
- Maximum 1 active hedge position at a time
- You MUST respond with valid JSON only

Available actions:
- "buy_put_spread": buy a put spread (specify "long_contract" and "short_contract")
- "buy_put": buy a single protective put
- "hold": take no action this period
- "close_position": close existing hedge position"""
```

---

### Task 5: Update LLM Agent Action Handling for sell_put + active_call/active_put Split

**Context:** After Task 2 adds `sell_put` to the system prompt, the LLM action handler needs to process `sell_put` actions AND track calls and puts independently. This is more complex than a one-line change — the entire `active_option` tracking must be refactored.

**Files:**
- Modify: `infra/pmb/demos/overlay_llm_agent.py`

**Step 1: Replace `active_option` with `active_call` and `active_put`**

Change initialization (~line 329):
```python
# Before:
active_option = None

# After:
active_call = None
active_put = None
```

**Step 2: Update expiry handler**

In the expiry event handler (~line 377-393), determine contract type and clear the correct tracker:

```python
for evt in events:
    if evt.get("type") == "OPTION_EXPIRY_EVENT":
        payload = evt.get("payload", {})
        contract = payload.get("contract", "")
        is_itm = payload.get("is_itm", False)

        outcome = "ITM" if is_itm else "OTM"
        action_str = f"EXPIRY {outcome}: {contract[-21:]}"
        print(f"  {day_count:4d} | {current_date:^10} | ${current_price:7.2f} | "
              f"{action_str:^45} | ${equity:13,.2f}")
        options_log.append({...})

        # Determine if call or put from OPRA ticker
        opra = contract.split(":")[-1] if ":" in contract else contract
        is_put = "P" in opra[len(opra)-9:]
        if is_put:
            active_put = None
        else:
            active_call = None
```

**Step 3: Update close_position handler**

The close handler (~line 547-568) currently uses `active_option`. Change to specify which position to close:

```python
if action_type == "close_position":
    # Determine which position to close — LLM may specify contract
    close_contract = action.get("contract") or active_call or active_put
    if close_contract:
        close_side = "BUY" if close_contract == active_call else "SELL"
        # ... place close order ...
        if resp.get("ok"):
            if close_contract == active_call:
                active_call = None
            else:
                active_put = None
```

**Step 4: Update "already holding" gate**

The gate at line 571-575 that checks `if active_option is not None` must be split:

```python
elif action_type in ("sell_call", "sell_put", "buy_put") and contract_ticker:
    # Check appropriate position slot
    if action_type == "sell_call" and active_call is not None:
        print(f"  ... LLM: already holding call, skipping ...")
        continue
    if action_type == "sell_put" and active_put is not None:
        print(f"  ... LLM: already holding put, skipping ...")
        continue
    if action_type == "buy_put" and active_put is not None:
        print(f"  ... LLM: already holding put, skipping ...")
        continue
```

**Step 5: Update side determination and position tracking on fill**

```python
side = "SELL" if action_type in ("sell_call", "sell_put") else "BUY"
# ... place order ...
if resp.get("ok"):
    if action_type == "sell_call":
        active_call = contract_ticker
    else:  # sell_put or buy_put
        active_put = contract_ticker
```

**Step 6: Update `active_list` for user prompt**

Change `active_list = [active_option] if active_option else []` to:

```python
active_list = [c for c in [active_call, active_put] if c is not None]
```

---

### Task 6: Deploy and Run on qlib

**Context:** After all code changes, push to git, pull on qlib, and run the full demo suite.

**Step 1: Commit changes**

```bash
git add infra/pmb/demos/overlay_profit_increase_v2.py \
        infra/pmb/demos/overlay_hedging_v2.py \
        infra/pmb/demos/overlay_llm_agent.py \
        infra/pmb/demos/overlay_helpers.py
git commit -m "fix(pmb): align overlay demos with paper spec

- Fix contract qty from 1 to STOCK_QTY//100 (100 contracts)
- Add cash-secured put selling to profit strategy (dynamic qty)
- Add put spread support to hedge strategy (same-expiry pairing)
- Enforce hard delta constraint in LLM agent via compute_effective_delta
- Split active_option into active_call/active_put tracking
- Update LLM system prompts with all available actions"
```

**Step 2: Push and pull on qlib**

```bash
git push origin feat/overlay-strategy-backtest
ssh qlib "cd /home/qlib/qfinzero && git pull"
```

**Step 3: Run demos**

```bash
ssh qlib "cd /home/qlib/qfinzero/infra/pmb && /home/qlib/qfinzero/.venv/bin/python demos/run_all.py --all"
```

**Step 4: Verify differentiated results**

Expected: overlay strategies should now show meaningfully different returns from buy-and-hold:
- Covered call: should show positive alpha in flat/down markets from premium collection
- Protective put spread: should show reduced drawdown at lower cost than naked puts
- Cash-secured put: should add income in stable/rising markets (qty may be < 100 when cash-limited)
- LLM agent: should show variation depending on decisions

The key metric: `overlay_return - benchmark_return` should be in the range of ±1-5%, not ±0.01%.
