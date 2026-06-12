#!/usr/bin/env python3
"""Benchmark diarization records with prefix-chunk streaming metrics."""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    active_speakers_at,
    intersection_duration,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)
from prepare_real_speech_fixture import prepare_real_speech_fixture


DEFAULT_RUN_ID = "real-speech-librispeech-overlap-chunked-oracle"
DEFAULT_CHUNK_S = 2.0
DEFAULT_HOP_S = 1.0
_MIN_DETECTION_OVERLAP_S = 0.05


@dataclass(frozen=True)
class ChunkWindow:
    index: int
    start_s: float
    end_s: float


def prefix_chunk_windows(duration_s: float, chunk_s: float, hop_s: float) -> list[ChunkWindow]:
    if duration_s <= 0.0:
        raise ValueError("duration_s must be greater than zero")
    if chunk_s <= 0.0:
        raise ValueError("chunk_s must be greater than zero")
    if hop_s <= 0.0:
        raise ValueError("hop_s must be greater than zero")

    ends: list[float] = []
    current_end_s = min(chunk_s, duration_s)
    while current_end_s < duration_s:
        ends.append(round(current_end_s, 6))
        current_end_s += hop_s
    if not ends or ends[-1] < duration_s:
        ends.append(round(duration_s, 6))
    return [ChunkWindow(index=index, start_s=0.0, end_s=end_s) for index, end_s in enumerate(ends)]


def human_reference_segments(annotation: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "speaker_id": str(segment["speaker_id"]),
            "start_s": float(segment["start_s"]),
            "end_s": float(segment["end_s"]),
        }
        for segment in annotation["segments"]
        if segment.get("source_kind") == "human"
    ]


def clip_segments_to_window(
    segments: list[dict[str, Any]],
    window: ChunkWindow,
) -> list[dict[str, Any]]:
    clipped: list[dict[str, Any]] = []
    for segment in segments:
        start_s = max(float(segment["start_s"]), window.start_s)
        end_s = min(float(segment["end_s"]), window.end_s)
        if end_s <= start_s:
            continue
        clipped.append(
            {
                "speaker_id": str(segment.get("speaker_id", segment.get("speaker_label"))),
                "start_s": round(start_s, 6),
                "end_s": round(end_s, 6),
                "confidence": float(segment.get("confidence", 1.0)),
            }
        )
    return clipped


def chunk_window_from_record(record: dict[str, Any]) -> ChunkWindow:
    metadata = record.get("metadata", {})
    return ChunkWindow(
        index=int(metadata["chunk_index"]),
        start_s=float(metadata.get("chunk_start_s", 0.0)),
        end_s=float(metadata["chunk_end_s"]),
    )


def clip_prediction_record_to_window(record: dict[str, Any]) -> dict[str, Any]:
    window = chunk_window_from_record(record)
    raw_segments = list(record.get("segments", []))
    clipped_segments = clip_segments_to_window(raw_segments, window)
    boundary_clipped_count = sum(
        1
        for segment in raw_segments
        if float(segment["start_s"]) < window.start_s or float(segment["end_s"]) > window.end_s
    )
    dropped_count = len(raw_segments) - len(clipped_segments)

    clipped_record = dict(record)
    metadata = dict(record.get("metadata", {}))
    if boundary_clipped_count or dropped_count:
        metadata["chunk_boundary_clipped_segments"] = boundary_clipped_count
        metadata["chunk_boundary_dropped_segments"] = dropped_count
    clipped_record["metadata"] = metadata
    clipped_record["segments"] = clipped_segments
    return clipped_record


