#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT_DIR="${AUDIO_EVAL_OUTPUT_DIR:-$ROOT_DIR/artifacts/audio_eval}"
REPORT_PATH="${AUDIO_EVAL_REPORT_PATH:-$OUTPUT_DIR/audio-eval-report.json}"

log() {
  printf '\n==> %s\n' "$1"
}

log "Running deterministic audio evaluation harness"
python3 "$ROOT_DIR/scripts/audio_eval_harness.py" check \
  --manifest "$ROOT_DIR/fixtures/audio_eval/v1/manifest.json" \
  --output-dir "$OUTPUT_DIR" \
  --report "$REPORT_PATH"

log "Audio evaluation check complete: $REPORT_PATH"
