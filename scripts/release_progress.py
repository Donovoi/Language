#!/usr/bin/env python3
"""Print an evidence-linked release progress estimate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATE_REPORT = ROOT / "artifacts/release/audio-gate-report.json"
RELEASE_GATE_SCRIPT = ROOT / "scripts/release_audio_gate.py"
PORTABLE_FLUTTER = Path("C:/tmp/flutter/bin/flutter.bat")
LOCAL_ARTIFACT_DIR = ROOT / "dist/local-release-artifacts"
LOCAL_ARTIFACT_MANIFEST = LOCAL_ARTIFACT_DIR / "manifest.md"
LOCAL_ARTIFACT_CHECKSUMS = LOCAL_ARTIFACT_DIR / "SHA256SUMS.txt"
RELEASE_ARTIFACT_PACKAGE_SMOKE_LOG = (
    ROOT / "artifacts/test-categories/release-artifacts/02-gateway-package-smoke.log"
)
EXPECTED_LOCAL_ARTIFACTS = (
    "language_gateway-0.1.0-py3-none-any.whl",
    "language-0.1.0-source.tar.gz",
    "language-0.1.0-source.zip",
    "language-gateway-0.1.0.tar.gz",
)
MANUAL_RECORDING_FILENAMES = {
    "source_open_ear_recording": "source-open-ear-recording.wav",
    "source_isolated_ear_recording": "source-isolated-ear-recording.wav",
    "translated_headphone_recording": "translated-headphone-recording.wav",
}


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


def _file_has_all_text(path: str, required: tuple[str, ...]) -> bool:
    candidate = ROOT / path
    if not candidate.exists():
        return False
    content = candidate.read_text(encoding="utf-8", errors="replace")
    return all(text in content for text in required)


def _recording_display_name(value: Any) -> str:
    text = str(value).strip()
    return MANUAL_RECORDING_FILENAMES.get(text, text)


def _token_discipline_status_from_flags(
    *,
    doc_ready: bool,
    agent_handoff_ready: bool,
    runner_ready: bool,
) -> tuple[int, str]:
    if doc_ready and agent_handoff_ready and runner_ready:
        return (
            98,
            "conversation-token guide, agent handoff rules, and quiet runner wiring are present; live usage remains operator-enforced",
        )
    if doc_ready and runner_ready:
        return 96, "conversation-token guide and quiet runner are present; agent handoff rules incomplete"
    if doc_ready:
        return 92, "conversation-token guide present; quiet handoff enforcement incomplete"
    return 85, "token budget guide missing"


def _token_discipline_status() -> tuple[int, str]:
    doc_ready = _file_has_all_text(
        "docs/development/token-budget.md",
        (
            "Codex/OpenAI conversation tokens used while developing the product.",
            "Product API tokens used later by Language itself.",
            "Treat the first one as the default concern in agent handoffs.",
            "assume",
            "conversation-token pressure first",
            "Keep push summaries bounded to changed files, validations, release-progress",
            "Use it, if adopted, as development-agent context compression",
            "Until that eval exists, the supported repo-level token control is the category runner",
        ),
    )
    agent_handoff_ready = _file_has_all_text(
        "AGENTS.md",
        (
            "Keep agent runs token-light by default.",
            "Treat user concern about token usage as Codex/OpenAI conversation-token pressure",
            "logs to `artifacts/test-categories/` by default.",
            "Reference full logs and JSON reports by path under `artifacts/`",
            "Keep progress updates and push summaries bounded",
            "Treat Headroom or similar compression tools as optional infrastructure",
        ),
    )
    runner_ready = _file_has_all_text(
        "scripts/run_test_category.py",
        (
            "Use release-status in low-token agent handoffs.",
            "Output: quiet; full logs under",
        ),
    )
    return _token_discipline_status_from_flags(
        doc_ready=doc_ready,
        agent_handoff_ready=agent_handoff_ready,
        runner_ready=runner_ready,
    )


def _smoke_local_passed() -> bool:
    return _file_has_text(
        "artifacts/test-categories/smoke-local/01-smoke-local-demo.log",
        "Local demo smoke check passed",
    )


def _log_is_fresh_for_manifest(log_path: Path) -> bool:
    if not LOCAL_ARTIFACT_MANIFEST.exists() or not log_path.exists():
        return False
    return log_path.stat().st_mtime >= LOCAL_ARTIFACT_MANIFEST.stat().st_mtime


def _gateway_package_smoke_passed(local_artifacts_ready: bool) -> bool:
    return (
        local_artifacts_ready
        and _log_is_fresh_for_manifest(RELEASE_ARTIFACT_PACKAGE_SMOKE_LOG)
        and _file_has_text(
            str(RELEASE_ARTIFACT_PACKAGE_SMOKE_LOG.relative_to(ROOT)),
            "Packaged gateway smoke check passed",
        )
    )


def _gateway_auth_smoke_passed(
    *,
    local_artifacts_ready: bool,
    auth_tests_ready: bool,
    auth_runtime_ready: bool,
) -> bool:
    return (
        local_artifacts_ready
        and auth_tests_ready
        and auth_runtime_ready
        and _log_is_fresh_for_manifest(RELEASE_ARTIFACT_PACKAGE_SMOKE_LOG)
        and _file_has_text(
            str(RELEASE_ARTIFACT_PACKAGE_SMOKE_LOG.relative_to(ROOT)),
            "Packaged gateway auth smoke check passed",
        )
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _current_head() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def _worktree_has_tracked_changes() -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _local_release_artifacts_status() -> tuple[bool, str]:
    if not LOCAL_ARTIFACT_MANIFEST.exists() or not LOCAL_ARTIFACT_CHECKSUMS.exists():
        return False, "local artifact manifest/checksums are missing; run release-artifacts"

    manifest = LOCAL_ARTIFACT_MANIFEST.read_text(encoding="utf-8", errors="replace")
    if "- dirty_tree: `false`" not in manifest:
        return False, "local artifact manifest is not clean"
    if _worktree_has_tracked_changes():
        return False, "worktree has uncommitted changes; commit and rerun release-artifacts"
    head = _current_head()
    if head and f"- commit: `{head}`" not in manifest:
        return False, "local artifact manifest does not match current HEAD"

    checksums: dict[str, str] = {}
    for line in LOCAL_ARTIFACT_CHECKSUMS.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split()
        if len(parts) == 2:
            checksums[parts[1]] = parts[0].lower()

    missing = [name for name in EXPECTED_LOCAL_ARTIFACTS if not (LOCAL_ARTIFACT_DIR / name).exists()]
    if missing:
        return False, f"local artifacts missing files: {', '.join(missing)}"

    checksum_missing = [name for name in EXPECTED_LOCAL_ARTIFACTS if name not in checksums]
    if checksum_missing:
        return False, f"local artifact checksums missing files: {', '.join(checksum_missing)}"

    mismatched = [
        name
        for name in EXPECTED_LOCAL_ARTIFACTS
        if _sha256_file(LOCAL_ARTIFACT_DIR / name) != checksums[name]
    ]
    if mismatched:
        return False, f"local artifact checksums mismatch: {', '.join(mismatched)}"

    return True, f"clean local source/gateway artifacts ready ({_repo_relative(LOCAL_ARTIFACT_MANIFEST)})"


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


def _resolve_flutter() -> str | None:
    for name in ("LANGUAGE_FLUTTER", "FLUTTER"):
        candidate = os.environ.get(name, "").strip()
        if candidate:
            return candidate
    resolved = shutil.which("flutter")
    if resolved:
        return resolved
    if PORTABLE_FLUTTER.exists():
        return str(PORTABLE_FLUTTER)
    return None


def _audio_percent(report: dict[str, Any]) -> tuple[int, str]:
    summary = _as_dict(report.get("summary"))
    gate_count = int(summary.get("release_blocking_gate_count", 0) or 0)
    failure_count = int(summary.get("release_blocking_failure_count", 0) or 0)
    if gate_count and failure_count == 0:
        return 100, "audio release gate passed"

    handoff = _as_dict(report.get("operator_handoff"))
    manual = _as_dict(handoff.get("headphone_manual_status"))
    manual_summary = _as_dict(manual.get("summary"))
    placeholder_label_count = int(manual_summary.get("placeholder_label_count", 0) or 0)
    label_gap = (
        "labels still needed: LANGUAGE_HEADPHONE_DEVICE_LABEL, "
        "LANGUAGE_ISOLATION_FIXTURE_LABEL, LANGUAGE_MEASUREMENT_MICROPHONE_LABEL"
        if placeholder_label_count
        else ""
    )
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    dropbox = _as_dict(collection.get("raw_recording_dropbox"))
    state = _as_dict(dropbox.get("state"))
    dropbox_path = str(dropbox.get("path", "")).strip()
    missing = [str(item) for item in _as_list(state.get("missing_recordings"))]
    score_category_ready = _file_has_text("scripts/run_test_category.py", "release-evidence-score")
    if missing and score_category_ready:
        missing_text = ", ".join(_recording_display_name(item) for item in missing)
        dropbox_candidate = Path(dropbox_path)
        if dropbox_path and not dropbox_candidate.is_absolute():
            dropbox_candidate = ROOT / dropbox_candidate
        path_text = f" in {_repo_relative(dropbox_candidate)}" if dropbox_path else ""
        evidence = f"{gate_count - failure_count}/{gate_count} gates; missing WAVs{path_text}: {missing_text}"
        if label_gap:
            evidence = f"{evidence}; {label_gap}"
        return 90, evidence
    if label_gap and score_category_ready:
        return 90, f"{gate_count - failure_count}/{gate_count} gates; {label_gap}"
    if failure_count:
        return 85, f"{gate_count - failure_count}/{gate_count} gates; release blocker remains"
    return 80, "audio gate evidence is incomplete"


def build_progress(report: dict[str, Any]) -> dict[str, Any]:
    audio_percent, audio_evidence = _audio_percent(report)
    release_reports_exist = DEFAULT_GATE_REPORT.exists() and (ROOT / "artifacts/release/audio-gate-report.md").exists()
    checklist_ready = (ROOT / "artifacts/release/physical-audio-checklist.md").exists()
    flutter_path = _resolve_flutter()
    flutter_ready = flutter_path is not None
    smoke_ready = _smoke_local_passed()
    local_artifacts_ready, local_artifacts_evidence = _local_release_artifacts_status()
    auth_tests_ready = _file_has_text("services/gateway/tests/test_gateway.py", "test_read_endpoints_remain_auth_free")
    auth_runtime_ready = _file_has_text("services/gateway/app/auth.py", "require_write_token")
    gateway_package_smoke_ready = _gateway_package_smoke_passed(local_artifacts_ready)
    auth_smoke_ready = _gateway_auth_smoke_passed(
        local_artifacts_ready=local_artifacts_ready,
        auth_tests_ready=auth_tests_ready,
        auth_runtime_ready=auth_runtime_ready,
    )
    category_runner_ready = _file_has_text("scripts/run_test_category.py", "physical-audio-handoff")
    token_percent, token_evidence = _token_discipline_status()

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
            100
            if release_reports_exist and checklist_ready and flutter_ready and smoke_ready and local_artifacts_ready
            else 99
            if release_reports_exist and checklist_ready and flutter_ready and smoke_ready
            else 98
            if release_reports_exist and checklist_ready and flutter_ready
            else 95
            if release_reports_exist and checklist_ready
            else 90,
            0.12,
            f"release reports, physical checklist, Flutter host, local smoke, and {local_artifacts_evidence} ({flutter_path})"
            if release_reports_exist and checklist_ready and flutter_ready and smoke_ready and local_artifacts_ready
            else f"release reports, physical checklist, Flutter host, and local smoke are ready; {local_artifacts_evidence} ({flutter_path})"
            if release_reports_exist and checklist_ready and flutter_ready and smoke_ready
            else f"release reports, physical checklist, and Flutter host are ready; local smoke category has not passed ({flutter_path})"
            if release_reports_exist and checklist_ready and flutter_ready
            else "release reports/checklist exist; Flutter is not on PATH for local app validation"
            if release_reports_exist and checklist_ready
            else "release report artifact set incomplete",
        ),
        Milestone(
            "gateway_package_ergonomics",
            "Gateway/package ergonomics",
            100
            if gateway_package_smoke_ready
            else 95
            if (ROOT / "scripts/verify_gateway_package.py").exists()
            else 90,
            0.10,
            "packaged gateway smoke passed"
            if gateway_package_smoke_ready
            else "gateway package verifier present; packaged smoke pending",
        ),
        Milestone(
            "auth_internal_beta",
            "Auth-enabled internal beta readiness",
            100
            if auth_smoke_ready
            else 92
            if auth_tests_ready and auth_runtime_ready
            else 80,
            0.14,
            "packaged write-token auth smoke passed"
            if auth_smoke_ready
            else "write-token runtime and gateway auth tests present"
            if auth_tests_ready and auth_runtime_ready
            else "auth runtime/tests incomplete",
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
            token_percent,
            0.06,
            token_evidence,
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
            "headphone_manual_status": {
                "summary": {
                    "placeholder_label_count": 3,
                },
            },
            "headphone_collection_plan_status": {
                "raw_recording_dropbox": {
                    "path": "artifacts/audio_eval/runs/manual/raw-listener-ear-recordings",
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
        "source-open-ear-recording.wav",
        "artifacts\\audio_eval\\runs\\manual\\raw-listener-ear-recordings",
        "LANGUAGE_HEADPHONE_DEVICE_LABEL",
        "LANGUAGE_ISOLATION_FIXTURE_LABEL",
        "LANGUAGE_MEASUREMENT_MICROPHONE_LABEL",
        "conversation-token guide, agent handoff rules, and quiet runner wiring are present",
        "Total release goal:",
        "release gate remains authoritative",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing progress text: {text}")
    if not 0 <= int(progress["total_percent"]) <= 100:
        raise AssertionError("total percent out of range")
    expected_token_cases = [
        ((True, True, True), 98),
        ((True, False, True), 96),
        ((True, False, False), 92),
        ((False, True, True), 85),
    ]
    for (doc_ready, agent_ready, runner_ready), expected_percent in expected_token_cases:
        actual_percent, _ = _token_discipline_status_from_flags(
            doc_ready=doc_ready,
            agent_handoff_ready=agent_ready,
            runner_ready=runner_ready,
        )
        if actual_percent != expected_percent:
            raise AssertionError(
                "unexpected token discipline percent for "
                f"doc={doc_ready}, agent={agent_ready}, runner={runner_ready}: {actual_percent}"
            )
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
