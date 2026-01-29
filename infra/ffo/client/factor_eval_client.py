#!/usr/bin/env python
"""
Factor Evaluation REST API Client (updated for new unified input format).

Endpoints (expected):
- GET  /health
- POST /factors/check
- POST /factors/eval
- POST /clear_cache          (optional)
- GET  /cache_stats          (optional)

Unified input:
- {"expression": "xxx"}                      # single
- {"expression": {"name": "expr", ...}}      # dict (one or many)
- {"expression": ["expr1", "expr2", ...]}    # list (no names)
- {"expression": ["expr1", {"n2":"expr2"}]}  # mixed list (optional)
"""

import time
import json
import logging
from typing import Dict, List, Optional, Union, Any

import requests

logger = logging.getLogger(__name__)

DEFAULT_API_URL = "http://127.0.0.1:19320"
DEFAULT_TIMEOUT = 120  # seconds
MAX_RETRIES = 5
RETRY_DELAY = 1  # seconds


ExpressionInput = Union[str, Dict[str, str], List[Union[str, Dict[str, str]]]]


class FactorEvalClient:
    """Client for Factor Evaluation API."""

    def __init__(self, base_url: str = DEFAULT_API_URL, timeout: int = DEFAULT_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        logger.info("FactorEvalClient initialized with base URL: %s", self.base_url)

    # ---------------------------
    # low-level request wrapper
    # ---------------------------
    def _make_request(self, method: str, endpoint: str, **kwargs) -> Optional[Any]:
        """
        Make an HTTP request with retry logic.

        Returns:
            Parsed JSON (dict/list) or None if failed.
        """
        url = f"{self.base_url}{endpoint}"

        for retry in range(MAX_RETRIES):
            try:
                resp = self.session.request(
                    method=method, url=url, timeout=self.timeout, **kwargs
                )

                # accept 200 only; you can also accept 400 as json if you want
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except Exception:
                        logger.warning("Non-JSON response: %s", resp.text[:300])
                        return {
                            "success": False,
                            "error": "Non-JSON response",
                            "_raw": resp.text,
                        }

                # for debugging: still try parse json
                try:
                    j = resp.json()
                except Exception:
                    j = {"_raw": resp.text}

                logger.warning(
                    "API request failed: %s %s -> %s, body=%s",
                    method,
                    endpoint,
                    resp.status_code,
                    str(j)[:300],
                )

            except requests.exceptions.ConnectionError:
                logger.warning(
                    "Connection error (attempt %d/%d)", retry + 1, MAX_RETRIES
                )
                if retry < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY * (retry + 1))

            except requests.exceptions.Timeout:
                logger.warning("Timeout (attempt %d/%d)", retry + 1, MAX_RETRIES)
                if retry < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)

            except Exception as e:
                logger.exception("Unexpected error: %s", e)
                break

        return None

    # ---------------------------
    # helpers
    # ---------------------------
    @staticmethod
    def _ensure_list_result(result: Any) -> List[Dict]:
        """
        Server now returns list for both single/multi,
        but just in case, normalize:
        - dict -> [dict]
        - list -> list
        - None -> []
        """
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return [result]
        return [
            {"success": False, "error": "Unexpected response type", "result": result}
        ]

    # ---------------------------
    # public API
    # ---------------------------
    def health_check(self) -> bool:
        result = self._make_request("GET", "/health")
        return isinstance(result, dict) and result.get("status") == "healthy"

    def check_factor(
        self,
        expression: ExpressionInput,
        instruments: str = "CSI300",
        start: Optional[str] = None,
        end: Optional[str] = None,
        timeout: Optional[int] = None,
    ) -> List[Dict]:
        """
        POST /factors/check
        Returns: always list of results
        """
        payload: Dict[str, Any] = {"expression": expression, "instruments": instruments}
        if start is not None:
            payload["start"] = start
        if end is not None:
            payload["end"] = end
        if timeout is not None:
            payload["timeout"] = int(timeout)

        result = self._make_request("POST", "/factors/check", json=payload)
        if result is None:
            return [
                {
                    "success": False,
                    "name": "",
                    "expression": "" if not isinstance(expression, str) else expression,
                    "error": "Server check failed",
                }
            ]
        return self._ensure_list_result(result)

    def evaluate_factor(
        self,
        expression: ExpressionInput,
        market: str = "csi300",
        start_date: str = "2023-01-01",
        end_date: str = "2024-01-01",
        label: str = "close_return",
        use_cache: bool = True,
        topk: int = 50,
        n_drop: int = 5,
        timeout: int = 120,
        fast: bool = False,
        n_jobs_backtest: int = 4,
    ) -> List[Dict]:
        """
        POST /factors/eval
        Returns: always list
        """
        payload = {
            "expression": expression,
            "start": start_date,
            "end": end_date,
            "market": market,
            "label": label,
            "use_cache": use_cache,
            "topk": int(topk),
            "n_drop": int(n_drop),
            "timeout": int(timeout),
            "fast": bool(fast),
            "n_jobs_backtest": int(n_jobs_backtest),
        }

        result = self._make_request("POST", "/factors/eval", json=payload)
        if result is None:
            # default failure list
            return [
                {
                    "success": False,
                    "error": "API request failed",
                    "metrics": {
                        "ic": 0.0,
                        "rank_ic": 0.0,
                        "ir": 0.0,
                        "icir": 0.0,
                        "rank_icir": 0.0,
                        "turnover": 1.0,
                    },
                }
            ]

        return self._ensure_list_result(result)

    def batch_evaluate_factors(
        self,
        factors: List[Dict[str, str]],
        market: str = "csi300",
        start_date: str = "2023-01-01",
        end_date: str = "2024-01-01",
        label: str = "close_return",
        timeout: int = 300,
        n_jobs: int = 1,
    ) -> Dict:
        """
        If you still keep /factors/batch_eval:
        Body:
        {
          "factors": [{"name":"F1","expression":"..."}, ...],
          ...
        }
        """
        payload = {
            "factors": factors,
            "start": start_date,
            "end": end_date,
            "market": market,
            "label": label,
            "timeout": int(timeout),
            "n_jobs": int(n_jobs),
        }
        result = self._make_request("POST", "/factors/batch_eval", json=payload)
        if result is None:
            return {
                "success": False,
                "error": "Batch API request failed",
                "results": [],
            }
        return result

    def clear_cache(self) -> bool:
        result = self._make_request("POST", "/clear_cache", json={})
        return isinstance(result, dict) and result.get("success", False)

    def get_cache_stats(self) -> Dict:
        result = self._make_request("GET", "/cache_stats")
        return (
            result
            if isinstance(result, dict)
            else {"cache_size": 0, "max_cache_size": 0}
        )


