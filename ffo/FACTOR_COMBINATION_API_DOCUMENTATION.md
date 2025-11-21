# Factor Combination REST API Usage Document

## Endpoints

### 1. Fixed Period Optimization (`/fixed`)

**Purpose**: Optimize factor weights for a single training period, then evaluate on a separate testing period.

**Request Format (Periods Array)**:
```json
{
  "periods": [
    {
      "start": "2020-01-01",
      "end": "2020-12-31",
      "factors": [
        "$close",
        "Mean($close, 20)",
        "Std($close, 20)",
        "$close/Mean($close, 20)",
        "($close-Mean($close, 20))/Mean($close, 20)",
        "$volume/Mean($volume, 20)",
        "($high-$low)/$close",
        "Corr($close, Log($volume+1), 20)",
        "Delta($close, 20)",
        "Rank($close, 20)"
      ]
    }
  ],
  "market": "csi300",
  "alpha": 0.001,
  "methods": ["baseline", "lasso", "ic_optimization"],
  "include_baseline": true
}
```

**Request Format (Direct)**:
```json
{
  "factors": ["$close", "Mean($close, 20)", "Std($close, 20)"],
  "training_start_date": "2020-01-01",
  "training_end_date": "2020-12-31",
  "testing_start_date": "2021-01-01",
  "testing_end_date": "2021-12-31",
  "market": "csi300",
  "alpha": 0.01,
  "methods": ["baseline", "lasso", "ic_optimization"]
}
```

**Response Format**:
```json
{
  "success": true,
  "message": "Fixed factor combination training completed",
  "results": {
    "baseline": {
      "method": "baseline",
      "status": "success",
      "weights": [0.333, 0.333, 0.333],
      "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"],
      "metrics": {
        "r2": 0.15,
        "mse": 0.002,
        "rolling_r2_mean": 0.12,
        "n_samples": 242
      },
      "performance": 0.08
    },
    "lasso": {
      "method": "lasso",
      "status": "success",
      "weights": [0.0, 0.45, 0.0],
      "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"],
      "metrics": {
        "r2": 0.18,
        "mse": 0.0018,
        "rolling_r2_mean": 0.15,
        "n_samples": 242
      },
      "performance": 0.12
    },
    "ic_optimization": {
      "method": "ic_optimization",
      "status": "success",
      "weights": [0.2, 0.3, 0.5],
      "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"],
      "metrics": {
        "combined_ic_mean": 0.08,
        "combined_ic_ir": 0.65,
        "num_factors_used": 3
      },
      "performance": 0.08
    }
  },
  "summary": {
    "training_period": {
      "start": "2020-01-01",
      "end": "2020-12-31"
    },
    "testing_period": {
      "start": "2021-01-01",
      "end": "2021-12-31"
    },
    "factors_count": 3,
    "methods": ["baseline", "lasso", "ic_optimization"],
    "market": "csi300",
    "include_baseline": true
  }
}
```

### 2. Dynamic Period Optimization (`/dynamic`)

**Purpose**: Optimize factor weights across multiple periods with continuity validation.

**Request Format**:
```json
{
  "periods": [
    {
      "start": "2020-01-01",
      "end": "2020-12-31",
      "factors": [
        "$close",
        "Mean($close, 20)",
        "Std($close, 20)",
        "$close/Mean($close, 20)",
        "($close-Mean($close, 20))/Mean($close, 20)",
        "$volume/Mean($volume, 20)",
        "($high-$low)/$close",
        "Corr($close, Log($volume+1), 20)",
        "Delta($close, 20)",
        "Rank($close, 20)"
      ]
    },
    {
      "start": "2021-01-01",
      "end": "2021-12-31",
      "factors": [
        "$close",
        "Mean($close, 20)",
        "Std($close, 20)",
        "$close/Mean($close, 20)",
        "($close-Mean($close, 20))/Mean($close, 20)",
        "$volume/Mean($volume, 20)",
        "($high-$low)/$close",
        "Corr($close, Log($volume+1), 20)",
        "Delta($close, 20)",
        "Rank($close, 20)"
      ]
    },
    {
      "start": "2022-01-01",
      "end": "2022-12-31",
      "factors": [
        "$close",
        "Mean($close, 20)",
        "Std($close, 20)",
        "$close/Mean($close, 20)",
        "($close-Mean($close, 20))/Mean($close, 20)",
        "$volume/Mean($volume, 20)",
        "($high-$low)/$close",
        "Corr($close, Log($volume+1), 20)",
        "Delta($close, 20)",
        "Rank($close, 20)"
      ]
    }
  ],
  "market": "csi300",
  "lookback_window": 60,
  "alpha": 0.001,
  "include_baseline": true,
  "methods": ["baseline", "lasso", "ic_optimization"]
}
```

