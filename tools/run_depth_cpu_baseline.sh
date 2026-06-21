#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEVICE="${1:-auto}"
shift || true
python3 scripts/run_depth_jetson.py --device "$DEVICE" --no-gui --duration 30 "$@"
