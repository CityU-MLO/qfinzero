# QFinZero Demos

Usage demonstrations for each QFinZero service. Each subdirectory contains runnable examples showing common workflows.

## Structure

```
demos/
├── ffo/     # Factor evaluation & combination demos
├── npp/     # News ingestion & query demos
├── pmb/     # Paper trading strategy demos
└── upq/     # Price data query demos
```

## Prerequisites

Make sure the relevant service is running before running its demos. See the root [README](../README.md) for quick start instructions.

## Existing Demos

Some demo scripts currently live within each service's directory:

- **FFO**: `infra/ffo/examples/enhanced_usage.py` — 6 usage patterns for factor evaluation
- **PMB**: `infra/pmb/demos/` — Daily accumulation, intraday mean reversion, covered call strategies
