# QFinZero Clients

Python client libraries for each QFinZero service. Each client wraps the service's REST API and provides a clean interface for agent integration.

## Structure

```
clients/
├── ffo/     # FFO client — factor evaluation & combination
├── npp/     # NPP client — news query & push
├── pmb/     # PMB client — paper trading session management
└── upq/     # UPQ client — price data queries
```

## Status

Client implementations are planned but not yet consolidated here. Current client code lives within each service's `infra/` directory:

- FFO client: `infra/ffo/client/`
- NPP client: `infra/npp/massive_client.py`
- PMB client: `infra/pmb/clients/`
- UPQ client: used internally by PMB (`infra/pmb/clients/upq_client.py`)
