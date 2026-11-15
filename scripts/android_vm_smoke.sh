#!/usr/bin/env bash
# Disposable Linux/KVM Android guest. SDKs are supplied by the host/CI VM.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
: "${ANDROID_HOME:?Set ANDROID_HOME to an Android SDK}"
PYTHON="${PYTHON:-python3}"
ADB="$ANDROID_HOME/platform-tools/adb"
SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
AVDMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
EMULATOR="$ANDROID_HOME/emulator/emulator"
IMAGE="system-images;android-35;google_apis;x86_64"
PORT="${LANGUAGE_EMULATOR_PORT:-5580}"
DEVICE="emulator-$PORT"
LOGS="$ROOT/artifacts/android-smoke"
mkdir -p "$LOGS"
printf '%s\n' '{"passed": false, "stage": "starting-vm", "release_audio_evidence": false}' > "$LOGS/report.json"
"$EMULATOR" -accel-check
# Fail before starting a second emulator on an occupied console/ADB port.
"$PYTHON" - "$PORT" <<'PY'
import socket
import sys
port = int(sys.argv[1])
if port < 5554 or port > 5682 or port % 2:
    raise SystemExit('LANGUAGE_EMULATOR_PORT must be an even port from 5554 to 5682')
for value in (port, port + 1):
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(('127.0.0.1', value))
PY
"$SDKMANAGER" "$IMAGE" > "$LOGS/sdk.log" 2>&1
AVD_DIR="$(mktemp -d -t language-avd-XXXXXXXX)"
export ANDROID_AVD_HOME="$AVD_DIR"
EMULATOR_PID=""
cleanup() {
    if [[ -n "$EMULATOR_PID" ]]; then
        kill "$EMULATOR_PID" 2>/dev/null || true
        wait "$EMULATOR_PID" 2>/dev/null || true
    fi
    rm -rf -- "$AVD_DIR"
}
trap cleanup EXIT
echo no | "$AVDMANAGER" create avd --name language-smoke --package "$IMAGE" --device pixel_6
"$EMULATOR" @language-smoke -port "$PORT" -no-window -no-audio -no-snapshot \
    -no-boot-anim -gpu swiftshader -memory 2048 -cores 2 \
    > "$LOGS/emulator.log" 2>&1 &
EMULATOR_PID=$!
for ((attempt=0; attempt<180; attempt++)); do
    if ! kill -0 "$EMULATOR_PID" 2>/dev/null; then
        tail -n 40 "$LOGS/emulator.log"
        exit 1
    fi
    if [[ "$("$ADB" -s "$DEVICE" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == 1 ]]; then
        "$ADB" -s "$DEVICE" shell input keyevent 82
        "$PYTHON" "$ROOT/scripts/smoke_android.py" --device "$DEVICE" --adb "$ADB"
        "$PYTHON" "$ROOT/scripts/smoke_android_audio.py" --device "$DEVICE" --adb "$ADB" --virtual
        exit $?
    fi
    sleep 2
done
echo "Android guest did not boot; see $LOGS/emulator.log" >&2
exit 1
