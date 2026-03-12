# PMB Option Lifecycle Management Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add option expiry lifecycle management to PMB so that expired option positions are
automatically closed, ITM short options trigger underlying stock assignment, and P&L/margin
correctly reflect reality after expiry.

**Architecture:** A new pure-function module `domain/option_lifecycle.py` computes expiry
actions from current positions + underlying prices. `ExecutionEngine.process_expiries()` applies
synthetic fills via `Ledger.apply_fill`. `SessionService._process_tick()` calls both after
mark-to-market, before order execution. See design doc: `docs/plans/2026-03-06-pmb-option-lifecycle-design.md`.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pytest. All source under `infra/pmb/`.

---

## Task 1: Add `OPTION_EXPIRY_EVENT` to enums and event models

**Files:**
- Modify: `infra/pmb/models/enums.py`
- Modify: `infra/pmb/models/event.py`
- Create: `infra/pmb/tests/__init__.py` (empty, enables pytest discovery)
- Create: `infra/pmb/tests/test_event_models.py`

**Step 1: Write the failing test**

Create `infra/pmb/tests/__init__.py` (empty file).

Create `infra/pmb/tests/test_event_models.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.enums import EventType
from models.event import OptionExpiryEventPayload


def test_option_expiry_event_type_exists():
    assert EventType.OPTION_EXPIRY_EVENT == "OPTION_EXPIRY_EVENT"


def test_option_expiry_payload_otm():
    p = OptionExpiryEventPayload(
        contract="NVDA250117C00136000",
        is_itm=False,
        intrinsic_value=0.0,
        option_qty=-1,
        realized_pnl=3.50,
    )
    assert p.assignment is None
    assert p.intrinsic_value == 0.0


def test_option_expiry_payload_itm_call():
    p = OptionExpiryEventPayload(
        contract="NVDA250117C00136000",
        is_itm=True,
        intrinsic_value=5.0,
        option_qty=-1,
        realized_pnl=-1.50,
        assignment={"underlying": "NVDA", "side": "SELL", "qty": 100, "strike": 136.0},
    )
    assert p.assignment["side"] == "SELL"
    assert p.assignment["strike"] == 136.0
```

**Step 2: Run test to verify it fails**

```bash
cd infra/pmb
python -m pytest tests/test_event_models.py -v
```

Expected: `ImportError` or `AttributeError` — `OPTION_EXPIRY_EVENT` and `OptionExpiryEventPayload` don't exist yet.

**Step 3: Add `OPTION_EXPIRY_EVENT` to enums**

In `infra/pmb/models/enums.py`, add to `EventType`:

```python
class EventType(str, Enum):
    MARKET_TICK = "MARKET_TICK"
    ORDER_EVENT = "ORDER_EVENT"
    TRADE_EVENT = "TRADE_EVENT"
    ACCOUNT_SNAPSHOT = "ACCOUNT_SNAPSHOT"
    RISK_EVENT = "RISK_EVENT"
    ERROR_EVENT = "ERROR_EVENT"
    OPTION_EXPIRY_EVENT = "OPTION_EXPIRY_EVENT"   # <-- add this
```

**Step 4: Add `OptionExpiryEventPayload` to event models**

In `infra/pmb/models/event.py`, add at the end:

```python
class OptionExpiryEventPayload(BaseModel):
    contract: str
    is_itm: bool
    intrinsic_value: float
    option_qty: int
    realized_pnl: float
    assignment: Optional[dict] = None
```

**Step 5: Run tests to verify they pass**

```bash
cd infra/pmb
python -m pytest tests/test_event_models.py -v
```

Expected: 3 PASSED.

**Step 6: Commit**

```bash
git add infra/pmb/models/enums.py infra/pmb/models/event.py \
        infra/pmb/tests/__init__.py infra/pmb/tests/test_event_models.py
git commit -m "feat(pmb): add OPTION_EXPIRY_EVENT type and payload model"
```

---

## Task 2: Add `option_exercise_fee` to FeeModel

