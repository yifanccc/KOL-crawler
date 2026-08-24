#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

grep -Fq 'basePath: process.env.NEXT_PUBLIC_BASE_PATH || ""' "$ROOT/frontend/next.config.ts"
grep -Fq 'ARG NEXT_PUBLIC_BASE_PATH=' "$ROOT/frontend/Dockerfile"
grep -Fq 'COPY --from=builder /app/next.config.ts ./next.config.ts' "$ROOT/frontend/Dockerfile"
grep -Fq 'NEXT_PUBLIC_BASE_PATH: /kol' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'NEXT_PUBLIC_API_BASE_URL: https://www.yifanlab.cloud/kol' "$ROOT/deploy/docker-compose.prod.yml"
if grep -Fq 'NEXT_PUBLIC_API_BASE_URL: http://www.yifanlab.cloud/kol' "$ROOT/deploy/docker-compose.prod.yml"; then
  echo "production browser API URL must not downgrade HTTPS pages to HTTP" >&2
  exit 1
fi
grep -Fq '127.0.0.1:${KOL_API_PORT:-18010}:8000' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq '127.0.0.1:${KOL_WEB_PORT:-13010}:3000' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'DEEPSEEK_API_KEY: ${DEEPSEEK_API_KEY:-}' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'OPENAI_API_KEY: ${OPENAI_API_KEY:-}' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'MODEL_API_STYLE: ${MODEL_API_STYLE:-chat_completions}' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'OPENAI_BASE_URL: ${OPENAI_BASE_URL:-https://api.deepseek.com}' "$ROOT/deploy/docker-compose.prod.yml"
grep -Fq 'OPENAI_MODEL: ${OPENAI_MODEL:-deepseek-v4-pro}' "$ROOT/deploy/docker-compose.prod.yml"

if awk '/^  mysql:/{service="mysql"} /^  redis:/{service="redis"} /^  [a-z][a-z0-9_-]*:/{if ($1 != "mysql:" && $1 != "redis:") service=""} service && /ports:/' "$ROOT/deploy/docker-compose.prod.yml" | grep -q .; then
  echo "production mysql/redis must not publish host ports" >&2
  exit 1
fi

grep -Fq 'location ^~ /kol/api/' "$ROOT/deploy/nginx/kol-crawler.conf"
grep -Fq 'location ^~ /kol/' "$ROOT/deploy/nginx/kol-crawler.conf"
grep -Fq 'location = /kol' "$ROOT/deploy/nginx/kol-crawler.conf"
if grep -A2 -F 'location = /kol' "$ROOT/deploy/nginx/kol-crawler.conf" | grep -q 'return 30'; then
  echo "/kol must proxy directly because Next.js removes the trailing slash" >&2
  exit 1
fi
grep -Fq 'proxy_pass http://127.0.0.1:18010/api/' "$ROOT/deploy/nginx/kol-crawler.conf"
grep -Fq 'proxy_pass http://127.0.0.1:13010;' "$ROOT/deploy/nginx/kol-crawler.conf"

bash -n "$ROOT/deploy/install-nginx.sh"
docker compose --env-file "$ROOT/.env" -f "$ROOT/deploy/docker-compose.prod.yml" config --quiet

echo "production deployment contract ok"
