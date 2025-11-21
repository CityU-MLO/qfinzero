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
    parser.add_argument("-f", "--file", type=str, help="Path to a .oql file to read as query")
    parser.add_argument("-d", "--date", type=str, help="as-of date in YYYY-MM-DD")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="API host")
    parser.add_argument("--port", type=int, default=19019, help="API port")
    parser.add_argument("--demo", action="store_true", help="Run built-in demo queries")
    args = parser.parse_args()

    as_of = "2025-04-10" # args.date or datetime.now().strftime("%Y-%m-%d")
    engine = OQLEngine(data_client=OptionDataClient(host=args.host, port=args.port))

    # Demo mode: run a few predefined queries
    if args.demo:
        demos = [
            """
            SELECT BULL_CALL_SPREAD
            FROM NVDA
            WHERE L.Delta > 0.65
              AND S.Delta ~ 0.30
              AND L.Volume > 50
              AND S.Volume > 50
            HAVING net_theta > -0.1
            ORDER BY net_delta DESC
            LIMIT 5
            """,
            """
            SELECT CALENDAR_CALL
            FROM NVDA
            WHERE F.Dte ~ 7
              AND B.Dte ~ 35
              AND B.Volume > 20
            HAVING net_cost < 4.0
            ORDER BY net_vega DESC
            LIMIT 5
            """,
            """
            SELECT BULL_CALL_SPREAD
            FROM NVDA
            WHERE L.Delta < 0.15
              AND S.Delta < 0.10
            ORDER BY net_cost ASC
            LIMIT 5
            """,
        ]
        for i, q in enumerate(demos, 1):
            print(f"\n--- Demo {i} ---")
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