**Files:**
- Modify: `infra/pmb/models/session.py`
- Create: `infra/pmb/tests/test_fee_model.py`

**Step 1: Write the failing test**

Create `infra/pmb/tests/test_fee_model.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models.session import FeeModel


def test_fee_model_default_exercise_fee_is_zero():
    fm = FeeModel()
    assert fm.option_exercise_fee == 0.0


def test_fee_model_custom_exercise_fee():
    fm = FeeModel(option_exercise_fee=5.0)
    assert fm.option_exercise_fee == 5.0
```

**Step 2: Run test to verify it fails**

```bash
cd infra/pmb
python -m pytest tests/test_fee_model.py -v
```

Expected: `AttributeError: option_exercise_fee`.

**Step 3: Add field to FeeModel**

In `infra/pmb/models/session.py`, update `FeeModel`:

```python
class FeeModel(BaseModel):
    stock_fee_per_share: float = 0.0005
    option_fee_per_contract: float = 0.65
    option_exercise_fee: float = 0.0
```

**Step 4: Run tests**

```bash
cd infra/pmb
python -m pytest tests/test_fee_model.py -v
```

Expected: 2 PASSED.

**Step 5: Commit**

```bash
git add infra/pmb/models/session.py infra/pmb/tests/test_fee_model.py
git commit -m "feat(pmb): add option_exercise_fee to FeeModel (default 0.0)"
```

---

## Task 3: Implement `domain/option_lifecycle.py` — OPRA parsing

**Files:**
- Create: `infra/pmb/domain/option_lifecycle.py`
- Create: `infra/pmb/tests/test_option_lifecycle.py`

**Background:** OPRA contract format is `O:NVDA250117C00136000`:
- `O:` prefix
- Underlying symbol (variable length, uppercase letters)
- `YYMMDD` expiry (6 digits)
- `C` or `P` (right)
- 8-digit strike × 1000 (zero-padded)

**Step 1: Write the failing test**

Create `infra/pmb/tests/test_option_lifecycle.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.option_lifecycle import parse_opra_expiry


def test_parse_nvda_call():
    assert parse_opra_expiry("O:NVDA250117C00136000") == "2025-01-17"


def test_parse_spx_put():
    assert parse_opra_expiry("O:SPX260320P05800000") == "2026-03-20"


def test_parse_single_letter_symbol():
    # "O:A" style — symbol length 1
    assert parse_opra_expiry("O:A251231C00050000") == "2025-12-31"


def test_parse_invalid_returns_none():
    assert parse_opra_expiry("STOCK:NVDA") is None
    assert parse_opra_expiry("O:BAD") is None
```

**Step 2: Run test to verify it fails**

```bash
cd infra/pmb
python -m pytest tests/test_option_lifecycle.py::test_parse_nvda_call -v
```

Expected: `ImportError` — file doesn't exist yet.

**Step 3: Create `domain/option_lifecycle.py` with `parse_opra_expiry`**

Create `infra/pmb/domain/option_lifecycle.py`:

```python
import re
from dataclasses import dataclass
from typing import Optional

from models.enums import Side
from models.position import Position


_OPRA_RE = re.compile(
    r"^O:([A-Z]+)(\d{2})(\d{2})(\d{2})([CP])(\d{8})$"
)


def parse_opra_expiry(contract: str) -> Optional[str]:
    """Parse expiry date from OPRA contract string.

    Returns "YYYY-MM-DD" or None if contract is not a valid OPRA string.
    """
    m = _OPRA_RE.match(contract)
    if not m:
        return None
    yy, mm, dd = m.group(2), m.group(3), m.group(4)
    year = 2000 + int(yy)
    return f"{year:04d}-{mm}-{dd}"
```

**Step 4: Run parsing tests**

```bash
cd infra/pmb
python -m pytest tests/test_option_lifecycle.py -k "parse" -v
```

Expected: 4 PASSED.

**Step 5: Commit**

```bash
git add infra/pmb/domain/option_lifecycle.py infra/pmb/tests/test_option_lifecycle.py
git commit -m "feat(pmb): add option_lifecycle module with OPRA expiry parser"
```

