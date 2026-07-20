#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python3 -m accounting_agent.cli closeproof-demo
python3 -m unittest tests.test_closeproof
npm --prefix apps/closeproof-web test
npm --prefix apps/closeproof-web run build
diff -qr apps/closeproof-web/dist plugins/closeproof/assets/web
python3 -m unittest discover
python3 -m json.tool plugins/closeproof/.codex-plugin/plugin.json >/dev/null

if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git diff --check
fi

echo "BalanceDocket verification passed"
