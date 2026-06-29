"""
Demo: Query option data via UPQClient.

Shows how to:
  - Query an option chain for an underlying (calls/puts, strike/expiry filters)
  - Fetch daily price data for a specific option contract
  - Fetch minute-level option data
  - Build OPRA contract IDs with make_opra()
  - Chain discovery → contract detail workflow

Prerequisites:
  - UPQ running on http://127.0.0.1:19350 with option data

Usage:
  cd qfinzero
  python demos/upq/option_query.py
"""

from qfinzero.clients.upq import UPQClient


def main():
    with UPQClient() as upq:

        # ── 1. Query option chain ───────────────────────────────
        print("=== NVDA Call Options Chain (2025-01-06) ===\n")

        chain = upq.option_chain(
            underlying="NVDA",
            date="2025-01-06",
            type="C",
            strike_min=130,
            strike_max=150,
            expiry_max="2025-02-21",
        )

        if chain:
            print(f"{'Contract':^28} | {'Strike':>7} | {'Expiry':^10} | {'Close':>7} | {'Volume':>7}")
            print("-" * 70)
            for opt in chain[:15]:  # show first 15
                contract = opt.get("ticker", opt.get("contract", ""))
                print(
                    f"{contract:^28} | ${opt['strike']:6.2f} | {opt['expiry']:^10} | "
                    f"${opt['close']:6.2f} | {opt.get('volume', 0):7,}"
                )
            print(f"\n{len(chain)} contracts found")
        else:
            print("No option data found. Make sure UPQ has NVDA option data loaded.\n")
            print("Continuing with constructed contract IDs...\n")

        # ── 2. Build OPRA contract ID ───────────────────────────
        print("\n=== Build OPRA Contract ID ===\n")

        contract_id = UPQClient.make_opra("NVDA", "2025-01-17", "C", 136.0)
        print(f"  make_opra('NVDA', '2025-01-17', 'C', 136.0)")
        print(f"  -> {contract_id}")

        contract_id2 = UPQClient.make_opra("AAPL", "2025-02-21", "P", 230.0)
        print(f"  make_opra('AAPL', '2025-02-21', 'P', 230.0)")
        print(f"  -> {contract_id2}")

        # ── 3. Query specific contract (daily) ──────────────────
        print(f"\n=== {contract_id} Daily Bars ===\n")

        try:
            bars = upq.option_contract(
                contract=contract_id,
                start="2025-01-06",
                end="2025-01-17",
                resolution="day",
            )

            if bars:
                print(f"{'Date':^12} | {'Open':>7} | {'High':>7} | {'Low':>7} | {'Close':>7} | {'Vol':>7}")
                print("-" * 60)
                for bar in bars:
                    date_str = bar.get("expiry", "")  # daily bars have metadata
                    print(
                        f"{'':^12} | ${bar['open']:6.2f} | ${bar['high']:6.2f} | "
                        f"${bar['low']:6.2f} | ${bar['close']:6.2f} | {bar.get('volume', 0):7,}"
                    )
                print(f"\nContract info: underlying={bars[0].get('underlying')}, "
                      f"strike={bars[0].get('strike')}, type={bars[0].get('type')}, "
                      f"expiry={bars[0].get('expiry')}")
            else:
                print("No data for this contract/date range.")
        except Exception as e:
            print(f"Query failed: {e}")

        # ── 4. Query specific contract (minute) ─────────────────
        print(f"\n=== {contract_id} Minute Bars (first 10) ===\n")

        try:
            bars = upq.option_contract(
                contract=contract_id,
                start="2025-01-06T09:30:00",
                end="2025-01-06T16:00:00",
                resolution="minute",
            )

            if bars:
                print(f"{'Time (UTC)':^24} | {'Close':>7} | {'Volume':>7}")
                print("-" * 45)
                for bar in bars[:10]:
                    ts = UPQClient.ns_to_datetime(bar["window_start"])
                    print(f"{ts.strftime('%Y-%m-%d %H:%M'):^24} | ${bar['close']:6.2f} | {bar.get('volume', 0):7,}")
                print(f"\n... {len(bars)} minute bars total")
            else:
                print("No minute data for this contract.")
        except Exception as e:
            print(f"Query failed: {e}")

        # ── 5. Chain discovery → contract detail workflow ────────
        print("\n=== Workflow: Chain → Contract Detail ===\n")

        chain = upq.option_chain(
            underlying="NVDA",
            date="2025-01-06",
            type="C",
            strike_min=130,
            strike_max=140,
            expiry_max="2025-02-21",
        )

        if chain:
            # Pick the highest-volume contract
            best = max(chain, key=lambda x: x.get("volume", 0))
            ticker = best.get("ticker", best.get("contract"))
            print(f"Highest volume call: {ticker}")
            print(f"  Strike: ${best['strike']:.2f}, Expiry: {best['expiry']}, "
                  f"Close: ${best['close']:.2f}, Volume: {best.get('volume', 0):,}")

            # Fetch its daily history
            bars = upq.option_contract(
                contract=ticker,
                start="2025-01-06",
                end="2025-01-17",
                resolution="day",
            )
            print(f"  Daily bars fetched: {len(bars)} rows")
        else:
            print("No chain data available for this example.")


if __name__ == "__main__":
    main()
