#!/usr/bin/env python3
"""Run Whisper on rolling oracle-diarized slices from the mixed FLEURS fixture.

This is the first falsifying bridge between clean source-clip speech translation
and the live app shape. Diarization boundaries are still oracle, but the audio
fed to Whisper comes from the room mix, so overlap and boundary context can hurt
language ID and translation quality.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    analyze_fixture,
    build_oracle_diarization_records,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    _primary_language,
    _token_f1,
    build_oracle_translation_records,
    prepare_multilingual_fixture,
    score_translation_predictions,
)
from prepare_real_speech_fixture import fixture_dir
from run_whisper_translation_fixture import (
    DEFAULT_MODEL_SIZE,
    load_whisper_model,
    run_self_test as run_source_clip_self_test,
    transcribe_segment,
)


DEFAULT_RUN_ID = "whisper-tiny-fleurs-rolling-mixed-translation"
DEFAULT_ADAPTER_ID = "faster_whisper_tiny_rolling_mixed_translate_v1"
DEFAULT_HOP_S = 2.0
DEFAULT_MIN_CLIP_S = 1.0


@dataclass(frozen=True)
class RollingPrediction:
    chunk_index: int
    chunk_end_s: float
    speaker_id: str
    segment_start_s: float
    clip_end_s: float
    segment_final: bool
    prediction: dict[str, Any]


def human_segments(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        segment
        for segment in sorted(annotation["segments"], key=lambda item: float(item["start_s"]))
        if segment.get("source_kind") == "human"
    ]


def chunk_end_times(duration_s: float, hop_s: float) -> list[float]:
    if duration_s <= 0.0:
        raise ValueError("duration_s must be greater than zero")
    if hop_s <= 0.0:
        raise ValueError("hop_s must be greater than zero")

    ends: list[float] = []
    current = hop_s
    while current < duration_s:
        ends.append(round(current, 6))
        current += hop_s
    if not ends or ends[-1] < duration_s:
        ends.append(round(duration_s, 6))
    return ends


def load_mix(output_dir: Path, annotation: dict[str, Any]) -> tuple[np.ndarray, int]:
    mix_file = fixture_dir(output_dir, annotation["fixture_set_id"], annotation["fixture_id"]) / str(
        annotation["mix_path"]
    )
    audio, sample_rate_hz = sf.read(mix_file, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate_hz)


def write_mixed_clip(
    mix_audio: np.ndarray,
    sample_rate_hz: int,
    *,
    start_s: float,
    end_s: float,
    clip_path: Path,
) -> None:
    start_sample = max(0, int(round(start_s * sample_rate_hz)))
    end_sample = min(int(mix_audio.shape[0]), int(round(end_s * sample_rate_hz)))
    if end_sample <= start_sample:
        raise ValueError("mixed clip end must be after start")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, mix_audio[start_sample:end_sample], sample_rate_hz, subtype=PCM_SUBTYPE)


def prediction_segment(
    source_segment: dict[str, Any],
    result: dict[str, Any],
    *,
    chunk_index: int,
    chunk_end_s: float,
    clip_end_s: float,
    clip_path: Path,
    run_dir: Path,
    segment_final: bool,
) -> dict[str, Any]:
    speech_elapsed_ms = max(0.0, chunk_end_s - float(source_segment["start_s"])) * 1000.0
    model_first_ms = float(result["first_partial_latency_ms"])
    model_final_ms = float(result["final_latency_ms"])
    return {
        "speaker_id": source_segment["speaker_id"],
        "start_s": source_segment["start_s"],
        "end_s": round(clip_end_s, 6),
        "detected_language_code": result["detected_language_code"],
        "language_confidence": result["language_confidence"],
        "source_text": None,
        "translated_text": result["translated_text"],
        "target_language_code": "en",
        "first_partial_latency_ms": round(speech_elapsed_ms + model_first_ms, 3),
        "final_latency_ms": round(speech_elapsed_ms + model_final_ms, 3),
        "metadata": {
            "chunk_index": chunk_index,
            "chunk_end_s": chunk_end_s,
            "clip_start_s": source_segment["start_s"],
            "clip_end_s": round(clip_end_s, 6),
            "segment_truth_end_s": source_segment["end_s"],
            "segment_final": segment_final,
            "source_audio": "mixed_fixture_clip",
            "mixed_clip_path": str(clip_path.relative_to(run_dir)),
            "whisper_segment_count": result["whisper_segment_count"],
            "model_first_partial_latency_ms": model_first_ms,
            "model_final_latency_ms": model_final_ms,
        },
    }


def rolling_whisper_predictions(
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    model = load_whisper_model(args.model_size, args.device, args.compute_type)
    mix_audio, sample_rate_hz = load_mix(output_dir, annotation)
    if sample_rate_hz != int(annotation["sample_rate_hz"]):
        raise ValueError(f"expected {annotation['sample_rate_hz']} Hz, got {sample_rate_hz} Hz")

    run_dir = output_dir / "runs" / args.run_id
    clip_dir = run_dir / "mixed_clips"
    completed_speakers: set[str] = set()
    records: list[dict[str, Any]] = []
    segments = human_segments(annotation)

    for chunk_index, chunk_end_s in enumerate(
        chunk_end_times(float(annotation["duration_s"]), args.hop_s)
    ):
        record_segments: list[dict[str, Any]] = []
        for source_segment in segments:
            speaker_id = str(source_segment["speaker_id"])
            if speaker_id in completed_speakers:
                continue
            segment_start_s = float(source_segment["start_s"])
            segment_end_s = float(source_segment["end_s"])
            if chunk_end_s <= segment_start_s:
                continue

            clip_end_s = min(segment_end_s, chunk_end_s)
            clip_duration_s = clip_end_s - segment_start_s
            segment_final = chunk_end_s >= segment_end_s
            if clip_duration_s < args.min_clip_s and not segment_final:
                continue

            clip_path = clip_dir / f"chunk_{chunk_index:03d}_{speaker_id}.wav"
            write_mixed_clip(
                mix_audio,
                sample_rate_hz,
                start_s=segment_start_s,
                end_s=clip_end_s,
                clip_path=clip_path,
            )
            result = transcribe_segment(
                model,
                clip_path,
                beam_size=args.beam_size,
                vad_filter=bool(args.vad_filter),
            )
            record_segments.append(
                prediction_segment(
                    source_segment,
                    result,
                    chunk_index=chunk_index,
                    chunk_end_s=chunk_end_s,
                    clip_end_s=clip_end_s,
                    clip_path=clip_path,
                    run_dir=run_dir,
                    segment_final=segment_final,
                )
            )
            if segment_final:
                completed_speakers.add(speaker_id)

        if record_segments:
            records.append(
                {
                    "schema_version": 1,
                    "fixture_id": annotation["fixture_id"],
                    "adapter_id": args.adapter_id,
                    "segments": record_segments,
                    "metadata": {
                        "kind": "whisper_rolling_mixed_translation",
                        "streaming_mode": "oracle_diarization_rolling_mixed_segments",
                        "chunk_index": chunk_index,
                        "chunk_start_s": 0.0,
                        "chunk_end_s": chunk_end_s,
                        "hop_s": args.hop_s,
                        "min_clip_s": args.min_clip_s,
                        "segmentation_prior": "oracle_diarization",
                        "audio_source": "mixed_fixture",
                    },
                }
            )

    return records


def final_prediction_from_rolling(
    annotation: dict[str, Any],
    records: list[dict[str, Any]],
    adapter_id: str,
) -> dict[str, Any]:
    first_latency_by_speaker: dict[str, float] = {}
    final_by_speaker: dict[str, dict[str, Any]] = {}
    for record in records:
        for segment in record.get("segments", []):
            speaker_id = str(segment["speaker_id"])
            first_latency_by_speaker.setdefault(
                speaker_id,
                float(segment["first_partial_latency_ms"]),
            )
            if segment.get("metadata", {}).get("segment_final"):
                final_by_speaker[speaker_id] = segment

    final_segments: list[dict[str, Any]] = []
    for source_segment in human_segments(annotation):
        speaker_id = str(source_segment["speaker_id"])
        final_segment = final_by_speaker.get(speaker_id)
        if final_segment is None:
            continue
        item = dict(final_segment)
        item["start_s"] = source_segment["start_s"]
        item["end_s"] = source_segment["end_s"]
        item["first_partial_latency_ms"] = round(
            first_latency_by_speaker.get(
                speaker_id,
                float(final_segment["first_partial_latency_ms"]),
            ),
            3,
        )
        final_segments.append(item)

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": adapter_id,
        "segments": final_segments,
        "metadata": {
            "kind": "whisper_rolling_mixed_translation_final",
            "streaming_mode": "oracle_diarization_rolling_mixed_segments",
        },
    }


def rolling_metrics(
    annotation: dict[str, Any],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_by_speaker = {
        str(segment["speaker_id"]): segment for segment in human_segments(annotation)
    }
    predictions_by_speaker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        for segment in record.get("segments", []):
            predictions_by_speaker[str(segment["speaker_id"])].append(segment)

    details: dict[str, dict[str, Any]] = {}
    total_language_flips = 0
    partial_token_f1_values: list[float] = []
    first_latencies: list[float] = []
    final_latencies: list[float] = []
    final_count = 0

    for speaker_id, expected in expected_by_speaker.items():
        predictions = predictions_by_speaker.get(speaker_id, [])
        primary_languages = [
            _primary_language(str(prediction.get("detected_language_code", "")))
            for prediction in predictions
            if str(prediction.get("detected_language_code", "")).strip()
        ]
        flips = sum(
            1
            for previous, current in zip(primary_languages, primary_languages[1:], strict=False)
            if previous != current
        )
        total_language_flips += flips
        expected_text = str(expected["english_reference_text"])
        speaker_partial_f1 = [
            round(_token_f1(expected_text, str(prediction.get("translated_text", ""))), 6)
            for prediction in predictions
        ]
        partial_token_f1_values.extend(speaker_partial_f1)
        final_predictions = [
            prediction
            for prediction in predictions
            if prediction.get("metadata", {}).get("segment_final")
        ]
        if predictions:
            first_latencies.append(float(predictions[0]["first_partial_latency_ms"]))
        if final_predictions:
            final_count += 1
            final_latencies.append(float(final_predictions[-1]["final_latency_ms"]))
        details[speaker_id] = {
            "prediction_count": len(predictions),
            "language_sequence": primary_languages,
            "language_flip_count": flips,
            "partial_translation_token_f1": speaker_partial_f1,
            "first_partial_latency_ms": (
                None if not predictions else float(predictions[0]["first_partial_latency_ms"])
            ),
            "final_latency_ms": (
                None if not final_predictions else float(final_predictions[-1]["final_latency_ms"])
            ),
        }

    partial_count = sum(len(items) for items in predictions_by_speaker.values())
    return {
        "partial_prediction_count": partial_count,
        "final_prediction_count": final_count,
        "speaker_language_flip_count": total_language_flips,
        "speakers_with_language_flips": [
            speaker_id
            for speaker_id, detail in details.items()
            if int(detail["language_flip_count"]) > 0
        ],
        "mean_partial_translation_token_f1": (
            round(sum(partial_token_f1_values) / len(partial_token_f1_values), 6)
            if partial_token_f1_values
            else 0.0
        ),
        "max_first_partial_latency_ms": (
            None if not first_latencies else round(max(first_latencies), 3)
        ),
        "max_final_latency_ms": None if not final_latencies else round(max(final_latencies), 3),
        "details_by_speaker": details,
    }


def rolling_quality_gates(
    annotation: dict[str, Any],
    translation_report: dict[str, Any],
    metrics: dict[str, Any],
    *,
    hop_s: float,
) -> list[dict[str, Any]]:
    expected_segments = len(human_segments(annotation))
    first_latency_threshold_ms = round(max(1.0, hop_s) * 1000.0 + 120000.0, 3)
    max_first_latency = metrics["max_first_partial_latency_ms"]
    return [
        {
            "name": "rolling_final_prediction_segment_count",
            "value": int(translation_report["summary"]["segment_count"]),
            "threshold": f"{expected_segments} human final segments",
            "passed": int(translation_report["summary"]["segment_count"]) == expected_segments,
        },
        {
            "name": "rolling_primary_language_accuracy",
            "value": float(translation_report["summary"]["language_primary_accuracy"]),
            "threshold": ">= 0.50 warning baseline on overlapped mix slices",
            "passed": float(translation_report["summary"]["language_primary_accuracy"]) >= 0.50,
        },
        {
            "name": "rolling_mean_translation_token_f1",
            "value": float(translation_report["summary"]["mean_translation_token_f1"]),
            "threshold": ">= 0.05 warning baseline on overlapped mix slices",
            "passed": float(translation_report["summary"]["mean_translation_token_f1"]) >= 0.05,
        },
        {
            "name": "rolling_first_partial_latency_recorded",
            "value": max_first_latency,
            "threshold": f"finite and <= {first_latency_threshold_ms} ms",
            "passed": max_first_latency is not None and max_first_latency <= first_latency_threshold_ms,
        },
        {
            "name": "rolling_language_flips_recorded",
            "value": int(metrics["speaker_language_flip_count"]),
            "threshold": "diagnostic count, lower is better",
            "passed": True,
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    records: list[dict[str, Any]],
    rolling_prediction_path: Path,
    final_prediction_path: Path,
) -> dict[str, Any]:
    run_dir = rolling_prediction_path.parent
    oracle_diarization_path = run_dir / "oracle_diarization_predictions.jsonl"
    oracle_translation_path = run_dir / "oracle_translation_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records([annotation]), oracle_diarization_path)
    write_jsonl(build_oracle_translation_records([annotation]), oracle_translation_path)

    final_prediction = final_prediction_from_rolling(annotation, records, records[-1]["adapter_id"])
    write_jsonl([final_prediction], final_prediction_path)
    diarization_report = score_diarization_predictions(
        [annotation],
        oracle_diarization_path,
        strict_oracle=True,
    )
    translation_report = score_translation_predictions(annotation, final_prediction)
    fixture_report = analyze_fixture(output_dir, annotation)
    metrics = rolling_metrics(annotation, records)
    gates = rolling_quality_gates(
        annotation,
        translation_report,
        metrics,
        hop_s=float(records[0]["metadata"]["hop_s"]),
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_whisper_rolling_mixed_translation",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
            "rolling_metrics": metrics,
        },
        "benchmarks": {
            "diarization": diarization_report,
            "language_translation": translation_report,
        },
        "prediction_paths": {
            "oracle_diarization": str(oracle_diarization_path),
            "oracle_language_translation": str(oracle_translation_path),
            "rolling_model_language_translation": str(rolling_prediction_path),
            "final_model_language_translation": str(final_prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": final_prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "This uses oracle diarization and disk-backed fixture audio. It does expose Whisper "
                "to mixed, overlapping speech slices, but it is not microphone capture, learned "
                "speaker separation, causal ASR, same-voice TTS, or source suppression."
            ),
            "cheapest_falsifying_benchmark": (
                "Replace oracle boundaries with the rolling diarizer output on the same multilingual "
                "mix, then compare language flips, translation token F1, and end-to-end latency."
            ),
            "fallback_if_falsified": (
                "Keep mixed-speech translation behind captions/uncertainty lanes and add separation "
                "or target-speaker extraction before spoken playback."
            ),
        },
    }


def run_self_test() -> dict[str, Any]:
    source_clip_report = run_source_clip_self_test()
    annotation = {
        "fixture_id": "self_test_rolling_translation_fixture",
        "segments": [
            {
                "speaker_id": "speaker_es",
                "source_kind": "human",
                "language_code": "es-419",
                "english_reference_text": "Fellow wrestlers also paid tribute to Luna.",
                "start_s": 0.0,
                "end_s": 2.0,
            },
            {
                "speaker_id": "speaker_en",
                "source_kind": "human",
                "language_code": "en-US",
                "english_reference_text": "Many people do not think about them as dinosaurs.",
                "start_s": 1.0,
                "end_s": 3.0,
            },
        ],
    }
    records = [
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": "self_test_rolling_contract",
            "segments": [
                {
                    "speaker_id": "speaker_es",
                    "detected_language_code": "fr",
                    "translated_text": "Fellow wrestlers",
                    "first_partial_latency_ms": 1000.0,
                    "final_latency_ms": 1010.0,
                    "metadata": {"segment_final": False},
                }
            ],
            "metadata": {"hop_s": 1.0},
        },
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": "self_test_rolling_contract",
            "segments": [
                {
                    "speaker_id": "speaker_es",
                    "detected_language_code": "es",
                    "translated_text": "Fellow wrestlers paid tribute to Luna.",
                    "first_partial_latency_ms": 2000.0,
                    "final_latency_ms": 2020.0,
                    "metadata": {"segment_final": True},
                },
                {
                    "speaker_id": "speaker_en",
                    "detected_language_code": "en",
                    "translated_text": "Many people do not think about them as dinosaurs.",
                    "first_partial_latency_ms": 1000.0,
                    "final_latency_ms": 1020.0,
                    "metadata": {"segment_final": True},
                },
            ],
            "metadata": {"hop_s": 1.0},
        },
    ]
    final_prediction = final_prediction_from_rolling(annotation, records, "self_test_rolling_contract")
    translation_report = score_translation_predictions(annotation, final_prediction)
    metrics = rolling_metrics(annotation, records)
    gates = rolling_quality_gates(annotation, translation_report, metrics, hop_s=1.0)
    if metrics["speaker_language_flip_count"] != 1:
        raise RuntimeError("self-test expected one language flip")
    if not all(bool(gate["passed"]) for gate in gates):
        raise RuntimeError("self-test expected rolling gates to pass")
    return {
        "source_clip_contract": source_clip_report["summary"],
        "rolling_contract": {
            "summary": translation_report["summary"],
            "rolling_metrics": metrics,
            "quality_gates": gates,
        },
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    metrics = report["summary"]["rolling_metrics"]
    print(f"whisper rolling mixed translation {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  rolling diagnostics: "
        f"partials={metrics['partial_prediction_count']} "
        f"language_flips={metrics['speaker_language_flip_count']} "
        f"mean_partial_token_f1={metrics['mean_partial_translation_token_f1']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run faster-whisper on rolling mixed-audio FLEURS slices"
    )
    parser.add_argument("--self-test", action="store_true", help="validate rolling scorer contract only")
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
    parser.add_argument("--hop-s", type=float, default=DEFAULT_HOP_S)
    parser.add_argument("--min-clip-s", type=float, default=DEFAULT_MIN_CLIP_S)
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
        print("whisper rolling mixed translation contract self-test PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )
    run_dir = output_dir / "runs" / args.run_id
    rolling_prediction_path = run_dir / "rolling_whisper_translation_predictions.jsonl"
    final_prediction_path = run_dir / "final_whisper_translation_predictions.jsonl"
    records = rolling_whisper_predictions(annotation, output_dir, args)
    if not records:
        raise RuntimeError("rolling Whisper translation produced no prediction records")
    write_jsonl(records, rolling_prediction_path)
    report = build_report(
        annotation,
        output_dir,
        records,
        rolling_prediction_path,
        final_prediction_path,
    )
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "rolling-whisper-translation-report.json"
    )
    write_report(report, report_path)
    print(f"wrote rolling whisper predictions to {rolling_prediction_path}")
    print(f"wrote rolling whisper final predictions to {final_prediction_path}")
    print(f"wrote rolling whisper report to {report_path}")
    print_summary(report)
    if report["summary"]["passed"]:
        return 0
    if args.score_warning_only:
        print("Whisper rolling mixed translation gates warned, but --score-warning-only was set")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
