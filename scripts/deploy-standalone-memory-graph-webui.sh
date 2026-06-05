#!/usr/bin/env bash
# Deploy the standalone Memory Graph WebUI/API. Set MG_PROJECT_DIR and NGINX_CONF for your deployment.
# This prevents the public Memory Graph dashboard from drifting back to the older
# embedded Hermes patch server on port 8900.
set -euo pipefail

MG_PROJECT_DIR="${MG_PROJECT_DIR:-}"
if [ -z "$MG_PROJECT_DIR" ]; then
  echo "MG_PROJECT_DIR must be set" >&2
  exit 2
fi
MG_BACKEND_DIR="$MG_PROJECT_DIR/backend"
MG_PORT="${MG_PORT:-8233}"
MG_HOST="${MG_HOST:-127.0.0.1}"
NGINX_CONF="${NGINX_CONF:-}"
NGINX_BIN="${NGINX_BIN:-/www/server/nginx/sbin/nginx}"
NGINX_MAIN_CONF="${NGINX_MAIN_CONF:-/www/server/nginx/conf/nginx.conf}"
UNIT_PATH="/etc/systemd/system/memory-graph-webui.service"

if [ ! -f "$MG_BACKEND_DIR/main.py" ]; then
  echo "❌ standalone Memory Graph backend missing: $MG_BACKEND_DIR/main.py" >&2
  exit 1
fi

# Runtime deps used by the standalone backend. Debian package names differ from
# Python import names; ahocorasick comes from python3-ahocorasick.
if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" -eq 0 ]; then
  missing_pkgs=()
  python3 - <<'PY' >/tmp/mg-webui-missing-mods
import importlib.util
for mod in ['bcrypt','itsdangerous','asyncpg','jieba','ahocorasick','filelock','diff_match_patch']:
    if not importlib.util.find_spec(mod):
        print(mod)
PY
  while read -r mod; do
    [ -z "$mod" ] && continue
    case "$mod" in
      bcrypt) missing_pkgs+=(python3-bcrypt) ;;
      itsdangerous) missing_pkgs+=(python3-itsdangerous) ;;
      asyncpg) missing_pkgs+=(python3-asyncpg) ;;
      jieba) missing_pkgs+=(python3-jieba) ;;
      ahocorasick) missing_pkgs+=(python3-ahocorasick) ;;
      filelock) missing_pkgs+=(python3-filelock) ;;
      diff_match_patch) missing_pkgs+=(python3-diff-match-patch) ;;
    esac
  done </tmp/mg-webui-missing-mods
  if [ ${#missing_pkgs[@]} -gt 0 ]; then
    DEBIAN_FRONTEND=noninteractive apt-get update -y >/dev/null 2>&1 || true
    DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_pkgs[@]}"
    echo "✅ installed deps: ${missing_pkgs[*]}"
  fi
fi

cat > "$UNIT_PATH" <<UNIT
[Unit]
Description=Standalone Memory Graph WebUI/API (project repo)
After=network-online.target postgresql@15-main.service
Wants=network-online.target postgresql@15-main.service

[Service]
Type=simple
WorkingDirectory=$MG_BACKEND_DIR
EnvironmentFile=-${HERMES_HOME:-$HOME/.hermes}/.env
Environment=PYTHONUNBUFFERED=1
Environment=HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}
ExecStart=/usr/bin/python3 $MG_BACKEND_DIR/main.py --host $MG_HOST --port $MG_PORT
Restart=always
RestartSec=5
TimeoutStartSec=30

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

# Remove stale manually-started backend processes that can steal port 8233.
if command -v ss >/dev/null 2>&1; then
  old_pids=$(ss -ltnp 2>/dev/null | awk -v port=":$MG_PORT" '$0 ~ port {print $NF}' | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u || true)
  for pid in $old_pids; do
    unit_pid=$(systemctl show -p MainPID --value memory-graph-webui.service 2>/dev/null || echo 0)
    if [ "$pid" != "$unit_pid" ] && [ "$pid" != "0" ]; then
      kill "$pid" 2>/dev/null || true
    fi
  done
fi

systemctl enable --now memory-graph-webui.service
systemctl restart memory-graph-webui.service
for _ in $(seq 1 30); do
  curl -fsS "http://$MG_HOST:$MG_PORT/health" >/dev/null 2>&1 && break
  sleep 0.5
done
curl -fsS "http://$MG_HOST:$MG_PORT/health" >/dev/null

if [ -f "$NGINX_CONF" ]; then
  python3 - "$NGINX_CONF" "$MG_PORT" <<'PY'
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); port=sys.argv[2]
text=p.read_text()
text2=re.sub(r'proxy_pass http://127\.0\.0\.1:\d+/', f'proxy_pass http://127.0.0.1:{port}/', text, count=1)
if text2 == text and f'proxy_pass http://127.0.0.1:{port}/' not in text:
    raise SystemExit('proxy_pass line not found')
p.write_text(text2)
PY
  if [ -x "$NGINX_BIN" ]; then
    "$NGINX_BIN" -t -c "$NGINX_MAIN_CONF"
    "$NGINX_BIN" -s reload -c "$NGINX_MAIN_CONF"
  fi
fi

echo "✅ standalone Memory Graph WebUI deployed on $MG_HOST:$MG_PORT"
