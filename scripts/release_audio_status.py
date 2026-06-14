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
DEFAULT_OPERATOR_CHECKLIST = ROOT / "artifacts/release/physical-audio-checklist.md"
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


def _preflight_lines(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    preflight = _as_dict(handoff.get("headphone_preflight_status"))
    if not preflight:
        return []

    lines = [f"Status: {preflight.get('status', 'unknown')}"]
    recommended_path = str(preflight.get("recommended_path", "")).strip()
    if recommended_path:
        lines.append(f"Recommended path: {recommended_path}")
    route_counts = [
        f"candidates={int(preflight.get('candidate_route_triple_count', 0) or 0)}",
        f"capture_ready={int(preflight.get('capture_ready_route_triple_count', 0) or 0)}",
        f"external_inputs={int(preflight.get('likely_external_input_count', 0) or 0)}",
    ]
    lines.append("Routes: " + ", ".join(route_counts))
    candidate_summary = _preflight_candidate_summary(preflight)
    if candidate_summary:
        lines.append(f"Suggested current route: {candidate_summary}")
    next_step = str(preflight.get("next_step", "")).strip()
    if next_step:
        lines.append(f"Next: {next_step}")
    path = str(preflight.get("markdown_path") or preflight.get("path") or "").strip()
    if path:
        lines.append(f"Report: {_repo_relative(path)}")
    return lines


def _preflight_candidate_device_label(candidate: dict[str, Any], role: str) -> str:
    if role == "input":
        index_key = "input_device"
        name_key = "input_name"
        hostapi_key = "input_hostapi_name"
    elif role == "source":
        index_key = "source_output_device"
        name_key = "source_name"
        hostapi_key = "source_hostapi_name"
    else:
        index_key = "headphone_output_device"
        name_key = "headphone_name"
        hostapi_key = "headphone_hostapi_name"

    name = str(candidate.get(name_key, "")).strip() or "unknown"
    index = str(candidate.get(index_key, "")).strip()
    hostapi = str(candidate.get(hostapi_key, "")).strip()
    details = [value for value in (f"index={index}" if index else "", hostapi) if value]
    return f"{name} ({', '.join(details)})" if details else name


def _preflight_candidate_summary(preflight: dict[str, Any]) -> str:
    candidate = _as_dict(preflight.get("selected_candidate")) or _as_dict(preflight.get("displayed_candidate"))
    if not candidate:
        return ""
    return (
        f"input={_preflight_candidate_device_label(candidate, 'input')}; "
        f"source={_preflight_candidate_device_label(candidate, 'source')}; "
        f"headphone={_preflight_candidate_device_label(candidate, 'headphone')}"
    )


def _preflight_playback_env_lines(preflight: dict[str, Any]) -> list[str]:
    candidate = _as_dict(preflight.get("selected_candidate")) or _as_dict(preflight.get("displayed_candidate"))
    if not candidate:
        return []
    source_device = str(candidate.get("source_output_device", "")).strip()
    headphone_device = str(candidate.get("headphone_output_device", "")).strip()
    if not source_device.isdigit() or not headphone_device.isdigit() or source_device == headphone_device:
        return []
    return [
        f'$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = "{source_device}"',
        f'$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = "{headphone_device}"',
        "python scripts/run_test_category.py reference-playback-dry-run",
        "python scripts/run_test_category.py reference-playback",
    ]


def _route_device_label(device: dict[str, Any]) -> str:
    name = str(device.get("name", "")).strip()
    index = str(device.get("index", "")).strip()
    hostapi = str(device.get("hostapi_name", "")).strip()
    label = name or "unknown"
    details = [value for value in (f"index={index}" if index else "", hostapi) if value]
    if details:
        label = f"{label} ({', '.join(details)})"
    return label


def _route_metric_summary(name: str, metric: dict[str, Any]) -> str:
    fields: list[str] = []
    for label, key in (
        ("dbfs", "recording_dbfs"),
        ("peak", "peak_dbfs"),
        ("corr", "reference_correlation"),
    ):
        value = metric.get(key)
        if isinstance(value, (float, int)):
            fields.append(f"{label}={value:.3g}")
    return f"{name}: " + (", ".join(fields) if fields else "no metrics")


def _route_probe_stale_reason(report: dict[str, Any]) -> str:
    handoff = _as_dict(report.get("operator_handoff"))
    preflight = _as_dict(handoff.get("headphone_preflight_status"))
    probe = _as_dict(handoff.get("headphone_route_probe_status"))
    freshness_status = str(probe.get("freshness_status", "")).strip()
    if freshness_status and freshness_status != "CURRENT":
        issues = [str(item) for item in _as_list(probe.get("freshness_issues"))]
        details = "; ".join(issues) if issues else "route probe freshness is unknown"
        return f"{freshness_status}: {details}"
    preflight_generated = preflight.get("generated_at_unix")
    probe_generated = probe.get("generated_at_unix")
    if (
        isinstance(preflight_generated, int)
        and isinstance(probe_generated, int)
        and preflight_generated > 0
        and probe_generated > 0
        and probe_generated < preflight_generated
    ):
        return "STALE: route probe predates the current preflight"
    return ""


def _route_probe_lines(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    probe = _as_dict(handoff.get("headphone_route_probe_status"))
    if not probe:
        return []

    stale_reason = _route_probe_stale_reason(report)
    status = str(probe.get("status", "unknown"))
    if stale_reason:
        freshness_label = stale_reason.split(":", 1)[0]
        status = f"{freshness_label}-TRIAGE ({stale_reason})"
    lines = [f"Status: {status}"]
    route = _as_dict(probe.get("device_route"))
    if route:
        lines.append(
            "Route: "
            f"input={_route_device_label(_as_dict(route.get('measurement_input')))}; "
            f"source={_route_device_label(_as_dict(route.get('source_output')))}; "
            f"headphone={_route_device_label(_as_dict(route.get('headphone_output')))}"
        )
    source_metric = _as_dict(probe.get("source_route"))
    headphone_metric = _as_dict(probe.get("headphone_route"))
    if source_metric:
        lines.append(_route_metric_summary("Source", source_metric))
    if headphone_metric:
        lines.append(_route_metric_summary("Headphone", headphone_metric))
    reasons = [str(item) for item in _as_list(probe.get("blocking_reasons"))]
    if reasons:
        lines.append(f"Blocking reasons: {', '.join(reasons)}")
    actions = [str(item) for item in _as_list(probe.get("next_actions"))]
    if stale_reason:
        actions.insert(0, "rerun python scripts/run_test_category.py route-triage before trusting these device IDs")
    if actions:
        lines.append(f"Next: {actions[0]}")
    path = str(probe.get("path", "")).strip()
    if path:
        lines.append(f"Report: {_repo_relative(path)}")
    return lines


def _release_state(report: dict[str, Any]) -> tuple[str, int, int]:
    summary = _as_dict(report.get("summary"))
    gate_count = int(summary.get("release_blocking_gate_count", 0) or 0)
    failure_count = int(summary.get("release_blocking_failure_count", 0) or 0)
    passed_count = max(gate_count - failure_count, 0)
    state = "READY" if failure_count == 0 and gate_count else "NOT READY"
    return state, passed_count, gate_count


def _blocking_gate_lines(report: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for gate in _as_list(report.get("release_blocking_gates")):
        if not isinstance(gate, dict) or gate.get("passed"):
            continue
        name = str(gate.get("name", "unknown")).strip() or "unknown"
        message = str(gate.get("message", "")).strip()
        if message:
            lines.append(f"`{name}`: {message}")
        else:
            lines.append(f"`{name}`")
    return lines


def render_operator_checklist(report: dict[str, Any]) -> str:
    state, passed_count, gate_count = _release_state(report)
    handoff = _as_dict(report.get("operator_handoff"))
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    dropbox = _as_dict(collection.get("raw_recording_dropbox"))
    dropbox_state = _as_dict(dropbox.get("state"))
    dropbox_path = str(dropbox.get("path", "")).strip()
    dropbox_readme_path = str(dropbox.get("readme_path", "")).strip()
    collection_markdown_path = str(collection.get("markdown_path", "")).strip()
    manual_status_path = str(collection.get("manual_status_report_path", "")).strip()
    score_report_path = str(collection.get("score_report_path", "")).strip()
    missing = [str(item) for item in _as_list(dropbox_state.get("missing_recordings"))]
    probe = _as_dict(handoff.get("headphone_route_probe_status"))
    route = _as_dict(probe.get("device_route"))
    stale_reason = _route_probe_stale_reason(report)
    preflight = _as_dict(handoff.get("headphone_preflight_status"))
    preflight_candidate_summary = _preflight_candidate_summary(preflight)
    preflight_playback_env_lines = _preflight_playback_env_lines(preflight)

    lines = [
        "# Physical Audio Test Checklist",
        "",
        "Generated from the current release audio reports. This is an operator handoff, not release proof.",
        "",
        "## Current State",
        "",
        f"- Release status: **{state}** ({passed_count}/{gate_count} gates passed)",
    ]
    blocking = _blocking_gate_lines(report)
    if blocking:
        lines.append(f"- Blocking gate(s): {'; '.join(blocking)}")
    if missing:
        lines.append(f"- Missing listener-ear recordings: {', '.join(missing)}")
    if dropbox_path:
        lines.append(f"- Raw WAV dropbox: `{_repo_relative(dropbox_path)}`")
    if dropbox_readme_path:
        lines.append(f"- Raw WAV dropbox instructions: `{_repo_relative(dropbox_readme_path)}`")
    if collection_markdown_path:
        lines.append(f"- Manual evidence plan: `{_repo_relative(collection_markdown_path)}`")
    if manual_status_path:
        lines.append(f"- Manual recording status: `{_repo_relative(manual_status_path)}`")
    if score_report_path:
        lines.append(f"- Score report target: `{_repo_relative(score_report_path)}`")

    if probe:
        lines.extend(
            [
                "",
                "## Current Route Triage",
                "",
                f"- Probe status: `{(stale_reason.split(':', 1)[0] + '-TRIAGE') if stale_reason else probe.get('status', 'unknown')}`",
            ]
        )
        if preflight_candidate_summary:
            lines.append(f"- Fresh preflight candidate: {preflight_candidate_summary}")
            lines.append(
                "- Use `python scripts/run_test_category.py route-triage` to refresh this candidate before route diagnostics."
            )
        if preflight_playback_env_lines:
            lines.extend(
                [
                    "- Playback helper for an external listener-ear recorder (not release proof):",
                    "",
                    "  ```powershell",
                    *[f"  {line}" for line in preflight_playback_env_lines],
                    "  ```",
                ]
            )
        if stale_reason:
            lines.append(
                f"- Probe freshness: {stale_reason}; rerun `python scripts/run_test_category.py route-triage` before trusting these device IDs."
            )
        if route:
            lines.extend(
                [
                    f"- Measurement input: {_route_device_label(_as_dict(route.get('measurement_input')))}",
                    f"- Source output: {_route_device_label(_as_dict(route.get('source_output')))}",
                    f"- Headphone output: {_route_device_label(_as_dict(route.get('headphone_output')))}",
                ]
            )
        reasons = [str(item) for item in _as_list(probe.get("blocking_reasons"))]
        if reasons:
            lines.append(f"- Blocking reasons: {', '.join(reasons)}")
        lines.append("- Detractor note: route probes and virtual labs stay `release_proof=false`.")

    lines.extend(
        [
            "",
            "## Do This With The Hardware",
            "",
            "1. For laptop-only triage, place one headphone earcup directly over the laptop microphone opening, disable Windows audio enhancements/noise suppression/AGC/echo cancellation, then run:",
            "",
            "   ```powershell",
            "   python scripts/run_test_category.py route-triage",
            "   ```",
            "",
            "   Copy and run the printed `probe-route` command only as non-release triage.",
            "",
            "2. For release evidence, use a separate listener-ear recorder: phone WAV recorder, USB mic, lav mic, or field recorder placed at the earcup/listener-ear point.",
            "",
            "3. Prepare the release-derived references and dropbox:",
            "",
            "   ```powershell",
            "   python scripts/run_test_category.py release-evidence",
            "   ```",
            "",
            "   If the repo should play the references while the external recorder is rolling, use the playback helper shown above, starting with `reference-playback-dry-run`.",
            "",
            "4. Record or export these three WAVs from the same listener-ear position:",
            "",
            "   - `source-open-ear-recording.wav`: source speaker plays, headphone/earpiece unsealed or removed.",
            "   - `source-isolated-ear-recording.wav`: same source speaker route and volume, headphone/earpiece sealed over the recorder mic.",
            "   - `translated-headphone-recording.wav`: headphone/earpiece remains sealed and plays the translated reference.",
            "",
            "5. Put the WAVs in the raw dropbox, then rerun:",
            "",
            "   ```powershell",
            "   python scripts/run_test_category.py release-evidence",
            "   ```",
            "",
            "6. When the WAVs are ready, set real labels for the headset, fixture, and measurement mic, then score the evidence:",
            "",
            "   ```powershell",
            "   $env:LANGUAGE_HEADPHONE_DEVICE_LABEL = \"Sony WH-1000XM6\"",
            "   $env:LANGUAGE_ISOLATION_FIXTURE_LABEL = \"left earcup sealed over phone recorder\"",
            "   $env:LANGUAGE_MEASUREMENT_MICROPHONE_LABEL = \"phone WAV recorder at listener-ear point\"",
            "   python scripts/run_test_category.py release-evidence-score",
            "   ```",
            "",
            "   Use `python scripts/release_audio_status.py --full-commands` only when you need the lower-level score command.",
        ]
    )

    return "\n".join(lines) + "\n"


def write_operator_checklist(report: dict[str, Any], path: Path = DEFAULT_OPERATOR_CHECKLIST) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_operator_checklist(report), encoding="utf-8")
    return path


def _detailed_recommended_commands(report: dict[str, Any]) -> list[str]:
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


def _preflight_next_actions(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    preflight = _as_dict(handoff.get("headphone_preflight_status"))
    if not preflight:
        return ["Run: python scripts/run_test_category.py route-triage"]

    status = str(preflight.get("status", "")).strip()
    if status == "READY-FOR-GUIDED-CAPTURE":
        return [
            "Run: python scripts/run_test_category.py guided-capture --dry-run",
            "Run: python scripts/run_test_category.py guided-capture",
        ]
    if status == "NEEDS-PHYSICAL-INPUT-CONFIRMATION":
        return [
            "For host capture, place a real listener-ear input, rerun the generated selected-route preflight, then dry-run guided-capture.",
            "If you cannot confirm a listener-ear input, use the manual recorder WAV path below.",
        ]
    if status == "TRIAGE-ONLY":
        return [
            "Current host route is triage-only; use the printed probe command only for diagnostics.",
            "For release evidence, connect a real listener-ear mic or use the manual recorder WAV path below.",
        ]
    if status in {"MISSING", "UNREADABLE"}:
        return ["Run: python scripts/run_test_category.py route-triage"]
    return []


def _compact_next_actions(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    manual = _as_dict(handoff.get("headphone_manual_status"))
    collection = _as_dict(handoff.get("headphone_collection_plan_status"))
    dropbox = _as_dict(collection.get("raw_recording_dropbox"))
    dropbox_state = _as_dict(dropbox.get("state"))
    dropbox_path = str(dropbox.get("path", "")).strip()
    missing = [str(item) for item in _as_list(dropbox_state.get("missing_recordings"))]
    status = str(manual.get("status", "")).strip()
    preflight_actions = _preflight_next_actions(report)

    if status == "SCORE-READY":
        return [
            "Run: python scripts/run_test_category.py release-evidence-score",
            "Run: python scripts/run_test_category.py release",
        ]
    if status == "FILES-READY-LABELS-PENDING":
        return [
            "Replace REPLACE_WITH_* labels with concrete hardware/fixture labels.",
            "Run: python scripts/run_test_category.py release-evidence-score",
        ]

    actions = [*preflight_actions, "Run: python scripts/run_test_category.py release-evidence"]
    if dropbox_path and missing:
        missing_text = ", ".join(missing)
        actions.append(f"Record/export missing WAVs into {_repo_relative(dropbox_path)}: {missing_text}")
        actions.append("Rerun: python scripts/run_test_category.py release-evidence")
        actions.append("When WAVs are ready and labels are set, run: python scripts/run_test_category.py release-evidence-score")
    else:
        actions.append("Use --full-commands for the detailed hardware command list.")
    return actions


def _playback_helper_status_lines(report: dict[str, Any]) -> list[str]:
    handoff = _as_dict(report.get("operator_handoff"))
    preflight = _as_dict(handoff.get("headphone_preflight_status"))
    commands = _preflight_playback_env_lines(preflight)
    if not commands:
        return []
    return [
        "Playback helper for an external listener-ear recorder (not release proof):",
        "```powershell",
        *commands,
        "```",
    ]


def render_status(report: dict[str, Any], gate_returncode: int, *, full_commands: bool = False) -> str:
    state, passed_count, gate_count = _release_state(report)

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

    preflight_lines = _preflight_lines(report)
    if preflight_lines:
        lines.append("")
        lines.append("Host audio preflight:")
        lines.extend(f"- {line}" for line in preflight_lines)

    route_probe_lines = _route_probe_lines(report)
    if route_probe_lines:
        lines.append("")
        lines.append("Route probe:")
        lines.extend(f"- {line}" for line in route_probe_lines)

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

    if failures and full_commands:
        lines.append("")
        lines.append("Next commands:")
        for index, command in enumerate(_detailed_recommended_commands(report), start=1):
            lines.append(f"{index}. {command}")
    elif failures:
        lines.append("")
        lines.append("Next actions:")
        for index, action in enumerate(_compact_next_actions(report), start=1):
            lines.append(f"{index}. {action}")
        playback_helper = _playback_helper_status_lines(report)
        if playback_helper:
            lines.append("")
            lines.extend(playback_helper)
        lines.append("Full command list: python scripts/release_audio_status.py --full-commands")

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
                "manual_status_report_path": "artifacts/audio_eval/runs/manual/manual-recording-status.json",
                "markdown_path": "artifacts/audio_eval/runs/manual/headphone-evidence-collection-plan.md",
                "score_report_path": "artifacts/audio_eval/runs/headphone-earpiece-isolation/headphone-isolation-report.json",
                "recommended_commands": {
                    "prepare": "prepare command",
                    "release_gate": "release command",
                },
                "raw_recording_dropbox": {
                    "path": "artifacts/audio_eval/runs/manual/raw",
                    "readme_path": "artifacts/audio_eval/runs/manual/raw/listener-ear-recording-dropbox.md",
                    "state": {"missing_recordings": ["source_open_ear_recording"]},
                },
            },
            "headphone_manual_status": {
                "status": "NOT-READY",
                "next_step": "Capture WAVs.",
            },
            "headphone_preflight_status": {
                "status": "NEEDS-PHYSICAL-INPUT-CONFIRMATION",
                "generated_at_unix": 1,
                "recommended_path": "guided_capture_possible_after_physical_input_confirmation",
                "candidate_route_triple_count": 4,
                "capture_ready_route_triple_count": 1,
                "likely_external_input_count": 0,
                "next_step": "Confirm a listener-ear input or use manual recordings.",
                "markdown_path": "artifacts/audio_eval/runs/preflight/headphone-preflight-report.md",
                "displayed_candidate": {
                    "input_device": "11",
                    "input_name": "Input (SoundWire Microphone)",
                    "input_hostapi_name": "Windows WDM-KS",
                    "source_output_device": "12",
                    "source_name": "Output 1 (SoundWire Speaker)",
                    "source_hostapi_name": "Windows WDM-KS",
                    "headphone_output_device": "10",
                    "headphone_name": "Headphones ()",
                    "headphone_hostapi_name": "Windows WDM-KS",
                },
            },
            "headphone_route_probe_status": {
                "status": "FAIL-TRIAGE",
                "generated_at_unix": 2,
                "path": "artifacts/audio_eval/runs/headphone-earpiece-route-probe/headphone-route-probe-report.json",
                "device_route": {
                    "measurement_input": {
                        "index": "1",
                        "name": "Microphone Array",
                        "hostapi_name": "MME",
                    },
                    "source_output": {
                        "index": "5",
                        "name": "Speakers",
                        "hostapi_name": "MME",
                    },
                    "headphone_output": {
                        "index": "4",
                        "name": "Headphones",
                        "hostapi_name": "MME",
                    },
                },
                "source_route": {
                    "recording_dbfs": -32.067,
                    "peak_dbfs": -10.134,
                    "reference_correlation": 0.00003,
                },
                "headphone_route": {
                    "recording_dbfs": -51.135,
                    "peak_dbfs": -25.644,
                    "reference_correlation": -0.000164,
                },
                "blocking_reasons": [
                    "source:reference_not_detected",
                    "headphone:reference_not_detected",
                ],
                "next_actions": ["Disable Windows audio enhancements, then retry."],
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
        "Next actions:",
        "Playback helper for an external listener-ear recorder (not release proof):",
        "$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = \"12\"",
        "$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = \"10\"",
        "python scripts/run_test_category.py release-evidence",
        "python scripts/run_test_category.py release-evidence-score",
        "--full-commands",
        "Host audio preflight:",
        "NEEDS-PHYSICAL-INPUT-CONFIRMATION",
        "capture_ready=1",
        "Suggested current route:",
        "Input (SoundWire Microphone)",
        "Route probe:",
        "FAIL-TRIAGE",
        "source:reference_not_detected",
        "generated selected-route preflight",
        "manual recorder WAV path",
        "Detractor check:",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing rendered text: {text}")
    if "prepare command" in rendered or "release command" in rendered:
        raise AssertionError("compact status should not render detailed hardware commands")

    triage_report = json.loads(json.dumps(failed_report))
    triage_report["operator_handoff"]["headphone_preflight_status"].update(
        {
            "status": "TRIAGE-ONLY",
            "generated_at_unix": 3,
            "recommended_path": "route_probe_triage_only_manual_listener_ear_capture_required",
            "capture_ready_route_triple_count": 0,
        }
    )
    triage_rendered = render_status(triage_report, gate_returncode=1)
    for text in (
        "Current host route is triage-only",
        "real listener-ear mic",
        "STALE-TRIAGE",
        "rerun python scripts/run_test_category.py route-triage",
    ):
        if text not in triage_rendered:
            raise AssertionError(f"missing triage next-action text: {text}")

    detailed = render_status(failed_report, gate_returncode=1, full_commands=True)
    for text in ("Next commands:", "prepare command", "release command"):
        if text not in detailed:
            raise AssertionError(f"missing detailed rendered text: {text}")

    checklist = render_operator_checklist(failed_report)
    expected_dropbox_readme = _repo_relative("artifacts/audio_eval/runs/manual/raw/listener-ear-recording-dropbox.md")
    expected_collection_plan = _repo_relative("artifacts/audio_eval/runs/manual/headphone-evidence-collection-plan.md")
    expected_manual_status = _repo_relative("artifacts/audio_eval/runs/manual/manual-recording-status.json")
    expected_score_report = _repo_relative(
        "artifacts/audio_eval/runs/headphone-earpiece-isolation/headphone-isolation-report.json"
    )
    for text in (
        "Physical Audio Test Checklist",
        "Release status: **NOT READY**",
        "source-open-ear-recording.wav",
        f"- Raw WAV dropbox instructions: `{expected_dropbox_readme}`",
        f"- Manual evidence plan: `{expected_collection_plan}`",
        f"- Manual recording status: `{expected_manual_status}`",
        f"- Score report target: `{expected_score_report}`",
        "python scripts/run_test_category.py route-triage",
        "Fresh preflight candidate:",
        "$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = \"12\"",
        "$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = \"10\"",
        "python scripts/run_test_category.py reference-playback-dry-run",
        "python scripts/run_test_category.py reference-playback",
        "Output 1 (SoundWire Speaker)",
        "python scripts/run_test_category.py release-evidence-score",
        "route probes and virtual labs stay `release_proof=false`",
    ):
        if text not in checklist:
            raise AssertionError(f"missing checklist text: {text}")
    stale_checklist = render_operator_checklist(triage_report)
    for text in ("Probe status: `STALE-TRIAGE`", "Probe freshness:"):
        if text not in stale_checklist:
            raise AssertionError(f"missing stale checklist text: {text}")

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
    parser.add_argument(
        "--full-commands",
        action="store_true",
        help="print the detailed hardware command handoff instead of compact next actions",
    )
    parser.add_argument(
        "--write-operator-checklist",
        action="store_true",
        help="write a current physical-audio checklist under artifacts/release",
    )
    parser.add_argument(
        "--operator-checklist-path",
        type=Path,
        default=DEFAULT_OPERATOR_CHECKLIST,
        help="path used with --write-operator-checklist",
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
    rendered = render_status(report, gate_returncode, full_commands=args.full_commands)
    if args.write_operator_checklist:
        checklist_path = write_operator_checklist(report, args.operator_checklist_path)
        rendered = (
            f"{rendered}\n\n"
            "Operator checklist:\n"
            f"- {_repo_relative(checklist_path)}"
        )
    print(rendered)
    return gate_returncode if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
