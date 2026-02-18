# QFinZero Demos

Usage demonstrations for each QFinZero service. Each subdirectory contains runnable examples showing common workflows.

## Structure

```
demos/
├── npp/     # News ingestion & query demos
├── pmb/     # Paper trading strategy demos
└── upq/     # Price data query demos
```

## Prerequisites

Make sure the relevant service is running before running its demos. See the root [README](../README.md) for quick start instructions.

## Existing Demos

- **NPP**: `demos/npp/` — earnings calendar, economic calendar, news search, trigger checks
- **UPQ**: `demos/upq/` — stock, option, and rates queries
- **PMB**: `demos/pmb/` and `infra/pmb/demos/` — daily accumulation, intraday mean reversion, covered call strategies
