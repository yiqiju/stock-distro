"""Generate grafana/dashboards/portfolio.json. Edit the SQL here, then run:
    python3 tools/make_dashboard.py
(Grafana reloads the file within ~10 seconds.)
"""
import json
from pathlib import Path

DS = {"type": "frser-sqlite-datasource", "uid": "portfolio-sqlite"}
T = "ts >= $__from / 1000 AND ts <= $__to / 1000"
ACC = "account IN (${account:sqlstring})"
HF = f"{ACC} AND asset_class IN (${{asset_class:sqlstring}}) AND holding IN (${{holding:sqlstring}})"
BENCH = "name IN (${benchmark:sqlstring})"
PRICE_AT = ("(SELECT adj_close FROM benchmark_prices x WHERE x.symbol = s.symbol "
            "AND x.ts <= {t} ORDER BY x.ts DESC LIMIT 1)")
_id = 0


def target(sql, ts=False, ref="A"):
    # always "table": the plugin's own long->wide conversion errors on empty results,
    # so the pivot is done by the prepareTimeSeries transformation instead
    return {"refId": ref, "datasource": DS, "queryType": "table",
            "queryText": sql, "rawQueryText": sql, "timeColumns": ["time"] if ts else []}


def panel(kind, title, x, y, w, h, sqls, ts=False, desc="", unit=None, custom=None, options=None,
          overrides=None, decimals=None, color=None):
    global _id
    _id += 1
    defaults = {"custom": custom or {}}
    if unit:
        defaults["unit"] = unit
    if decimals is not None:
        defaults["decimals"] = decimals
    if color:
        defaults["color"] = color
    return {"id": _id, "type": kind, "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [target(s, ts, chr(65 + i)) for i, s in enumerate(sqls)],
            "fieldConfig": {"defaults": defaults, "overrides": overrides or []},
            "options": options or {}}


def row(title, y):
    global _id
    _id += 1
    return {"id": _id, "type": "row", "title": title, "collapsed": False,
            "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def var(name, label, sql, default_all=True, current=None):
    v = {"name": name, "label": label, "type": "query", "datasource": DS,
         "query": sql, "definition": sql,
         "multi": True, "includeAll": True, "refresh": 2, "sort": 0,
         "current": {"text": ["All"], "value": ["$__all"]} if default_all else current}
    return v


# one frame for all series (so bars group and tooltips line up); the SQLite plugin
# names series "value <metric>", so strip the prefix
RENAME = [{"id": "prepareTimeSeries", "options": {"format": "multi"}},
          {"id": "joinByField", "options": {"byField": "time", "mode": "outer"}},
          {"id": "renameByRegex", "options": {"regex": "^value (.*)$", "renamePattern": "$1"}}]
LATEST = f"ts = (SELECT MAX(ts) FROM holdings WHERE {T})"
STAT = {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        "colorMode": "value", "graphMode": "none", "textMode": "auto"}
LEGEND_TABLE = {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"],
                           "sortBy": "Last *", "sortDesc": True},
                "tooltip": {"mode": "multi", "sort": "desc"}}
PCT_BARS = {"drawStyle": "bars", "fillOpacity": 85, "lineWidth": 0, "barWidthFactor": 0.7,
            "stacking": {"mode": "percent", "group": "A"}}
LINES = {"drawStyle": "line", "lineWidth": 2, "showPoints": "always", "pointSize": 6,
         "spanNulls": True, "fillOpacity": 0}

# ---------- cumulative return: selected accounts vs benchmarks ----------
ACC_CUM = f"""WITH p AS (
  SELECT ts, MIN(begin_ts) AS b,
         SUM(change_in_investment_value) / SUM(beginning_value + 0.5 * net_flow) AS r
  FROM account_periods WHERE {ACC} AND {T} GROUP BY ts)
SELECT MIN(b) AS time, 'My portfolio' AS metric, 0.0 AS value FROM p HAVING COUNT(*) > 0
UNION ALL
SELECT ts, 'My portfolio', EXP(SUM(LN(1 + r)) OVER (ORDER BY ts)) - 1 FROM p
ORDER BY 1"""


