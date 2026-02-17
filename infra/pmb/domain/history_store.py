import csv
import io

from models.order import Order
from models.trade import Trade
from models.event import EventEnvelope, AccountSnapshotPayload


class HistoryStore:
    """Append-only store for orders, trades, snapshots, equity curve, events."""

    def __init__(self):
        self._orders: list[dict] = []
        self._trades: list[dict] = []
        self._snapshots: list[dict] = []
        self._equity_curve: list[dict] = []
        self._order_events: list[dict] = []
        self._events: list[dict] = []

    def record_order(self, order: Order):
        self._orders.append(order.model_dump())

    def update_order(self, order: Order):
        for i, o in enumerate(self._orders):
            if o["order_id"] == order.order_id:
                self._orders[i] = order.model_dump()
                return
        self._orders.append(order.model_dump())

    def record_trade(self, trade: Trade):
        self._trades.append(trade.model_dump())

    def record_snapshot(self, ts: str, snapshot: AccountSnapshotPayload):
        d = snapshot.model_dump()
        d["ts"] = ts
        self._snapshots.append(d)

    def record_equity_point(self, ts: str, equity: float):
        self._equity_curve.append({"ts": ts, "equity": round(equity, 2)})

    def record_order_event(self, event_dict: dict):
        self._order_events.append(event_dict)

    def append_event(self, event: EventEnvelope):
        self._events.append(event.model_dump())

    def get_orders(
        self,
        session_id: str | None = None,
        status_in: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        result = self._orders
        if session_id:
            result = [o for o in result if o.get("session_id") == session_id]
        if status_in:
            result = [o for o in result if o.get("status") in status_in]
        if limit:
            result = result[:limit]
        return result

    def get_trades(
        self,
        session_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        result = self._trades
        if limit:
            result = result[:limit]
        return result

    def get_equity_curve(self) -> list[dict]:
        return self._equity_curve

    def get_snapshots(self) -> list[dict]:
        return self._snapshots

    def export_json(self) -> dict:
        return {
            "orders": self._orders,
            "order_events": self._order_events,
            "trades": self._trades,
            "equity_curve": self._equity_curve,
            "snapshots": self._snapshots,
        }

    def export_csv(self, what: str) -> str:
        data_map = {
            "orders": self._orders,
            "trades": self._trades,
            "equity_curve": self._equity_curve,
            "snapshots": self._snapshots,
        }
        rows = data_map.get(what, [])
        if not rows:
            return ""
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys())
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return output.getvalue()
