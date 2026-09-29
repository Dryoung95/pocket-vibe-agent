#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

echo "Pocket Vibe Linux Control App"
echo "============================="
echo
echo "This script will:"
echo "  1) create/reuse .venv"
echo "  2) install Python requirements"
echo "  3) print PVA_PAIRING_CODE for the Windows operator"
echo "  4) start the Linux Hub at http://<linux-ip>:8787"
echo

chmod +x scripts/start-rk3588-pairing.sh
exec ./scripts/start-rk3588-pairing.sh
