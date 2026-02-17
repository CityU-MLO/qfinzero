# FFO — Formulaic Factor Optimization

A high-performance quantitative factor evaluation and optimization platform. FFO provides REST APIs for evaluating alpha factor expressions, computing IC/ICIR metrics, running portfolio backtests, and training multi-factor combinations.

## Server

- **Language**: Python (Flask)
- **Default Port**: 19330
- **Entry Point**: `infra/ffo/backend_app.py`

```bash
cd infra/ffo
python backend_app.py
# http://127.0.0.1:19330
```

## API Overview

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check with cache statistics |
| `/factors/check` | POST | Validate factor expression syntax |
| `/factors/eval` | POST | Evaluate factors (IC, RankIC, ICIR, portfolio backtest) |
| `/combination/train` | POST | Train multi-factor combination weights (LASSO / IC optimization) |
| `/combination/backtest` | POST | Backtest a trained factor combination |
| `/combination/compare_methods` | POST | Compare LASSO vs IC optimization side-by-side |
| `/combination/automated_training` | POST | Rolling window automated training |
| `/combination/generate_report` | POST | Generate comprehensive factor report |
| `/combination/list_models` | GET | List saved trained models |
| `/combination/load_model` | GET | Load a saved model |
| `/clear_cache` | POST | Clear evaluation cache |
| `/cache_stats` | GET | Cache statistics |

## Key Concepts

### Factor Expressions

Factor expressions use a DSL compatible with Qlib's formulaic alpha engine:

```
Rank($close, 20)                          # Rank of close price over 20 days
Ts_Mean($close, 20) - Ts_Mean($close, 60) # Moving average crossover
Rank(Corr($close, $volume, 10), 252)      # Correlation-based momentum
```

### Evaluation Modes

- **Fast mode** (`fast=true`): Only compute IC metrics (IC, RankIC, ICIR). ~5x faster.
- **Full mode** (`fast=false`): IC metrics + portfolio backtest with configurable top-K selection.

### Markets

Supported markets: `csi300`, `csi500`, `csi1000`

### Caching

SQLite-backed persistent cache. Cache key = hash(expression + market + dates + label + topk + n_drop).

## Quick Example

```bash
# Evaluate a single factor
curl -X POST http://127.0.0.1:19330/factors/eval \
  -H "Content-Type: application/json" \
  -d '{
    "expression": "Rank($close, 20)",
    "start": "2023-01-01",
    "end": "2024-01-01",
    "market": "csi300",
    "fast": true
  }'
```

## Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PORT` | 19330 | Server port |
| `DEFAULT_MARKET` | csi300 | Default market |
| `DEFAULT_START` | 2023-01-01 | Default start date |
| `DEFAULT_END` | 2024-01-01 | Default end date |
| `DEFAULT_LABEL` | close_return | Default label column |
| `TIMEOUT_EVAL_SEC` | 180 | Evaluation timeout (seconds) |

## References

- [OpenAPI Specification](openapi.yaml)
- [Server Implementation](../../infra/ffo/)
- [Client Library](../../clients/ffo/)
- [Demos](../../demos/ffo/)
