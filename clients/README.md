# QFinZero Clients

Python client libraries for each QFinZero service. Each client wraps the service's REST API and provides a clean interface for agent integration.

## Structure

```
clients/
├── ffo/     # FFO client — factor evaluation & combination (planned)
├── npp/     # NPP client — news query & push (planned)
├── pmb/     # PMB client — paper trading session management
└── upq/     # UPQ client — price data queries
```

## Implemented Clients

| Client | Import | Default Port | Agent Guide |
|--------|--------|-------------|-------------|
| PMB | `from clients.pmb import PMBClient` | 24444 | [docs/pmb/agent-guide.md](../docs/pmb/agent-guide.md) |
| UPQ | `from clients.upq import UPQClient` | 19350 | [docs/upq/agent-guide.md](../docs/upq/agent-guide.md) |

### Quick Start

```python
from clients.pmb import PMBClient, StepResult, PMBError
from clients.upq import UPQClient, UPQError

# Both clients support context manager
with PMBClient() as pmb, UPQClient() as upq:
    # Query stock prices via UPQ
    bars = upq.stock_daily(["AAPL"], "2025-01-06", "2025-01-31")

    # Run a paper trading simulation via PMB
    acct = pmb.create_account(initial_cash=50000.0, start_date="2025-01-06")
    sess = pmb.create_session(
        account_id=acct["account_id"],
        frequency="1d",
        start_ts="2025-01-06",
        end_ts="2025-01-31",
        universe={"stocks": ["AAPL"]},
    )
```

## Agent Integration

The agent guide documents describe each client method as a callable tool with exact parameters, return types, and JSON response schemas. Use these when building agent skills:

- **[PMB Agent Guide](../docs/pmb/agent-guide.md)** — 16 tools for paper trading (account, session, orders, market)
- **[UPQ Agent Guide](../docs/upq/agent-guide.md)** — 6 tools + 2 utilities for price data queries

## Planned Clients

- FFO: `infra/ffo/client/` (existing, to be consolidated)
- NPP: `infra/npp/massive_client.py` (existing, to be consolidated)