def bench_cum(table, where):
    return f"""WITH a AS (SELECT MIN(begin_ts) AS t0 FROM {table} WHERE {where}),
pts AS (SELECT t0 AS ts FROM a WHERE t0 IS NOT NULL UNION SELECT DISTINCT ts FROM {table} WHERE {where}),
s AS (SELECT DISTINCT symbol, name FROM benchmark_prices WHERE {BENCH})
SELECT pts.ts AS time, s.name AS metric,
       {PRICE_AT.format(t='pts.ts')} / {PRICE_AT.format(t='a.t0')} - 1 AS value
FROM pts, s, a ORDER BY 1"""


def bench_period(table, where):
    return f"""WITH p AS (SELECT DISTINCT ts, begin_ts FROM {table} WHERE {where}),
s AS (SELECT DISTINCT symbol, name FROM benchmark_prices WHERE {BENCH})
SELECT p.ts AS time, s.name AS metric,
       {PRICE_AT.format(t='p.ts')} / {PRICE_AT.format(t='p.begin_ts')} - 1 AS value
FROM p, s ORDER BY 1"""


ACC_PERIOD = f"""SELECT ts AS time, 'My portfolio' AS metric,
       SUM(change_in_investment_value) / SUM(beginning_value + 0.5 * net_flow) AS value
FROM account_periods WHERE {ACC} AND {T} GROUP BY ts ORDER BY 1"""

HP_WHERE = f"{HF} AND {T}"
HOLD_CUM = f"""WITH p AS (
  SELECT ts, MIN(begin_ts) AS b, SUM(price_gain) / SUM(prev_value) AS r
  FROM holding_periods WHERE {HP_WHERE} GROUP BY ts HAVING SUM(prev_value) > 0)
SELECT MIN(b) AS time, 'Selected holdings' AS metric, 0.0 AS value FROM p HAVING COUNT(*) > 0
UNION ALL
SELECT ts, 'Selected holdings', EXP(SUM(LN(1 + r)) OVER (ORDER BY ts)) - 1 FROM p
ORDER BY 1"""

HOLD_EACH = f"""WITH p AS (
  SELECT ts, holding, SUM(price_gain) / SUM(prev_value) AS r
  FROM holding_periods WHERE {HP_WHERE} GROUP BY ts, holding HAVING SUM(prev_value) > 0)
SELECT (SELECT MIN(begin_ts) FROM holding_periods WHERE {HP_WHERE}) AS time, holding AS metric, 0.0 AS value
FROM p GROUP BY holding
UNION ALL
SELECT ts, holding, EXP(SUM(LN(MAX(1 + r, 0.0001))) OVER (PARTITION BY holding ORDER BY ts)) - 1
FROM p ORDER BY 1"""

