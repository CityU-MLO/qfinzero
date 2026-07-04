> **English** (below) · [中文](#中文文档) (在下方)

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

---

<a id="中文文档"></a>

# 中文文档

# QFinZero 演示

各个 QFinZero 服务的用法演示。每个子目录都包含可运行的示例，展示常见工作流程。

## 结构

```
demos/
├── esp/     # News ingestion & query demos
├── pmb/     # Paper trading strategy demos
└── upq/     # Price data query demos
```

## 前置条件

在运行某个服务的演示之前，请确保相关服务正在运行。快速上手说明请参见根目录 [README](../README.md)。

## 现有演示

- **ESP**：`demos/esp/` — 财报日历、经济日历、新闻检索、触发器检查
- **UPQ**：`demos/upq/` — 股票、期权和利率查询
- **PMB**：`demos/pmb/` 和 `infra/pmb/demos/` — 每日累积、日内均值回归、备兑看涨期权策略
