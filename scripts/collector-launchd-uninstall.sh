#!/usr/bin/env bash
set -euo pipefail

LABEL=com.caoyifan.kol-crawler.collector
DOMAIN=${COLLECTOR_LAUNCHD_DOMAIN:-gui/$(id -u)}
AGENTS_DIR=${COLLECTOR_LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
PLIST="$AGENTS_DIR/$LABEL.plist"
LAUNCHCTL=${LAUNCHCTL_BIN:-launchctl}

"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
echo "collector launchd uninstalled"
