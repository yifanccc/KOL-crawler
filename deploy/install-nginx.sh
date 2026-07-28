#!/usr/bin/env bash
set -euo pipefail

if [[ ${EUID:-$(id -u)} -ne 0 ]]; then
  echo "请使用 sudo bash deploy/install-nginx.sh" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="/etc/nginx/sites-available/yifanlab.cloud"
SNIPPET="/etc/nginx/snippets/kol-crawler.conf"
SOURCE_SNIPPET="$ROOT/deploy/nginx/kol-crawler.conf"
STAMP="$(date +%Y%m%d%H%M%S)"
SITE_BACKUP="${SITE}.before-kol-${STAMP}"
SNIPPET_BACKUP="${SNIPPET}.before-kol-${STAMP}"
SNIPPET_EXISTED=false

[[ -f "$SITE" ]] || { echo "找不到 $SITE" >&2; exit 1; }
[[ -f "$SOURCE_SNIPPET" ]] || { echo "找不到 $SOURCE_SNIPPET" >&2; exit 1; }
[[ $(grep -Fc 'server_name yifanlab.cloud www.yifanlab.cloud;' "$SITE") -eq 1 ]] || {
  echo "目标 server_name 不唯一，拒绝自动修改" >&2
  exit 1
}

cp -a "$SITE" "$SITE_BACKUP"
if [[ -f "$SNIPPET" ]]; then
  cp -a "$SNIPPET" "$SNIPPET_BACKUP"
  SNIPPET_EXISTED=true
fi

rollback() {
  cp -a "$SITE_BACKUP" "$SITE"
  if [[ "$SNIPPET_EXISTED" == true ]]; then
    cp -a "$SNIPPET_BACKUP" "$SNIPPET"
  else
    rm -f "$SNIPPET"
  fi
  nginx -t >/dev/null 2>&1 && systemctl reload nginx || true
  echo "Nginx 配置失败，已恢复原配置" >&2
}
trap rollback ERR

install -m 0644 "$SOURCE_SNIPPET" "$SNIPPET"
if ! grep -Fq 'include /etc/nginx/snippets/kol-crawler.conf;' "$SITE"; then
  sed -i '/server_name yifanlab.cloud www.yifanlab.cloud;/a\    include /etc/nginx/snippets/kol-crawler.conf;' "$SITE"
fi

nginx -t
systemctl reload nginx
trap - ERR

echo "KOL Crawler Nginx 路由已安装；站点备份：$SITE_BACKUP"
