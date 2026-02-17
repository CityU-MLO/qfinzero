import uuid
from datetime import datetime, timezone

from models.account import Account, CreateAccountRequest, MarginConfig, AccountConstraints


class AccountService:
    """Manages account creation and lookup."""

    def __init__(self):
        self._accounts: dict[str, Account] = {}

    def create_account(self, req: CreateAccountRequest) -> Account:
        account_id = f"acct_{uuid.uuid4().hex[:6]}"
        now = datetime.now(timezone.utc).isoformat()

        account = Account(
            account_id=account_id,
            base_currency=req.base_currency,
            account_type=req.account_type,
            initial_cash=req.initial_cash,
            timezone=req.timezone,
            start_date=req.start_date,
            created_at=now,
            constraints=req.constraints or AccountConstraints(),
            margin_config=req.margin_config or MarginConfig(),
        )
        self._accounts[account_id] = account
        return account

    def get_account(self, account_id: str) -> Account | None:
        return self._accounts.get(account_id)
