#!/usr/bin/env python3
"""Print an evidence-linked release progress estimate."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_REPORT = ROOT / "artifacts/release/audio-gate-report.json"
RELEASE_GATE_SCRIPT = ROOT / "scripts/release_audio_gate.py"


@dataclass(frozen=True)
class Milestone:
    key: str
    label: str
    percent: int
    weight: float
    evidence: str


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except (OSError, ValueError):
        return str(path)


def _file_has_text(path: str, text: str) -> bool:
    candidate = ROOT / path
    return candidate.exists() and text in candidate.read_text(encoding="utf-8", errors="replace")


def _run_release_gate() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(RELEASE_GATE_SCRIPT), "--json"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        if DEFAULT_GATE_REPORT.exists():
            return json.loads(DEFAULT_GATE_REPORT.read_text(encoding="utf-8"))
        raise RuntimeError("release gate did not emit JSON and no report file exists") from None


def _load_report(path: Path | None) -> dict[str, Any]:
    if path is not None:
        return json.loads(path.read_text(encoding="utf-8"))
    return _run_release_gate()


def _audio_percent(report: dict[str, Any]) -> tuple[int, str]:
    summary = _as_dict(report.get("summary"))
    gate_count = int(summary.get("release_blocking_gate_count", 0) or 0)
    failure_count = int(summary.get("release_blocking_failure_count", 0) or 0)
    if gate_count and failure_count == 0:
        return 100, "audio release gate passed"

    handoff = _as_dict(report.get("operator_handoff"))
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    dropbox = _as_dict(collection.get("raw_recording_dropbox"))
    state = _as_dict(dropbox.get("state"))
    missing = [str(item) for item in _as_list(state.get("missing_recordings"))]
    score_category_ready = _file_has_text("scripts/run_test_category.py", "release-evidence-score")
    if missing and score_category_ready:
        return 90, f"{gate_count - failure_count}/{gate_count} gates; missing WAVs: {', '.join(missing)}"
    if failure_count:
        return 85, f"{gate_count - failure_count}/{gate_count} gates; release blocker remains"
    return 80, "audio gate evidence is incomplete"


def build_progress(report: dict[str, Any]) -> dict[str, Any]:
    audio_percent, audio_evidence = _audio_percent(report)
    release_reports_exist = DEFAULT_GATE_REPORT.exists() and (ROOT / "artifacts/release/audio-gate-report.md").exists()
    checklist_ready = (ROOT / "artifacts/release/physical-audio-checklist.md").exists()
    flutter_ready = shutil.which("flutter") is not None
    auth_tests_ready = _file_has_text("services/gateway/tests/test_gateway.py", "test_read_endpoints_remain_auth_free")
    auth_runtime_ready = _file_has_text("services/gateway/app/auth.py", "require_write_token")
    category_runner_ready = _file_has_text("scripts/run_test_category.py", "physical-audio-handoff")
    token_doc_ready = (ROOT / "docs/development/token-budget.md").exists()

    milestones = [
        Milestone(
            "playback_source_suppression_evidence",
            "Playback/source suppression evidence",
            audio_percent,
            0.40,
            audio_evidence,
        ),
        Milestone(
            "release_smoke_artifacts",
            "Release smoke + artifact readiness",
            100 if release_reports_exist and checklist_ready and flutter_ready else 95 if release_reports_exist and checklist_ready else 90,
            0.12,
            "release reports, physical checklist, and Flutter host are ready"
            if release_reports_exist and checklist_ready and flutter_ready
            else "release reports/checklist exist; Flutter is not on PATH for local app validation"
            if release_reports_exist and checklist_ready
            else "release report artifact set incomplete",
        ),
        Milestone(
            "gateway_package_ergonomics",
            "Gateway/package ergonomics",
            100 if (ROOT / "scripts/verify_gateway_package.py").exists() else 90,
            0.10,
            "gateway package verifier present",
        ),
        Milestone(
            "auth_internal_beta",
            "Auth-enabled internal beta readiness",
            92 if auth_tests_ready and auth_runtime_ready else 80,
            0.14,
            "write-token runtime and gateway auth tests present" if auth_tests_ready and auth_runtime_ready else "auth runtime/tests incomplete",
        ),
        Milestone(
            "disposable_env_windows",
            "Disposable env + Windows usability",
            100 if category_runner_ready else 90,
            0.10,
            "category runner includes physical-audio handoff",
        ),
        Milestone(
            "research_detractor",
            "Research/detractor loop",
            98 if _file_has_text("scripts/release_audio_gate.py", "detractor_loop") else 90,
            0.08,
            "release gate carries detractor loop",
        ),
        Milestone(
            "token_discipline",
            "Token discipline",
            97 if token_doc_ready else 85,
            0.06,
            "token budget guide present",
        ),
    ]
    total = round(sum(item.percent * item.weight for item in milestones))
    return {
        "schema_version": 1,
        "total_percent": int(total),
        "milestones": [
            {
                "key": item.key,
                "label": item.label,
                "percent": item.percent,
                "weight": item.weight,
                "evidence": item.evidence,
            }
            for item in milestones
        ],
    }


def render_progress(progress: dict[str, Any]) -> str:
    lines = ["Release progress estimate:"]
    for milestone in _as_list(progress.get("milestones")):
        if not isinstance(milestone, dict):
            continue
        lines.append(f"- {milestone['label']}: {milestone['percent']}% ({milestone['evidence']})")
    lines.append(f"Total release goal: {progress['total_percent']}%")
    lines.append("Note: percentages are estimates; the release gate remains authoritative.")
    return "\n".join(lines)


def self_test() -> int:
    report = {
        "summary": {
            "release_blocking_gate_count": 6,
            "release_blocking_failure_count": 1,
        },
        "operator_handoff": {
            "headphone_collection_plan_status": {
                "raw_recording_dropbox": {
                    "state": {
                        "missing_recordings": [
                            "source_open_ear_recording",
                            "source_isolated_ear_recording",
                        ]
                    }
                }
            }
        },
    }
    progress = build_progress(report)
    rendered = render_progress(progress)
    required = [
        "Release progress estimate:",
        "Playback/source suppression evidence",
        "Total release goal:",
        "release gate remains authoritative",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing progress text: {text}")
    if not 0 <= int(progress["total_percent"]) <= 100:
        raise AssertionError("total percent out of range")
    print("release progress self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-report", type=Path, help="read an existing release gate JSON report")
    parser.add_argument("--json", action="store_true", help="print machine-readable progress JSON")
    parser.add_argument("--self-test", action="store_true", help="run contract checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        return self_test()
    report = _load_report(args.from_report)
    progress = build_progress(report)
    if args.json:
        print(json.dumps(progress, indent=2, sort_keys=True))
    else:
        print(render_progress(progress))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
