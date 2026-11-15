#!/usr/bin/env python3
"""Exercise a selected Android device against an isolated local gateway.

Use a Python environment with services/gateway[dev] installed. Flutter and adb
must be on PATH (or supplied with --flutter/--adb). No microphone is recorded.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, help="Exact serial from adb devices -l")
    parser.add_argument("--adb", default=os.environ.get("ADB", "adb"))
    parser.add_argument("--flutter", default=os.environ.get("FLUTTER", "flutter"))
    args = parser.parse_args()
    args.adb = shutil.which(args.adb) or args.adb
    args.flutter = shutil.which(args.flutter) or args.flutter
    logs = ROOT / "artifacts" / "android-smoke"
    logs.mkdir(parents=True, exist_ok=True)
    report = {"passed": False, "device": args.device, "release_audio_evidence": False}
    report_path = logs / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    adb = [args.adb, "-s", args.device]
    state = subprocess.run(adb + ["get-state"], capture_output=True, text=True, timeout=20)
    if state.returncode or state.stdout.strip() != "device":
        print("Android device is unavailable or unauthorized. Enable USB debugging, unlock it, "
              "and accept its RSA prompt. For Wi-Fi debugging, pair/connect with adb first.",
              file=sys.stderr)
        print((state.stderr or state.stdout).strip(), file=sys.stderr)
        return 1

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]

    with tempfile.TemporaryDirectory(prefix="language-android-") as temp:
        token = secrets.token_urlsafe(24)
        environment = os.environ | {
            "LANGUAGE_GATEWAY_AUTH_TOKEN": token,
            "LANGUAGE_GATEWAY_SESSION_DB_PATH": str(Path(temp) / "session.sqlite3"),
            "LANGUAGE_GATEWAY_TRANSLATION_PROVIDER": "disabled",
            "LANGUAGE_GATEWAY_PRIORITIZER_BACKEND": "python",
        }
        device_port = None
        with (logs / "gateway.log").open("w", encoding="utf-8") as gateway_log:
            gateway = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1",
                 "--port", str(port)],
                cwd=ROOT / "services" / "gateway", env=environment,
                stdout=gateway_log, stderr=subprocess.STDOUT,
            )
            try:
                for _ in range(100):
                    if gateway.poll() is not None:
                        raise RuntimeError("Smoke gateway exited; see gateway.log")
                    try:
                        with urlopen(f"http://127.0.0.1:{port}/readyz", timeout=1) as response:
                            if response.status == 200:
                                break
                    except (URLError, TimeoutError):
                        time.sleep(0.1)
                else:
                    raise RuntimeError("Smoke gateway did not become ready")

                # Let adb allocate a device port, preserving existing reverse mappings.
                reverse = subprocess.run(
                    adb + ["reverse", "tcp:0", f"tcp:{port}"], check=True,
                    capture_output=True, text=True, timeout=20,
                )
                device_port = int(reverse.stdout.strip())
                defines = Path(temp) / "defines.json"
                defines.write_text(json.dumps({
                    "FIELD_APP_API_BASE_URL": f"http://127.0.0.1:{device_port}",
                    "FIELD_APP_AUTH_TOKEN": token,
                }), encoding="utf-8")
                print(f"Android smoke on {args.device}; logs: {logs}", flush=True)
                with (logs / "flutter.log").open("w", encoding="utf-8") as flutter_log:
                    result = subprocess.run(
                        [args.flutter, "test", "integration_test/gateway_smoke_test.dart",
                         "-d", args.device, f"--dart-define-from-file={defines}",
                         "--reporter=expanded"],
                        cwd=ROOT / "apps" / "field_app_flutter",
                        stdout=flutter_log, stderr=subprocess.STDOUT, timeout=1200,
                    )
                report["passed"] = result.returncode == 0
                report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
                if result.returncode:
                    tail = (logs / "flutter.log").read_text(encoding="utf-8", errors="replace")
                    print("\n".join(tail.splitlines()[-60:]), file=sys.stderr)
                print("Android smoke passed." if report["passed"] else "Android smoke failed.")
                return result.returncode
            finally:
                try:
                    if device_port is not None:
                        subprocess.run(adb + ["reverse", "--remove", f"tcp:{device_port}"],
                                       capture_output=True, timeout=20)
                finally:
                    gateway.terminate()
                    try:
                        gateway.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        gateway.kill()
                        gateway.wait(timeout=10)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"Android smoke failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
