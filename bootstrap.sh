#!/bin/sh
# One-step setup and launch on macOS / Linux (Windows: bootstrap.ps1).
# Installs uv and Grafana if missing (via Homebrew), installs the SQLite data
# source plugin, builds the database from the PDFs in statements/, and starts
# Grafana with this project's dashboards.
#
#   ./bootstrap.sh                 # set up, rebuild data, start Grafana
#   ./bootstrap.sh --port 3001
#   ./bootstrap.sh --no-start      # set up and rebuild data only
#
# Safe to re-run: finished steps are skipped. Nothing is installed as a
# service; Grafana runs in this terminal until you press Ctrl+C.
set -e
cd "$(dirname "$0")"
ROOT="$PWD"
PORT=3000
START=1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --no-start) START=0; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '\n==> %s\n' "$1"; }
need() {  # need <command> <brew formula>
  command -v "$1" >/dev/null 2>&1 && return 0
  if command -v brew >/dev/null 2>&1; then
    brew install "$2"
  else
    echo "$1 not found and Homebrew is unavailable - install $2 and re-run." >&2
    exit 1
  fi
}

step 'Checking uv (Python package runner)'
need uv uv
uv --version

step 'Checking Grafana'
need grafana grafana
if [ -z "$GRAFANA_HOME" ]; then
  if command -v brew >/dev/null 2>&1 && brew --prefix grafana >/dev/null 2>&1; then
    GRAFANA_HOME="$(brew --prefix grafana)/share/grafana"
  else
    GRAFANA_HOME=/usr/share/grafana
  fi
fi
[ -d "$GRAFANA_HOME/conf" ] || { echo "Grafana home not found at $GRAFANA_HOME - set GRAFANA_HOME to the folder containing conf/." >&2; exit 1; }
echo "Grafana home: $GRAFANA_HOME"

RUNTIME="$ROOT/grafana/runtime"
mkdir -p "$RUNTIME/data" "$RUNTIME/logs" "$RUNTIME/plugins"
step 'Checking SQLite data source plugin'
if [ -d "$RUNTIME/plugins/frser-sqlite-datasource" ]; then
  echo 'already installed'
else
  grafana cli --homepath "$GRAFANA_HOME" --pluginsDir "$RUNTIME/plugins" plugins install frser-sqlite-datasource
fi

step 'Building the portfolio database from statements/*.pdf'
uv run stockdistro refresh

if [ "$START" -eq 0 ]; then
  printf '\nSetup complete. Run ./bootstrap.sh again without --no-start to launch Grafana.\n'
  exit 0
fi

in_use() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
if in_use "$PORT"; then
  FREE=$((PORT + 1))
  while in_use "$FREE"; do FREE=$((FREE + 1)); done
  echo "Port $PORT is already in use; using $FREE instead."
  PORT=$FREE
fi

export STOCKDISTRO_DB="$ROOT/data/portfolio.db"
export STOCKDISTRO_DASHBOARDS="$ROOT/grafana/dashboards"
export GF_PATHS_DATA="$RUNTIME/data"
export GF_PATHS_LOGS="$RUNTIME/logs"
export GF_PATHS_PLUGINS="$RUNTIME/plugins"
export GF_PATHS_PROVISIONING="$ROOT/grafana/provisioning"
export GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH="$ROOT/grafana/dashboards/portfolio.json"
export GF_SERVER_HTTP_PORT="$PORT"

step "Starting Grafana at http://127.0.0.1:$PORT  (Ctrl+C to stop)"
exec grafana server --homepath "$GRAFANA_HOME" --config "$ROOT/grafana/grafana.ini"
