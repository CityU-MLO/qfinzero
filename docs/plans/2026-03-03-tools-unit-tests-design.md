# Tools Unit & Regression Test Suite — Design

**Date:** 2026-03-03
**Status:** Approved

## Problem

The MCP tools layer (34 tools across UPQ/NPP/PMB) and their underlying Python clients have zero test coverage. Any code change can silently break parameter forwarding, URL construction, error handling, or JSON serialization without detection.

## Decision

HTTP-level mock tests using the `responses` library. Tests intercept `requests` calls at the transport layer, validating the full stack: MCP tool → client → HTTP request construction → response parsing.

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures, mock URL constants
├── test_upq_client.py       # UPQ client + MCP tools (9 tools, ~27 tests)
├── test_npp_client.py       # NPP client + MCP tools (11 tools, ~33 tests)
├── test_pmb_client.py       # PMB client + MCP tools (14 tools, ~42 tests)
└── test_pure_utils.py       # Pure functions: make_opra, ns_to_iso, StepResult (~15 tests)
```

**Total: ~117 tests**

## Test Pattern (per tool)

Each tool gets 2-4 tests:

1. **Happy path** — Mock 200 response → call client method → assert correct URL, params, and return value
2. **Error handling** — Mock 4xx/5xx → assert proper `*Error` exception with status_code and message
3. **Optional params** (where applicable) — Verify optional params are omitted from HTTP request when None, included when set

## Pure Utility Tests

- `UPQClient.make_opra`: integer/fractional strikes, various underlyings, C/P rights
- `upq_ns_to_iso`: epoch zero, known timestamps, boundary values
- `PMBClient.StepResult`: is_running, current_ts, get_event, get_stock_price with various payloads

## conftest.py Fixtures

- `MOCK_UPQ_URL`, `MOCK_NPP_URL`, `MOCK_PMB_URL` — base URL constants
- `mock_upq_url` / `mock_npp_url` / `mock_pmb_url` — fixtures that patch env vars
- Helper functions for building common mock responses

## Dependencies

Add `responses` to `pyproject.toml`:

```toml
[project.optional-dependencies]
dev = ["pytest", "responses"]
```

## Scope

- Client methods (HTTP request construction, response parsing, error handling)
- MCP tool functions (parameter forwarding, JSON serialization)
- Pure utility functions (OPRA building, timestamp conversion, StepResult)
- NOT tested: MCP protocol transport (FastMCP framework responsibility)