---

## Task 4: Implement `check_option_expiries` — core expiry logic

**Files:**
- Modify: `infra/pmb/domain/option_lifecycle.py`
- Modify: `infra/pmb/tests/test_option_lifecycle.py`

**Step 1: Write the failing tests**

Append to `infra/pmb/tests/test_option_lifecycle.py`:

```python
from domain.option_lifecycle import check_option_expiries, ExpiryAction
from models.position import Position
from models.enums import InstrumentType, Side


def _make_option_pos(contract: str, qty: int) -> Position:
    return Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=qty,
        avg_price=3.50,
        mark_price=0.10,
    )


def _make_stock_pos(symbol: str, qty: int) -> Position:
    return Position(
        instrument_id=f"STOCK:{symbol}",
        type=InstrumentType.STOCK,
        qty=qty,
        avg_price=130.0,
        mark_price=140.0,
    )


# --- OTM short call ---
def test_short_call_otm_expiry():
    contract = "O:NVDA250117C00150000"  # strike 150, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -1),
        "STOCK:NVDA": _make_stock_pos("NVDA", 100),
    }
    # underlying = 140 < 150 strike → OTM
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 140.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is False
    assert a.intrinsic_value == 0.0
    assert a.stock_side is None


# --- ITM short call (call-away) ---
def test_short_call_itm_expiry():
    contract = "O:NVDA250117C00136000"  # strike 136, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -2),
        "STOCK:NVDA": _make_stock_pos("NVDA", 200),
    }
    # underlying = 145 > 136 strike → ITM
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 145.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is True
    assert a.intrinsic_value == pytest.approx(9.0)   # 145 - 136
    assert a.stock_side == Side.SELL
    assert a.strike == 136.0
    assert a.stock_qty == 200   # 2 contracts × 100


# --- ITM short put (put assignment) ---
def test_short_put_itm_expiry():
    contract = "O:NVDA250117P00130000"  # strike 130, expires 2025-01-17
    positions = {
        f"OPTION:{contract}": _make_option_pos(contract, -1),
    }
    # underlying = 125 < 130 strike → ITM put
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 125.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is True
    assert a.intrinsic_value == pytest.approx(5.0)   # 130 - 125
    assert a.stock_side == Side.BUY
    assert a.strike == 130.0
    assert a.stock_qty == 100


# --- Not expired yet ---
def test_not_expired_yet():
    contract = "O:NVDA250120C00136000"  # expires 2025-01-20
    positions = {f"OPTION:{contract}": _make_option_pos(contract, -1)}
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 145.0})
    assert actions == []


# --- Long call OTM (loses premium) ---
def test_long_call_otm_expiry():
    contract = "O:NVDA250117C00150000"  # strike 150
    positions = {f"OPTION:{contract}": _make_option_pos(contract, 1)}
    actions = check_option_expiries(positions, "2025-01-17", {"NVDA": 140.0})
    assert len(actions) == 1
    a = actions[0]
    assert a.is_itm is False
    assert a.stock_side is None   # long option: no stock transaction


# --- Underlying price unavailable ---
def test_missing_underlying_price():
    contract = "O:NVDA250117C00136000"
    positions = {f"OPTION:{contract}": _make_option_pos(contract, -1)}
    # No NVDA in underlying_prices
    actions = check_option_expiries(positions, "2025-01-17", {})
    assert len(actions) == 1
    a = actions[0]
    # Can't determine ITM/OTM → treat as OTM, no assignment
    assert a.is_itm is False
    assert a.stock_side is None
```

Add `import pytest` at the top of the test file.

**Step 2: Run tests to verify they fail**

```bash
cd infra/pmb
python -m pytest tests/test_option_lifecycle.py -k "expiry" -v
```

Expected: `ImportError` — `ExpiryAction`, `check_option_expiries` not defined.

**Step 3: Implement `ExpiryAction` and `check_option_expiries`**

Append to `infra/pmb/domain/option_lifecycle.py`:

