#!/usr/bin/env python3
"""Run a bounded microphone/playback check on one selected Android device.

Records room sound for three seconds and replays it at the existing media volume.
Keeps only aggregate diagnostics; PCM is discarded on the device. Use --virtual
for emulator contract coverage, which cannot count as physical audio evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "com.example.field_app_flutter"
PERMISSION = "android.permission.RECORD_AUDIO"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True)
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    parser.add_argument("--flutter", default=os.environ.get("FLUTTER", "flutter"))
    parser.add_argument("--virtual", action="store_true")
    args = parser.parse_args()
    args.adb = shutil.which(args.adb) or args.adb
    args.flutter = shutil.which(args.flutter) or args.flutter
    logs = ROOT / "artifacts" / "android-audio-smoke"
    logs.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "physical_device": not args.virtual,
              "release_audio_evidence": False, "acoustic_quality_verified": False}
    report_path = logs / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    def adb(*command: str, check: bool = True) -> str:
        result = subprocess.run([args.adb, "-s", args.device, *command],
                                capture_output=True, text=True, timeout=20, check=check)
        return result.stdout.strip()

    if adb("get-state") != "device":
        raise RuntimeError("Selected device is unavailable; enable debugging and reconnect.")
    emulator = adb("shell", "getprop", "ro.kernel.qemu") == "1"
    if emulator != args.virtual:
        raise RuntimeError("Use --virtual only for an emulator; physical capture requires a phone.")
    package_info = adb("shell", "dumpsys", "package", PACKAGE)
    was_granted = f"{PERMISSION}: granted=true" in package_info
    # Revocation can stop the app. Do it before Flutter starts the test process.
    adb("shell", "pm", "revoke", PACKAGE, PERMISSION, check=False)
    process = None
    try:
        print(f"Android audio {'VM contract' if args.virtual else 'room-sound'} check; logs: {logs}",
              flush=True)
        process = subprocess.Popen(
            [args.flutter, "test", "integration_test/microphone_smoke_test.dart", "-d", args.device,
             f"--dart-define=FIELD_APP_PHYSICAL_AUDIO={str(not args.virtual).lower()}",
             "--reporter=expanded", "--no-uninstall"], cwd=ROOT / "apps" / "field_app_flutter",
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
        )
        lines: queue.Queue[str | None] = queue.Queue()

        def read_output() -> None:
            assert process is not None and process.stdout is not None
            for line in process.stdout:
                lines.put(line)
            lines.put(None)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        deadline = time.monotonic() + 1200
        with (logs / "flutter.log").open("w", encoding="utf-8") as log:
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("Android audio smoke exceeded 20 minutes.")
                try:
                    line = lines.get(timeout=0.25)
                except queue.Empty:
                    continue
                if line is None:
                    break
                log.write(line)
                log.flush()
                if line.strip() == "AUDIO_PERMISSION_WAIT":
                    adb("shell", "pm", "grant", PACKAGE, PERMISSION)
                elif line.strip() == "AUDIO_CAPTURE_START":
                    print("Recording three seconds of room sound, then replaying the clip.", flush=True)
                elif line.strip() == "AUDIO_BACKGROUND_WAIT":
                    adb("shell", "input", "keyevent", "KEYCODE_HOME")
                elif line.strip() == "AUDIO_BACKGROUND_CANCELLED":
                    adb("shell", "am", "start", "-n", f"{PACKAGE}/.MainActivity")
                    report["native_background_cancellation"] = True
                elif line.startswith("AUDIO_METRICS "):
                    report["metrics"] = json.loads(line.removeprefix("AUDIO_METRICS "))
        returncode = process.wait(timeout=20)
        report["passed"] = (returncode == 0 and "metrics" in report
                            and report.get("native_background_cancellation") is True)
        if not report["passed"]:
            tail = (logs / "flutter.log").read_text(encoding="utf-8", errors="replace")
            print("\n".join(tail.splitlines()[-50:]), file=sys.stderr)
        print("Android audio smoke passed." if report["passed"] else "Android audio smoke failed.")
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
        cleanup_errors = []
        for command in [
            ("shell", "am", "force-stop", PACKAGE),
            ("shell", "pm", "grant" if was_granted else "revoke", PACKAGE, PERMISSION),
        ]:
            try:
                adb(*command)
            except (OSError, subprocess.SubprocessError) as error:
                detail = str(error)
                if isinstance(error, subprocess.CalledProcessError):
                    detail += ": " + (error.stderr or error.stdout or "").strip()
                cleanup_errors.append(detail)
        report["cleanup_succeeded"] = not cleanup_errors
        if cleanup_errors:
            report["passed"] = False
            report["cleanup_errors"] = cleanup_errors
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        if cleanup_errors:
            raise RuntimeError("Device cleanup or permission restoration failed; see report.json.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Android audio smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
