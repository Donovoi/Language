#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_HOME="${FLUTTER_HOME:-$HOME/.local/share/flutter}"
FLUTTER_BIN_DIR="${FLUTTER_BIN_DIR:-$HOME/.local/bin}"
FLUTTER_WRAPPER="${FLUTTER_WRAPPER:-$FLUTTER_BIN_DIR/flutter}"
FLUTTER_RELEASES_JSON="${FLUTTER_RELEASES_JSON:-$HOME/.local/share/flutter-releases-linux.json}"
FLUTTER_ARCHIVE="${FLUTTER_ARCHIVE:-$HOME/.local/share/flutter-linux-stable.tar.xz}"
GATEWAY_DIR="$ROOT_DIR/services/gateway"
GATEWAY_VENV="${GATEWAY_VENV:-$GATEWAY_DIR/.venv}"

log() {
  printf '\n==> %s\n' "$1"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

ensure_path_entry() {
  local rc_file="$1"
  local line='export PATH="$HOME/.local/bin:$PATH"'
  touch "$rc_file"
  if ! grep -Fq "$line" "$rc_file"; then
    printf '\n%s\n' "$line" >> "$rc_file"
  fi
}

ensure_rust() {
  if command -v cargo >/dev/null 2>&1; then
    if command -v rustup >/dev/null 2>&1; then
      log "Ensuring Rust stable toolchain"
      rustup toolchain install stable --profile minimal --component clippy --component rustfmt --no-self-update >/dev/null
    fi
    return
  fi

  require_cmd curl
  log "Installing Rust via rustup"
  curl --proto '=https' --tlsv1.2 -fsSL https://sh.rustup.rs | sh -s -- -y --profile minimal --no-modify-path
  # shellcheck disable=SC1090
  . "$HOME/.cargo/env"
  rustup toolchain install stable --profile minimal --component clippy --component rustfmt --no-self-update >/dev/null
}

ensure_flutter() {
  require_cmd curl
  require_cmd python3
  require_cmd tar
  require_cmd xz

  mkdir -p "$FLUTTER_BIN_DIR" "$(dirname "$FLUTTER_HOME")"

  if [[ -x "$FLUTTER_HOME/bin/flutter" && -f "$FLUTTER_HOME/bin/internal/shared.sh" ]]; then
    log "Reusing existing Flutter SDK at $FLUTTER_HOME"
  else
    log "Resolving latest stable Flutter SDK"
    curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/releases_linux.json -o "$FLUTTER_RELEASES_JSON"
    local archive_path
    archive_path="$(
      python3 - "$FLUTTER_RELEASES_JSON" <<'PY'
import json
import sys

with open(sys.argv[1], 'r', encoding='utf-8') as fh:
    data = json.load(fh)
current = data['current_release']['stable']
for release in data['releases']:
    if (
        release.get('hash') == current
        and release.get('channel') == 'stable'
        and release.get('archive', '').startswith('stable/linux/')
    ):
        print(release['archive'])
        break
else:
    raise SystemExit('stable linux archive not found')
PY
  )"
    local archive_url="https://storage.googleapis.com/flutter_infra_release/releases/${archive_path}"
    log "Downloading Flutter from $archive_url"
    curl -fL --retry 5 --retry-all-errors --continue-at - "$archive_url" -o "$FLUTTER_ARCHIVE"
    log "Extracting Flutter SDK"
    rm -rf "$FLUTTER_HOME"
    tar -xJf "$FLUTTER_ARCHIVE" -C "$(dirname "$FLUTTER_HOME")"
  fi

  rm -f "$FLUTTER_WRAPPER"
  cat > "$FLUTTER_WRAPPER" <<'SH'
#!/usr/bin/env bash
exec "$HOME/.local/share/flutter/bin/flutter" "$@"
SH
  chmod +x "$FLUTTER_WRAPPER"
  ensure_path_entry "$HOME/.bashrc"
  ensure_path_entry "$HOME/.profile"
  export PATH="$FLUTTER_BIN_DIR:$PATH"

  log "Validating Flutter SDK"
  flutter --disable-analytics >/dev/null 2>&1 || true
  timeout 300 flutter --version
  timeout 300 flutter doctor -v || true
}

ensure_python_venv() {
  require_cmd python3

  log "Creating gateway virtual environment"
  python3 -m venv "$GATEWAY_VENV"
  "$GATEWAY_VENV/bin/python" -m pip install --upgrade pip
  (
    cd "$GATEWAY_DIR"
    "$GATEWAY_VENV/bin/python" -m pip install -e '.[dev]'
  )
}

bootstrap_workspace() {
  export PATH="$FLUTTER_BIN_DIR:$PATH"
  log "Fetching Rust dependencies"
  cargo fetch
  log "Preparing Flutter app"
  (
    cd "$ROOT_DIR/apps/field_app_flutter"
    flutter create . --platforms=android,ios,macos,windows
    rm -f test/widget_test.dart
    flutter pub get
  )
}

main() {
  require_cmd git
  require_cmd make
  require_cmd unzip
  ensure_rust
  ensure_flutter
  ensure_python_venv
  bootstrap_workspace
  log "Bootstrap complete"
  echo "Flutter wrapper: $FLUTTER_WRAPPER"
  echo "Gateway venv: $GATEWAY_VENV"
}

main "$@"