def truncate_annotation(annotation: dict[str, Any], window: ChunkWindow) -> dict[str, Any]:
    clipped_segments: list[dict[str, Any]] = []
    sample_rate_hz = int(annotation["sample_rate_hz"])
    for segment in annotation["segments"]:
        start_s = max(float(segment["start_s"]), window.start_s)
        end_s = min(float(segment["end_s"]), window.end_s)
        if end_s <= start_s:
            continue
        clipped = dict(segment)
        clipped["start_s"] = round(start_s, 6)
        clipped["end_s"] = round(end_s, 6)
        if "start_sample" in clipped:
            clipped["start_sample"] = int(round(start_s * sample_rate_hz))
        if "end_sample" in clipped:
            clipped["end_sample"] = int(round(end_s * sample_rate_hz))
        clipped_segments.append(clipped)

    truncated = dict(annotation)
    truncated["duration_s"] = round(window.end_s - window.start_s, 6)
    truncated["segments"] = clipped_segments
    return truncated


def oracle_chunk_records(
    annotation: dict[str, Any],
    windows: list[ChunkWindow],
    adapter_id: str,
) -> list[dict[str, Any]]:
    reference_segments = human_reference_segments(annotation)
    return [
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": adapter_id,
            "segments": clip_segments_to_window(reference_segments, window),
            "model_layer_latency_ms": {
                "diarization": 0.0,
            },
            "metadata": {
                "kind": "oracle",
                "streaming_mode": "prefix_chunk",
                "chunk_index": window.index,
                "chunk_start_s": window.start_s,
                "chunk_end_s": window.end_s,
            },
        }
        for window in windows
    ]


def score_chunk_records(
    annotation: dict[str, Any],
    chunk_records: list[dict[str, Any]],
    run_dir: Path,
    *,
    strict_oracle: bool,
) -> list[dict[str, Any]]:
    score_dir = run_dir / "chunk_scores"
    reports: list[dict[str, Any]] = []
    for record in chunk_records:
        record = clip_prediction_record_to_window(record)
        window = chunk_window_from_record(record)
        prediction_path = score_dir / f"chunk_{window.index:03d}.jsonl"
        write_jsonl([record], prediction_path)
        report = score_diarization_predictions(
            [truncate_annotation(annotation, window)],
            prediction_path,
            strict_oracle=strict_oracle,
        )
        reports.append(
            {
                "chunk_index": window.index,
                "chunk_start_s": window.start_s,
                "chunk_end_s": window.end_s,
                "segment_count": len(record.get("segments", [])),
                "model_layer_latency_ms": record.get("model_layer_latency_ms", {}),
                "summary": report["summary"],
            }
        )
    return reports


def predicted_overlap_present(segments: list[dict[str, Any]], duration_s: float) -> bool:
    boundaries = {0.0, duration_s}
    for segment in segments:
        boundaries.add(float(segment["start_s"]))
        boundaries.add(float(segment["end_s"]))
    ordered = sorted(boundary for boundary in boundaries if 0.0 <= boundary <= duration_s)
    for index in range(len(ordered) - 1):
        start_s = ordered[index]
        end_s = ordered[index + 1]
        if end_s <= start_s:
            continue
        if len(active_speakers_at(segments, start_s, end_s)) >= 2:
            return True
    return False


def reference_overlap_start_s(annotation: dict[str, Any]) -> float | None:
    segments = human_reference_segments(annotation)
    boundaries = {0.0, float(annotation["duration_s"])}
    for segment in segments:
        boundaries.add(float(segment["start_s"]))
        boundaries.add(float(segment["end_s"]))
    ordered = sorted(boundary for boundary in boundaries if 0.0 <= boundary <= float(annotation["duration_s"]))
    for index in range(len(ordered) - 1):
        start_s = ordered[index]
        end_s = ordered[index + 1]
        if end_s <= start_s:
            continue
        if len(active_speakers_at(segments, start_s, end_s)) >= 2:
            return start_s
    return None


