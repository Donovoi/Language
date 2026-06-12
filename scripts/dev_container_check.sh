#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATEWAY_DIR="$ROOT_DIR/services/gateway"
GATEWAY_VENV="$GATEWAY_DIR/.venv"

log() {
  printf '\n==> %s\n' "$1"
}

log "Verifying generated contract bindings"
python3 "$ROOT_DIR/scripts/generate_contract_bindings.py" --check

log "Verifying Robin research pack scaffolding"
python3 "$ROOT_DIR/scripts/prepare_robin_research_pack.py" --check

log "Verifying external audio corpus catalog"
python3 "$ROOT_DIR/scripts/check_audio_corpus_catalog.py"

log "Running Rust formatting, lint, and tests"
(
  cd "$ROOT_DIR"
  cargo fmt --all --check
  cargo clippy --workspace --all-targets --all-features -- -D warnings
  cargo test --workspace
)

log "Preparing gateway Python environment"
python3 -m venv "$GATEWAY_VENV"
"$GATEWAY_VENV/bin/python" -m pip install --upgrade pip
(
  cd "$GATEWAY_DIR"
  "$GATEWAY_VENV/bin/python" -m pip install -e '.[dev]'
)

log "Running gateway lint and tests"
(
  cd "$GATEWAY_DIR"
  "$GATEWAY_VENV/bin/python" -m ruff check .
  "$GATEWAY_VENV/bin/python" -m pytest
)

log "Disposable core check complete"
