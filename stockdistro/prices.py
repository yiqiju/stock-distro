"""Download dividend-adjusted daily closes for the benchmark funds (Yahoo Finance)."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from .schema import PRICE_COLUMNS, read_csv, write_csv


def fetch_benchmarks(benchmarks_csv: Path, start: date, end: date, out_csv: Path) -> int:
    import yfinance as yf

    names = {r["symbol"].strip(): r["name"].strip() for r in read_csv(benchmarks_csv)}
    df = yf.download(
        list(names),
        start=(start - timedelta(days=10)).isoformat(),
        end=(end + timedelta(days=4)).isoformat(),
        auto_adjust=True,   # total return: dividends reinvested
        progress=False,
        group_by="ticker",
        threads=False,      # parallel downloads trip over yfinance's own cache lock
    )
    rows = []
    for symbol, name in names.items():
        try:
            closes = df[symbol]["Close"].dropna()
        except KeyError:
            print(f"  ! no price data for {symbol}")
            continue
        for ts, close in closes.items():
            rows.append({"date": ts.date().isoformat(), "symbol": symbol, "name": name,
                         "adj_close": round(float(close), 6)})
        if closes.empty:
            print(f"  ! no price data for {symbol} in this date range")
    write_csv(out_csv, PRICE_COLUMNS, rows)
    return len(rows)
