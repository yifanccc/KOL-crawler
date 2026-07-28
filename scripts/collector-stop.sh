#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); PID="${COLLECTOR_RUNTIME_DIR:-"$ROOT/.runtime"}/collector.pid"
LABEL=com.caoyifan.kol-crawler.collector
DOMAIN=${COLLECTOR_LAUNCHD_DOMAIN:-gui/$(id -u)}
AGENTS_DIR=${COLLECTOR_LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
PLIST="$AGENTS_DIR/$LABEL.plist"
LAUNCHCTL=${LAUNCHCTL_BIN:-launchctl}
if [[ -f "$PLIST" ]]; then
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  for _ in {1..50}; do
    "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
    sleep 0.1
  done
  if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
    echo "collector launchd did not unload in time" >&2
    exit 1
  fi
  rm -f "$PID"
  echo "collector launchd stopped"
  exit 0
fi
[[ -f "$PID" ]] || { echo "stopped"; exit 0; }
PROCESS=$(cat "$PID")
if kill -0 "$PROCESS" 2>/dev/null; then kill -TERM "$PROCESS"; for _ in {1..20}; do kill -0 "$PROCESS" 2>/dev/null || break; sleep 1; done; fi
kill -0 "$PROCESS" 2>/dev/null && { echo "collector did not stop" >&2; exit 1; }
rm -f "$PID"; echo "stopped"
