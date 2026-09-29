#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if [ -f runtime/rk3588_pairing.env ]; then
  set -a
  . runtime/rk3588_pairing.env
  set +a
fi

HUB_URL="${POCKET_VIBE_HUB_URL:-http://127.0.0.1:${POCKET_VIBE_PORT:-8787}}"
TOKEN="${POCKET_VIBE_TOOL_TOKEN:-dev-tool-token}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [ -x ".venv/bin/python" ]; then
  PYTHON_BIN=".venv/bin/python"
elif [ -z "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

if [ "$#" -eq 0 ]; then
  cat <<'EOF'
Usage:
  ./send-prompt.sh --agent codex-worker --prompt "请检查项目状态" --wait
  ./send-prompt.sh --provider codex --model gpt-5.6-terra --effort high --prompt "继续这个任务" --wait
  ./send-prompt.sh --provider claude --model sonnet --effort max --prompt "总结仓库入口" --wait

Useful:
  ./send-prompt.sh agent list
  ./send-prompt.sh doctor

The script loads runtime/rk3588_pairing.env automatically after start-linux-control-app.sh has generated it.
EOF
  exit 0
fi

case "$1" in
  doctor|agent|turn|task)
    exec "$PYTHON_BIN" tools/pva.py --hub "$HUB_URL" --token "$TOKEN" "$@"
    ;;
  *)
    exec "$PYTHON_BIN" tools/pva.py --hub "$HUB_URL" --token "$TOKEN" turn send "$@"
    ;;
esac