**Response Format**:
```json
{
  "success": true,
  "message": "Dynamic factor combination training completed",
  "results": {
    "periods": [
      {
        "period_index": 0,
        "period": {"start": "2020-01-01", "end": "2020-12-31"},
        "baseline": {
          "method": "baseline",
          "weights": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.1],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)", ...],
          "metrics": {"r2": 0.12, "mse": 0.0021, "rolling_r2_mean": 0.10, "n_samples": 242}
        },
        "lasso": {
          "method": "lasso",
          "weights": [0.0, 0.0, 0.0, 0.45, 0.0, 0.0, 0.0, 0.0, 0.0, 0.55],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)", ...],
          "metrics": {"r2": 0.15, "mse": 0.0019, "rolling_r2_mean": 0.13, "n_samples": 242}
        },
        "ic_optimization": {
          "method": "ic_optimization",
          "weights": [0.0, 0.0, 0.0, 0.2, 0.0, 0.0, 0.0, 0.0, 0.3, 0.5],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)", ...],
          "metrics": {"combined_ic_mean": 0.08, "combined_ic_ir": 0.65, "num_factors_used": 3}
        }
      }
    ]
  },
  "export_format": {
    "metadata": {
      "version": "1.0",
      "created_at": "2025-11-10T12:00:00.000000",
      "export_timestamp": "20251110_120000",
      "pipeline_version": "1.0",
      "description": "dynamic_factor_optimization",
      "optimization_type": "dynamic"
    },
    "configuration": {
      "type": "dynamic",
      "market": "csi300",
      "lookback_window": 60,
      "alpha": 0.001,
      "methods": ["baseline", "lasso", "ic_optimization"],
      "include_baseline": true,
      "period_config": {
        "type": "dynamic",
        "continuity_validated": true,
        "continuity_warnings": [],
        "dynamic_periods": [
          {
            "period_index": 0,
            "test_start": "2020-01-01",
            "test_end": "2020-12-31",
            "training": {
              "type": "global_lookback",
              "lookback_days": 60,
              "computed_start": "2019-11-01",
              "computed_end": "2019-12-31"
            }
          }
        ]
      }
    },
    "factors": [
      {"index": 0, "formula": "$close", "name": "factor_0"},
      {"index": 1, "formula": "Mean($close, 20)", "name": "factor_1"}
    ],
    "results": {
      "status": "success",
      "total_periods": 3,
      "successful_periods": 3,
      "success_rate": 100.0,
      "periods": [...]
    },
    "computation_details": {
      "data_loading": {
        "market": "csi300",
        "factor_count": 10,
        "valid_factors": 10,
        "invalid_factors": 0
      },
      "weight_computation": {
        "lookback_window": 60,
        "rolling_window": 60,
        "max_iterations": 1000,
        "alpha": 0.001
      }
    }
  },
  "backtest_config": {
    "market": "csi300",
    "optimization_method": "dynamic_periods",
    "periods": [
      {
        "method": "lasso",
        "test_start": "2020-01-01",
        "test_end": "2020-12-31",
        "factors": ["$close", "Mean($close, 20)", ...],
        "weights": [0.0, 0.0, 0.0, 0.45, ...],
        "combined_expression": "(0.0)*($close) + (0.0)*(Mean($close, 20)) + ..."
      }
    ]
  },
  "summary": {
    "total_periods": 3,
    "market": "csi300",
    "lookback_window": 60,
    "methods": ["baseline", "lasso", "ic_optimization"],
    "baseline_enabled": true,
    "continuity_validated": true
  }
}
```

### 3. Backtesting with Weights (`/backtest`)

**Purpose**: Run backtest using pre-optimized weights from Categories A or B.

**Request Format (Fixed Mode)**:
```json
{
  "weights_data": {
    "periods": [
      {
        "baseline": {
          "weights": [0.333, 0.333, 0.333],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"]
        },
        "lasso": {
          "weights": [0.0, 0.45, 0.0],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"]
        },
        "ic_optimization": {
          "weights": [0.2, 0.3, 0.5],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"]
        }
      }
    ]
  },
  "backtest_config": {
    "market": "csi300",
    "method": "lasso",
    "start_date": "2021-01-01",
    "end_date": "2021-12-31"
  }
}
```

**Request Format (Dynamic Mode)**:
```json
{
  "weights_data": {
    "periods": [
      {
        "period": {"start": "2020-01-01", "end": "2020-12-31"},
        "lasso": {
          "weights": [0.0, 0.45, 0.0],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"]
        }
      },
      {
        "period": {"start": "2021-01-01", "end": "2021-12-31"},
        "lasso": {
          "weights": [0.0, 0.3, 0.7],
          "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"]
        }
      }
    ]
  },
  "backtest_config": {
    "market": "csi300",
    "method": "lasso"
  }
}
```

