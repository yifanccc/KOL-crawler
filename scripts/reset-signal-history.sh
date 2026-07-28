#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)

if [[ "${1:-}" != "--yes" ]]; then
  echo "This deletes all collected posts, signals, assets, notification events, and crawl history." >&2
  echo "Re-run with --yes after confirming the collector may be stopped and reinitialized." >&2
  exit 2
fi

cd "$ROOT"
./scripts/collector-stop.sh

docker compose exec -T api python - <<'PY'
import json

from app.db.session import SessionLocal
from app.services.history_reset import reset_signal_history

with SessionLocal.begin() as session:
    deleted = reset_signal_history(session)
print(json.dumps(deleted, ensure_ascii=False, sort_keys=True))
PY

if [[ -f "$ROOT/collector/.env" ]]; then
  set -a
  source "$ROOT/collector/.env"
  set +a
fi
COLLECTOR_DB_PATH=${COLLECTOR_DB_PATH:-../.runtime/collector.sqlite3}
if [[ "$COLLECTOR_DB_PATH" = /* ]]; then
  LOCAL_DB="$COLLECTOR_DB_PATH"
else
  LOCAL_DB="$ROOT/collector/$COLLECTOR_DB_PATH"
fi
rm -f "$LOCAL_DB" "$LOCAL_DB-shm" "$LOCAL_DB-wal" "$ROOT/.runtime/collector.pid"

./scripts/collector-start.sh
echo "signal history reset; collector restarted for one-post initialization"
