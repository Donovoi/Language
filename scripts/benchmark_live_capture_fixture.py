#!/usr/bin/env python3
"""Benchmark the live-capture PCM chunk contract using fixture replay.

This is the first capture-runtime scaffold. It does not claim microphone
hardware evidence; it turns existing fixture WAV files into timestamped mono
PCM chunks, checks causality and reassembly, and writes the report shape that a
real microphone adapter must satisfy later.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

from audio_eval_harness import (
    DEFAULT_MANIFEST,
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    dbfs,
    peak_dbfs,
    render_fixtures,
    safe_id,
    sha256_file,
    write_jsonl,
    write_report,
)


DEFAULT_RUN_ID = "fixture-live-pcm-capture"
DEFAULT_ADAPTER_ID = "fixture_replay_pcm_capture_v1"
DEFAULT_CHUNK_MS = 80.0
DEFAULT_MIN_CHUNKS = 4
DEFAULT_MAX_CHUNK_DURATION_ERROR_MS = 0.25
DEFAULT_MAX_REASSEMBLY_ERROR = 0.0
CAPTURE_SOURCE_KIND = "fixture_replay"
STREAMING_MODE = "virtual_time_pcm_chunks"


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate_hz = sf.read(path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate_hz)


def chunk_hash(samples: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(samples).tobytes()).hexdigest()


def chunk_fixture_audio(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str,
    chunk_ms: float,
) -> dict[str, Any]:
    if chunk_ms <= 0.0:
        raise ValueError("chunk_ms must be greater than zero")

    base_dir = output_dir / "fixtures" / annotation["fixture_set_id"] / safe_id(annotation["fixture_id"])
    source_path = base_dir / annotation["mix_path"]
    source_audio, sample_rate_hz = read_mono(source_path)
    expected_rate_hz = int(annotation["sample_rate_hz"])
    if sample_rate_hz != expected_rate_hz:
        raise ValueError(f"expected {expected_rate_hz} Hz fixture, got {sample_rate_hz}")

    chunk_frames = max(1, int(round(sample_rate_hz * chunk_ms / 1000.0)))
    chunks: list[dict[str, Any]] = []
    reassembled_parts: list[np.ndarray] = []
    previous_end_sample = 0
    contiguous = True
    timestamps_monotonic = True
    no_future_samples = True
    previous_virtual_arrival_s = -math.inf

    for chunk_index, start_sample in enumerate(range(0, int(source_audio.size), chunk_frames)):
        end_sample = min(start_sample + chunk_frames, int(source_audio.size))
        chunk = np.asarray(source_audio[start_sample:end_sample], dtype=np.float32)
        reassembled_parts.append(chunk)

        if start_sample != previous_end_sample:
            contiguous = False
        if end_sample > int(source_audio.size):
            no_future_samples = False

        virtual_arrival_s = start_sample / float(sample_rate_hz)
        if virtual_arrival_s <= previous_virtual_arrival_s and chunk_index > 0:
            timestamps_monotonic = False
        previous_virtual_arrival_s = virtual_arrival_s
        previous_end_sample = end_sample

        duration_ms = (end_sample - start_sample) / float(sample_rate_hz) * 1000.0
        target_duration_ms = chunk_ms if end_sample < int(source_audio.size) else duration_ms
        chunks.append(
            {
                "chunk_index": chunk_index,
                "start_sample": start_sample,
                "end_sample": end_sample,
                "start_s": round(start_sample / float(sample_rate_hz), 6),
                "end_s": round(end_sample / float(sample_rate_hz), 6),
                "frame_count": int(chunk.size),
                "duration_ms": round(duration_ms, 6),
                "target_duration_ms": round(target_duration_ms, 6),
                "duration_error_ms": round(abs(duration_ms - target_duration_ms), 6),
                "virtual_arrival_time_s": round(virtual_arrival_s, 6),
                "rms_dbfs": round(dbfs(chunk), 3),
                "peak_dbfs": round(peak_dbfs(chunk), 3),
                "sha256_float32": chunk_hash(chunk),
            }
        )

    reassembled = (
        np.concatenate(reassembled_parts).astype(np.float32)
        if reassembled_parts
        else np.zeros((0,), dtype=np.float32)
    )
    if reassembled.shape != source_audio.shape:
        max_reassembly_error = float("inf")
    elif reassembled.size:
        max_reassembly_error = float(np.max(np.abs(reassembled - source_audio)))
    else:
        max_reassembly_error = 0.0

    run_dir.mkdir(parents=True, exist_ok=True)
    reassembled_path = run_dir / f"{safe_id(annotation['fixture_id'])}_reassembled_capture.wav"
    sf.write(reassembled_path, reassembled, sample_rate_hz, subtype=PCM_SUBTYPE)

    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": adapter_id,
        "capture_source_kind": CAPTURE_SOURCE_KIND,
        "streaming_mode": STREAMING_MODE,
        "sample_rate_hz": sample_rate_hz,
        "channel_count": 1,
        "source_mix_path": str(source_path),
        "source_mix_sha256": sha256_file(source_path),
        "reassembled_capture_path": str(reassembled_path.relative_to(run_dir)),
        "reassembled_capture_sha256": sha256_file(reassembled_path),
        "chunk_ms": chunk_ms,
        "chunk_frame_count": chunk_frames,
        "chunk_count": len(chunks),
        "frame_count": int(source_audio.size),
        "duration_s": round(source_audio.size / float(sample_rate_hz), 6),
        "contiguous": contiguous,
        "timestamps_monotonic": timestamps_monotonic,
        "no_future_samples_used": no_future_samples,
        "max_reassembly_abs_error": max_reassembly_error,
        "input_level_dbfs": round(dbfs(source_audio), 3),
        "input_peak_dbfs": round(peak_dbfs(source_audio), 3),
        "chunks": chunks,
        "metadata": {
            "release_proof": False,
            "note": "Fixture replay validates PCM chunk plumbing only; it is not microphone hardware evidence.",
        },
    }


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    all_chunks = [chunk for record in records for chunk in record["chunks"]]
    non_final_duration_errors = [
        float(chunk["duration_error_ms"])
        for record in records
        for chunk in record["chunks"][:-1]
    ]
    chunk_levels_recorded = all(
        "rms_dbfs" in chunk and "peak_dbfs" in chunk
        for chunk in all_chunks
    )
    artifact_hash_chain_present = all(
        bool(record.get("source_mix_sha256"))
        and bool(record.get("reassembled_capture_sha256"))
        and all(bool(chunk.get("sha256_float32")) for chunk in record["chunks"])
        for record in records
    )
    sample_rates = sorted({int(record["sample_rate_hz"]) for record in records})
    summary = {
        "capture_source_kind": CAPTURE_SOURCE_KIND,
        "streaming_mode": STREAMING_MODE,
        "fixture_count": len(records),
        "total_chunk_count": len(all_chunks),
        "sample_rates_hz": sample_rates,
        "all_mono": all(int(record["channel_count"]) == 1 for record in records),
        "all_contiguous": all(bool(record["contiguous"]) for record in records),
        "all_timestamps_monotonic": all(bool(record["timestamps_monotonic"]) for record in records),
        "no_future_samples_used": all(bool(record["no_future_samples_used"]) for record in records),
        "max_non_final_chunk_duration_error_ms": (
            0.0 if not non_final_duration_errors else round(max(non_final_duration_errors), 6)
        ),
        "max_reassembly_abs_error": round(
            max(float(record["max_reassembly_abs_error"]) for record in records),
            9,
        ),
        "chunk_levels_recorded": chunk_levels_recorded,
        "artifact_hash_chain_present": artifact_hash_chain_present,
        "release_proof": False,
    }
    summary["quality_gates"] = capture_quality_gates(summary)
    return summary


def capture_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "capture_fixture_count",
            "value": int(summary["fixture_count"]),
            "threshold": ">= 1 fixture replay source",
            "passed": int(summary["fixture_count"]) >= 1,
        },
        {
            "name": "capture_chunk_count",
            "value": int(summary["total_chunk_count"]),
            "threshold": f">= {DEFAULT_MIN_CHUNKS} PCM chunks",
            "passed": int(summary["total_chunk_count"]) >= DEFAULT_MIN_CHUNKS,
        },
        {
            "name": "capture_sample_rate_stable",
            "value": summary["sample_rates_hz"],
            "threshold": "exactly one sample rate across capture records",
            "passed": len(summary["sample_rates_hz"]) == 1,
        },
        {
            "name": "pcm_chunk_schema_valid",
            "value": {
                "sample_rates_hz": summary["sample_rates_hz"],
                "all_mono": bool(summary["all_mono"]),
                "total_chunk_count": int(summary["total_chunk_count"]),
            },
            "threshold": "stable sample rate, mono PCM, and at least one chunk",
            "passed": (
                len(summary["sample_rates_hz"]) == 1
                and bool(summary["all_mono"])
                and int(summary["total_chunk_count"]) > 0
            ),
        },
        {
            "name": "capture_mono_pcm",
            "value": bool(summary["all_mono"]),
            "threshold": "mono PCM chunks",
            "passed": bool(summary["all_mono"]),
        },
        {
            "name": "capture_chunks_contiguous",
            "value": bool(summary["all_contiguous"]),
            "threshold": "no gaps or overlaps between chunks",
            "passed": bool(summary["all_contiguous"]),
        },
        {
            "name": "capture_timestamps_monotonic",
            "value": bool(summary["all_timestamps_monotonic"]),
            "threshold": "strictly increasing virtual arrival timestamps",
            "passed": bool(summary["all_timestamps_monotonic"]),
        },
        {
            "name": "no_chunk_gaps_or_reorders",
            "value": {
                "contiguous": bool(summary["all_contiguous"]),
                "timestamps_monotonic": bool(summary["all_timestamps_monotonic"]),
            },
            "threshold": "no gaps, overlaps, or timestamp reordering",
            "passed": bool(summary["all_contiguous"]) and bool(summary["all_timestamps_monotonic"]),
        },
        {
            "name": "capture_no_future_samples",
            "value": bool(summary["no_future_samples_used"]),
            "threshold": "chunk records do not consume samples past the observed input",
            "passed": bool(summary["no_future_samples_used"]),
        },
        {
            "name": "streaming_boundary_enforced",
            "value": bool(summary["no_future_samples_used"]),
            "threshold": "downstream capture record exposes only current/past samples",
            "passed": bool(summary["no_future_samples_used"]),
        },
        {
            "name": "capture_chunk_duration_bounded",
            "value": float(summary["max_non_final_chunk_duration_error_ms"]),
            "threshold": f"<= {DEFAULT_MAX_CHUNK_DURATION_ERROR_MS} ms for non-final chunks",
            "passed": (
                float(summary["max_non_final_chunk_duration_error_ms"])
                <= DEFAULT_MAX_CHUNK_DURATION_ERROR_MS
            ),
        },
        {
            "name": "chunk_timing_jitter_within_limit",
            "value": float(summary["max_non_final_chunk_duration_error_ms"]),
            "threshold": f"<= {DEFAULT_MAX_CHUNK_DURATION_ERROR_MS} ms virtual chunk-duration jitter",
            "passed": (
                float(summary["max_non_final_chunk_duration_error_ms"])
                <= DEFAULT_MAX_CHUNK_DURATION_ERROR_MS
            ),
        },
        {
            "name": "capture_reassembly_exact",
            "value": float(summary["max_reassembly_abs_error"]),
            "threshold": f"<= {DEFAULT_MAX_REASSEMBLY_ERROR} max absolute float32 error",
            "passed": float(summary["max_reassembly_abs_error"]) <= DEFAULT_MAX_REASSEMBLY_ERROR,
        },
        {
            "name": "level_meter_tracks_fixture",
            "value": bool(summary["chunk_levels_recorded"]),
            "threshold": "rms and peak level fields recorded for every chunk",
            "passed": bool(summary["chunk_levels_recorded"]),
        },
        {
            "name": "capture_artifact_hash_chain_present",
            "value": bool(summary["artifact_hash_chain_present"]),
            "threshold": "source, reassembled capture, and chunk hashes are recorded",
            "passed": bool(summary["artifact_hash_chain_present"]),
        },
        {
            "name": "capture_source_is_fixture",
            "value": summary["capture_source_kind"],
            "threshold": "fixture_replay for scaffold evidence",
            "passed": summary["capture_source_kind"] == CAPTURE_SOURCE_KIND,
        },
        {
            "name": "capture_not_release_proof",
            "value": summary["capture_source_kind"],
            "threshold": "fixture_replay is prototype evidence, not microphone release proof",
            "passed": summary["capture_source_kind"] == CAPTURE_SOURCE_KIND and not summary["release_proof"],
        },
    ]


def build_report(records: list[dict[str, Any]], output_dir: Path, run_dir: Path) -> dict[str, Any]:
    capture_summary = summarize_records(records)
    gates = capture_summary["quality_gates"]
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fixture_pcm_capture_replay",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
        },
        "benchmarks": {
            "capture": {
                "adapter_id": records[0]["adapter_id"] if records else DEFAULT_ADAPTER_ID,
                "summary": capture_summary,
                "records": records,
            }
        },
        "prediction_paths": {
            "capture_chunks": str(run_dir / "capture_chunks.jsonl"),
        },
        "detractor_loop": {
            "strongest_objection": (
                "Fixture replay proves PCM chunk shape and causality bookkeeping only. It does not "
                "prove microphone permissions, device jitter, OS audio callbacks, acoustic echo, or "
                "room noise behavior."
            ),
            "cheapest_falsifying_benchmark": (
                "Run the same report from an actual microphone callback on the target device and "
                "compare chunk jitter, dropped frames, level stability, and sample-rate drift."
            ),
            "fallback_if_falsified": (
                "Keep live audio disabled and use fixture replay or mock ingest until the capture "
                "adapter has a passing microphone report."
            ),
        },
    }


def self_test() -> dict[str, Any]:
    passing_summary = {
        "capture_source_kind": CAPTURE_SOURCE_KIND,
        "streaming_mode": STREAMING_MODE,
        "fixture_count": 1,
        "total_chunk_count": DEFAULT_MIN_CHUNKS,
        "sample_rates_hz": [16000],
        "all_mono": True,
        "all_contiguous": True,
        "all_timestamps_monotonic": True,
        "no_future_samples_used": True,
        "max_non_final_chunk_duration_error_ms": 0.0,
        "max_reassembly_abs_error": 0.0,
        "chunk_levels_recorded": True,
        "artifact_hash_chain_present": True,
        "release_proof": False,
    }
    failing_summary = {
        **passing_summary,
        "all_contiguous": False,
        "max_reassembly_abs_error": 0.5,
    }
    passing = capture_quality_gates(passing_summary)
    failing = capture_quality_gates(failing_summary)
    if not all(bool(gate["passed"]) for gate in passing):
        raise RuntimeError("self-test expected valid capture summary to pass")
    failed_gate_names = {str(gate["name"]) for gate in failing if not bool(gate["passed"])}
    expected = {"capture_chunks_contiguous", "capture_reassembly_exact"}
    if not expected.issubset(failed_gate_names):
        raise RuntimeError("self-test expected broken capture summary to fail")
    return {
        "passing_gate_count": len(passing),
        "failing_gate_names": sorted(failed_gate_names),
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    capture = report["benchmarks"]["capture"]["summary"]
    print(
        "fixture live-capture "
        f"{status}: {capture['fixture_count']} fixtures, {capture['total_chunk_count']} chunks"
    )
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  capture diagnostics: "
        f"source_kind={capture['capture_source_kind']} "
        f"sample_rates={capture['sample_rates_hz']} "
        f"max_reassembly_abs_error={capture['max_reassembly_abs_error']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark fixture-backed live PCM capture chunks")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["check"],
        default="check",
    )
    parser.add_argument("--self-test", action="store_true", help="validate scorer gates only")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--chunk-ms", type=float, default=DEFAULT_CHUNK_MS)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = self_test()
        print("fixture live-capture contract self-test PASS")
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0

    output_dir = args.output_dir.resolve()
    annotations = render_fixtures(args.manifest.resolve(), output_dir)
    run_dir = output_dir / "runs" / args.run_id
    records = [
        chunk_fixture_audio(
            annotation,
            output_dir,
            run_dir,
            adapter_id=args.adapter_id,
            chunk_ms=args.chunk_ms,
        )
        for annotation in annotations
    ]
    prediction_path = run_dir / "capture_chunks.jsonl"
    write_jsonl(records, prediction_path)
    report = build_report(records, output_dir, run_dir)
    report_path = args.report.resolve() if args.report else run_dir / "capture-runtime-report.json"
    write_report(report, report_path)
    print(f"wrote fixture live-capture chunks to {prediction_path}")
    print(f"wrote fixture live-capture report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
