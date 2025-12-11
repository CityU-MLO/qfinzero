"""
Entry point for running OQL queries from the command line.
- Supports demo queries via --demo
- Accepts a query string via -q/--query
- Accepts an as-of date YYYY-MM-DD via -d/--date
- Accepts API host/port
"""

import argparse
from datetime import datetime
import pandas as pd

from executor.data_client import OptionDataClient
from executor.executor import OQLEngine


def main():
    parser = argparse.ArgumentParser(description="Run OQL query")
    parser.add_argument("-q", "--query", type=str, help="OQL query string")
    parser.add_argument(
        "-f", "--file", type=str, help="Path to a .oql file to read as query"
    )
    parser.add_argument("-d", "--date", type=str, help="as-of date in YYYY-MM-DD")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API host")
    parser.add_argument("--port", type=int, default=19019, help="API port")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo queries")
    args = parser.parse_args()

    # Use user-specified date if provided, otherwise fallback to today
    as_of = args.date or datetime.now().strftime("%Y-%m-%d")

    engine = OQLEngine(data_client=OptionDataClient(host=args.host, port=args.port))

    # Demo mode: run a few predefined queries covering all strategies
    if args.demo:
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

        for i, q in enumerate(demos, 1):
            print(f"\n--- Demo {i} ---")
            print(q.strip())
            df = engine.execute(q, as_of_date=as_of)
            print(df if isinstance(df, str) else df.to_string(index=False))
        return

    # Read query from file if provided
    if args.file and not args.query:
        with open(args.file, "r", encoding="utf-8") as rf:
            args.query = rf.read()

    if not args.query:
        print("Please provide -q/--query or use --demo")
        return

    df = engine.execute(args.query, as_of_date=as_of)
    if isinstance(df, pd.DataFrame):
        print(df.to_string(index=False))
    else:
        print(df)


if __name__ == "__main__":
    main()
