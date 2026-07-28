#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
LABEL=com.caoyifan.kol-crawler.collector
DOMAIN=${COLLECTOR_LAUNCHD_DOMAIN:-gui/$(id -u)}
AGENTS_DIR=${COLLECTOR_LAUNCH_AGENTS_DIR:-"$HOME/Library/LaunchAgents"}
PLIST="$AGENTS_DIR/$LABEL.plist"
LAUNCHCTL=${LAUNCHCTL_BIN:-launchctl}
PYTHON_BIN=${COLLECTOR_PYTHON:-$(command -v python)}
LAUNCHD_PATH=${COLLECTOR_LAUNCHD_PATH:-$PATH}

[[ -f "$ROOT/collector/.env" ]] || { echo "missing $ROOT/collector/.env" >&2; exit 1; }
mkdir -p "$AGENTS_DIR" "$ROOT/.runtime"
"$PYTHON_BIN" - "$ROOT/scripts/$LABEL.plist.template" "$PLIST" \
  "$ROOT" "$PYTHON_BIN" "$LAUNCHD_PATH" <<'PY'
from html import escape
from pathlib import Path
import os
import sys

template_path, output_path, root, python_bin, launchd_path = sys.argv[1:]
proxy_entries = "".join(
    f"    <key>{name}</key>\n    <string>{escape(value)}</string>\n"
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
    if (value := os.environ.get(name))
)
rendered = Path(template_path).read_text().replace("__ROOT__", escape(root))
rendered = rendered.replace("__PYTHON__", escape(python_bin))
rendered = rendered.replace("__PATH__", escape(launchd_path))
rendered = rendered.replace("__PROXY_ENV__", proxy_entries)
Path(output_path).write_text(rendered)
PY
chmod 600 "$PLIST"

"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
for _ in {1..50}; do
  "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
  sleep 0.1
done
if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  echo "collector launchd did not unload in time" >&2
  exit 1
fi
"$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST"
"$LAUNCHCTL" enable "$DOMAIN/$LABEL"
"$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL"
echo "collector launchd installed: $PLIST"