panels = [
    row("Overview — latest statement in the selected time range", 0),
    panel("stat", "Market value (selected holdings)", 0, 1, 5, 4,
          [f"SELECT SUM(market_value) AS value FROM holdings WHERE {HF} AND {LATEST}"],
          unit="currencyUSD", decimals=0, options=STAT, color={"mode": "fixed", "fixedColor": "blue"}),
    panel("stat", "Unrealized gain / loss", 5, 1, 5, 4,
          [f"SELECT SUM(unrealized_gain) AS value FROM holdings WHERE {HF} AND {LATEST}"],
          desc="Market value minus cost basis, for selected positions where the statement reports a cost basis.",
          unit="currencyUSD", decimals=0, options=STAT,
          color={"mode": "thresholds"}),
    panel("stat", "Return over range — selected accounts", 10, 1, 5, 4,
          [f"""SELECT EXP(SUM(LN(1 + r))) - 1 AS value FROM (
  SELECT SUM(change_in_investment_value) / SUM(beginning_value + 0.5 * net_flow) AS r
  FROM account_periods WHERE {ACC} AND {T} GROUP BY ts)"""],
          desc="Monthly returns chained together. Each month = change in investment value / "
               "(beginning value + half of net deposits), so deposits and withdrawals do not count as gains.",
          unit="percentunit", decimals=2, options=STAT, color={"mode": "thresholds"}),
    panel("stat", "Benchmarks over the same months", 15, 1, 6, 4,
          [f"""WITH a AS (SELECT MIN(begin_ts) AS t0, MAX(ts) AS t1 FROM account_periods WHERE {ACC} AND {T}),
s AS (SELECT DISTINCT symbol, name FROM benchmark_prices WHERE {BENCH})
SELECT s.name, {PRICE_AT.format(t='a.t1')} / {PRICE_AT.format(t='a.t0')} - 1 AS value FROM s, a"""],
          desc="Total return (dividends reinvested) of each selected benchmark fund between the same dates.",
          unit="percentunit", decimals=2,
          options={**STAT, "reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^value$/", "values": True},
                   "textMode": "value_and_name", "wideLayout": False},
          color={"mode": "thresholds"}),
    panel("stat", "Statements loaded", 21, 1, 3, 4,
          [f"SELECT COUNT(DISTINCT period_end) AS value FROM account_periods WHERE {T}"],
          options={**STAT, "colorMode": "none"}),

    row("Distribution over time", 5),
    panel("timeseries", "Share of portfolio by holding", 0, 6, 16, 11,
          [f"SELECT ts AS time, holding AS metric, SUM(market_value) AS value FROM holdings "
           f"WHERE {HF} AND {T} AND market_value > 0 GROUP BY 1, 2 ORDER BY 1"], ts=True,
          desc="Each bar is one statement; segments are each holding's share of the selected holdings "
               "(short positions excluded). Click a legend entry to isolate it, Cmd/Ctrl-click to toggle.",
          unit="currencyUSD", decimals=0, custom=PCT_BARS, options=LEGEND_TABLE),
    panel("piechart", "Latest statement — by holding", 16, 6, 8, 11,
          [f"SELECT holding, SUM(market_value) AS value FROM holdings WHERE {HF} AND {LATEST} "
           f"AND market_value > 0 GROUP BY 1 ORDER BY 2 DESC"],
          unit="currencyUSD", decimals=0,
          options={"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/^value$/", "values": True},
                   "pieType": "donut", "displayLabels": ["percent"],
                   "legend": {"displayMode": "table", "placement": "right", "values": ["percent"]},
                   "tooltip": {"mode": "single"}}),
    panel("timeseries", "Share of portfolio by asset class", 0, 17, 12, 9,
          [f"SELECT ts AS time, asset_class AS metric, SUM(market_value) AS value FROM holdings "
           f"WHERE {HF} AND {T} AND market_value > 0 GROUP BY 1, 2 ORDER BY 1"], ts=True,
          unit="currencyUSD", decimals=0, custom=PCT_BARS,
          options={"legend": {"displayMode": "list", "placement": "bottom"},
                   "tooltip": {"mode": "multi", "sort": "desc"}}),
    panel("timeseries", "Market value by account", 12, 17, 12, 9,
          [f"SELECT ts AS time, account AS metric, SUM(market_value) AS value FROM holdings "
           f"WHERE {HF} AND {T} GROUP BY 1, 2 ORDER BY 1"], ts=True,
          unit="currencyUSD", decimals=0,
          custom={**PCT_BARS, "stacking": {"mode": "normal", "group": "A"}},
          options={"legend": {"displayMode": "list", "placement": "bottom"},
                   "tooltip": {"mode": "multi", "sort": "desc"}}),

    row("Gain vs benchmarks — whole accounts (uses the Account and Benchmark selectors)", 26),
    panel("timeseries", "Cumulative return: my accounts vs benchmarks", 0, 27, 14, 10,
          [ACC_CUM, bench_cum("account_periods", f"{ACC} AND {T}")], ts=True,
          desc="Everything starts at 0% on the day before the first statement in range. Portfolio return is "
               "flow-adjusted (deposits are not gains) and includes dividends/interest; benchmarks are "
               "total return, sampled on statement dates.",
          unit="percentunit", decimals=2, custom=LINES,
          options={"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull"]},
                   "tooltip": {"mode": "multi", "sort": "desc"}},
          overrides=[{"matcher": {"id": "byName", "options": "My portfolio"},
                      "properties": [{"id": "custom.lineWidth", "value": 4},
                                     {"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}}]}]),
    {**panel("barchart", "Return per statement period", 14, 27, 10, 10,
             [ACC_PERIOD, bench_period("account_periods", f"{ACC} AND {T}")], ts=True,
             unit="percentunit", decimals=2,
             options={"xField": "time", "barWidth": 0.85, "groupWidth": 0.75, "showValue": "never",
                      "xTickLabelRotation": -45, "legend": {"displayMode": "list", "placement": "bottom"},
                      "tooltip": {"mode": "multi", "sort": "desc"}},
             overrides=[{"matcher": {"id": "byName", "options": "My portfolio"},
                         "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}}]},
                        {"matcher": {"id": "byName", "options": "time"},
                         "properties": [{"id": "unit", "value": "time:YYYY-MM"}]}]),
     "transformations": RENAME},

    row("Gain vs benchmarks — selected holdings (uses all selectors; needs 2+ statements)", 37),
    panel("timeseries", "Cumulative price return: selected holdings as a basket vs benchmarks", 0, 38, 12, 10,
          [HOLD_CUM, bench_cum("holding_periods", HP_WHERE)], ts=True,
          desc="Tick / untick holdings in the Holding selector to see how the basket would have done. "
               "Month-to-month price change of each position, weighted by its value at the previous "
               "statement. Price only: dividends and interest paid out are not included, so this "
               "slightly understates income-heavy holdings versus the total-return benchmarks.",
          unit="percentunit", decimals=2, custom=LINES,
          options={"legend": {"displayMode": "table", "placement": "bottom", "calcs": ["lastNotNull"]},
                   "tooltip": {"mode": "multi", "sort": "desc"}},
          overrides=[{"matcher": {"id": "byName", "options": "Selected holdings"},
                      "properties": [{"id": "custom.lineWidth", "value": 4},
                                     {"id": "color", "value": {"mode": "fixed", "fixedColor": "text"}}]}]),
    panel("timeseries", "Cumulative price return: each selected holding", 12, 38, 12, 10,
          [HOLD_EACH], ts=True, unit="percentunit", decimals=1,
          custom={**LINES, "lineWidth": 1, "showPoints": "never"}, options=LEGEND_TABLE),
    panel("barchart", "Price gain / loss in dollars by holding, over the range", 0, 48, 24, 20,
          [f"SELECT holding, SUM(price_gain) AS gain FROM holding_periods WHERE {HP_WHERE} "
           f"GROUP BY 1 ORDER BY 2 DESC"],
          unit="currencyUSD", decimals=0,
          options={"orientation": "horizontal", "xField": "holding", "showValue": "auto",
                   "legend": {"showLegend": False}, "barWidth": 0.8},
          color={"mode": "thresholds"}),

    row("Holdings detail — latest statement in range", 68),
    panel("table", "Holdings", 0, 69, 24, 14,
          [f"""SELECT h.account AS Account, h.asset_class AS "Asset class", h.holding AS Holding,
       h.quantity AS Quantity, h.price AS Price, h.market_value AS "Market value",
       h.market_value / (SELECT SUM(market_value) FROM holdings WHERE {HF} AND {LATEST} AND market_value > 0) AS Weight,
       h.cost_basis AS "Cost basis", h.unrealized_gain AS "Unrealized gain",
       CASE WHEN h.cost_basis > 0 THEN h.unrealized_gain / h.cost_basis END AS "Unrealized %",
       (SELECT hp.price_gain / hp.prev_value FROM holding_periods hp
         WHERE hp.ts = h.ts AND hp.account = h.account AND hp.security_id = h.security_id) AS "Price change (period)"
FROM holdings h WHERE {HF} AND {LATEST} ORDER BY h.market_value DESC"""],
          custom={"filterable": True},
          options={"footer": {"show": True, "reducer": ["sum"],
                              "fields": ["Market value", "Cost basis", "Unrealized gain"]},
                   "sortBy": [{"displayName": "Market value", "desc": True}]},
          overrides=[
              {"matcher": {"id": "byRegexp", "options": "/Market value|Cost basis|Unrealized gain|Price$/"},
               "properties": [{"id": "unit", "value": "locale"}, {"id": "decimals", "value": 2}]},
              {"matcher": {"id": "byRegexp", "options": "/Weight|%|Price change/"},
               "properties": [{"id": "unit", "value": "percentunit"}, {"id": "decimals", "value": 2}]},
              {"matcher": {"id": "byRegexp", "options": "/Unrealized|Price change/"},
               "properties": [{"id": "custom.cellOptions", "value": {"type": "color-text"}},
                              {"id": "thresholds", "value": {"mode": "absolute", "steps": [
                                  {"color": "red", "value": None}, {"color": "green", "value": 0}]}}]},
              {"matcher": {"id": "byName", "options": "Holding"},
               "properties": [{"id": "custom.minWidth", "value": 320}]},
              {"matcher": {"id": "byName", "options": "Account"},
               "properties": [{"id": "custom.minWidth", "value": 190}]},
          ]),
]

for p in panels:
    if p["type"] == "timeseries":
        p["transformations"] = RENAME

GAIN_THRESHOLDS = {"mode": "absolute", "steps": [{"color": "red", "value": None}, {"color": "green", "value": 0}]}
for p in panels:
    d = p.get("fieldConfig", {}).get("defaults", {})
    if d.get("color", {}).get("mode") == "thresholds":
        d["thresholds"] = GAIN_THRESHOLDS

out = Path(__file__).resolve().parent.parent / "grafana/dashboards/portfolio.json"
try:
    time_range = json.loads(out.read_text(encoding="utf-8"))["time"]   # keep the range `stockdistro build` set
except Exception:
    time_range = {"from": "now-3y", "to": "now"}

dashboard = {
    "uid": "fidelity-portfolio", "title": "Fidelity Portfolio", "tags": ["portfolio"],
    "schemaVersion": 39, "editable": True, "graphTooltip": 1, "timezone": "utc",
    "time": time_range, "refresh": "",
    "templating": {"list": [
        var("account", "Account", "SELECT DISTINCT account FROM account_periods ORDER BY 1"),
        var("asset_class", "Asset class", "SELECT DISTINCT asset_class FROM holdings ORDER BY 1"),
        var("holding", "Holding",
            "SELECT DISTINCT holding FROM holdings WHERE account IN (${account:sqlstring}) "
            "AND asset_class IN (${asset_class:sqlstring}) ORDER BY 1"),
        var("benchmark", "Benchmark", "SELECT DISTINCT name FROM benchmark_prices ORDER BY 1",
            default_all=False,
            current={"text": ["S&P 500 (SPY)", "Russell 1000 (IWB)"],
                     "value": ["S&P 500 (SPY)", "Russell 1000 (IWB)"]}),
    ]},
    "panels": panels,
}
out.write_text(json.dumps(dashboard, indent=1) + "\n", encoding="utf-8")
print(f"wrote {out}")
