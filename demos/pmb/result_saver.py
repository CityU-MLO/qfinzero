"""
Utility to save demo results to disk in structured format.
"""

import json
import os
from datetime import datetime


class ResultSaver:
    """Save trading results to files."""

    def __init__(self, strategy_name: str, results_dir: str = "results"):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.strategy_name = strategy_name
        self.output_dir = os.path.join(results_dir, f"{strategy_name}_{timestamp}")
        os.makedirs(self.output_dir, exist_ok=True)
        self.summary_lines = []

    def add_summary_line(self, line: str):
        """Add a line to the summary report."""
        self.summary_lines.append(line)

    def save_summary(self, summary_data: dict):
        """Save summary.json with key metrics."""
        path = os.path.join(self.output_dir, "summary.json")
        with open(path, "w") as f:
            json.dump(summary_data, indent=2, fp=f)
        print(f"   ✓ Saved summary: {path}")

    def save_holdings(self, positions: list):
        """Save holdings.json with final positions."""
        path = os.path.join(self.output_dir, "holdings.json")
        with open(path, "w") as f:
            json.dump({"positions": positions}, indent=2, fp=f)
        print(f"   ✓ Saved holdings: {path}")

        # Also save as CSV
        csv_path = os.path.join(self.output_dir, "holdings.csv")
        with open(csv_path, "w") as f:
            f.write("instrument_id,qty,avg_price,mark_price,unrealized_pnl,realized_pnl\n")
            for pos in positions:
                f.write(
                    f"{pos['instrument_id']},{pos['qty']},{pos['avg_price']},"
                    f"{pos['mark_price']},{pos['unrealized_pnl']},{pos['realized_pnl']}\n"
                )
        print(f"   ✓ Saved holdings CSV: {csv_path}")

    def save_operations(self, orders: list, trades: list):
        """Save operations.json with all orders and trades."""
        path = os.path.join(self.output_dir, "operations.json")
        with open(path, "w") as f:
            json.dump({"orders": orders, "trades": trades}, indent=2, fp=f)
        print(f"   ✓ Saved operations: {path}")

        # Save orders CSV
        orders_csv = os.path.join(self.output_dir, "orders.csv")
        if orders:
            with open(orders_csv, "w") as f:
                keys = orders[0].keys()
                f.write(",".join(keys) + "\n")
                for order in orders:
                    f.write(",".join(str(order.get(k, "")) for k in keys) + "\n")
            print(f"   ✓ Saved orders CSV: {orders_csv}")

        # Save trades CSV
        trades_csv = os.path.join(self.output_dir, "trades.csv")
        if trades:
            with open(trades_csv, "w") as f:
                keys = trades[0].keys()
                f.write(",".join(keys) + "\n")
                for trade in trades:
                    f.write(",".join(str(trade.get(k, "")) for k in keys) + "\n")
            print(f"   ✓ Saved trades CSV: {trades_csv}")

    def save_equity_curve(self, equity_curve: list):
        """Save equity_curve.json and CSV."""
        path = os.path.join(self.output_dir, "equity_curve.json")
        with open(path, "w") as f:
            json.dump({"equity_curve": equity_curve}, indent=2, fp=f)
        print(f"   ✓ Saved equity curve: {path}")

        # CSV
        csv_path = os.path.join(self.output_dir, "equity_curve.csv")
        with open(csv_path, "w") as f:
            f.write("timestamp,equity\n")
            for point in equity_curve:
                f.write(f"{point['ts']},{point['equity']}\n")
        print(f"   ✓ Saved equity CSV: {csv_path}")

    def save_text_report(self):
        """Save a text summary report."""
        path = os.path.join(self.output_dir, "report.txt")
        with open(path, "w") as f:
            f.write("\n".join(self.summary_lines))
        print(f"   ✓ Saved text report: {path}")

    def print_saved_location(self):
        """Print the output directory."""
        print(f"\n{'='*70}")
        print(f"  Results saved to: {self.output_dir}")
        print(f"{'='*70}\n")
