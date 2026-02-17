# **QFinZero: Foundational Infrastructure for Modern Quant Research**

**QFinZero** is a modular and extensible infrastructure suite designed for quantitative finance research at scale.
It consolidates four core components frequently needed across our research projects:

* **FFO — Formulaic Factor Optimizer**
  A unified platform for **alpha factor execution, evaluation, and portfolio construction**.

* **OQL — Option Query Language**
  A domain-specific language for **structuring, searching, and retrieving signals from option chains**.

* **NPP — News Push Pipeline**
  A flexible pipeline for **collecting, parsing, and broadcasting news events** into downstream trading or modeling systems.

* **UPQ — Unified Price Query**
  A high-performance Rust-based service for **querying stock, option, and rates price data** via REST API.

QFinZero serves as the shared backbone for multiple ongoing projects, providing reusable abstractions, clean APIs, and scalable workflows.

---

## **🧩 Architecture Overview**

```
QFinZero
│
├── FFO (Factor & Portfolio)
│   ├── DSL execution engine
│   ├── Backtesting + IC/ICIR/Sharpe metrics
│   ├── Factor evaluation APIs
│   └── Daily/rolling portfolio optimizer
│
├── OQL (Option Query Language)
│   ├── Unified DSL for option chain filtering
│   ├── Greeks / IV surface integration
│   ├── Multi-step search operators (AND, OR, windows)
│   └── LLM-friendly serialization + parser
│
├── NPP (News Push Pipeline)
│   ├── Multi-source news ingestion
│   ├── Cleaning + metadata tagging
│   ├── Priority scoring
│   └── Real-time push to downstream agents or DB
│
└── UPQ (Unified Price Query)
    ├── High-performance Rust service
    ├── Stock/Option/Rates data via REST API
    ├── DuckDB Parquet backend
    └── Support for minute/daily resolution
```

---

# **📦 Modules**

## **1. FFO — Formulaic Factor Optimizer**

FFO provides a complete workflow for factor-based quantitative strategies:

### **Core Features**

* Executable **factor DSL** compatible with price/volume features
* Unified evaluation metrics:

  * IC, RankIC
  * ICIR, Sharpe
  * Turnover, stability
* Built-in factor scoring & filtering
* Rolling backtesting engine
* Portfolio optimizer supporting:

  * Long-only / long-short
  * Sparse constraints
  * Custom objective (IC, risk parity, etc.)

### **Typical Usage**

* Factor evaluation for AlphaBench
* LLM-generated factor testing
* Daily portfolio rebalancing using dynamic factor signals

---

## **2. OQL — Option Query Language**

OQL is a compact DSL designed to express queries over **option chain data**.

### **Why OQL**

Option-chain search is often ad-hoc and requires repeated filtering logic.
OQL standardizes this process with an LLM-friendly syntax.

### **Capabilities**

* Window-based filters (Δ, moneyness, volume spikes)
* Structural operators (AND / OR / NOT)
* Complete access to:

  * IV surface
  * Greeks
  * Liquidity metrics
  * Chain-level patterns

### **Use Cases**

* Strategy search for OptionBench / OptionQuant
* Building IV-based signals
* Automated trading rule generation with LLM agents

---

## **3. NPP — News Push Pipeline**

NPP provides a unified framework for managing **real-time news data**.

### **Components**

* Multi-source ingestion (RSS, APIs, scrapers)
* Content cleaning and normalization
* Entity tagging & timestamp alignment
* Priority scoring / relevancy estimation
* Push service to:

  * search agents
  * memory DB
  * research servers
  * factor generators

### **Why NPP**

Most research pipelines need a consistent way to bring news into factor models, RL agents, or option strategies.
NPP ensures news data is structured, deduped, and can be consumed in real time.

---

## **4. UPQ — Unified Price Query**

UPQ is a Rust-based high-performance price query service providing REST API access to stock, option, and treasury rates data.

### **Core Features**

* Fast REST API for price data queries
* Support for multiple data types:

  * Stock minute/daily OHLCV data
  * Option chain data (minute/daily)
  * Treasury yield curves
* DuckDB + Parquet backend for efficient storage
* Automatic data ingestion from CSV.GZ sources
* Idempotent ingest with manifest tracking
* LRU cache for rates data
* Comprehensive OpenAPI 3.0 specification

### **API Endpoints**

* `GET /health` — Health check
* `GET /stock` — Stock minute data (ISO datetime)
* `GET /stock/daily` — Stock daily data (date format)
* `GET /option/ticker_query` — Query by option contract
* `GET /option/chain_query` — Query option chain with filters
* `GET /rates/query` — Treasury yields

### **Quick Start**

```bash
# 1. Sync data from qlib server
cd infra/upq
./scripts/sync_from_qlib.sh

# 2. Build and run
cargo build --release
cargo run -p upq-ingest -- ingest --raw-root ~/upq_data --storage-root ~/upq_storage
STORAGE_ROOT=~/upq_storage PORT=19350 cargo run -p upq-service

# 3. Test
curl http://localhost:19350/health
curl "http://localhost:19350/stock/daily?tickers=AAPL&start=2025-12-01&end=2025-12-31"
```

See [infra/upq/README.md](infra/upq/README.md) for detailed documentation.

---

# **🚀 Getting Started**

### **Install**

```bash
git clone https://github.com/yourname/qfinzero.git
cd qfinzero
pip install -r requirements.txt
```

### **Basic Example (Factor Execution)**

```python
from qfinzero.ffo import run_factor

result = run_factor("Ts_Mean($close, 20) - Ts_Mean($close, 60)")
print(result.ic, result.sharpe)
```

### **Basic Example (OQL Search)**

```python
from qfinzero.oql import query

expr = "ATM & IV_Change > 5% & Volume_Surge"
matches = query(expr, chain_data)
```

### **Basic Example (NPP)**

```python
from qfinzero.npp import push_news

push_news({
    "headline": "...",
    "source": "Bloomberg",
    "timestamp": ...
})
```

---
# **📜 License**

MIT License (or your preferred license).
