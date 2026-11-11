"""Canonical interchange format: plain CSV, one folder per statement.

    data/normalized/<period_end>_<source>/accounts.csv
    data/normalized/<period_end>_<source>/holdings.csv
    data/benchmark_prices.csv

Anything that can be converted to these files (Fidelity PDF, a Fidelity
positions CSV export, another broker) can be loaded into the dashboards.
"""
from __future__ import annotations

import csv
from pathlib import Path

ACCOUNT_COLUMNS = [
    "period_start",                # ISO date, first day of the statement period
    "period_end",                  # ISO date, statement closing date
    "account_number",
    "account_name",
    "beginning_value",
    "additions",                   # deposits / transfers in (>= 0)
    "subtractions",                # withdrawals / transfers out (<= 0)
    "change_in_investment_value",  # market gain/loss + income for the period
    "ending_value",
    "source_file",
]
HOLDING_COLUMNS = [
    "period_start",
    "period_end",
    "account_number",
    "account_name",
    "asset_class",        # Stocks, Bonds, Mutual Funds, Exchange Traded Products, Core Account, Other
    "asset_subclass",     # e.g. Common Stocks, Bond Funds, Municipal Bonds
    "symbol",             # ticker when the statement shows one
    "cusip",              # bonds
    "description",
    "maturity",
    "quantity",
    "price",
    "market_value",
    "cost_basis",         # blank when unknown / not applicable
    "unrealized_gain",
    "est_annual_income",
    "source_file",
]
PRICE_COLUMNS = ["date", "symbol", "name", "adj_close"]


def write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_statement(out_root: Path, accounts: list[dict], holdings: list[dict]) -> Path:
    first = accounts[0]
    stem = Path(first["source_file"]).stem
    folder = out_root / f"{first['period_end']}_{stem}"
    write_csv(folder / "accounts.csv", ACCOUNT_COLUMNS, accounts)
    write_csv(folder / "holdings.csv", HOLDING_COLUMNS, holdings)
    return folder


def load_normalized(root: Path) -> tuple[list[dict], list[dict]]:
    accounts, holdings = [], []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if (folder / "accounts.csv").exists():
            accounts += read_csv(folder / "accounts.csv")
        if (folder / "holdings.csv").exists():
            holdings += read_csv(folder / "holdings.csv")
    return accounts, holdings
