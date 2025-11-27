"""
Wrapper around optional infra.oql Greeks / IV utilities.

All imports are centralized here so the rest of the codebase can simply
import from this module and check for None when needed.
"""

try:
    # Greeks & IV utilities from the internal infra package.
    from infra.oql.utils.greeks import (
        yearfrac as greeks_yearfrac,
        build_rate_lookup as greeks_build_rate_lookup,
        implied_vol as greeks_implied_vol,
        bs_greeks as greeks_bs_greeks,
        compute_iv_and_greeks_timeseries,
    )
    greeks_import_error = None
except ImportError as e:
    greeks_import_error = e
    greeks_yearfrac = None
    greeks_build_rate_lookup = None
    greeks_implied_vol = None
    greeks_bs_greeks = None
    compute_iv_and_greeks_timeseries = None

try:
    # Optional helper - not currently used, but kept for future use.
    from infra.oql.utils.iv_infer import compute_iv_series  # noqa: F401
except ImportError:
    compute_iv_series = None
