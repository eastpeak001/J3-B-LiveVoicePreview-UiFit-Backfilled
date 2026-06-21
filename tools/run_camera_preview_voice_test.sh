#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# All UI-fit and device options are intentionally passed through unchanged.
exec python3 scripts/jetson_camera_preview_voice_test.py "$@"
