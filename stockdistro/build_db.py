"""Load canonical CSVs into the SQLite database that Grafana reads."""
from __future__ import annotations

import sqlite3
from calendar import timegm
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from .schema import load_normalized, read_csv

DDL = """
CREATE TABLE account_periods (
    ts INTEGER, begin_ts INTEGER, period_start TEXT, period_end TEXT,
    account_number TEXT, account_name TEXT, account TEXT,
    beginning_value REAL, additions REAL, subtractions REAL,
    change_in_investment_value REAL, ending_value REAL,
    net_flow REAL, period_return REAL, source_file TEXT
);
CREATE TABLE holdings (
    ts INTEGER, period_end TEXT, account_number TEXT, account TEXT,
    asset_class TEXT, asset_subclass TEXT, security_id TEXT, holding TEXT,
    symbol TEXT, cusip TEXT, description TEXT, maturity TEXT,
    quantity REAL, price REAL, market_value REAL, cost_basis REAL,
    unrealized_gain REAL, est_annual_income REAL, source_file TEXT
);
-- one row per holding per pair of consecutive statements: what the position
-- held at the previous statement gained from price movement alone
CREATE TABLE holding_periods (
    ts INTEGER, begin_ts INTEGER, period_end TEXT, account TEXT, asset_class TEXT,
    security_id TEXT, holding TEXT, prev_value REAL, price_gain REAL
);
CREATE TABLE benchmark_prices (ts INTEGER, date TEXT, symbol TEXT, name TEXT, adj_close REAL);
CREATE INDEX ix_ap ON account_periods(ts);
CREATE INDEX ix_h ON holdings(ts);
CREATE INDEX ix_hp ON holding_periods(ts);
CREATE INDEX ix_bp ON benchmark_prices(symbol, ts);
"""


def _ts(iso: str) -> int:
    return timegm(date.fromisoformat(iso).timetuple())


def _f(v) -> float | None:
    return None if v in ("", None) else float(v)


def build(normalized_root: Path, prices_csv: Path, db_path: Path) -> dict:
    accounts, holdings = load_normalized(normalized_root)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_suffix(".db.tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(DDL)

    for a in accounts:
        begin, end, change = _f(a["beginning_value"]), _f(a["ending_value"]), _f(a["change_in_investment_value"])
        # everything that moved the balance but was not investment gain is a cash flow
        net_flow = round(end - begin - change, 2)
        # Modified Dietz with flows assumed mid-period
        denom = begin + 0.5 * net_flow
        ret = change / denom if denom > 0 else None
        begin_date = (date.fromisoformat(a["period_start"]) - timedelta(days=1)).isoformat()
        con.execute(
            "INSERT INTO account_periods VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_ts(a["period_end"]), _ts(begin_date), a["period_start"], a["period_end"],
             a["account_number"], a["account_name"], _account_label(a),
             begin, _f(a["additions"]), _f(a["subtractions"]), change, end, net_flow, ret, a["source_file"]),
        )

    by_position: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for h in holdings:
        sec = h["symbol"] or h["cusip"] or h["description"]
        label = f"{h['symbol']} · {h['description']}" if h["symbol"] else h["description"]
        label = label[:60]
        acct = _account_label(h)
        con.execute(
            "INSERT INTO holdings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_ts(h["period_end"]), h["period_end"], h["account_number"], acct,
             h["asset_class"], h["asset_subclass"], sec, label, h["symbol"], h["cusip"],
             h["description"], h["maturity"], _f(h["quantity"]), _f(h["price"]), _f(h["market_value"]),
             _f(h["cost_basis"]), _f(h["unrealized_gain"]), _f(h["est_annual_income"]), h["source_file"]),
        )
        by_position[(acct, sec)][h["period_end"]] = {**h, "holding": label}

    period_ends = sorted({h["period_end"] for h in holdings})
    prev_of = dict(zip(period_ends[1:], period_ends))
    for (acct, sec), series in by_position.items():
        for end, cur in series.items():
            prev = series.get(prev_of.get(end, ""))
            if not prev:
                continue
            p0, p1, v0 = _f(prev["price"]), _f(cur["price"]), _f(prev["market_value"])
            if not p0 or p1 is None or not v0:
                continue
            con.execute(
                "INSERT INTO holding_periods VALUES (?,?,?,?,?,?,?,?,?)",
                (_ts(end), _ts(prev["period_end"]), end, acct, cur["asset_class"], sec,
                 cur["holding"], v0, v0 * (p1 / p0 - 1)),
            )

    n_prices = 0
    if prices_csv.exists():
        for p in read_csv(prices_csv):
            con.execute("INSERT INTO benchmark_prices VALUES (?,?,?,?,?)",
                        (_ts(p["date"]), p["date"], p["symbol"], p["name"], float(p["adj_close"])))
            n_prices += 1
    con.commit()
    con.close()
    tmp.replace(db_path)
    return {"account_periods": len(accounts), "holdings": len(holdings),
            "statements": len(period_ends), "benchmark_prices": n_prices}


def _account_label(row: dict) -> str:
    """'Traditional IRA (…2222)' - readable, and keeps the full number off the charts."""
    name = row.get("account_name", "")
    short = name.split(" - ", 1)[1] if " - " in name else name
    return f"{short} (…{row['account_number'][-4:]})".strip()