def streaming_metrics(annotation: dict[str, Any], chunk_records: list[dict[str, Any]]) -> dict[str, Any]:
    reference_segments = human_reference_segments(annotation)
    detection_latency_by_speaker: dict[str, float | None] = {}
    for reference in reference_segments:
        speaker_id = str(reference["speaker_id"])
        if speaker_id in detection_latency_by_speaker:
            continue
        first_detection_end_s: float | None = None
        for record in chunk_records:
            chunk_end_s = float(record["metadata"]["chunk_end_s"])
            for prediction in record.get("segments", []):
                if intersection_duration(reference, prediction) >= _MIN_DETECTION_OVERLAP_S:
                    first_detection_end_s = chunk_end_s
                    break
            if first_detection_end_s is not None:
                break
        detection_latency_by_speaker[speaker_id] = (
            None
            if first_detection_end_s is None
            else round((first_detection_end_s - float(reference["start_s"])) * 1000.0, 3)
        )

    overlap_start_s = reference_overlap_start_s(annotation)
    overlap_detected_at_s: float | None = None
    if overlap_start_s is not None:
        for record in chunk_records:
            chunk_end_s = float(record["metadata"]["chunk_end_s"])
            if chunk_end_s < overlap_start_s:
                continue
            if predicted_overlap_present(record.get("segments", []), chunk_end_s):
                overlap_detected_at_s = chunk_end_s
                break

    label_sets = [
        sorted({str(segment["speaker_id"]) for segment in record.get("segments", [])})
        for record in chunk_records
    ]
    label_set_changes = sum(
        1
        for previous, current in zip(label_sets, label_sets[1:], strict=False)
        if previous != current
    )

    numeric_latencies = [
        value for value in detection_latency_by_speaker.values() if value is not None
    ]
    return {
        "first_speech_detection_latency_ms_by_reference_speaker": detection_latency_by_speaker,
        "max_first_speech_detection_latency_ms": (
            None if not numeric_latencies else round(max(numeric_latencies), 3)
        ),
        "reference_overlap_start_s": overlap_start_s,
        "overlap_detected_at_s": overlap_detected_at_s,
        "overlap_detection_latency_ms": (
            None
            if overlap_start_s is None or overlap_detected_at_s is None
            else round((overlap_detected_at_s - overlap_start_s) * 1000.0, 3)
        ),
        "speaker_label_sets_by_chunk": label_sets,
        "speaker_label_set_changes": label_set_changes,
    }


def chunked_quality_gates(
    final_report: dict[str, Any],
    metrics: dict[str, Any],
    *,
    strict_oracle: bool,
    chunk_s: float,
    hop_s: float,
    chunk_count: int,
    latency_threshold_ms: float | None = None,
    step_unit: str = "prefix chunks",
) -> list[dict[str, Any]]:
    der_threshold = 0.001 if strict_oracle else 0.15
    if latency_threshold_ms is None:
        latency_threshold_ms = round((chunk_s + hop_s) * 1000.0, 3)
    max_detection_latency = metrics["max_first_speech_detection_latency_ms"]
    overlap_latency = metrics["overlap_detection_latency_ms"]
    return [
        {
            "name": "chunked_chunk_count",
            "value": chunk_count,
            "threshold": f">= 2 {step_unit}",
            "passed": chunk_count >= 2,
        },
        {
            "name": "chunked_final_der_like",
            "value": final_report["summary"]["der_like"],
            "threshold": f"<= {der_threshold}",
            "passed": float(final_report["summary"]["der_like"]) <= der_threshold,
        },
        {
            "name": "chunked_first_speech_detection_latency",
            "value": max_detection_latency,
            "threshold": f"<= {latency_threshold_ms} ms",
            "passed": max_detection_latency is not None and max_detection_latency <= latency_threshold_ms,
        },
        {
            "name": "chunked_overlap_detected",
            "value": overlap_latency,
            "threshold": "overlap detected in a prefix chunk",
            "passed": overlap_latency is not None,
        },
    ]


