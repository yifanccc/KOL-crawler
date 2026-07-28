#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); PID="${COLLECTOR_RUNTIME_DIR:-"$ROOT/.runtime"}/collector.pid"
LABEL=com.caoyifan.kol-crawler.collector
DOMAIN=${COLLECTOR_LAUNCHD_DOMAIN:-gui/$(id -u)}
AGENTS_DIR=${COLLECTOR_LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
PLIST="$AGENTS_DIR/$LABEL.plist"
LAUNCHCTL=${LAUNCHCTL_BIN:-launchctl}
if [[ -f "$PLIST" ]]; then
  STATE=$("$LAUNCHCTL" print "$DOMAIN/$LABEL" 2>/dev/null || true)
  if [[ "$STATE" == *"state = running"* ]]; then
    PROCESS=$(awk '/^[[:space:]]*pid = / { print $3; exit }' <<< "$STATE")
    echo "running ${PROCESS:-unknown} (launchd)"
  elif [[ -n "$STATE" ]]; then
    echo "launchd loaded but not running"
  else
    echo "launchd installed but unloaded"
  fi
  exit 0
fi
if [[ ! -f "$PID" ]]; then echo "stopped"; exit 0; fi
if kill -0 "$(cat "$PID")" 2>/dev/null; then echo "running $(cat "$PID")"; else echo "stale PID $(cat "$PID")"; fi
