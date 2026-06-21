#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
DEVICE="${1:-auto}"
if [[ $# -gt 0 ]]; then
  shift
fi
python3 scripts/jetson_camera_audio_concurrent_test.py --device "$DEVICE" --duration 60 "$@"
