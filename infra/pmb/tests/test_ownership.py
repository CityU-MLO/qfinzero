"""Per-user scoping: hub identity headers decide which accounts/sessions a caller sees."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.accounts import router as accounts_router
from routes.orders import router as orders_router
from routes.ownership import ownership_middleware
from routes.sessions import router as sessions_router
from services.account_service import AccountService
from services.order_service import OrderService
from services.session_service import SessionService


class FakeUPQ:
    async def get_stock_minute_bars(self, *a, **k):
        from models.market import StockBar
        return [StockBar(symbol="SPY", window_start_ns=i * 1_000_000_000, open=1, high=1, low=1,
                         close=1, volume=1) for i in (1, 2, 3)]

    async def get_option_quotes(self, *a, **k):
        return []


def make_client():
    app = FastAPI()
    app.state.account_service = AccountService()
    app.state.session_service = SessionService(FakeUPQ())
    app.state.order_service = OrderService(app.state.session_service)
    app.middleware("http")(ownership_middleware)
    for r in (accounts_router, sessions_router, orders_router):
        app.include_router(r)
    return TestClient(app)


ALICE = {"x-qfz-user": "alice", "x-qfz-role": "researcher"}
BOB = {"x-qfz-user": "bob", "x-qfz-role": "researcher"}
ROOT = {"x-qfz-user": "root", "x-qfz-role": "admin"}


def test_users_see_only_their_accounts_and_sessions():
    c = make_client()
    a = c.post("/v1/accounts", json={"initial_cash": 1000}, headers=ALICE).json()["account_id"]
    b = c.post("/v1/accounts", json={"initial_cash": 1000}, headers=BOB).json()["account_id"]
    mine = [x["account_id"] for x in c.get("/v1/accounts", headers=ALICE).json()["accounts"]]
    assert mine == [a]
    assert len(c.get("/v1/accounts", headers=ROOT).json()["accounts"]) == 2
    assert c.get(f"/v1/accounts/{b}", headers=ALICE).status_code == 404
    assert c.get(f"/v1/accounts/{b}", headers=BOB).status_code == 200

    body = {"account_id": b, "frequency": "1m", "start_ts": "1970-01-01T00:00:01+00:00",
            "end_ts": "1970-01-01T00:00:03+00:00", "universe": {"stocks": ["SPY"]}}
    assert c.post("/v1/sessions", json=body, headers=ALICE).status_code == 400
    sid = c.post("/v1/sessions", json=body, headers=BOB).json()["session_id"]
    assert c.get(f"/v1/sessions/{sid}/state", headers=ALICE).status_code == 404
    assert c.post(f"/v1/sessions/{sid}/step", json={"step": 1}, headers=ALICE).status_code == 404
    order = {"session_id": sid, "account_id": b, "order": {
        "instrument": {"type": "STOCK", "symbol": "SPY"}, "side": "BUY",
        "order_type": "MARKET", "qty": 1}}
    assert c.post("/v1/orders", json=order, headers=ALICE).status_code == 404
    assert c.post("/v1/orders", json=order, headers=BOB).status_code == 200
    # direct local access without identity keeps the old unscoped behaviour
    assert c.get(f"/v1/sessions/{sid}/state").status_code == 200
