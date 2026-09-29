#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="${POCKET_VIBE_PAIRING_ENV:-runtime/rk3588_pairing.env}"
mkdir -p runtime

random_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 24
  else
    "$PYTHON_BIN" -c 'import secrets; print(secrets.token_hex(24))'
  fi
}

quote_env_value() {
  local name="$1"
  local value="$2"
  printf "%s='" "$name"
  printf "%s" "$value" | sed "s/'/'\\\\''/g"
  printf "'\n"
}

detect_lan_ip() {
  local candidate=""
  if command -v hostname >/dev/null 2>&1; then
    for candidate in $(hostname -I 2>/dev/null || true); do
      case "$candidate" in
        127.*|169.254.*|"") continue ;;
        *) printf "%s\n" "$candidate"; return 0 ;;
      esac
    done
  fi
  if command -v ip >/dev/null 2>&1; then
    candidate="$(ip route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
    if [ -n "$candidate" ]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  fi
  printf "127.0.0.1\n"
}

if [ -f "$ENV_FILE" ]; then
  set -a
  . "$ENV_FILE"
  set +a
fi

POCKET_VIBE_TOKEN="${POCKET_VIBE_TOKEN:-$(random_token)}"
POCKET_VIBE_TOOL_TOKEN="${POCKET_VIBE_TOOL_TOKEN:-$(random_token)}"
POCKET_VIBE_HOST="${POCKET_VIBE_HOST:-0.0.0.0}"
POCKET_VIBE_PORT="${POCKET_VIBE_PORT:-8787}"
LAN_IP="${POCKET_VIBE_PAIRING_IP:-$(detect_lan_ip)}"
HUB_URL="${POCKET_VIBE_HUB_URL:-http://${LAN_IP}:${POCKET_VIBE_PORT}}"
DEVICE_NAME="$(hostname 2>/dev/null || printf "rk3588")"

{
  quote_env_value "POCKET_VIBE_TOKEN" "$POCKET_VIBE_TOKEN"
  quote_env_value "POCKET_VIBE_TOOL_TOKEN" "$POCKET_VIBE_TOOL_TOKEN"
  quote_env_value "POCKET_VIBE_HOST" "$POCKET_VIBE_HOST"
  quote_env_value "POCKET_VIBE_PORT" "$POCKET_VIBE_PORT"
  quote_env_value "POCKET_VIBE_PAIRING_IP" "$LAN_IP"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE" 2>/dev/null || true

export POCKET_VIBE_TOKEN POCKET_VIBE_TOOL_TOKEN POCKET_VIBE_HOST POCKET_VIBE_PORT
export HUB_URL DEVICE_NAME

PAIRING_CODE="$("$PYTHON_BIN" - <<'PY'
import base64
import datetime as dt
import json
import os

payload = {
    "type": "pocket-vibe-pairing",
    "version": 1,
    "hub": os.environ["HUB_URL"],
    "desktop_token": os.environ["POCKET_VIBE_TOKEN"],
    "tool_token": os.environ["POCKET_VIBE_TOOL_TOKEN"],
    "device": os.environ.get("DEVICE_NAME") or "rk3588",
    "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
}
raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
print(base64.urlsafe_b64encode(raw).decode("ascii").rstrip("="))
PY
)"

PAIRING_HTML="$ROOT/runtime/rk3588_pairing.html"
PAIRING_CODE_ESCAPED="${PAIRING_CODE//&/&amp;}"
PAIRING_CODE_ESCAPED="${PAIRING_CODE_ESCAPED//</&lt;}"
PAIRING_CODE_ESCAPED="${PAIRING_CODE_ESCAPED//>/&gt;}"

cat > "$PAIRING_HTML" <<HTML
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Pocket Vibe RK3588 Pairing</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #07111e; color: #f8fbff; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    main { width: min(920px, calc(100vw - 32px)); border: 1px solid rgba(148, 163, 184, .22); border-radius: 24px; padding: 28px; background: rgba(17, 25, 52, .92); box-shadow: 0 24px 80px rgba(0,0,0,.36); }
    h1 { margin: 0 0 8px; font-size: clamp(28px, 5vw, 54px); line-height: 1; }
    p { color: #9aa8c7; line-height: 1.7; }
    code, textarea { font-family: "Cascadia Code", Consolas, monospace; }
    textarea { width: 100%; min-height: 190px; box-sizing: border-box; border: 1px solid rgba(103,232,249,.45); border-radius: 16px; padding: 14px; color: #dbeafe; background: #040816; font-size: 13px; }
    .row { display: grid; gap: 10px; margin: 18px 0; }
    .pill { display: inline-block; width: fit-content; border: 1px solid rgba(103,232,249,.45); border-radius: 999px; padding: 8px 12px; color: #67e8f9; }
  </style>
</head>
<body>
  <main>
    <span class="pill">Pocket Vibe RK3588 Pairing</span>
    <h1>把下面的配对码发给 Windows 端</h1>
    <p>Windows 控制台打开 <code>http://127.0.0.1:8790/#pairing</code>，粘贴到“开发板配对码”，点击“应用配对码”。</p>
    <div class="row">
      <strong>Hub URL: <code>${HUB_URL}</code></strong>
      <textarea readonly onclick="this.select()">PVA_PAIRING_CODE=${PAIRING_CODE_ESCAPED}</textarea>
    </div>
    <p>保持这个终端不要关闭；关闭后 RK3588 Hub 会停止。</p>
  </main>
</body>
</html>
HTML

clear 2>/dev/null || true
cat <<EOF
Pocket Vibe RK3588 pairing
===========================

Device:      ${DEVICE_NAME}
Hub URL:     ${HUB_URL}
Token file:  ${ENV_FILE}
Pairing UI:  ${PAIRING_HTML}

Send this line to the Windows operator:

PVA_PAIRING_CODE=${PAIRING_CODE}

Windows side:
1. Open http://127.0.0.1:8790/#pairing
2. Paste the pairing code
3. Click "Apply pairing code"

Starting Device Hub now. Keep this terminal open.
EOF

if command -v xdg-open >/dev/null 2>&1 && { [ -n "${DISPLAY:-}" ] || [ -n "${WAYLAND_DISPLAY:-}" ]; }; then
  xdg-open "$PAIRING_HTML" >/dev/null 2>&1 &
fi

if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi

. .venv/bin/activate
python -m pip install -r requirements.txt
python device/device_hub.py
