from services.session_service import SessionService


class HistoryService:
    """Query and export history from sessions."""

    def __init__(self, session_service: SessionService):
        self._session_service = session_service

    def get_orders(
        self,
        session_id: str,
        status_in: list[str] | None = None,
        limit: int | None = None,
    ) -> list[dict] | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        return state.history.get_orders(session_id=session_id, status_in=status_in, limit=limit)

    def get_trades(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict] | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        return state.history.get_trades(session_id=session_id, limit=limit)

    def get_equity_curve(self, session_id: str) -> list[dict] | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        return state.history.get_equity_curve()

    def export_json(self, session_id: str) -> dict | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        return state.history.export_json()

    def export_csv(self, session_id: str, what: str) -> str | None:
        state = self._session_service.get_session(session_id)
        if state is None:
            return None
        return state.history.export_csv(what)
