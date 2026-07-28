#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd); LOG="${COLLECTOR_RUNTIME_DIR:-"$ROOT/.runtime"}/collector.log"; LINES=50
[[ "${1:-}" == "--lines" ]] && LINES="${2:?missing line count}"
[[ -f "$LOG" ]] && tail -n "$LINES" "$LOG" || true
