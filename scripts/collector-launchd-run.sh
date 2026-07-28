#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ENV_FILE="$ROOT/collector/.env"
[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE" >&2; exit 1; }

set -a
source "$ENV_FILE"
set +a
mkdir -p "$ROOT/.runtime"
cd "$ROOT/collector"
exec "${COLLECTOR_PYTHON:-python}" -u -m collector_agent
