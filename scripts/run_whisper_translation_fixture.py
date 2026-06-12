#!/usr/bin/env python3
"""Run a Whisper speech-translation adapter on the FLEURS fixture.

This is a measured baseline for language ID plus to-English speech translation.
It uses oracle fixture segmentation/source clips so failures are isolated to the
speech translation layer rather than diarization or separation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    analyze_fixture,
    build_oracle_diarization_records,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    build_oracle_translation_records,
    prepare_multilingual_fixture,
    score_translation_predictions,
)
from prepare_real_speech_fixture import fixture_dir


DEFAULT_MODEL_SIZE = "tiny"
DEFAULT_RUN_ID = "whisper-tiny-fleurs-translation"
DEFAULT_ADAPTER_ID = "faster_whisper_tiny_translate_v1"


def run_self_test() -> dict[str, Any]:
    annotation = {
        "fixture_id": "self_test_translation_fixture",
        "duration_s": 2.0,
        "segments": [
            {
                "speaker_id": "speaker_es",
                "source_kind": "human",
                "language_code": "es-419",
                "english_reference_text": "Fellow wrestlers also paid tribute to Luna.",
            },
            {
                "speaker_id": "speaker_en",
                "source_kind": "human",
                "language_code": "en-US",
                "english_reference_text": "Many people do not think about them as dinosaurs.",
            },
        ],
    }
    prediction = {
        "fixture_id": annotation["fixture_id"],
        "adapter_id": "self_test_whisper_contract",
        "segments": [
            {
                "speaker_id": "speaker_es",
                "detected_language_code": "es",
                "translated_text": "Fellow wrestlers paid tribute to Luna.",
                "first_partial_latency_ms": 10.0,
                "final_latency_ms": 20.0,
            },
            {
                "speaker_id": "speaker_en",
                "detected_language_code": "en",
                "translated_text": "Many people do not think about them as dinosaurs.",
                "first_partial_latency_ms": 8.0,
                "final_latency_ms": 15.0,
            },
        ],
    }
    report = score_translation_predictions(annotation, prediction)
    summary = report["summary"]
    if float(summary["language_primary_accuracy"]) != 1.0:
        raise RuntimeError("self-test expected primary language matches to pass")
    if float(summary["mean_translation_token_f1"]) <= 0.75:
        raise RuntimeError("self-test expected useful partial-credit translation scoring")
    return report


def load_whisper_model(model_size: str, device: str, compute_type: str) -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise SystemExit(
            "Whisper translation runner requires the audio-eval-whisper Docker profile."
        ) from exc
    return WhisperModel(model_size, device=device, compute_type=compute_type)


def fixture_path(output_dir: Path, annotation: dict[str, Any]) -> Path:
    return fixture_dir(output_dir, annotation["fixture_set_id"], annotation["fixture_id"])


def transcribe_segment(
    model: Any,
    clip_path: Path,
    *,
    beam_size: int,
    vad_filter: bool,
) -> dict[str, Any]:
    started = time.perf_counter()
    segments_iter, info = model.transcribe(
        str(clip_path),
        task="translate",
        beam_size=beam_size,
        vad_filter=vad_filter,
        condition_on_previous_text=False,
    )
    text_parts: list[str] = []
    first_partial_latency_ms: float | None = None
    segment_count = 0
    for segment in segments_iter:
        segment_count += 1
        if first_partial_latency_ms is None:
            first_partial_latency_ms = (time.perf_counter() - started) * 1000.0
        text = str(getattr(segment, "text", "")).strip()
        if text:
            text_parts.append(text)

    final_latency_ms = (time.perf_counter() - started) * 1000.0
    if first_partial_latency_ms is None:
        first_partial_latency_ms = final_latency_ms

    return {
        "detected_language_code": str(getattr(info, "language", "") or ""),
        "language_confidence": float(getattr(info, "language_probability", 0.0) or 0.0),
        "translated_text": " ".join(text_parts).strip(),
        "first_partial_latency_ms": round(first_partial_latency_ms, 3),
        "final_latency_ms": round(final_latency_ms, 3),
        "whisper_segment_count": segment_count,
    }


def build_whisper_prediction(
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    model = load_whisper_model(args.model_size, args.device, args.compute_type)
    base_dir = fixture_path(output_dir, annotation)
    prediction_segments: list[dict[str, Any]] = []
    for segment in annotation["segments"]:
        if segment["source_kind"] != "human":
            continue
        clip_path = base_dir / segment["source_clip_path"]
        result = transcribe_segment(
            model,
            clip_path,
            beam_size=args.beam_size,
            vad_filter=bool(args.vad_filter),
        )
        prediction_segments.append(
            {
                "speaker_id": segment["speaker_id"],
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "detected_language_code": result["detected_language_code"],
                "language_confidence": result["language_confidence"],
                "source_text": None,
                "translated_text": result["translated_text"],
                "target_language_code": "en",
                "first_partial_latency_ms": result["first_partial_latency_ms"],
                "final_latency_ms": result["final_latency_ms"],
                "metadata": {
                    "source_clip_path": segment["source_clip_path"],
                    "whisper_segment_count": result["whisper_segment_count"],
                },
            }
        )

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": args.adapter_id,
        "segments": prediction_segments,
        "metadata": {
            "kind": "whisper_translate",
            "model_size": args.model_size,
            "device": args.device,
            "compute_type": args.compute_type,
            "beam_size": args.beam_size,
            "vad_filter": bool(args.vad_filter),
            "segmentation_prior": "oracle_source_clips",
        },
    }


def model_quality_gates(
    annotation: dict[str, Any],
    translation_report: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_segments = len(
        [segment for segment in annotation["segments"] if segment["source_kind"] == "human"]
    )
    summary = translation_report["summary"]
    max_final_latency_ms = float(summary["max_final_latency_ms"])
    return [
        {
            "name": "whisper_prediction_segment_count",
            "value": int(summary["segment_count"]),
            "threshold": f"{expected_segments} human segments",
            "passed": int(summary["segment_count"]) == expected_segments,
        },
        {
            "name": "whisper_primary_language_accuracy",
            "value": float(summary["language_primary_accuracy"]),
            "threshold": ">= 0.75 warning baseline",
            "passed": float(summary["language_primary_accuracy"]) >= 0.75,
        },
        {
            "name": "whisper_mean_translation_token_f1",
            "value": float(summary["mean_translation_token_f1"]),
            "threshold": ">= 0.10 warning baseline",
            "passed": float(summary["mean_translation_token_f1"]) >= 0.10,
        },
        {
            "name": "whisper_final_latency_recorded",
            "value": max_final_latency_ms,
            "threshold": "finite positive latency",
            "passed": max_final_latency_ms > 0.0 and max_final_latency_ms < float("inf"),
        },
        {
            "name": "whisper_final_latency_smoke_budget",
            "value": round(max_final_latency_ms, 3),
            "threshold": "<= 120000 ms per short source clip on CPU",
            "passed": max_final_latency_ms <= 120000.0,
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    prediction: dict[str, Any],
    prediction_path: Path,
) -> dict[str, Any]:
    run_dir = prediction_path.parent
    diarization_predictions_path = run_dir / "oracle_diarization_predictions.jsonl"
    oracle_translation_predictions_path = run_dir / "oracle_translation_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records([annotation]), diarization_predictions_path)
    write_jsonl(build_oracle_translation_records([annotation]), oracle_translation_predictions_path)

    diarization_report = score_diarization_predictions(
        [annotation],
        diarization_predictions_path,
        strict_oracle=True,
    )
    translation_report = score_translation_predictions(annotation, prediction)
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = model_quality_gates(annotation, translation_report)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_whisper_language_translation",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "diarization": diarization_report,
            "language_translation": translation_report,
        },
        "prediction_paths": {
            "diarization": str(diarization_predictions_path),
            "oracle_language_translation": str(oracle_translation_predictions_path),
            "model_language_translation": str(prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "This uses oracle source clips rather than live diarization/separation, and Whisper "
                "is not a native low-latency streaming speech-translation engine."
            ),
            "cheapest_falsifying_benchmark": (
                "Run the same adapter on rolling diarization segments from the mixed fixture and "
                "compare language flips, partial latency, and translation token F1."
            ),
            "fallback_if_falsified": (
                "Keep text captions and provider MT as the fallback path while researching a direct "
                "streaming S2ST candidate."
            ),
        },
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    print(f"whisper translation audio-eval {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run faster-whisper on the FLEURS translation fixture")
    parser.add_argument("--self-test", action="store_true", help="validate JSONL/scorer contract only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--vad-filter", action="store_true")
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument(
        "--score-warning-only",
        action="store_true",
        help="write measured report but exit 0 even when model quality gates warn",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = run_self_test()
        print("whisper translation contract self-test PASS")
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )
    run_dir = output_dir / "runs" / args.run_id
    prediction_path = run_dir / "whisper_translation_predictions.jsonl"
    prediction = build_whisper_prediction(annotation, output_dir, args)
    write_jsonl([prediction], prediction_path)
    report = build_report(annotation, output_dir, prediction, prediction_path)
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "whisper-translation-fixture-report.json"
    )
    write_report(report, report_path)
    print(f"wrote whisper translation predictions to {prediction_path}")
    print(f"wrote whisper translation report to {report_path}")
    print_summary(report)
    if report["summary"]["passed"]:
        return 0
    return 0 if args.score_warning_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
