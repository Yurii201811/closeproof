#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

port="${CLOSEPROOF_PORT:-4173}"
web_root="plugins/closeproof/assets/web"

if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo "CLOSEPROOF_PORT must be an integer from 1 through 65535" >&2
  exit 2
fi

if [[ ! -f "$web_root/index.html" ]]; then
  echo "The checked-in CloseProof web bundle is missing" >&2
  exit 1
fi

if [[ -n "${CLOSEPROOF_OUTPUT:-}" ]]; then
  output="$CLOSEPROOF_OUTPUT"
elif [[ "$port" == "4173" ]]; then
  output=".local/closeproof-demo"
else
  output=".local/closeproof-demo-$port"
fi

exec python3 scripts/run_closeproof_guarded.py \
  --output "$output" \
  --port "$port" \
  --web-root "$web_root"
