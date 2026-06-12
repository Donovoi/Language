#!/usr/bin/env python3
"""Run pyannote on the tiny real-speech overlap fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audio_eval_harness import DEFAULT_OUTPUT_DIR, score_diarization_predictions, write_jsonl, write_report
from prepare_real_speech_fixture import (
    DEFAULT_CONFIG,
    DEFAULT_DATASET,
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    DEFAULT_SAMPLE_RATE_HZ,
    prepare_real_speech_fixture,
)
from run_pyannote_diarization_fixture import (
    DEFAULT_MODEL,
    env_token,
    load_pyannote_pipeline,
    run_fixture,
    should_require_token,
)


DEFAULT_RUN_ID = "pyannote-community-1-real-speech"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pyannote on a tiny real-speech fixture")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--exclusive", action="store_true")
    parser.add_argument("--num-speakers-from-truth", action="store_true")
    parser.add_argument("--min-speakers", type=int)
    parser.add_argument("--max-speakers", type=int)
    parser.add_argument("--no-score", action="store_true")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--dataset", default=DEFAULT_DATASET)
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    if args.adapter_id is None:
        args.adapter_id = args.run_id
    predictions_path = (
        args.predictions.resolve()
        if args.predictions
        else output_dir / "runs" / args.run_id / "predictions.jsonl"
    )
    report_path = (
        args.report.resolve()
        if args.report
        else output_dir / "runs" / args.run_id / "diarization-score-report.json"
    )

    token = args.hf_token
    token_source = "argument" if token else None
    if not token:
        token, token_source = env_token()
    if should_require_token(args.model) and not token and not args.allow_no_token:
        raise SystemExit(
            "pyannote Community-1 requires accepting Hugging Face model conditions and setting "
            "HF_TOKEN or HUGGINGFACE_TOKEN. Use --allow-no-token only for a local/offline model path."
        )

    annotation = prepare_real_speech_fixture(
        output_dir=output_dir,
        dataset=args.dataset,
        config=args.config,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        sample_rate_hz=args.sample_rate_hz,
    )
    annotations = [annotation]
    pipeline = load_pyannote_pipeline(args.model, token, args.device)
    records = [run_fixture(pipeline, annotation, output_dir, args)]
    for record in records:
        record["metadata"]["token_source"] = token_source or "none"
        record["metadata"]["fixture_kind"] = "real_speech_mixed_overlap"
    write_jsonl(records, predictions_path)
    print(f"wrote pyannote real-speech predictions to {predictions_path}")

    if args.no_score:
        return 0

    report = score_diarization_predictions(annotations, predictions_path, strict_oracle=False)
    report["detractor_loop"]["strongest_objection"] = (
        "This real-speech fixture is a tiny clean LibriSpeech mix. It is useful for catching "
        "obvious diarization failures, but it does not prove realtime, multilingual, noisy-room, "
        "or source-suppression behavior."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Compare this result against one consented local room recording with overlap, measured "
        "source levels, and the same JSONL scoring path."
    )
    write_report(report, report_path)
    print(f"wrote pyannote real-speech score report to {report_path}")

    passed = all(bool(gate["passed"]) for gate in report["summary"]["quality_gates"])
    if not passed and args.score_warning_only:
        print("pyannote real-speech score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