```python
@dataclass
class ExpiryAction:
    contract: str
    instrument_id: str
    option_pos: Position
    is_itm: bool
    intrinsic_value: float
    underlying: Optional[str]
    stock_side: Optional[Side]
    strike: Optional[float]
    stock_qty: int


def _parse_opra_parts(contract: str):
    """Return (underlying, right, strike_float) or None."""
    m = _OPRA_RE.match(contract)
    if not m:
        return None
    underlying = m.group(1)
    right = m.group(5)
    strike = int(m.group(6)) / 1000.0
    return underlying, right, strike


def check_option_expiries(
    positions: dict,
    current_date: str,
    underlying_prices: dict,
) -> list:
    """Return one ExpiryAction per option position whose expiry == current_date."""
    actions = []
    for iid, pos in positions.items():
        if not iid.startswith("OPTION:"):
            continue
        contract = iid[len("OPTION:"):]
        expiry = parse_opra_expiry(contract)
        if expiry != current_date:
            continue

        parts = _parse_opra_parts(contract)
        if parts is None:
            continue

        underlying, right, strike = parts
        spot = underlying_prices.get(underlying)

        if spot is None:
            # Cannot determine moneyness — treat as OTM, skip assignment
            actions.append(ExpiryAction(
                contract=contract,
                instrument_id=iid,
                option_pos=pos,
                is_itm=False,
                intrinsic_value=0.0,
                underlying=underlying,
                stock_side=None,
                strike=strike,
                stock_qty=abs(pos.qty) * 100,
            ))
            continue

        if right == "C":
            intrinsic = max(0.0, spot - strike)
        else:
            intrinsic = max(0.0, strike - spot)

        is_itm = intrinsic > 0.0

        # Stock transaction only for short positions
        stock_side = None
        if is_itm and pos.qty < 0:
            stock_side = Side.SELL if right == "C" else Side.BUY

        actions.append(ExpiryAction(
            contract=contract,
            instrument_id=iid,
            option_pos=pos,
            is_itm=is_itm,
            intrinsic_value=intrinsic,
            underlying=underlying,
            stock_side=stock_side,
            strike=strike,
            stock_qty=abs(pos.qty) * 100,
        ))

    return actions
```

**Step 4: Run all option_lifecycle tests**

```bash
cd infra/pmb
python -m pytest tests/test_option_lifecycle.py -v
```

Expected: all PASSED.

**Step 5: Commit**

```bash
git add infra/pmb/domain/option_lifecycle.py infra/pmb/tests/test_option_lifecycle.py
git commit -m "feat(pmb): implement check_option_expiries with ITM/OTM and call/put support"
```

---

## Task 5: Add `process_expiries` to `ExecutionEngine`

**Files:**
- Modify: `infra/pmb/domain/execution_engine.py`
- Create: `infra/pmb/tests/test_execution_expiry.py`

**Step 1: Write the failing tests**