**Response Format (Fixed Mode)**:
```json
{
  "success": true,
  "message": "Backtest completed successfully (fixed mode)",
  "backtest_results": {
    "combined_expression": "(0.0)*($close) + (0.45)*(Mean($close, 20)) + (0.0)*(Std($close, 20))",
    "weights": [0.0, 0.45, 0.0],
    "factor_names": ["$close", "Mean($close, 20)", "Std($close, 20)"],
    "method": "lasso",
    "mode": "fixed",
    "period": {
      "start": "2021-01-01",
      "end": "2021-12-31"
    },
    "market": "csi300",
    "metrics": {
      "total_return": 0.125,
      "annualized_return": 0.125,
      "sharpe_ratio": 0.465,
      "max_drawdown": -0.506,
      "win_rate": 0.52,
      "trading_days": 242,
      "information_ratio": 0.465
    },
    "daily_returns": [
      {"date": "2021-01-04", "return": 0.002},
      {"date": "2021-01-05", "return": -0.001}
    ],
    "cumulative_returns": [
      {"date": "2021-01-04", "cumulative_return": 0.002},
      {"date": "2021-01-05", "cumulative_return": 0.001}
    ]
  }
}
```

**Response Format (Dynamic Mode)**:
```json
{
  "success": true,
  "message": "Backtest completed successfully (dynamic mode)",
  "backtest_results": {
    "combined_expression": "DYNAMIC (2 periods)",
    "method": "lasso",
    "mode": "dynamic",
    "period": {
      "start": "2020-01-01",
      "end": "2021-12-31"
    },
    "market": "csi300",
    "metrics": {
      "total_return": 0.17,
      "annualized_return": 0.085,
      "sharpe_ratio": 0.312,
      "max_drawdown": -0.423,
      "win_rate": 0.534,
      "trading_days": 484,
      "information_ratio": 0.312
    },
    "daily_returns": [
      {"date": "2020-01-02", "return": 0.001, "period_index": 0},
      {"date": "2021-01-04", "return": -0.002, "period_index": 1}
    ],
    "cumulative_returns": [
      {"date": "2020-01-02", "cumulative_return": 0.001},
      {"date": "2021-01-04", "cumulative_return": -0.001}
    ],
    "period_results": [
      {
        "period_index": 0,
        "start": "2020-01-01",
        "end": "2020-12-31",
        "metrics": {
          "annualized_return": 0.142,
          "information_ratio": 0.523,
          "max_drawdown": -0.387
        },
        "num_factors": 3,
        "expression": "(0.0)*($close) + (0.45)*(Mean($close, 20)) + ..."
      }
    ],
    "total_periods": 2
  }
}
```

### 4. Review/Export (`/review`)

**Purpose**: Export results for sharing or import previously saved results.

**Request Format (Export)**:
```json
{
  "action": "export",
  "results": {...},
  "configuration": {...},
  "experiment_name": "my_experiment"
}
```

**Request Format (Import)**:
```json
{
  "action": "load",
  "filepath": "path/to/exported_results.json"
}
```

**Request Format (Validate Periods)**:
```json
{
  "action": "validate_periods",
  "periods": [
    {"start": "2020-01-01", "end": "2020-12-31"},
    {"start": "2021-01-01", "end": "2021-12-31"}
  ]
}
```

## Sample Files

- `samples/test_fixed_sample.json`: Example for Category A (fixed period) using periods array format
- `samples/test_dynamic_sample.json`: Example for Category B (dynamic periods) with multiple periods

## Usage Examples

### 1. Single Factor Backtest
Use one factor in the factors array:
```json
{
  "periods": [{"start": "2020-01-01", "end": "2020-12-31", "factors": ["$close"]}],
  "market": "csi300",
  "methods": ["baseline"]
}
```

### 2. Multi-Factor Portfolio
Use multiple factors, weights will be optimized:
```json
{
  "periods": [{"start": "2020-01-01", "end": "2020-12-31", "factors": ["$close", "Mean($close, 20)", "Std($close, 20)"]}],
  "market": "csi300",
  "methods": ["lasso", "ic_optimization"]
}
```

### 3. Custom Periods
Specify any date ranges in the periods array:
```json
{
  "periods": [
    {"start": "2019-01-01", "end": "2019-12-31", "factors": ["$close"]},
    {"start": "2020-01-01", "end": "2020-12-31", "factors": ["$close"]}
  ],
  "market": "csi300"
}
```

### 4. Method Comparison
Run all three methods and compare results:
```json
{
  "periods": [{"start": "2020-01-01", "end": "2020-12-31", "factors": ["$close", "Mean($close, 20)"]}],
  "market": "csi300",
  "methods": ["baseline", "lasso", "ic_optimization"]
}
```