def build_chunked_report(
    annotation: dict[str, Any],
    chunk_records: list[dict[str, Any]],
    *,
    output_dir: Path,
    run_id: str,
    chunk_predictions_path: Path,
    final_predictions_path: Path,
    strict_oracle: bool,
    chunk_s: float,
    hop_s: float,
    streaming_mode: str = "prefix_chunk",
    latency_threshold_ms: float | None = None,
    step_unit: str = "prefix chunks",
) -> dict[str, Any]:
    if not chunk_records:
        raise ValueError("at least one chunk record is required")

    run_dir = output_dir / "runs" / run_id
    chunk_records = [clip_prediction_record_to_window(record) for record in chunk_records]
    write_jsonl(chunk_records, chunk_predictions_path)
    write_jsonl([chunk_records[-1]], final_predictions_path)
    final_report = score_diarization_predictions(
        [annotation],
        final_predictions_path,
        strict_oracle=strict_oracle,
    )
    chunk_reports = score_chunk_records(
        annotation,
        chunk_records,
        run_dir,
        strict_oracle=strict_oracle,
    )
    metrics = streaming_metrics(annotation, chunk_records)
    gates = chunked_quality_gates(
        final_report,
        metrics,
        strict_oracle=strict_oracle,
        chunk_s=chunk_s,
        hop_s=hop_s,
        chunk_count=len(chunk_records),
        latency_threshold_ms=latency_threshold_ms,
        step_unit=step_unit,
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "run_id": run_id,
        "fixture_id": annotation["fixture_id"],
        "streaming_mode": streaming_mode,
        "chunk_s": chunk_s,
        "hop_s": hop_s,
        "chunk_predictions_path": str(chunk_predictions_path),
        "final_predictions_path": str(final_predictions_path),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "final": final_report["summary"],
            "streaming_metrics": metrics,
        },
        "chunks": chunk_reports,
        "final_diarization": final_report,
        "detractor_loop": {
            "strongest_objection": (
                "Prefix chunks are only a streaming-ish proxy. They expose latency and label churn, "
                "but they do not prove microphone capture, causal buffering, or realtime playback."
            ),
            "cheapest_falsifying_benchmark": (
                "Run the same chunked report on a true online diarizer and a consented local room "
                "recording with measured overlap."
            ),
            "fallback_if_falsified": (
                "Keep diarization output in benchmark-only or captions-only mode until chunked "
                "real-speech gates pass."
            ),
        },
    }


def print_chunked_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    streaming_mode = report.get("streaming_mode")
    if streaming_mode == "online_stateful":
        unit = "online steps"
    elif streaming_mode == "raw_pcm_rolling_stateful":
        unit = "rolling PCM steps"
    else:
        unit = "prefix chunks"
    print(f"chunked diarization {status}: {len(report['chunks'])} {unit}")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run chunked diarization benchmark fixtures")
    subparsers = parser.add_subparsers(dest="command", required=True)

    oracle = subparsers.add_parser("oracle", help="run chunked oracle predictions")
    oracle.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    oracle.add_argument("--run-id", default=DEFAULT_RUN_ID)
    oracle.add_argument("--chunk-s", type=float, default=DEFAULT_CHUNK_S)
    oracle.add_argument("--hop-s", type=float, default=DEFAULT_HOP_S)
    oracle.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    annotation = prepare_real_speech_fixture(output_dir=output_dir)
    windows = prefix_chunk_windows(float(annotation["duration_s"]), args.chunk_s, args.hop_s)
    chunk_records = oracle_chunk_records(annotation, windows, adapter_id=f"{args.run_id}-oracle")
    run_dir = output_dir / "runs" / args.run_id
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "chunked-diarization-report.json"
    )
    report = build_chunked_report(
        annotation,
        chunk_records,
        output_dir=output_dir,
        run_id=args.run_id,
        chunk_predictions_path=run_dir / "chunk_predictions.jsonl",
        final_predictions_path=run_dir / "predictions.jsonl",
        strict_oracle=True,
        chunk_s=args.chunk_s,
        hop_s=args.hop_s,
    )
    write_report(report, report_path)
    print(f"wrote chunked diarization report to {report_path}")
    print_chunked_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
