# stock-distro

Fidelity monthly statements → canonical CSV → SQLite → local Grafana dashboard.

```
statements/*.pdf ──ingest──▶ data/normalized/<month>/{accounts,holdings}.csv ─┐
benchmarks.csv ───prices──▶ data/benchmark_prices.csv ────────────────────────┼─build─▶ data/portfolio.db ─▶ Grafana
```

## Use

```bash
# 1. drop monthly statement PDFs into statements/, then:
uv run stockdistro refresh        # parse PDFs, download benchmark prices, rebuild the database

# 2. start Grafana (leave it running) and open http://127.0.0.1:3000
./run-grafana.sh
```

Re-run `refresh` whenever you add a statement; the dashboard picks up the new
database on its next refresh. Everything stays on this machine — `statements/`
and `data/` are git-ignored, Grafana listens on localhost only.

Other commands: `ingest`, `prices`, `build` (the three steps of `refresh`),
`demo --months 11` (adds clearly-tagged **fake** earlier months so the
over-time panels can be tried with a single statement) and `clean-demo`.

## Dashboard

Selectors at the top: **Account**, **Asset class**, **Holding** (tick/untick
positions), **Benchmark**.

| Section | What it shows |
|---|---|
| Overview | market value, unrealized gain, return over the range, benchmark returns |
| Distribution over time | % share by holding and by asset class per statement, value by account |
| Gain vs benchmarks — whole accounts | flow-adjusted cumulative and per-month return vs benchmarks |
| Gain vs benchmarks — selected holdings | price return of the ticked holdings as a basket, and individually |
| Holdings detail | table of the latest statement with weight, cost basis, gain |

How returns are computed:

- **Accounts**: per statement, `change in investment value / (beginning value + ½ net flow)`
  (Modified Dietz), chained across months. Deposits and withdrawals are not counted as gains.
- **Selected holdings**: price change of each position between consecutive statements,
  weighted by its value at the earlier statement. Price only (no dividends), and trades made
  mid-month are not time-weighted.
- **Benchmarks**: dividend-adjusted closes of the funds in `benchmarks.csv` (edit to add more
  tickers), rebased to 0% at the same start date and sampled on statement dates.

## Canonical format

Plain CSV, one folder per statement — see `stockdistro/schema.py` for column definitions.
Any other source (Fidelity positions CSV export, another broker) only needs a converter
that writes these two files:

- `accounts.csv`: `period_start, period_end, account_number, account_name, beginning_value,
  additions, subtractions, change_in_investment_value, ending_value, source_file`
- `holdings.csv`: `period_start, period_end, account_number, account_name, asset_class,
  asset_subclass, symbol, cusip, description, maturity, quantity, price, market_value,
  cost_basis, unrealized_gain, est_annual_income, source_file`

SQLite is read by Grafana through the `frser-sqlite-datasource` plugin (installed into
`grafana/runtime/plugins` by `run-grafana.sh`).

## Layout

- `stockdistro/fidelity_pdf.py` — statement parser. Holding rows are recognised by
  `quantity × price = value`; `ingest` prints a warning when an account's holdings do not
  add up to its stated ending value, which is the signal that a layout was not understood.
- `tools/make_dashboard.py` — generates `grafana/dashboards/portfolio.json`; edit SQL there.
- `grafana/q.sh "select ..."` — run a query through Grafana's data source for debugging.
- Grafana admin login (only needed to edit dashboards in the UI) is the stock default; anonymous
  access is view-only.
