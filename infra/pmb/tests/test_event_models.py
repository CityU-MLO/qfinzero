from models.enums import EventType
from models.event import OptionExpiryEventPayload, AssignmentPayload, EventEnvelope


def test_option_expiry_event_type_exists():
    assert EventType.OPTION_EXPIRY_EVENT == "OPTION_EXPIRY_EVENT"
    # Round-trip: verify EventEnvelope accepts this type
    env = EventEnvelope(
        event_id="evt_001",
        ts="2025-01-17T16:00:00+00:00",
        type=EventType.OPTION_EXPIRY_EVENT,
        payload={},
    )
    assert env.model_dump()["type"] == "OPTION_EXPIRY_EVENT"


def test_option_expiry_payload_otm():
    p = OptionExpiryEventPayload(
        contract="NVDA250117C00136000",
        is_itm=False,
        intrinsic_value=0.0,
        option_qty=-1,
        realized_pnl=3.50,
    )
    assert p.is_itm is False
    assert p.assignment is None
    assert p.intrinsic_value == 0.0
    assert p.realized_pnl == 3.50


def test_option_expiry_payload_itm_call():
    p = OptionExpiryEventPayload(
        contract="NVDA250117C00136000",
        is_itm=True,
        intrinsic_value=5.0,
        option_qty=-1,
        realized_pnl=-1.50,
        assignment=AssignmentPayload(underlying="NVDA", side="SELL", qty=100, strike=136.0),
    )
    assert p.assignment.side == "SELL"
    assert p.assignment.strike == 136.0
    assert p.is_itm is True
