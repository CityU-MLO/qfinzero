#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Factor Evaluation API (clean rewrite)

Improvements:
- Hard timeouts with kill-on-timeout using subprocesses
- Persistent SQLite cache keyed by expr hash + params
- Vectorized IC/RankIC, faster batch eval
- Smaller, clearer endpoints with robust error handling
"""

import os
import logging
from datetime import datetime, timezone
from urllib.parse import unquote
import agent.qlib_contrib.qlib_extend_ops
from flask import Flask, request, jsonify
from flask_cors import CORS

from api.utils import (
    PersistentCache,
    cache_key,
    run_eval_with_timeout,
    run_check_with_timeout,
    run_batch_with_timeout,
    DEFAULT_INSTRUMENTS,
)

# -----------------------------
# App / Logging
# -----------------------------
app = Flask(__name__)
CORS(app)

logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
logger = logging.getLogger("FactorAPI")

# -----------------------------
# Defaults
# -----------------------------
DEFAULTS = {
    "market": os.environ.get("DEFAULT_MARKET", "csi300"),
    "start": os.environ.get("DEFAULT_START", "2023-01-01"),
    "end": os.environ.get("DEFAULT_END", "2024-01-01"),
    "label": os.environ.get("DEFAULT_LABEL", "close_return"),
    "check_start": os.environ.get("CHECK_START", "2020-01-01"),
    "check_end": os.environ.get("CHECK_END", "2020-01-15"),
    "use_cache": True,
    "timeout_eval": int(os.environ.get("TIMEOUT_EVAL_SEC", "180")),
    "timeout_check": int(os.environ.get("TIMEOUT_CHECK_SEC", "120")),
    "timeout_batch": int(os.environ.get("TIMEOUT_BATCH_SEC", "600")),
}

# Persistent cache
CACHE = PersistentCache()

# -----------------------------
# Helpers
# -----------------------------
def _fail_result(expr: str, market: str, start: str, end: str, msg: str):
    return {
        "success": False,
        "error": msg,
        "expression": expr,
        "market": market,
        "start_date": start,
        "end_date": end,
        "metrics": {
            "ic": 0.0,
            "rank_ic": 0.0,
            "ir": 0.0,
            "icir": 0.0,
            "rank_icir": 0.0,
            "turnover": 1.0,
            "n_dates": 0,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# -----------------------------
# Routes
# -----------------------------
@app.route("/health", methods=["GET"])
def health():
    return jsonify(
        {
            "status": "healthy",
            "service": "Factor Evaluation API",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cache": CACHE.stats(),
        }
    )


@app.route("/check", methods=["POST"])
def check():
    """
    Quick validation that an expression loads and isn't mostly NaN.

    Body JSON:
    {
      "expression": "...",
      "instruments": "CSI300"  (optional; default from utils.DEFAULT_INSTRUMENTS)
      "start": "YYYY-MM-DD"    (optional; default DEFAULTS['check_start'])
      "end": "YYYY-MM-DD"      (optional; default DEFAULTS['check_end'])
      "timeout": 30            (optional; seconds)
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    expr = (data.get("expression") or "").strip()
    if not expr:
        return (
            jsonify(
                {
                    "success": False,
                    "error_message": "Missing 'expression'",
                    "error_type": "EMPTY_EXPR",
                }
            ),
            400,
        )

    instruments = data.get("instruments", DEFAULT_INSTRUMENTS)
    start = data.get("start", DEFAULTS["check_start"])
    end = data.get("end", DEFAULTS["check_end"])
    timeout = int(data.get("timeout", DEFAULTS["timeout_check"]))

    res = run_check_with_timeout(expr, instruments, start, end, timeout)

    status = 200 if res.ok else 500
    return (
        jsonify(
            res.payload
            if res.ok
            else {
                "success": False,
                "error_message": res.payload,
                "error_type": res.error_type,
            }
        ),
        status,
    )


@app.route("/eval", methods=["GET", "POST"])
def eval_once():
    """
    Evaluate a single expression over a time range.

    GET params:
      expr, start, end, market, label, use_cache=true|false, timeout
    POST JSON:
    {
      "expression": "...",
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD",
      "market": "csi300",
      "label": "close_return",
      "use_cache": true,
      "timeout": 120
    }
    """
    try:
        if request.method == "GET":
            expr = unquote(
                (request.args.get("expression") or "").strip().strip("'").strip('"')
            )
            start = (
                (request.args.get("start") or DEFAULTS["start"]).strip("'").strip('"')
            )
            end = (request.args.get("end") or DEFAULTS["end"]).strip("'").strip('"')
            market = (
                (request.args.get("market") or DEFAULTS["market"])
                .strip("'")
                .strip('"')
                .lower()
            )
            label = (request.args.get("label") or DEFAULTS["label"]).strip()
            use_cache = request.args.get("use_cache", "true").lower() == "true"
            timeout = int(request.args.get("timeout", DEFAULTS["timeout_eval"]))
        else:
            data = request.get_json(force=True, silent=True) or {}
            expr = (data.get("expression") or "").strip()
            start = data.get("start", DEFAULTS["start"])
            end = data.get("end", DEFAULTS["end"])
            market = data.get("market", DEFAULTS["market"]).lower()
            label = data.get("label", DEFAULTS["label"])
            use_cache = bool(data.get("use_cache", DEFAULTS["use_cache"]))
            timeout = int(data.get("timeout", DEFAULTS["timeout_eval"]))

        if not expr:
            return jsonify({"success": False, "error": "Missing 'expression'"}), 400

        key = cache_key(expr, market, start, end, label)
        if use_cache:
            cached = CACHE.get(key)
            if cached:
                return jsonify(cached), 200

        logger.info(
            "Evaluating expr (market=%s, %s→%s, label=%s)", market, start, end, label
        )
        res = run_eval_with_timeout(expr, market, start, end, label, timeout)

        if res.ok:
            # Also run portfolio backtest
            portfolio_metrics = None
            try:
                from backtest.qlib.single_alpha_backtest import backtest_by_single_alpha, get_portfolio_analysis
                
                # Get topk and n_drop from request (works for both GET and POST)
                if request.method == "POST":
                    topk = int(data.get("topk", 50))
                    n_drop = int(data.get("n_drop", 5))
                else:
                    topk = int(request.args.get("topk", 50))
                    n_drop = int(request.args.get("n_drop", 5))
                
                # Map market to qlib format
                market_map = {
                    "csi300": ("csi300", "~/.qlib/qlib_data/cn_data", "cn", "SH000300"),
                    "csi500": ("csi500", "~/.qlib/qlib_data/cn_data", "cn", "SH000905"),
                    "csi1000": ("csi1000", "~/.qlib/qlib_data/cn_data", "cn", "SH000852"),
                }
                instruments, data_path, region, benchmark = market_map.get(
                    market.lower(), market_map["csi300"]
                )
                
                # Run backtest
                analysis_df, report_normal, positions_normal = backtest_by_single_alpha(
                    alpha_factor=expr,
                    topk=topk,
                    n_drop=n_drop,
                    start_time=start,
                    end_time=end,
                    data_path=data_path,
                    instruments=instruments,
                    region=region,
                    BENCH=benchmark,
                )
                
                # Extract portfolio metrics from DataFrame
                if analysis_df is not None and not analysis_df.empty:
                    portfolio_metrics = {}
                    
                    # Extract metrics for each return type
                    for return_type in ["benchmark", "pure_return_without_cost", "pure_return_with_cost",
                                       "excess_return_without_cost", "excess_return_with_cost"]:
                        if return_type in analysis_df.index.get_level_values(0):
                            metrics_df = analysis_df.loc[return_type]
                            portfolio_metrics[return_type] = {
                                "mean_return": float(metrics_df.loc["mean", "risk"]) * 100,
                                "std": float(metrics_df.loc["std", "risk"]) * 100,
                                "annualized_return": float(metrics_df.loc["annualized_return", "risk"]) * 100,
                                "information_ratio": float(metrics_df.loc["information_ratio", "risk"]),
                                "max_drawdown": float(metrics_df.loc["max_drawdown", "risk"]) * 100,
                            }
                
            except Exception as e:
                logger.warning(f"Portfolio backtest failed: {e}")
                # Continue anyway, just without portfolio metrics
            
            # Add portfolio metrics to response
            response_payload = res.payload.copy()
            if portfolio_metrics:
                response_payload["portfolio_metrics"] = portfolio_metrics
            
            if use_cache:
                CACHE.set(key, response_payload)
            return jsonify(response_payload), 200
        else:
            return (
                jsonify(
                    _fail_result(
                        expr, market, start, end, f"{res.error_type}: {res.payload}"
                    )
                ),
                200,
            )

    except Exception as e:
        logger.exception("eval error")
        return (
            jsonify(
                {
                    "success": False,
                    "error": f"{type(e).__name__}: {e}",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ),
            500,
        )


@app.route("/batch_eval", methods=["POST"])
def batch_eval():
    """
    Batch evaluate many expressions (faster than N single calls).

    Body JSON:
    {
      "factors": [{"name": "F1", "expression": "..."}, ...],
      "start": "YYYY-MM-DD",
      "end": "YYYY-MM-DD",
      "market": "csi300",
      "label": "close_return",    # will be turned into label spec for QlibDataLoader
      "timeout": 300
    }
    """
    data = request.get_json(force=True, silent=True) or {}
    factors = data.get("factors") or []
    if not isinstance(factors, list) or not all(
        isinstance(f, dict) and "name" in f and "expression" in f for f in factors
    ):
        return jsonify({"success": False, "error": "Invalid 'factors' format"}), 400

    start = data.get("start", DEFAULTS["start"])
    end = data.get("end", DEFAULTS["end"])
    market = (
        data.get("market", DEFAULTS["market"]) or "csi300"
    ).upper()  # instruments name for loader
    label = data.get("label", DEFAULTS["label"])
    timeout = int(data.get("timeout", DEFAULTS["timeout_batch"]))

    # QlibDataLoader expects a label expression. For common 'close_return', we use next day's return.
    # Adjust here if your setup defines labels differently.
    label_spec = {"close_return": "Ref($close, -1) / $close - 1"}.get(
        label, "Ref($close, -1) / $close - 1"
    )

    res = run_batch_with_timeout(factors, market, start, end, label_spec, timeout)
    status = 200 if res.ok else 500
    if res.ok:
        return jsonify(res.payload), status
    return (
        jsonify(
            {
                "success": False,
                "error": f"{res.error_type}: {res.payload}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
        status,
    )


@app.route("/factor_combination/train", methods=["POST"])
def train_factor_combination():
    """
    Train factor combination models using LASSO or IC optimization.

    Body JSON:
    {
      "factor_expressions": ["expr1", "expr2", "expr3"],
      "method": "lasso" or "ic_optimization",
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "market": "csi300",
      "method_config": {
        "alpha": 0.01,           // for LASSO
        "lambda_risk": 1.0,      // for IC optimization
        "alpha_l1": 0.0,         // for IC optimization
        "non_negative": true     // for IC optimization
      }
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}

        factor_expressions = data.get("factor_expressions", [])
        method = data.get("method", "lasso")
        start_date = data.get("start_date", "2018-01-01")
        end_date = data.get("end_date", "2020-12-31")
        market = data.get("market", "csi300")
        method_config = data.get("method_config", {})

        if not factor_expressions:
            return jsonify({"success": False, "error": "Missing factor_expressions"}), 400

        if method not in ["lasso", "ic_optimization"]:
            return jsonify({"success": False, "error": "Method must be 'lasso' or 'ic_optimization'"}), 400

        # Import training functions
        if method == "lasso":
            from data.pipeline.optim.ml_training import train_lasso_factor_combination
            result = train_lasso_factor_combination(
                factor_expressions=factor_expressions,
                start_date=start_date,
                end_date=end_date,
                instruments=market,
                **method_config
            )
        else:  # ic_optimization
            from data.pipeline.optim.ic_optimization import optimize_factor_weights_ic
            result = optimize_factor_weights_ic(
                factor_expressions=factor_expressions,
                start_date=start_date,
                end_date=end_date,
                instruments=market,
                **method_config
            )

        return jsonify({
            "success": True,
            "method": method,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.exception("Factor combination training error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route("/factor_combination/backtest", methods=["POST"])
def backtest_factor_combination():
    """
    Run backtest using trained factor combination weights.

    Body JSON:
    {
      "trained_model": {...},  // Result from /factor_combination/train
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "market": "csi300",
      "topk": 50,
      "n_drop": 5
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}

        trained_model = data.get("trained_model")
        start_date = data.get("start_date", "2021-01-01")
        end_date = data.get("end_date", "2021-12-31")
        market = data.get("market", "csi300")
        topk = int(data.get("topk", 50))
        n_drop = int(data.get("n_drop", 5))

        if not trained_model:
            return jsonify({"success": False, "error": "Missing trained_model"}), 400

        method = trained_model.get("factor_expressions", []) and "lasso" or "ic_optimization"

        # Run backtest
        if method == "lasso":
            from data.pipeline.optim.ml_training import evaluate_lasso_combination_backtest
            analysis_df, report_normal, positions_normal = evaluate_lasso_combination_backtest(
                trained_model=trained_model,
                start_date=start_date,
                end_date=end_date,
                topk=topk,
                n_drop=n_drop,
                instruments=market
            )
        else:
            from data.pipeline.optim.ic_optimization import evaluate_ic_optimized_combination_backtest
            analysis_df, report_normal, positions_normal = evaluate_ic_optimized_combination_backtest(
                optimized_model=trained_model,
                start_date=start_date,
                end_date=end_date,
                topk=topk,
                n_drop=n_drop,
                instruments=market
            )

        return jsonify({
            "success": True,
            "backtest_result": {
                "analysis": analysis_df.to_dict() if analysis_df is not None else None,
                "report_normal": report_normal,
                "positions_normal": positions_normal
            },
            "method": method,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.exception("Factor combination backtest error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route("/factor_combination/automated_training", methods=["POST"])
def automated_factor_training():
    """
    Run automated rolling window training pipeline.

    Body JSON:
    {
      "factor_expressions": ["expr1", "expr2", "expr3"],
      "start_date": "YYYY-MM-DD",
      "end_date": "YYYY-MM-DD",
      "training_window_days": 252,
      "update_frequency_days": 21,
      "methods": ["lasso", "ic_optimization"],
      "method_configs": {
        "lasso": {"alpha": 0.01},
        "ic_optimization": {"lambda_risk": 1.0}
      },
      "market": "csi300"
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}

        factor_expressions = data.get("factor_expressions", [])
        start_date = data.get("start_date", "2018-01-01")
        end_date = data.get("end_date", "2022-12-31")
        training_window_days = int(data.get("training_window_days", 252))
        update_frequency_days = int(data.get("update_frequency_days", 21))
        methods = data.get("methods", ["lasso"])
        method_configs = data.get("method_configs", {})
        market = data.get("market", "csi300")

        if not factor_expressions:
            return jsonify({"success": False, "error": "Missing factor_expressions"}), 400

        # Run automated training
        from data.pipeline.optim.training_pipeline import AutomatedFactorTrainingPipeline

        pipeline = AutomatedFactorTrainingPipeline(
            factor_expressions=factor_expressions,
            instruments=market
        )

        results = pipeline.run_rolling_training(
            start_date=start_date,
            end_date=end_date,
            training_window_days=training_window_days,
            update_frequency_days=update_frequency_days,
            methods=methods,
            method_configs=method_configs
        )

        return jsonify({
            "success": True,
            "automated_training_result": results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.exception("Automated training error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route("/factor_combination/compare_methods", methods=["POST"])
def compare_factor_methods():
    """
    Compare LASSO vs IC optimization approaches.

    Body JSON:
    {
      "factor_expressions": ["expr1", "expr2", "expr3"],
      "train_start": "YYYY-MM-DD",
      "train_end": "YYYY-MM-DD",
      "test_start": "YYYY-MM-DD",
      "test_end": "YYYY-MM-DD",
      "market": "csi300",
      "lasso_config": {"alpha": 0.01},
      "ic_config": {"lambda_risk": 1.0, "alpha_l1": 0.0}
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}

        factor_expressions = data.get("factor_expressions", [])
        train_start = data.get("train_start", "2018-01-01")
        train_end = data.get("train_end", "2020-12-31")
        test_start = data.get("test_start", "2021-01-01")
        test_end = data.get("test_end", "2021-12-31")
        market = data.get("market", "csi300")
        lasso_config = data.get("lasso_config", {"alpha": 0.01})
        ic_config = data.get("ic_config", {"lambda_risk": 1.0, "alpha_l1": 0.0})

        if not factor_expressions:
            return jsonify({"success": False, "error": "Missing factor_expressions"}), 400

        # Run comparison
        from data.pipeline.optim.ic_optimization import compare_ml_vs_ic_optimization

        comparison_result = compare_ml_vs_ic_optimization(
            factor_expressions=factor_expressions,
            train_start=train_start,
            train_end=train_end,
            test_start=test_start,
            test_end=test_end,
            instruments=market,
            lasso_alpha=lasso_config.get("alpha", 0.01),
            ic_lambda_risk=ic_config.get("lambda_risk", 1.0),
            ic_alpha_l1=ic_config.get("alpha_l1", 0.0)
        )

        return jsonify({
            "success": True,
            "comparison": comparison_result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.exception("Method comparison error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route("/factor_combination/generate_report", methods=["POST"])
def generate_factor_report():
    """
    Generate comprehensive report for factor combination results.

    Body JSON:
    {
      "training_results": {...},  // From automated training
      "backtest_results": {...},  // Optional backtest results
      "report_title": "My Factor Report"
    }
    """
    try:
        data = request.get_json(force=True, silent=True) or {}

        training_results = data.get("training_results")
        backtest_results = data.get("backtest_results")
        report_title = data.get("report_title", "Factor Combination Report")

        if not training_results:
            return jsonify({"success": False, "error": "Missing training_results"}), 400

        # Generate report
        from data.pipeline.optim.reporting import FactorCombinationReporter

        reporter = FactorCombinationReporter()
        report_result = reporter.generate_comprehensive_report(
            training_results=training_results,
            backtest_results=backtest_results,
            report_title=report_title
        )

        return jsonify({
            "success": True,
            "report_result": report_result,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

    except Exception as e:
        logger.exception("Report generation error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }), 500


@app.route("/factor_combination/list_models", methods=["GET"])
def list_saved_models():
    """
    List saved trained models.

    Query params:
      method: "lasso" or "ic_optimization" (optional)
    """
    try:
        method_filter = request.args.get("method")

        from data.pipeline.optim.training_pipeline import AutomatedFactorTrainingPipeline

        # Create pipeline instance to access model directory
        pipeline = AutomatedFactorTrainingPipeline(factor_expressions=[])
        model_dir = pipeline.model_save_path

        if not os.path.exists(model_dir):
            return jsonify({
                "success": True,
                "models": [],
                "message": "No models directory found"
            })

        models = []
        for filename in os.listdir(model_dir):
            if filename.endswith('.json'):
                parts = filename.split('_')
                if len(parts) >= 2:
                    method = parts[0]
                    date = parts[1].split('.')[0]

                    if method_filter and method != method_filter:
                        continue

                    models.append({
                        "filename": filename,
                        "method": method,
                        "training_date": date,
                        "path": os.path.join(model_dir, filename)
                    })

        # Sort by date descending
        models.sort(key=lambda x: x['training_date'], reverse=True)

        return jsonify({
            "success": True,
            "models": models,
            "total_count": len(models)
        })

    except Exception as e:
        logger.exception("List models error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}"
        }), 500


@app.route("/factor_combination/load_model", methods=["GET"])
def load_saved_model():
    """
    Load a saved trained model.

    Query params:
      method: "lasso" or "ic_optimization"
      training_date: "YYYY-MM-DD"
    """
    try:
        method = request.args.get("method")
        training_date = request.args.get("training_date")

        if not method or not training_date:
            return jsonify({"success": False, "error": "Missing method or training_date"}), 400

        from data.pipeline.optim.training_pipeline import AutomatedFactorTrainingPipeline

        pipeline = AutomatedFactorTrainingPipeline(factor_expressions=[])
        model = pipeline.load_model(method, training_date)

        if model is None:
            return jsonify({"success": False, "error": "Model not found"}), 404

        return jsonify({
            "success": True,
            "model": model
        })

    except Exception as e:
        logger.exception("Load model error")
        return jsonify({
            "success": False,
            "error": f"{type(e).__name__}: {e}"
        }), 500


# -----------------------------
# Entrypoint
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "9889"))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    print(f"Starting Factor Evaluation API on port {port}")
    print(f"Debug mode: {debug}")
    print(
        f"Example: http://localhost:{port}/eval?expr=%22Rank(Corr($close,$volume,10),252)%22&start=2023-01-01&end=2024-01-01&market=csi300"
    )

    # threaded=True is fine: all heavy work is pushed to subprocesses with hard timeouts
    app.run(host="0.0.0.0", port=port, debug=debug, threaded=True)
