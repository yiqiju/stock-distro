"""Synthesize earlier months from one real statement, so the over-time panels
can be tried before a full history of statements is loaded.

The generated rows are FAKE (random walk backwards from the real statement) and
are tagged source_file=SYNTHETIC-DEMO. `stockdistro clean-demo` removes them.
"""
from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

from .schema import load_normalized, write_statement

DEMO_TAG = "SYNTHETIC-DEMO"
DRIFT_VOL = {  # monthly mean / stdev of the price walk per asset class
    "Stocks": (0.010, 0.050),
    "Exchange Traded Products": (0.007, 0.035),
    "Mutual Funds": (0.004, 0.015),
    "Bonds": (0.002, 0.008),
    "Other": (0.005, 0.030),
    "Core Account": (0.0, 0.0),
}


def make_history(normalized_root: Path, months: int, seed: int = 7) -> int:
    accounts, holdings = load_normalized(normalized_root)
    real = [a for a in accounts if a["source_file"] != DEMO_TAG]
    if not real:
        raise SystemExit("ingest at least one real statement first")
    first_end = min(a["period_end"] for a in real)
    cur_accounts = [a for a in real if a["period_end"] == first_end]
    cur = [dict(h) for h in holdings if h["period_end"] == first_end and h["source_file"] != DEMO_TAG]
    for h in cur:
        for k in ("quantity", "price", "market_value"):
            h[k] = float(h[k])
    rng = random.Random(seed)
    period_start = date.fromisoformat(cur_accounts[0]["period_start"])

    for _ in range(months):
        end = period_start - timedelta(days=1)
        start = end.replace(day=1)
        prev, gain = [], {}
        for h in cur:
            mu, sd = DRIFT_VOL.get(h["asset_class"], (0.005, 0.03))
            money_fund = abs(h["price"] - 1.0) < 1e-9
            r = 0.0 if money_fund else max(-0.25, rng.gauss(mu, sd))
            p = dict(h)
            p["price"] = round(h["price"] / (1 + r), 4)
            if rng.random() < 0.12:               # position was smaller a month earlier
                p["quantity"] = round(h["quantity"] * rng.choice([0.6, 0.8, 1.25]), 3)
            scale = 100 if h["asset_class"] == "Bonds" else 1
            p["market_value"] = round(p["quantity"] * p["price"] / scale, 2)
            cost = float(h["cost_basis"]) if h.get("cost_basis") not in ("", None) else None
            p["unrealized_gain"] = round(p["market_value"] - cost, 2) if cost is not None else ""
            p.update(period_start=start.isoformat(), period_end=end.isoformat(), source_file=DEMO_TAG)
            prev.append(p)
        acct_rows = []
        for a in cur_accounts:
            num = a["account_number"]
            end_value = sum(p["market_value"] for p in prev if p["account_number"] == num)
            r = rng.gauss(0.007, 0.025)
            flow = rng.choice([0, 0, 500, 1000, -750])
            begin_value = (end_value - flow * (1 + r / 2)) / (1 + r)
            acct_rows.append({
                "period_start": start.isoformat(), "period_end": end.isoformat(),
                "account_number": num, "account_name": a["account_name"],
                "beginning_value": round(begin_value, 2),
                "additions": max(flow, 0), "subtractions": min(flow, 0),
                "change_in_investment_value": round(end_value - begin_value - flow, 2),
                "ending_value": round(end_value, 2), "source_file": DEMO_TAG,
            })
        write_statement(normalized_root, acct_rows, prev)
        cur, period_start = prev, start
    return months


def clean(normalized_root: Path) -> int:
    n = 0
    for folder in normalized_root.glob(f"*_{DEMO_TAG}"):
        for f in folder.iterdir():
            f.unlink()
        folder.rmdir()
        n += 1
    return n
