#!/usr/bin/env python3
"""Thin CLI for diarization fixture scoring.

Model adapters should write JSONL predictions and call this script rather than
depending on internal harness function names.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audio_eval_harness import (
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT_DIR,
    build_oracle_diarization_records,
    print_summary,
    render_fixtures,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)


DEFAULT_PREDICTIONS = DEFAULT_OUTPUT_DIR / "predictions" / "oracle_diarization.jsonl"
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "diarization-score-report.json"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score diarization fixture predictions")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    oracle = subparsers.add_parser("oracle", help="write oracle diarization predictions")
    add_common(oracle)
    oracle.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)

    score = subparsers.add_parser("score", help="score diarization JSONL predictions")
    add_common(score)
    score.add_argument("--predictions", type=Path, required=True)
    score.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    score.add_argument("--strict-oracle", action="store_true")

    check_oracle = subparsers.add_parser("check-oracle", help="write and score oracle predictions")
    add_common(check_oracle)
    check_oracle.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    check_oracle.add_argument("--report", type=Path, default=DEFAULT_REPORT)

    return parser.parse_args(argv)


def summary_for_print(report: dict[str, object]) -> dict[str, object]:
    summary = report["summary"]
    assert isinstance(summary, dict)
    gates = summary["quality_gates"]
    assert isinstance(gates, list)
    return {
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": len(report["fixtures"]),
            "quality_gates": gates,
        }
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    annotations = render_fixtures(manifest_path, output_dir)

    if args.command == "oracle":
        predictions_path = args.predictions.resolve()
        write_jsonl(build_oracle_diarization_records(annotations), predictions_path)
        print(f"wrote oracle diarization predictions to {predictions_path}")
        return 0

    if args.command == "check-oracle":
        predictions_path = args.predictions.resolve()
        write_jsonl(build_oracle_diarization_records(annotations), predictions_path)
        report = score_diarization_predictions(annotations, predictions_path, strict_oracle=True)
    else:
        report = score_diarization_predictions(
            annotations,
            args.predictions.resolve(),
            strict_oracle=bool(args.strict_oracle),
        )

    write_report(report, args.report.resolve())
    printable = summary_for_print(report)
    print_summary(printable)
    return 0 if printable["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