Create `infra/pmb/tests/test_execution_expiry.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from domain.execution_engine import ExecutionEngine
from domain.option_lifecycle import ExpiryAction
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.margin_engine import MarginEngine
from models.enums import InstrumentType, Side, EventType
from models.position import Position
from models.session import FeeModel, MarginConfig


def _engine():
    return ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel())


def _make_short_option_pos(contract: str, qty: int, avg_price: float) -> Position:
    return Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=qty,
        avg_price=avg_price,
        mark_price=0.05,
    )


def test_process_expiries_otm_closes_option():
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00150000"
    # Manually inject a short option position
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -1, 3.50)

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=False,
        intrinsic_value=0.0,
        underlying="NVDA",
        stock_side=None,
        strike=150.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option position should be closed
    assert f"OPTION:{contract}" not in ledger.positions or ledger.positions[f"OPTION:{contract}"].qty == 0
    # Cash increases by premium (short closed at 0 → realized = avg_price * qty)
    # Realized PnL = 1 * 3.50 (received premium, closed at 0)
    assert ledger.realized_pnl == pytest.approx(3.50, abs=0.01)
    # Event emitted
    assert len(events) == 1
    assert events[0].type == EventType.OPTION_EXPIRY_EVENT


def test_process_expiries_itm_call_triggers_stock_sell():
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117C00136000"
    # Short 2 call contracts, already have 200 NVDA shares
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -2, 3.50)
    ledger._positions["STOCK:NVDA"] = Position(
        instrument_id="STOCK:NVDA",
        type=InstrumentType.STOCK,
        qty=200,
        avg_price=130.0,
        mark_price=145.0,
    )
    cash_before = ledger.cash

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=9.0,   # 145 - 136
        underlying="NVDA",
        stock_side=Side.SELL,
        strike=136.0,
        stock_qty=200,         # 2 contracts × 100
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option closed
    assert f"OPTION:{contract}" not in ledger.positions or ledger.positions[f"OPTION:{contract}"].qty == 0
    # 200 shares sold at 136 — stock position should be 0
    stock_pos = ledger.positions.get("STOCK:NVDA")
    assert stock_pos is None or stock_pos.qty == 0
    # Cash increased by 200 * 136 = 27200
    assert ledger.cash == pytest.approx(cash_before + 200 * 136.0, abs=1.0)
    # One OPTION_EXPIRY_EVENT
    assert any(e.type == EventType.OPTION_EXPIRY_EVENT for e in events)


def test_process_expiries_itm_put_triggers_stock_buy():
    import pytest
    engine = _engine()
    ledger = Ledger(initial_cash=50000.0)
    contract = "O:NVDA250117P00130000"
    ledger._positions[f"OPTION:{contract}"] = _make_short_option_pos(contract, -1, 4.0)
    cash_before = ledger.cash

    action = ExpiryAction(
        contract=contract,
        instrument_id=f"OPTION:{contract}",
        option_pos=ledger._positions[f"OPTION:{contract}"],
        is_itm=True,
        intrinsic_value=5.0,   # 130 - 125
        underlying="NVDA",
        stock_side=Side.BUY,
        strike=130.0,
        stock_qty=100,
    )

    order_manager = OrderManager()
    margin_engine = MarginEngine(MarginConfig())
    events = engine.process_expiries("2025-01-17T16:00:00+00:00", [action], ledger, order_manager, margin_engine)

    # Option closed
    assert f"OPTION:{contract}" not in ledger.positions or ledger.positions[f"OPTION:{contract}"].qty == 0
    # 100 shares bought at 130
    stock_pos = ledger.positions.get("STOCK:NVDA")
    assert stock_pos is not None and stock_pos.qty == 100
    assert ledger.cash == pytest.approx(cash_before - 100 * 130.0, abs=1.0)
    assert any(e.type == EventType.OPTION_EXPIRY_EVENT for e in events)
```

Add `import pytest` at top.

**Step 2: Run tests to verify they fail**

```bash
cd infra/pmb
python -m pytest tests/test_execution_expiry.py -v
```

Expected: `AttributeError: process_expiries`.

**Step 3: Add `process_expiries` to `ExecutionEngine`**

Add the following method to the `ExecutionEngine` class in `infra/pmb/domain/execution_engine.py`:

```python
def process_expiries(
    self,
    ts: str,
    actions: list,
    ledger: "Ledger",
    order_manager: "OrderManager",
    margin_engine: "MarginEngine",
) -> list:
    """Apply option expiry lifecycle actions. Returns list of EventEnvelope."""
    from domain.option_lifecycle import ExpiryAction
    from models.enums import EventType
    from models.event import EventEnvelope, OptionExpiryEventPayload

    events = []
    for action in actions:
        pos = action.option_pos
        option_iid = action.instrument_id

        # 1. Close option position at intrinsic value
        exercise_fee = self._fee_model.option_exercise_fee * abs(pos.qty)
        realized_option = ledger.apply_fill(
            instrument_id=option_iid,
            instrument_type=InstrumentType.OPTION,
            side=Side.BUY if pos.qty < 0 else Side.SELL,  # close direction
            qty=abs(pos.qty),
            price=action.intrinsic_value,
            fees=exercise_fee,
        )

        # 2. If ITM short: execute underlying stock transaction
        assignment_dict = None
        if action.stock_side is not None and action.underlying is not None:
            stock_iid = f"STOCK:{action.underlying}"
            stock_fee = self._fee_model.stock_fee_per_share * action.stock_qty
            ledger.apply_fill(
                instrument_id=stock_iid,
                instrument_type=InstrumentType.STOCK,
                side=action.stock_side,
                qty=action.stock_qty,
                price=action.strike,
                fees=stock_fee,
            )
            assignment_dict = {
                "underlying": action.underlying,
                "side": action.stock_side.value,
                "qty": action.stock_qty,
                "strike": action.strike,
            }

        # 3. Emit OPTION_EXPIRY_EVENT
        payload = OptionExpiryEventPayload(
            contract=action.contract,
            is_itm=action.is_itm,
            intrinsic_value=action.intrinsic_value,
            option_qty=pos.qty,
            realized_pnl=round(realized_option, 4),
            assignment=assignment_dict,
        )
        events.append(EventEnvelope(
            event_id=self._next_event_id(),
            ts=ts,
            type=EventType.OPTION_EXPIRY_EVENT,
            payload=payload.model_dump(),
        ))

    return events
```

**Step 4: Run tests**

```bash
cd infra/pmb
python -m pytest tests/test_execution_expiry.py -v
```

Expected: all PASSED.

**Step 5: Commit**

```bash
git add infra/pmb/domain/execution_engine.py infra/pmb/tests/test_execution_expiry.py
git commit -m "feat(pmb): add ExecutionEngine.process_expiries for option lifecycle fills"
```

---

## Task 6: Wire expiry check into `SessionService._process_tick()`

**Files:**
- Modify: `infra/pmb/services/session_service.py`
- Create: `infra/pmb/tests/test_session_expiry_integration.py`

**Step 1: Write the integration test**

Create `infra/pmb/tests/test_session_expiry_integration.py`:

```python
"""Integration test: full session tick with option expiry."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from domain.session_clock import iso_to_ns
from domain.ledger import Ledger
from domain.order_manager import OrderManager
from domain.execution_engine import ExecutionEngine
from domain.margin_engine import MarginEngine
from domain.history_store import HistoryStore
from domain.market_data_cache import MarketDataCache
from models.enums import InstrumentType, EventType, Frequency, SessionStatus
from models.market import StockBar, OptionBar
from models.position import Position
from models.session import FeeModel, ExecutionConfig, MarginConfig, CreateSessionRequest, Universe
from models.account import Account, AccountConstraints
from services.session_service import SessionService, SessionState
from domain.session_clock import SessionClock
from clients.upq_client import UPQClient


def _make_state(expiry_date: str, stock_price: float, option_avg_price: float) -> SessionState:
    """Build a minimal SessionState with one short call expiring on expiry_date."""
    contract = f"O:NVDA{expiry_date[2:4]}{expiry_date[5:7]}{expiry_date[8:10]}C00136000"
    ts_ns = iso_to_ns(f"{expiry_date}T16:00:00+00:00")

    cache = MarketDataCache()
    # Stock bar
    stock_bar = StockBar(symbol="NVDA", window_start_ns=ts_ns, open=stock_price,
                         high=stock_price, low=stock_price, close=stock_price, volume=1000)
    cache._stock_bars["NVDA"] = {ts_ns: stock_bar}
    # Option bar (near-zero value on expiry day)
    opt_bar = OptionBar(contract=contract, window_start_ns=ts_ns, open=0.01,
                        high=0.01, low=0.0, close=0.0, volume=10,
                        underlying="NVDA", expiry=expiry_date, strike=136.0, right="C")
    cache._option_bars[contract] = {ts_ns: opt_bar}
    cache._rebuild_timestamps()

    clock = SessionClock([ts_ns], Frequency.DAILY, f"{expiry_date}T23:59:59+00:00")

    ledger = Ledger(50000.0)
    # Inject short call position
    ledger._positions[f"OPTION:{contract}"] = Position(
        instrument_id=f"OPTION:{contract}",
        type=InstrumentType.OPTION,
        qty=-1,
        avg_price=option_avg_price,
        mark_price=0.01,
    )
    # Inject 100 NVDA shares
    ledger._positions["STOCK:NVDA"] = Position(
        instrument_id="STOCK:NVDA",
        type=InstrumentType.STOCK,
        qty=100,
        avg_price=130.0,
        mark_price=stock_price,
    )

    exec_config = ExecutionConfig(fee_model=FeeModel())
    req = CreateSessionRequest(
        account_id="acct_test",
        frequency=Frequency.DAILY,
        start_ts=f"{expiry_date}T00:00:00+00:00",
        end_ts=f"{expiry_date}T23:59:59+00:00",
        universe=Universe(stocks=["NVDA"], options=[contract]),
        execution_config=exec_config,
    )

    return SessionState(
        session_id="sess_test",
        account_id="acct_test",
        config=req,
        clock=clock,
        cache=cache,
        ledger=ledger,
        order_manager=OrderManager(),
        execution_engine=ExecutionEngine(seed=42, slippage_bps=0.0, fee_model=FeeModel()),
        margin_engine=MarginEngine(MarginConfig()),
        history=HistoryStore(),
    )


def test_otm_expiry_closes_option_position():
    """Short call expires OTM: option removed, cash unchanged from assignment."""
    state = _make_state("2025-01-17", stock_price=125.0, option_avg_price=3.50)
    contract = list(state.cache._option_bars.keys())[0]
    ts_ns = state.clock._timestamps[0]

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_test": state}

    from domain.session_clock import ns_to_iso
    ts = ns_to_iso(ts_ns)
    events = svc._process_tick(state, ts_ns, ts)

    # Option position should be gone
    opt_pos = state.ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0

    # An OPTION_EXPIRY_EVENT should be in events
    types = [e["type"] for e in events]
    assert EventType.OPTION_EXPIRY_EVENT.value in types

    # Stock position unchanged (OTM = no assignment)
    stock_pos = state.ledger.positions.get("STOCK:NVDA")
    assert stock_pos is not None and stock_pos.qty == 100


def test_itm_expiry_triggers_call_away():
    """Short call expires ITM: option closed, stock sold at strike."""
    state = _make_state("2025-01-17", stock_price=145.0, option_avg_price=3.50)
    contract = list(state.cache._option_bars.keys())[0]
    ts_ns = state.clock._timestamps[0]
    cash_before = state.ledger.cash

    svc = SessionService.__new__(SessionService)
    svc._sessions = {"sess_test": state}

    from domain.session_clock import ns_to_iso
    ts = ns_to_iso(ts_ns)
    events = svc._process_tick(state, ts_ns, ts)

    # Option should be closed
    opt_pos = state.ledger.positions.get(f"OPTION:{contract}")
    assert opt_pos is None or opt_pos.qty == 0

    # Stock should be sold (100 shares at strike 136)
    stock_pos = state.ledger.positions.get("STOCK:NVDA")
    assert stock_pos is None or stock_pos.qty == 0

    # Cash increases by ~100 * 136 = 13600
    assert state.ledger.cash > cash_before + 13500

    # Expiry event present
    types = [e["type"] for e in events]
    assert EventType.OPTION_EXPIRY_EVENT.value in types
```

**Step 2: Run tests to verify they fail**

```bash
cd infra/pmb
python -m pytest tests/test_session_expiry_integration.py -v
```

Expected: FAILED — `_process_tick` doesn't call expiry check yet.

**Step 3: Wire expiry check into `_process_tick`**

In `infra/pmb/services/session_service.py`:

1. Add import at top of file:

```python
from domain.option_lifecycle import check_option_expiries
```

2. In `_process_tick`, after `state.ledger.update_market_prices(prices)` (step 2), add:

