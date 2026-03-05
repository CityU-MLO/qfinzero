# PMB Option Lifecycle Management Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

PMB supports selling options (short positions) but has no lifecycle management. Option positions
accumulate indefinitely past their expiry date, causing:

1. Unrealized P&L calculations to diverge from reality after expiry
2. Margin requirements continuing on worthless contracts
3. No simulation of ITM assignment (call-away / put assignment)

This makes multi-week covered call and cash-secured put backtests produce incorrect results.

## Goals

1. Each tick, check all option positions for expiry
2. OTM expiry → close at `price = 0.0`, emit `OPTION_EXPIRY_EVENT`
3. ITM short call expiry → close at intrinsic, sell underlying stock at strike (call-away)
4. ITM short put expiry → close at intrinsic, buy underlying stock at strike (put assignment)
5. Long option expiry → close at intrinsic (OTM = 0), no stock transaction
6. Fee: configurable `option_exercise_fee` (default `0.0`, matching IBKR/Schwab standard)

## Non-Goals

- Complex early exercise logic
- American vs European distinction
- Fractional shares from assignment

## Architecture

### Tick Processing Order (updated)

```
per tick:
  1. market_tick event
  2. update_market_prices (ledger mark-to-market)
  2b. [NEW] option_expiry_check → synthetic lifecycle fills + OPTION_EXPIRY_EVENT(s)
  3. process open orders (execution engine)
  3b. re-mark after fills
  4. account snapshot
  5. risk check
```

Expiry check runs **after** mark-to-market so it has the current underlying price to compute
intrinsic value, but **before** order execution so that margin is freed before new orders fill.

### New Module: `domain/option_lifecycle.py`

Pure functions, no state, fully unit-testable in isolation.

```python
@dataclass
class ExpiryAction:
    contract: str            # OPRA contract id (without "OPTION:" prefix)
    instrument_id: str       # "OPTION:<contract>"
    option_pos: Position     # the position being closed
    is_itm: bool
    intrinsic_value: float   # fill price for option close (0.0 if OTM)
    underlying: str | None   # stock symbol (None if price unavailable)
    stock_side: Side | None  # BUY (put) or SELL (call), None if OTM or long
    strike: float | None     # stock transaction price
    stock_qty: int           # abs(option_qty) * 100

def parse_opra_expiry(contract: str) -> str | None:
    """Extract expiry date "YYYY-MM-DD" from OPRA string like O:NVDA250117C00136000."""

def check_option_expiries(
    positions: dict[str, Position],
    current_date: str,               # "YYYY-MM-DD"
    underlying_prices: dict[str, float],  # symbol -> price
) -> list[ExpiryAction]:
    """Return one ExpiryAction per expired option position."""
```

### New EventType: `OPTION_EXPIRY_EVENT`

Added to `models/enums.py`:

```python
OPTION_EXPIRY_EVENT = "OPTION_EXPIRY_EVENT"
```

New payload in `models/event.py`:

```python
class OptionExpiryEventPayload(BaseModel):
    contract: str
    is_itm: bool
    intrinsic_value: float
    option_qty: int               # position qty (negative = short)
    realized_pnl: float           # from closing the option
    assignment: dict | None = None  # {underlying, side, qty, strike} if ITM
```

### FeeModel Extension

In `models/session.py`:

```python
class FeeModel(BaseModel):
    stock_fee_per_share: float = 0.0005
    option_fee_per_contract: float = 0.65
    option_exercise_fee: float = 0.0   # per-contract fee on expiry/assignment
```

### Integration Point: `SessionService._process_tick()`

After step 2 (update_market_prices), before step 3 (execution):

```python
# 2b. Option expiry lifecycle
underlying_prices = {
    sym: bar.close
    for sym, bar in stock_bars.items()
}
expiry_actions = check_option_expiries(
    state.ledger.positions,
    ts[:10],          # "YYYY-MM-DD"
    underlying_prices,
)
expiry_events = state.execution_engine.process_expiries(
    ts, expiry_actions, state.ledger, state.order_manager,
    state.margin_engine,
)
for evt in expiry_events:
    events.append(evt.model_dump())
    state.history.append_event(evt)
```

`process_expiries` is a new method on `ExecutionEngine` that applies fills via `Ledger.apply_fill`
and emits `OPTION_EXPIRY_EVENT` envelopes.

## Boundary Conditions

| Scenario | Behavior |
|----------|----------|
| Short call OTM | Close at 0.0, fee = `option_exercise_fee`, emit event |
| Short call ITM | Close at intrinsic, sell stock at strike (qty×100), emit event |
| Short put OTM | Close at 0.0, emit event |
| Short put ITM | Close at intrinsic, buy stock at strike (qty×100), emit event |
| Long call/put OTM | Close at 0.0 (premium lost) |
| Long call/put ITM | Close at intrinsic (profit realized), no stock transaction |
| Underlying price unavailable | Log warning, close option at 0.0, skip stock transaction |
| Naked short call ITM | Call-away still executes, may result in short stock position |

## Testing Strategy

- Unit tests for `parse_opra_expiry` (edge cases: various OPRA formats)
- Unit tests for `check_option_expiries` (OTM/ITM, call/put, long/short)
- Unit tests for `ExecutionEngine.process_expiries`
- Integration test via `SessionService`: full tick with expired option, verify ledger state
- All tests in `infra/pmb/tests/` using `pytest`