# ---------------------------
# global convenience wrappers
# ---------------------------
_global_client: Optional[FactorEvalClient] = None


def get_client(
    base_url: str = DEFAULT_API_URL, timeout: int = DEFAULT_TIMEOUT
) -> FactorEvalClient:
    global _global_client
    base_url = base_url.rstrip("/")
    if (
        _global_client is None
        or _global_client.base_url != base_url
        or _global_client.timeout != timeout
    ):
        _global_client = FactorEvalClient(base_url=base_url, timeout=timeout)
    return _global_client


def check_factor_via_api(
    expression: ExpressionInput, api_url: str = DEFAULT_API_URL
) -> List[Dict]:
    client = get_client(api_url)
    return client.check_factor(expression)


def evaluate_factor_via_api(
    expression: ExpressionInput,
    market: str = "csi300",
    start_date: str = "2023-01-01",
    end_date: str = "2024-01-01",
    label: str = "close_return",
    use_cache: bool = True,
    topk: int = 50,
    n_drop: int = 5,
    timeout: int = 120,
    fast: bool = False,
    n_jobs_backtest: int = 4,
    api_url: str = DEFAULT_API_URL,
) -> List[Dict]:
    client = get_client(api_url)
    return client.evaluate_factor(
        expression=expression,
        market=market,
        start_date=start_date,
        end_date=end_date,
        label=label,
        use_cache=use_cache,
        topk=topk,
        n_drop=n_drop,
        timeout=timeout,
        fast=fast,
        n_jobs_backtest=n_jobs_backtest,
    )
