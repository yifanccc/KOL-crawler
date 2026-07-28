#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/home/Library/LaunchAgents" "$TMP/bin"

cat > "$TMP/bin/launchctl" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$LAUNCHCTL_LOG"
case "${1:-}" in
  print)
    test -f "$LAUNCHCTL_STATE"
    ;;
  bootstrap)
    test ! -f "$LAUNCHCTL_STATE" || exit 5
    printf 'loaded\n' > "$LAUNCHCTL_STATE"
    ;;
  bootout)
    printf 'unloading\n' > "$LAUNCHCTL_STATE"
    (sleep 0.1; rm -f "$LAUNCHCTL_STATE") &
    ;;
  kickstart)
    grep -Fqx 'loaded' "$LAUNCHCTL_STATE"
    ;;
esac
SH
chmod +x "$TMP/bin/launchctl"

export HOME="$TMP/home"
export COLLECTOR_LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
export COLLECTOR_LAUNCHD_DOMAIN="gui/501"
export LAUNCHCTL_BIN="$TMP/bin/launchctl"
export LAUNCHCTL_LOG="$TMP/launchctl.log"
export LAUNCHCTL_STATE="$TMP/launchctl.state"
export COLLECTOR_LAUNCHD_PATH="/test/opencli:/usr/bin:/bin"
export HTTP_PROXY="http://proxy.test:8080"
export HTTPS_PROXY="http://secure-proxy.test:8443"
export ALL_PROXY="socks5://proxy.test:1080"
export NO_PROXY="127.0.0.1,localhost"

"$ROOT/scripts/collector-launchd-install.sh"
"$ROOT/scripts/collector-launchd-install.sh"

PLIST="$COLLECTOR_LAUNCH_AGENTS_DIR/com.caoyifan.kol-crawler.collector.plist"
test -f "$PLIST"
grep -Fq '<string>com.caoyifan.kol-crawler.collector</string>' "$PLIST"
grep -Fq "<string>$ROOT/scripts/collector-launchd-run.sh</string>" "$PLIST"
grep -Fq '<key>RunAtLoad</key>' "$PLIST"
grep -Fq '<key>KeepAlive</key>' "$PLIST"
if grep -Fq '<key>ProcessType</key>' "$PLIST"; then
  echo "launchd plist must not force background process throttling" >&2
  exit 1
fi
grep -Fq '<string>/test/opencli:/usr/bin:/bin</string>' "$PLIST"
grep -Fq '<key>HTTP_PROXY</key>' "$PLIST"
grep -Fq '<string>http://proxy.test:8080</string>' "$PLIST"
grep -Fq '<key>HTTPS_PROXY</key>' "$PLIST"
grep -Fq '<string>http://secure-proxy.test:8443</string>' "$PLIST"
grep -Fq '<key>ALL_PROXY</key>' "$PLIST"
grep -Fq '<string>socks5://proxy.test:1080</string>' "$PLIST"
grep -Fq '<key>NO_PROXY</key>' "$PLIST"
grep -Fq '<string>127.0.0.1,localhost</string>' "$PLIST"
grep -Fq "bootstrap gui/501 $PLIST" "$LAUNCHCTL_LOG"
grep -Fq 'kickstart -k gui/501/com.caoyifan.kol-crawler.collector' "$LAUNCHCTL_LOG"
test "$(grep -c '^bootstrap gui/501 ' "$LAUNCHCTL_LOG")" -eq 2

"$ROOT/scripts/collector-stop.sh"
test ! -e "$LAUNCHCTL_STATE"
"$ROOT/scripts/collector-start.sh"
test "$(grep -c '^bootstrap gui/501 ' "$LAUNCHCTL_LOG")" -eq 3

"$ROOT/scripts/collector-launchd-uninstall.sh"

test ! -e "$PLIST"
grep -Fq 'bootout gui/501/com.caoyifan.kol-crawler.collector' "$LAUNCHCTL_LOG"
echo "launchd scripts ok"
