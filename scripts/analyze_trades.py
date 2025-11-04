"""Utility script to analyze option trade profitability from the provided CSV."""

from __future__ import annotations

import csv
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Iterable, List


CSV_PATH = Path(__file__).resolve().parents[1] / "trades.csv"


@dataclass
class Transaction:
    description: str
    instrument: str
    activity_date: str
    process_date: str
    settle_date: str
    trans_code: str
    quantity: int
    price: float
    amount: float


@dataclass
class ClosedTrade:
    open_txn: Transaction
    close_txn: Transaction

    @property
    def profit(self) -> float:
        """Return the net profit or loss for the closed trade."""
        return self.open_txn.amount + self.close_txn.amount


def parse_amount(value: str) -> float:
    """Convert a dollar amount that may contain parentheses into a float."""

    cleaned = value.replace("$", "").replace(",", "").strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    return -float(cleaned) if negative else float(cleaned)


def parse_price(value: str) -> float:
    """Convert a price string into a float."""

    cleaned = value.replace("$", "").strip()
    return float(cleaned)


def load_transactions(csv_path: Path) -> Iterable[Transaction]:
    """Load transactions from a CSV file."""

    with csv_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield Transaction(
                description=row["Description"],
                instrument=row["Instrument"],
                activity_date=row["Activity Date"],
                process_date=row["Process Date"],
                settle_date=row["Settle Date"],
                trans_code=row["Trans Code"],
                quantity=int(row["Quantity"]),
                price=parse_price(row["Price"]),
                amount=parse_amount(row["Amount"]),
            )


def group_closed_trades(
    transactions: Iterable[Transaction],
) -> tuple[List[ClosedTrade], Dict[str, Deque[Transaction]]]:
    """Pair open and close transactions into completed trades."""

    open_positions: Dict[str, Deque[Transaction]] = defaultdict(deque)
    closed_trades: List[ClosedTrade] = []

    for txn in transactions:
        key = txn.description
        if txn.trans_code in {"BTO", "STO"}:
            open_positions[key].append(txn)
        elif txn.trans_code in {"STC", "BTC"}:
            if not open_positions[key]:
                continue
            opening = open_positions[key].popleft()
            closed_trades.append(ClosedTrade(open_txn=opening, close_txn=txn))

    return closed_trades, open_positions


def main() -> None:
    transactions = list(load_transactions(CSV_PATH))
    closed_trades, open_positions = group_closed_trades(transactions)

    if not closed_trades:
        print("No closed trades were found in the CSV file.")
        return

    print("Closed trades and profitability:\n")
    for trade in closed_trades:
        direction = "Long" if trade.open_txn.trans_code == "BTO" else "Short"
        profit = trade.profit
        print(
            f"{trade.open_txn.description} ({direction})\n"
            f"  Opened: {trade.open_txn.activity_date} @ ${trade.open_txn.price:.2f}"
            f" ({trade.open_txn.amount:+.2f})\n"
            f"  Closed: {trade.close_txn.activity_date} @ ${trade.close_txn.price:.2f}"
            f" ({trade.close_txn.amount:+.2f})\n"
            f"  Profit: {profit:+.2f}\n"
        )

    total_profit = sum(trade.profit for trade in closed_trades)
    print(f"Total profit across closed trades: {total_profit:+.2f}\n")

    remaining = {
        desc: entries
        for desc, entries in open_positions.items()
        if entries
    }
    if remaining:
        print("Open positions that were not matched with a closing trade:")
        for desc, entries in remaining.items():
            for txn in entries:
                direction = "Long" if txn.trans_code == "BTO" else "Short"
                print(
                    f"  {desc} ({direction}) opened {txn.activity_date}"
                    f" @ ${txn.price:.2f} ({txn.amount:+.2f})"
                )


if __name__ == "__main__":
    main()
