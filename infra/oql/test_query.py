"""
Greek-focused OQL demo runner.

- Uses the same engine/OptionDataClient as the CLI.
- Runs a set of predefined queries that exercise Greeks in WHERE/HAVING.
- Applies summarize_strategy_df() to show a compact, human-friendly table.
"""

from datetime import datetime
from typing import List, Tuple

import pandas as pd

from executor.data_client import OptionDataClient
from executor.executor import OQLEngine
from executor.view import summarize_strategy_df, first_raw_row_json


demos = [
    # 1. Bull Call Spread
    """
    SELECT BULL_CALL_SPREAD
    FROM NVDA
    WHERE L.Delta > 0.50
        AND S.Delta ~ 0.25
        AND L.Volume > 50
        AND S.Volume > 50
    HAVING max_loss <= 300
        AND rr_ratio >= 1.0
    ORDER BY net_delta DESC
    LIMIT 5
    """,

    # 2. Bear Put Spread
    """
    SELECT BEAR_PUT_SPREAD
    FROM SPY
    WHERE L.Delta < -0.50
        AND S.Delta < -0.20
        AND L.Dte ~ 30
        AND S.Dte ~ 30
    HAVING max_loss <= 300
        AND rr_ratio >= 1.0
    ORDER BY net_delta ASC
    LIMIT 5
    """,

    # 3. Calendar Call
    """
    SELECT CALENDAR_CALL
    FROM NVDA
    WHERE F.Dte ~ 7
        AND B.Dte ~ 35
        AND B.Volume > 20
    HAVING net_cost < 5.0
        AND net_vega > 0
        AND net_theta > 0
    ORDER BY net_vega DESC
    LIMIT 5
    """,

    # 4. Calendar Put
    """
    SELECT CALENDAR_PUT
    FROM NVDA
    WHERE F.Dte ~ 14
        AND B.Dte ~ 60
        AND B.Volume > 10
    HAVING net_cost < 5.0
        AND net_vega > 0
    ORDER BY time_gap DESC
    LIMIT 5
    """,

    # 5. Straddle (ATM)
    """
    SELECT STRADDLE
    FROM NVDA
    WHERE C.Moneyness = ATM
        AND P.Moneyness = ATM
        AND C.Dte ~ 14
    HAVING net_theta < 0
        AND net_vega > 0
    ORDER BY net_vega DESC
    LIMIT 5
    """,

    # 6. Strangle (OTM)
    """
    SELECT STRANGLE
    FROM SPY
    WHERE C.Moneyness = OTM
        AND P.Moneyness = OTM
        AND C.Dte ~ 30
    HAVING net_delta BETWEEN -0.1 AND 0.1
    ORDER BY net_cost ASC
    LIMIT 5
    """,

    # 7. Iron Condor
    """
    SELECT IRON_CONDOR
    FROM SPY
    WHERE SC.Dte ~ 30 AND LC.Dte ~ 30
        AND SP.Dte ~ 30 AND LP.Dte ~ 30
    HAVING net_credit >= 50
        AND call_width BETWEEN 5 AND 20
        AND put_width  BETWEEN 5 AND 20
    ORDER BY rr_ratio DESC
    LIMIT 5
    """,

    # 8. Butterfly Call
    """
    SELECT BUTTERFLY_CALL
    FROM NVDA
    WHERE L1.Dte ~ 30 AND L2.Dte ~ 30 AND S.Dte ~ 30
        AND S.Moneyness = ATM
    HAVING net_debit <= 300
        AND rr_ratio >= 1.5
    ORDER BY max_profit DESC
    LIMIT 5
    """,
]