```python
        # 2b. Option expiry lifecycle check
        current_date = ts[:10]  # "YYYY-MM-DD"
        underlying_prices = {
            sym: bar.close for sym, bar in stock_bars.items()
        }
        expiry_actions = check_option_expiries(
            state.ledger.positions,
            current_date,
            underlying_prices,
        )
        if expiry_actions:
            expiry_events = state.execution_engine.process_expiries(
                ts,
                expiry_actions,
                state.ledger,
                state.order_manager,
                state.margin_engine,
            )
            for evt in expiry_events:
                events.append(evt.model_dump())
                state.history.append_event(evt)
```

**Step 4: Run integration tests**

```bash
cd infra/pmb
python -m pytest tests/test_session_expiry_integration.py -v
```

Expected: all PASSED.

**Step 5: Run full test suite**

```bash
cd infra/pmb
python -m pytest tests/ -v
```

Expected: all PASSED.

**Step 6: Commit**

```bash
git add infra/pmb/services/session_service.py \
        infra/pmb/tests/test_session_expiry_integration.py
git commit -m "feat(pmb): wire option expiry lifecycle into session tick processing"
```

---

## Task 7: Update covered call demo to handle lifecycle events

**Files:**
- Modify: `infra/pmb/demos/covered_call.py`
- Modify: `demos/pmb/client_demos/covered_call.py`

**Step 1: Update `infra/pmb/demos/covered_call.py`**

In the main step loop, add handling for `OPTION_EXPIRY_EVENT`:

```python
# After result = pmb.step(session_id):
for evt in result.events:
    if evt.get("type") == "OPTION_EXPIRY_EVENT":
        payload = evt.get("payload", {})
        contract = payload.get("contract", "")
        is_itm = payload.get("is_itm", False)
        assignment = payload.get("assignment")
        if is_itm and assignment:
            print(f"  [EXPIRY] {contract} expired ITM → {assignment['side']} "
                  f"{assignment['qty']} shares at ${assignment['strike']:.2f}")
            # Remove from tracked option_positions
            option_positions = [p for p in option_positions
                                 if p.get("contract") != contract]
        else:
            print(f"  [EXPIRY] {contract} expired worthless")
            option_positions = [p for p in option_positions
                                 if p.get("contract") != contract]
```

**Step 2: Same update in `demos/pmb/client_demos/covered_call.py`**

Apply the same event-handling snippet in the step loop.

**Step 3: Commit**

```bash
git add infra/pmb/demos/covered_call.py demos/pmb/client_demos/covered_call.py
git commit -m "feat(pmb): handle OPTION_EXPIRY_EVENT in covered call demo"
```

---

## Task 8: Final verification and cleanup

**Step 1: Run full test suite**

```bash
cd infra/pmb
python -m pytest tests/ -v --tb=short
```

Expected: all PASSED, no warnings about missing imports.

**Step 2: Check all new files are properly structured**

```bash
cd infra/pmb
python -c "from domain.option_lifecycle import check_option_expiries, parse_opra_expiry; print('OK')"
python -c "from models.enums import EventType; print(EventType.OPTION_EXPIRY_EVENT)"
python -c "from models.event import OptionExpiryEventPayload; print('OK')"
python -c "from models.session import FeeModel; print(FeeModel().option_exercise_fee)"
```

Expected: all print their OK/values.

**Step 3: Final commit**

```bash
git add -A
git commit -m "chore(pmb): option lifecycle management complete - all tests passing"
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `models/enums.py` | Add `OPTION_EXPIRY_EVENT` to `EventType` |
| `models/event.py` | Add `OptionExpiryEventPayload` |
| `models/session.py` | Add `option_exercise_fee: float = 0.0` to `FeeModel` |
| `domain/option_lifecycle.py` | New: `parse_opra_expiry`, `ExpiryAction`, `check_option_expiries` |
| `domain/execution_engine.py` | Add `process_expiries` method |
| `services/session_service.py` | Wire step 2b into `_process_tick` |
| `demos/covered_call.py` (×2) | Handle `OPTION_EXPIRY_EVENT` in step loop |
| `tests/` (×4 new files) | Unit + integration tests |
