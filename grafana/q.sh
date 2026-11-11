#!/bin/sh
# Run one SQL query through Grafana's data source proxy (debug helper).
# usage: grafana/q.sh "select ..." [from_ms] [to_ms]
python3 - "$@" <<'PY'
import json, sys, urllib.request
sql = sys.argv[1]
frm = sys.argv[2] if len(sys.argv) > 2 else "0"
to = sys.argv[3] if len(sys.argv) > 3 else "4102444800000"
body = {"from": frm, "to": to, "queries": [{"refId": "A", "datasource": {"uid": "portfolio-sqlite"},
        "queryType": "table", "rawQueryText": sql, "queryText": sql, "timeColumns": []}]}
req = urllib.request.Request("http://127.0.0.1:3000/api/ds/query", json.dumps(body).encode(),
                             {"content-type": "application/json"})
try:
    res = json.load(urllib.request.urlopen(req))
except urllib.error.HTTPError as e:
    print(e.read().decode()[:600]); sys.exit(1)
for frame in res["results"]["A"].get("frames", []):
    names = [f["name"] for f in frame["schema"]["fields"]]
    print(" | ".join(names))
    for row in zip(*frame["data"]["values"]):
        print(" | ".join(str(v) for v in row))
PY
