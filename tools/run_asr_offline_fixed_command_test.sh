#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 INPUT.wav [additional arguments]" >&2
  exit 2
fi

python3 scripts/jetson_asr_offline_fixed_command_test.py "$@"
