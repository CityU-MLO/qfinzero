> 中文: [../docs/cn/demos/README.md](../docs/cn/demos/README.md)


# QFinZero Demos

Usage demonstrations for each QFinZero service. Each subdirectory contains runnable examples showing common workflows.

## Structure

```
demos/
├── esp/     # News ingestion & query demos
├── pmb/     # Paper trading strategy demos
└── upq/     # Price data query demos
```

## Prerequisites

Make sure the relevant service is running before running its demos. See the root [README](../README.md) for quick start instructions.

## Existing Demos

- **ESP**: `demos/esp/` — earnings calendar, economic calendar, news search, trigger checks
- **UPQ**: `demos/upq/` — stock, option, and rates queries
- **PMB**: `demos/pmb/` and `infra/pmb/demos/` — daily accumulation, intraday mean reversion, covered call strategies
