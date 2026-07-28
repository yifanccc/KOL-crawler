#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
LABEL=com.caoyifan.kol-crawler.collector
DOMAIN=${COLLECTOR_LAUNCHD_DOMAIN:-gui/$(id -u)}
AGENTS_DIR=${COLLECTOR_LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
PLIST="$AGENTS_DIR/$LABEL.plist"
LAUNCHCTL=${LAUNCHCTL_BIN:-launchctl}
if [[ -f "$PLIST" ]]; then
  "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 || "$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST"
  "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL"
  echo "collector launchd started"
  exit 0
fi
RUNTIME=${COLLECTOR_RUNTIME_DIR:-"$ROOT/.runtime"}
PID="$RUNTIME/collector.pid"
LOG="$RUNTIME/collector.log"
mkdir -p "$RUNTIME"
if [[ -f "$PID" ]] && kill -0 "$(cat "$PID")" 2>/dev/null; then echo "collector already running: $(cat "$PID")" >&2; exit 1; fi
rm -f "$PID"
[[ -f "$ROOT/collector/.env" ]] && set -a && source "$ROOT/collector/.env" && set +a
(
  cd "$ROOT/collector"
  nohup python -m collector_agent >>"$LOG" 2>&1 &
  echo $! > "$PID"
)
echo "collector started: $(cat "$PID")"
