#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python3 -m json.tool .codex-plugin/plugin.json >/dev/null
python3 -m json.tool .mcp.json >/dev/null
python3 -m py_compile scripts/*.py
if python3 -m pytest --version >/dev/null 2>&1; then
  python3 -m pytest tests
elif command -v uvx >/dev/null 2>&1; then
  uvx pytest tests
else
  echo "pytest is required; install pytest or make uvx available." >&2
  exit 127
fi
swift test --package-path native/XcodeMCPServer

version="$(bin/xcode --version)"
out="/tmp/xcode-plugin-${version}.zip"
bin/xcode package zip --output "$out" --json
bin/xcode package audit --zip "$out" --json

if [[ "$(uname -s)" == "Darwin" ]]; then
  bin/xcode mcp bootstrap --json
  bin/xcode mcp version --json
  bin/xcode mcp health --json
  bin/xcode mcp list-tools --json
  bin/xcode mcp doctor --json
  bin/xcode doctor --json
fi

printf 'Release gate passed: %s\n' "$out"
