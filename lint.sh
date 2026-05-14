#!/usr/bin/env bash
# Lint everything: ruff (api + ingestor) and eslint (web).
# Exit non-zero if any check fails. Run from repo root.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

red()    { printf '\033[31m%s\033[0m\n' "$*"; }
green()  { printf '\033[32m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }

FAILED=0

run_ruff() {
  local svc="$1"
  local dir="services/$svc"
  if [[ ! -d "$dir/.venv" ]]; then
    yellow "[$svc] no .venv — run: cd $dir && uv venv && uv pip install -e \".[dev]\""
    FAILED=1
    return
  fi
  yellow "[$svc] ruff check"
  if (cd "$dir" && .venv/bin/ruff check .); then
    green "[$svc] ruff: ok"
  else
    red "[$svc] ruff: failed"
    FAILED=1
  fi
}

run_eslint() {
  local svc="$1"
  local dir="services/$svc"
  if [[ ! -d "$dir/node_modules" ]]; then
    yellow "[$svc] no node_modules — run: cd $dir && npm install"
    FAILED=1
    return
  fi
  yellow "[$svc] eslint"
  if (cd "$dir" && npm run --silent lint); then
    green "[$svc] eslint: ok"
  else
    red "[$svc] eslint: failed"
    FAILED=1
  fi
}

run_ruff api
run_ruff ingestor-garmin
run_ruff treadmill-tracker
run_ruff pi-agent
run_eslint web

echo
if [[ $FAILED -eq 0 ]]; then
  green "All lint checks passed."
else
  red "Lint failed — see output above."
  exit 1
fi
