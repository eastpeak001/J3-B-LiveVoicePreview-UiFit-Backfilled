#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEVICE="${1:-auto}"
python3 scripts/jetson_capture_smoke_test.py --device "$DEVICE" --duration 60
