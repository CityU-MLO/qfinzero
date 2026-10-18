"""A synthetic, redistributable QFinZero dataset (``qfz-sample``).

    qfz-sample generate --out ./qfz-sample        # UPQ storage + ESP data
    QFZ_DATA_ROOT=./qfz-sample qfz-server          # run the whole stack on it

Fictional tickers on the real Q1-2025 NYSE calendar: daily bars, minute bars
(pre-market, regular, after-hours and overnight), stock and option quotes,
option chains, a split, dividends, rates, earnings, macro releases and news.
Generation is deterministic (fixed seed); the benchmark in
:mod:`qfinzero.bench` is built on it.
"""

from .universe import SAMPLE_VERSION

__all__ = ["SAMPLE_VERSION", "generate"]


def generate(out, *, with_esp: bool = True) -> dict:
    from .build import build
    return build(out, with_esp=with_esp)
