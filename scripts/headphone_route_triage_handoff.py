#!/usr/bin/env python3
"""Print the safest route-triage probe command from a headphone preflight report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREFLIGHT_REPORT = (
    ROOT / "artifacts/audio_eval/runs/headphone-earpiece-preflight/headphone-preflight-report.json"
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _display_device_name(value: Any) -> str:
    name = str(value or "").strip()
    if name.endswith("()"):
        name = name[:-2].rstrip()
    return name or "unknown"


def _preflight_benchmark(report: dict[str, Any]) -> dict[str, Any]:
    benchmarks = _as_dict(report.get("benchmarks"))
    return _as_dict(benchmarks.get("headphone_earpiece_preflight"))


def _recommended_commands(report: dict[str, Any]) -> dict[str, Any]:
    return _as_dict(_preflight_benchmark(report).get("recommended_commands"))


def _without_python_override(command: str) -> str:
    return command.replace(" -Python $env:LANGUAGE_PYTHON", "")


def _first_candidate(report: dict[str, Any]) -> dict[str, Any]:
    benchmark = _preflight_benchmark(report)
    for candidate in _as_list(benchmark.get("candidate_route_triples")):
        if isinstance(candidate, dict):
            return candidate
    return {}


def build_route_probe_command(report: dict[str, Any]) -> str:
    summary = _as_dict(report.get("summary"))
    candidate = _first_candidate(report)
    if not candidate:
        command = str(_recommended_commands(report).get("route_probe_triage_only", "")).strip()
        if command:
            return _without_python_override(command)
        raise ValueError("preflight report does not include a route triage candidate")

    sample_rate_hz = int(summary.get("sample_rate_hz", 48000) or 48000)
    input_channels = int(summary.get("input_channels", 1) or 1)
    output_channels = int(summary.get("output_channels", 2) or 2)
    return (
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 "
        "-Action probe-route "
        f"--measurement-input-device {int(candidate['input_device'])} "
        f"--source-output-device {int(candidate['source_output_device'])} "
        f"--headphone-output-device {int(candidate['headphone_output_device'])} "
        f"--sample-rate-hz {sample_rate_hz} "
        f"--input-channels {input_channels} "
        f"--output-channels {output_channels} "
        "--playback-gain-db -18 "
        "--score-warning-only"
    )


def build_physical_confirmation_command(report: dict[str, Any]) -> str:
    command = str(_recommended_commands(report).get("confirm_physical_input_preflight", "")).strip()
    if command:
        return _without_python_override(command)

    summary = _as_dict(report.get("summary"))
    candidate = _first_candidate(report)
    if not candidate:
        return ""
    sample_rate_hz = int(summary.get("sample_rate_hz", 48000) or 48000)
    input_channels = int(summary.get("input_channels", 1) or 1)
    output_channels = int(summary.get("output_channels", 2) or 2)
    route = (
        f"{int(candidate['input_device'])}:"
        f"{int(candidate['source_output_device'])}:"
        f"{int(candidate['headphone_output_device'])}"
    )
    return (
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 "
        "-Action preflight "
        f"--sample-rate-hz {sample_rate_hz} "
        f"--input-channels {input_channels} "
        f"--output-channels {output_channels} "
        f"--selected-route {route} "
        "--confirm-physical-listener-ear-input"
    )


def physical_capture_handoff(report: dict[str, Any], candidate: dict[str, Any]) -> list[str]:
    summary = _as_dict(report.get("summary"))
    if summary.get("recommended_path") != "guided_capture_possible_after_physical_input_confirmation":
        return []
    command = build_physical_confirmation_command(report)
    if not command or not candidate:
        return []
    input_device = str(candidate.get("input_device", "")).strip()
    source_device = str(candidate.get("source_output_device", "")).strip()
    headphone_device = str(candidate.get("headphone_output_device", "")).strip()
    if not input_device.isdigit() or not source_device.isdigit() or not headphone_device.isdigit():
        return []
    return [
        "",
        "Physical listener-ear confirmation (only after the mic is at the earcup/listener-ear point):",
        command,
        "",
        "Guided capture env for this confirmed route:",
        f'$env:LANGUAGE_MEASUREMENT_INPUT_DEVICE = "{input_device}"',
        f'$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = "{source_device}"',
        f'$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = "{headphone_device}"',
        "Set concrete LANGUAGE_HEADPHONE_DEVICE_LABEL, LANGUAGE_ISOLATION_FIXTURE_LABEL, and LANGUAGE_MEASUREMENT_MICROPHONE_LABEL.",
        "python scripts/run_test_category.py guided-capture --dry-run",
        "python scripts/run_test_category.py guided-capture",
    ]


def reference_playback_handoff(candidate: dict[str, Any]) -> list[str]:
    source_device = str(candidate.get("source_output_device", "")).strip()
    headphone_device = str(candidate.get("headphone_output_device", "")).strip()
    if not source_device.isdigit() or not headphone_device.isdigit() or source_device == headphone_device:
        return []
    return [
        "",
        "Reference playback helper for external recorder (not release proof):",
        f'$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = "{source_device}"',
        f'$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = "{headphone_device}"',
        "python scripts/run_test_category.py reference-playback-dry-run",
        "python scripts/run_test_category.py recording-session-dry-run",
        "python scripts/run_test_category.py reference-playback",
    ]


def render_handoff(report: dict[str, Any], report_path: Path) -> str:
    summary = _as_dict(report.get("summary"))
    command = build_route_probe_command(report)
    candidate = _first_candidate(report)
    lines = [
        "Headphone route triage handoff",
        f"- Preflight report: {_repo_relative(report_path)}",
        f"- Release proof: {bool(report.get('release_proof'))}",
        f"- Recommended path: {summary.get('recommended_path', 'unknown')}",
        (
            "- Routes: "
            f"candidates={int(summary.get('candidate_route_triple_count', 0) or 0)}, "
            f"capture_ready={int(summary.get('capture_ready_route_triple_count', 0) or 0)}, "
            f"external_inputs={int(summary.get('likely_external_input_count', 0) or 0)}"
        ),
    ]
    if candidate:
        lines.append(
            "- Candidate: "
            f"input {candidate.get('input_device')} {_display_device_name(candidate.get('input_name'))}; "
            f"source {candidate.get('source_output_device')} {_display_device_name(candidate.get('source_name'))}; "
            f"headphone {candidate.get('headphone_output_device')} {_display_device_name(candidate.get('headphone_name'))}"
        )
    lines.extend(
        [
            "- Detractor: this command plays/records a probe and is route triage only.",
            "- Release gate: still requires scored physical listener-ear WAV evidence.",
            "- Audible diagnostic: the printed probe plays a short -18 dB test signal; keep volume moderate.",
            "",
            "Run deliberately:",
            command,
        ]
    )
    lines.extend(physical_capture_handoff(report, candidate))
    lines.extend(reference_playback_handoff(candidate))
    return "\n".join(lines)


def self_test() -> int:
    report = {
        "release_proof": False,
        "summary": {
            "candidate_route_triple_count": 1,
            "capture_ready_route_triple_count": 1,
            "input_channels": 1,
            "likely_external_input_count": 0,
            "output_channels": 2,
            "recommended_path": "guided_capture_possible_after_physical_input_confirmation",
            "sample_rate_hz": 48000,
        },
        "benchmarks": {
            "headphone_earpiece_preflight": {
                "recommended_commands": {
                    "confirm_physical_input_preflight": (
                        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 "
                        "-Action preflight -Python $env:LANGUAGE_PYTHON --sample-rate-hz 48000 "
                        "--input-channels 1 --output-channels 2 --selected-route 7:8:9 "
                        "--confirm-physical-listener-ear-input"
                    )
                },
                "candidate_route_triples": [
                    {
                        "headphone_name": "Headphones ()",
                        "headphone_output_device": 9,
                        "input_device": 7,
                        "input_name": "Laptop mic",
                        "source_name": "Speakers",
                        "source_output_device": 8,
                    }
                ]
            }
        },
    }
    rendered = render_handoff(report, ROOT / "artifacts/example.json")
    required = [
        "Headphone route triage handoff",
        "Release proof: False",
        "--measurement-input-device 7",
        "--source-output-device 8",
        "--headphone-output-device 9",
        "headphone 9 Headphones",
        "--score-warning-only",
        "route triage only",
        "short -18 dB test signal",
        "Physical listener-ear confirmation",
        "--selected-route 7:8:9",
        "--confirm-physical-listener-ear-input",
        "$env:LANGUAGE_MEASUREMENT_INPUT_DEVICE = \"7\"",
        "Set concrete LANGUAGE_HEADPHONE_DEVICE_LABEL",
        "python scripts/run_test_category.py guided-capture --dry-run",
        "$env:LANGUAGE_SOURCE_OUTPUT_DEVICE = \"8\"",
        "$env:LANGUAGE_HEADPHONE_OUTPUT_DEVICE = \"9\"",
        "python scripts/run_test_category.py recording-session-dry-run",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing rendered text: {text}")
    if "-Python $env:LANGUAGE_PYTHON" in rendered:
        raise AssertionError("handoff should rely on wrapper Python auto-selection")
    if "Headphones ()" in rendered:
        raise AssertionError("handoff should hide empty parentheses in display names")
    print("headphone route triage handoff self-test PASS")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preflight-report", type=Path, default=DEFAULT_PREFLIGHT_REPORT)
    parser.add_argument("--command-only", action="store_true", help="print only the probe command")
    parser.add_argument("--self-test", action="store_true", help="run script contract checks")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    report_path = args.preflight_report
    if not report_path.exists():
        raise SystemExit(
            f"preflight report not found: {_repo_relative(report_path)}; run route-triage first"
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise SystemExit("preflight report root must be a JSON object")
    if args.command_only:
        print(build_route_probe_command(report))
    else:
        print(render_handoff(report, report_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
