> English: [../../../demos/README.md](../../../demos/README.md)

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