# (Title, Query)
GREEK_DEMO_QUERIES: List[Tuple[str, str]] = [
    (
        "Test",
        """
        SELECT BULL_PUT_SPREAD
        FROM   SPY
        WHERE  S.Strike ~ 500         -- "Panic fading... around 500": Sell the support/panic strike
        AND S.Dte ~ 30             -- "30-day horizon"
        AND L.Dte ~ 30             -- Matched expiry for vertical spread
        AND L.Moneyness = OTM      -- "Keep a hedge just in case": Buy further OTM put
        AND L.Strike < S.Strike    -- Ensure correct vertical spread structure (Long < Short)
        HAVING net_credit > 0         -- "Act like an insurance company": Ensure net income
        AND net_vega < 0           -- "VIX is huge": Position to profit from Volatility Crush
        AND rr_ratio >= 0.2        -- Optional: Minimum Reward-to-Risk floor
        ORDER BY rr_ratio DESC
        LIMIT 5
        """,
    ),
    # 1. Bull Call Spread – long leg high delta, positive net vega
    (
        "Bull Call Spread – high-delta long, positive net vega",
        """
        SELECT BULL_CALL_SPREAD
        FROM NVDA
        WHERE L.Dte ~ 30
          AND S.Dte ~ 30
          AND L.Delta > 0.55
          AND S.Delta ~ 0.30
          AND L.Vega > 0.20
          AND S.Vega > 0.10
        HAVING net_vega > 0
          AND net_theta < 0
        ORDER BY net_vega DESC
        LIMIT 5
        """,
    ),

    # 2. Bear Put Spread – strong negative delta, limited vega exposure
    (
        "Bear Put Spread – strong negative delta, moderate net vega",
        """
        SELECT BEAR_PUT_SPREAD
        FROM SPY
        WHERE L.Dte ~ 30
          AND S.Dte ~ 30
          AND L.Delta < -0.55
          AND S.Delta < -0.25
          AND L.Vega > 0.20
        HAVING net_delta < -0.20
          AND net_vega > 0
        ORDER BY net_delta ASC
        LIMIT 5
        """,
    ),

    # 3. Calendar Call – classic positive vega, positive theta
    (
        "Calendar Call – positive net vega and theta",
        """
        SELECT CALENDAR_CALL
        FROM NVDA
        WHERE F.Dte ~ 7
          AND B.Dte ~ 35
          AND F.Vega > 0.10
          AND B.Vega > 0.20
        HAVING net_vega > 0
          AND net_theta > 0
        ORDER BY net_vega DESC
        LIMIT 5
        """,
    ),

    # 4. Calendar Put – vega-focused downside hedge
    (
        "Calendar Put – vega-heavy downside hedge",
        """
        SELECT CALENDAR_PUT
        FROM NVDA
        WHERE F.Dte ~ 14
          AND B.Dte ~ 60
          AND F.Delta < -0.20
          AND B.Delta < -0.20
        HAVING net_vega > 0
          AND net_delta < 0
        ORDER BY net_vega DESC
        LIMIT 5
        """,
    ),

    # 5. Straddle – near ATM, vega heavy, negative theta
    (
        "Straddle – ATM, high net vega, negative net theta",
        """
        SELECT STRADDLE
        FROM NVDA
        WHERE C.Moneyness = ATM
          AND P.Moneyness = ATM
          AND C.Dte ~ 14
          AND C.Vega > 0.20
          AND P.Vega > 0.20
        HAVING net_vega > 0.5
          AND net_theta < 0
        ORDER BY net_vega DESC
        LIMIT 5
        """,
    ),

    # 6. Strangle – delta-neutral-ish, vega positive
    (
        "Strangle – delta-near-neutral, long volatility",
        """
        SELECT STRANGLE
        FROM SPY
        WHERE C.Moneyness = OTM
          AND P.Moneyness = OTM
          AND C.Dte ~ 30
          AND C.Vega > 0.15
          AND P.Vega > 0.15
        HAVING net_delta >= -0.10
          AND net_delta <=  0.10
          AND net_vega > 0.3
        ORDER BY net_vega DESC
        LIMIT 5
        """,
    ),

    # 7. Iron Condor – short volatility, near delta-neutral
    (
        "Iron Condor – short vega, near delta-neutral",
        """
        SELECT IRON_CONDOR
        FROM SPY
        WHERE SC.Dte ~ 30 AND LC.Dte ~ 30
          AND SP.Dte ~ 30 AND LP.Dte ~ 30
        HAVING put_width  >= 5
          AND put_width  <= 20
          AND call_width >= 5
          AND call_width <= 20
          AND net_delta >= -0.10
          AND net_delta <=  0.10
          AND net_vega <  0.10
        ORDER BY rr_ratio DESC
        LIMIT 5
        """,
    ),

    # 8. Butterfly Call – gamma-focused structure
    (
        "Butterfly Call – gamma-focused structure",
        """
        SELECT BUTTERFLY_CALL
        FROM NVDA
        WHERE L1.Dte ~ 30 AND L2.Dte ~ 30 AND S.Dte ~ 30
          AND S.Moneyness = ATM
        HAVING net_gamma > 0
          AND net_vega  < 0.2
        ORDER BY net_gamma DESC
        LIMIT 5
        """,
    ),
]


def run_greek_demos(
    as_of: str ,
    host: str = "127.0.0.1",
    port: int = 19019,
) -> None:
    """
    Run all Greek demo queries and print compact summaries.

    Parameters
    ----------
    as_of : str, optional
        As-of date in 'YYYY-MM-DD'. If None, uses today's date.
    host : str
        API host for OptionDataClient.
    port : int
        API port for OptionDataClient.
    """
    as_of_date = as_of or datetime.now().strftime("%Y-%m-%d")
    print(f"📆 Using as-of date: {as_of_date}")

    engine = OQLEngine(data_client=OptionDataClient(host=host, port=port))

    for i, (title, query) in enumerate(GREEK_DEMO_QUERIES, start=1):
        print("\n" + "=" * 80)
        print(f"[#{i}] {title}")
        print("-" * 80)
        print(query.strip())
        print("-" * 80)

        df = engine.execute(query, as_of_date=as_of_date)

        if isinstance(df, str):
            # Parser / strategy / data error message
            print(f"⚠️  Engine returned message: {df}")
            continue

        if df is None or df.empty:
            print("⚠️  No combos returned.")
            continue

        # Compact, human-friendly view

        if isinstance(df, pd.DataFrame) and not df.empty:
            df_view = summarize_strategy_df(df)
            print(df_view.head(10).to_string(index=False))

            # extra: print first raw row JSON preview
            print("\n[raw preview]")
            print(first_raw_row_json(df, indent=2))

        # If still huge, just show top 10 rows
        with pd.option_context("display.width", 200, "display.max_columns", 50):
            print(df_view.head(10).to_string(index=False))


if __name__ == "__main__":
    # Example: you can hardcode a date here if needed
    run_greek_demos(as_of="2025-04-10")
