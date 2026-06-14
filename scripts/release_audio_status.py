#!/usr/bin/env python3
"""Print a compact release-audio status and next action summary."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_REPORT = ROOT / "artifacts/release/audio-gate-report.json"
RELEASE_GATE_SCRIPT = ROOT / "scripts/release_audio_gate.py"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _repo_relative(path: str | Path) -> str:
    candidate = Path(path)
    try:
        return str(candidate.resolve().relative_to(ROOT))
    except (OSError, ValueError):
        return str(path)


def _run_release_gate() -> tuple[int, dict[str, Any], str]:
    command = [sys.executable, str(RELEASE_GATE_SCRIPT), "--json"]
    result = subprocess.run(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        return result.returncode, json.loads(result.stdout), result.stderr.strip()
    except json.JSONDecodeError:
        if DEFAULT_GATE_REPORT.exists():
            return (
                result.returncode,
                json.loads(DEFAULT_GATE_REPORT.read_text(encoding="utf-8")),
                result.stderr.strip(),
            )
        raise RuntimeError(
            "release gate did not emit JSON and no report file was available"
        ) from None


def _load_report(path: Path) -> tuple[int, dict[str, Any], str]:
    return 0, json.loads(path.read_text(encoding="utf-8")), ""


def _manual_evidence_lines(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    manual = _as_dict(handoff.get("headphone_manual_status"))
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    dropbox = _as_dict(collection.get("raw_recording_dropbox"))
    dropbox_state = _as_dict(dropbox.get("state"))

    lines: list[str] = []
    if manual:
        lines.append(f"Manual WAV status: {manual.get('status', 'unknown')}")
        next_step = str(manual.get("next_step", "")).strip()
        if next_step:
            lines.append(f"Manual next step: {next_step}")
    if collection:
        path = str(collection.get("manifest_path", "")).strip()
        if path:
            lines.append(f"Manual manifest: {_repo_relative(path)}")
    dropbox_path = str(dropbox.get("path", "")).strip()
    if dropbox_path:
        lines.append(f"Raw WAV dropbox: {_repo_relative(dropbox_path)}")
    missing = [str(item) for item in _as_list(dropbox_state.get("missing_recordings"))]
    if missing:
        lines.append(f"Missing recordings: {', '.join(missing)}")
    return lines


def _recommended_commands(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    commands = _as_dict(collection.get("recommended_commands"))
    ordered_keys = (
        "prepare",
        "play_references",
        "import_recordings",
        "check_recordings",
        "score_recordings",
        "release_gate",
    )
    rendered: list[str] = []
    for key in ordered_keys:
        command = str(commands.get(key, "")).strip()
        if command:
            rendered.append(command)
    if not rendered:
        rendered.extend(
            [
                "pwsh -NoProfile -File scripts/dev_container.ps1 test-category evidence-kit",
                "pwsh -NoProfile -File scripts/dev_container.ps1 test-category recording-status",
                "python scripts/release_audio_gate.py --json",
            ]
        )
    return rendered


def render_status(report: dict[str, Any], gate_returncode: int) -> str:
    summary = _as_dict(report.get("summary"))
    gate_count = int(summary.get("release_blocking_gate_count", 0) or 0)
    failure_count = int(summary.get("release_blocking_failure_count", 0) or 0)
    passed_count = max(gate_count - failure_count, 0)
    state = "READY" if failure_count == 0 and gate_count else "NOT READY"

    lines = [
        f"Release audio status: {state}",
        f"Release gates: {passed_count}/{gate_count} passed",
    ]

    failures = [
        gate
        for gate in _as_list(report.get("release_blocking_gates"))
        if isinstance(gate, dict) and not gate.get("passed")
    ]
    if failures:
        lines.append("")
        lines.append("Blocking gates:")
        for gate in failures:
            name = str(gate.get("name", "unknown"))
            message = str(gate.get("message", "")).strip()
            next_step = str(gate.get("next_step", "")).strip()
            lines.append(f"- {name}: {message}")
            if next_step:
                lines.append(f"  Next: {next_step}")

    manual_lines = _manual_evidence_lines(report)
    if manual_lines:
        lines.append("")
        lines.append("Listener-ear evidence:")
        lines.extend(f"- {line}" for line in manual_lines)

    detractor = _as_dict(report.get("detractor_loop"))
    objection = str(detractor.get("strongest_current_objection", "")).strip()
    verdict = str(detractor.get("verdict", "")).strip()
    if objection or verdict:
        lines.append("")
        lines.append("Detractor check:")
        if objection:
            lines.append(f"- Objection: {objection}")
        if verdict:
            lines.append(f"- Verdict: {verdict}")

    if failures:
        lines.append("")
        lines.append("Next commands:")
        for index, command in enumerate(_recommended_commands(report), start=1):
            lines.append(f"{index}. {command}")

    markdown_path = ROOT / "artifacts/release/audio-gate-report.md"
    json_path = ROOT / "artifacts/release/audio-gate-report.json"
    if markdown_path.exists() or json_path.exists():
        lines.append("")
        lines.append("Reports:")
        if json_path.exists():
            lines.append(f"- {_repo_relative(json_path)}")
        if markdown_path.exists():
            lines.append(f"- {_repo_relative(markdown_path)}")

    if gate_returncode != 0 and not failures:
        lines.append("")
        lines.append(f"Gate command exited {gate_returncode}; inspect the full gate logs/report.")

    return "\n".join(lines)


def self_test() -> int:
    failed_report: dict[str, Any] = {
        "summary": {
            "release_blocking_gate_count": 2,
            "release_blocking_failure_count": 1,
        },
        "release_blocking_gates": [
            {"name": "capture", "passed": True},
            {
                "name": "playback_source_suppression_evidence",
                "passed": False,
                "message": "listener-ear WAVs missing",
                "next_step": "Collect WAVs.",
            },
        ],
        "operator_handoff": {
            "headphone_collection_plan_status": {
                "manifest_path": "artifacts/audio_eval/runs/manual/manifest.json",
                "recommended_commands": {
                    "prepare": "prepare command",
                    "release_gate": "release command",
                },
                "raw_recording_dropbox": {
                    "path": "artifacts/audio_eval/runs/manual/raw",
                    "state": {"missing_recordings": ["source_open_ear_recording"]},
                },
            },
            "headphone_manual_status": {
                "status": "NOT-READY",
                "next_step": "Capture WAVs.",
            },
        },
        "detractor_loop": {
            "strongest_current_objection": "reports alone are insufficient",
            "verdict": "keep gate strict",
        },
    }
    rendered = render_status(failed_report, gate_returncode=1)
    required = [
        "Release audio status: NOT READY",
        "Release gates: 1/2 passed",
        "playback_source_suppression_evidence",
        "Missing recordings: source_open_ear_recording",
        "prepare command",
        "release command",
        "Detractor check:",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing rendered text: {text}")

    passed_report: dict[str, Any] = {
        "summary": {
            "release_blocking_gate_count": 1,
            "release_blocking_failure_count": 0,
        },
        "release_blocking_gates": [{"name": "capture", "passed": True}],
    }
    passed = render_status(passed_report, gate_returncode=0)
    if "Release audio status: READY" not in passed or "Blocking gates:" in passed:
        raise AssertionError("passed release summary rendered incorrectly")

    print("release audio status self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-report",
        type=Path,
        help="summarize an existing release gate JSON report instead of running the gate",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with the release gate status; default exits 0 after printing the summary",
    )
    parser.add_argument("--self-test", action="store_true", help="run script contract checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return self_test()
    if args.from_report:
        gate_returncode, report, warning = _load_report(args.from_report)
    else:
        gate_returncode, report, warning = _run_release_gate()
    if warning:
        print(f"warning: {warning}", file=sys.stderr)
    print(render_status(report, gate_returncode))
    return gate_returncode if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
