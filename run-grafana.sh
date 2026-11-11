#!/bin/sh
# Start the local Grafana (http://127.0.0.1:3000) with this project's config.
cd "$(dirname "$0")" || exit 1
HOMEPATH="$(brew --prefix grafana)/share/grafana"
export STOCKDISTRO_DB="$PWD/data/portfolio.db"
export STOCKDISTRO_DASHBOARDS="$PWD/grafana/dashboards"
export GF_PATHS_DATA="$PWD/grafana/runtime/data"
export GF_PATHS_LOGS="$PWD/grafana/runtime/logs"
export GF_PATHS_PLUGINS="$PWD/grafana/runtime/plugins"
export GF_PATHS_PROVISIONING="$PWD/grafana/provisioning"
export GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH="$PWD/grafana/dashboards/portfolio.json"
mkdir -p grafana/runtime/data grafana/runtime/logs grafana/runtime/plugins
if [ ! -d grafana/runtime/plugins/frser-sqlite-datasource ]; then
  grafana cli --homepath "$HOMEPATH" --pluginsDir grafana/runtime/plugins plugins install frser-sqlite-datasource
fi
exec grafana server --homepath "$HOMEPATH" --config "$PWD/grafana/grafana.ini"
