"""stockdistro command line.

    stockdistro ingest statements/*.pdf   PDF -> canonical CSV (data/normalized)
    stockdistro prices                    download benchmark prices
    stockdistro build                     canonical CSV -> data/portfolio.db
    stockdistro refresh [pdfs...]         all three (default: every PDF in statements/)
    stockdistro demo --months 11          add synthetic earlier months (fake data)
    stockdistro clean-demo                remove the synthetic months
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from . import build_db, demo, prices, schema
from .fidelity_pdf import parse_statement

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
NORMALIZED = DATA / "normalized"
PRICES = DATA / "benchmark_prices.csv"
DB = DATA / "portfolio.db"


def cmd_ingest(pdfs: list[str]) -> None:
    paths = [Path(p) for p in pdfs] or sorted((ROOT / "statements").glob("*.pdf"))
    if not paths:
        raise SystemExit("no PDFs given and none found in statements/")
    for path in paths:
        accounts, holdings, warnings = parse_statement(path)
        if not accounts:
            print(f"✗ {path.name}: nothing parsed")
        else:
            folder = schema.write_statement(NORMALIZED, accounts, holdings)
            total = sum(a["ending_value"] for a in accounts)
            print(f"✓ {path.name}: {accounts[0]['period_start']} → {accounts[0]['period_end']}, "
                  f"{len(accounts)} accounts, {len(holdings)} holdings, ${total:,.2f} → {folder.relative_to(ROOT)}")
        for w in warnings:
            print(f"  ! {w}")


def cmd_prices() -> None:
    accounts, _ = schema.load_normalized(NORMALIZED)
    if not accounts:
        raise SystemExit("ingest a statement first")
    start = date.fromisoformat(min(a["period_start"] for a in accounts))
    end = date.fromisoformat(max(a["period_end"] for a in accounts))
    n = prices.fetch_benchmarks(ROOT / "benchmarks.csv", start, end, PRICES)
    print(f"✓ {n} benchmark prices {start} → {end} → {PRICES.relative_to(ROOT)}")


def cmd_build() -> None:
    stats = build_db.build(NORMALIZED, PRICES, DB)
    print(f"✓ {DB.relative_to(ROOT)}: " + ", ".join(f"{v} {k}" for k, v in stats.items()))
    _fit_dashboard_time_range()


def _fit_dashboard_time_range() -> None:
    """Point the dashboard's default time range at the months that are loaded."""
    accounts, _ = schema.load_normalized(NORMALIZED)
    dash = ROOT / "grafana" / "dashboards" / "portfolio.json"
    if not accounts or not dash.exists():
        return
    start = date.fromisoformat(min(a["period_start"] for a in accounts)) - timedelta(days=20)
    end = date.fromisoformat(max(a["period_end"] for a in accounts)) + timedelta(days=20)
    doc = json.loads(dash.read_text(encoding="utf-8"))
    doc["time"] = {"from": f"{start}T00:00:00.000Z", "to": f"{end}T00:00:00.000Z"}
    dash.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")


def main() -> None:
    # Windows consoles default to a legacy code page that cannot print ✓ / →
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="stockdistro", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest").add_argument("pdfs", nargs="*")
    sub.add_parser("prices")
    sub.add_parser("build")
    sub.add_parser("refresh").add_argument("pdfs", nargs="*")
    sub.add_parser("demo").add_argument("--months", type=int, default=11)
    sub.add_parser("clean-demo")
    args = ap.parse_args()

    if args.cmd == "ingest":
        cmd_ingest(args.pdfs)
    elif args.cmd == "prices":
        cmd_prices()
    elif args.cmd == "build":
        cmd_build()
    elif args.cmd == "refresh":
        cmd_ingest(args.pdfs)
        cmd_prices()
        cmd_build()
    elif args.cmd == "demo":
        n = demo.make_history(NORMALIZED, args.months)
        print(f"✓ added {n} synthetic months (fake data, tagged {demo.DEMO_TAG})")
        cmd_prices()
        cmd_build()
    elif args.cmd == "clean-demo":
        print(f"✓ removed {demo.clean(NORMALIZED)} synthetic months")
        cmd_prices()
        cmd_build()


if __name__ == "__main__":
    main()
