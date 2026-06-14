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


def _preflight_benchmark(report: dict[str, Any]) -> dict[str, Any]:
    benchmarks = _as_dict(report.get("benchmarks"))
    return _as_dict(benchmarks.get("headphone_earpiece_preflight"))


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
        command = str(
            _as_dict(_preflight_benchmark(report).get("recommended_commands")).get(
                "route_probe_triage_only", ""
            )
        ).strip()
        if command:
            return command.replace(" -Python $env:LANGUAGE_PYTHON", "")
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
            f"input {candidate.get('input_device')} {candidate.get('input_name')}; "
            f"source {candidate.get('source_output_device')} {candidate.get('source_name')}; "
            f"headphone {candidate.get('headphone_output_device')} {candidate.get('headphone_name')}"
        )
    lines.extend(
        [
            "- Detractor: this command plays/records a probe and is route triage only.",
            "- Release gate: still requires scored physical listener-ear WAV evidence.",
            "",
            "Run deliberately:",
            command,
        ]
    )
    return "\n".join(lines)


def self_test() -> int:
    report = {
        "release_proof": False,
        "summary": {
            "candidate_route_triple_count": 1,
            "capture_ready_route_triple_count": 0,
            "input_channels": 1,
            "likely_external_input_count": 0,
            "output_channels": 2,
            "recommended_path": "route_probe_triage_only_manual_listener_ear_capture_required",
            "sample_rate_hz": 48000,
        },
        "benchmarks": {
            "headphone_earpiece_preflight": {
                "candidate_route_triples": [
                    {
                        "headphone_name": "Headphones",
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
        "--score-warning-only",
        "route triage only",
    ]
    for text in required:
        if text not in rendered:
            raise AssertionError(f"missing rendered text: {text}")
    if "-Python $env:LANGUAGE_PYTHON" in rendered:
        raise AssertionError("handoff should rely on wrapper Python auto-selection")
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
