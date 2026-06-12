#!/usr/bin/env python3
"""Run NVIDIA Sortformer on a tiny real-speech fixture with prefix chunks."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from audio_eval_harness import DEFAULT_OUTPUT_DIR, PCM_SUBTYPE
from benchmark_chunked_diarization_fixture import (
    DEFAULT_CHUNK_S,
    DEFAULT_HOP_S,
    build_chunked_report,
    prefix_chunk_windows,
    print_chunked_summary,
)
from prepare_real_speech_fixture import prepare_real_speech_fixture
from run_pyannote_diarization_fixture import fixture_mix_path
from run_sortformer_real_speech_fixture import (
    DEFAULT_MODEL,
    env_token,
    load_sortformer_model,
    should_require_token,
    sortformer_segments,
)


DEFAULT_RUN_ID = "sortformer-streaming-4spk-v2-1-real-speech-chunked"


def run_chunk(
    diar_model: Any,
    prefix_path: Path,
    annotation: dict[str, Any],
    args: argparse.Namespace,
    chunk_index: int,
    chunk_end_s: float,
) -> dict[str, Any]:
    started = time.perf_counter()
    output = diar_model.diarize(audio=[str(prefix_path)], batch_size=args.batch_size)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": args.adapter_id,
        "segments": sortformer_segments(output),
        "model_layer_latency_ms": {
            "diarization": round(elapsed_ms, 3),
        },
        "metadata": {
            "model": args.model,
            "model_path": None if args.model_path is None else str(args.model_path),
            "device": args.device,
            "batch_size": args.batch_size,
            "fixture_kind": "real_speech_mixed_overlap",
            "streaming_mode": "prefix_chunk",
            "chunk_index": chunk_index,
            "chunk_start_s": 0.0,
            "chunk_end_s": chunk_end_s,
            "max_speakers": 4,
            "nemo_entrypoint": "SortformerEncLabelModel.diarize",
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NVIDIA Sortformer on prefix chunks")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--chunk-s", type=float, default=DEFAULT_CHUNK_S)
    parser.add_argument("--hop-s", type=float, default=DEFAULT_HOP_S)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    if args.adapter_id is None:
        args.adapter_id = args.run_id

    token = args.hf_token
    token_source = "argument" if token else None
    if not token:
        token, token_source = env_token()
    if should_require_token(args.model, args.model_path) and not token and not args.allow_no_token:
        raise SystemExit(
            "NVIDIA Sortformer model downloads require a Hugging Face token. Set HF_TOKEN or "
            "HUGGINGFACE_TOKEN, pass --hf-token, or use --model-path for a local .nemo checkpoint."
        )

    annotation = prepare_real_speech_fixture(output_dir=output_dir)
    windows = prefix_chunk_windows(float(annotation["duration_s"]), args.chunk_s, args.hop_s)
    run_dir = output_dir / "runs" / args.run_id
    chunk_dir = run_dir / "chunk_audio"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    mix_audio, sample_rate_hz = sf.read(fixture_mix_path(output_dir, annotation), dtype="float32")
    if getattr(mix_audio, "ndim", 1) > 1:
        mix_audio = mix_audio.mean(axis=1)

    diar_model = load_sortformer_model(args.model, args.model_path, token, args.device)
    chunk_records: list[dict[str, Any]] = []
    for window in windows:
        end_frame = int(round(window.end_s * sample_rate_hz))
        prefix_path = chunk_dir / f"prefix_{window.index:03d}_{window.end_s:.3f}s.wav"
        sf.write(prefix_path, mix_audio[:end_frame], sample_rate_hz, subtype=PCM_SUBTYPE)
        record = run_chunk(
            diar_model,
            prefix_path,
            annotation,
            args,
            chunk_index=window.index,
            chunk_end_s=window.end_s,
        )
        record["metadata"]["token_source"] = token_source or "none"
        chunk_records.append(record)

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
        strict_oracle=False,
        chunk_s=args.chunk_s,
        hop_s=args.hop_s,
    )
    report["detractor_loop"]["strongest_objection"] = (
        "Streaming Sortformer is the right research candidate, but this check still runs NeMo's "
        "direct diarize() method repeatedly on growing prefixes. It is a proxy, not the true "
        "stateful AOSC streaming path from the paper/model card."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Replace prefix reprocessing with the official online/e2e Sortformer path, then compare "
        "DER/JER, label churn, and measured wall-clock latency on the same fixture."
    )
    report["detractor_loop"]["fallback_if_falsified"] = (
        "Keep Sortformer as a benchmark-only adapter and avoid product claims about live diarization "
        "until the true online path passes local room tests."
    )
    from audio_eval_harness import write_report

    write_report(report, report_path)
    print(f"wrote Sortformer chunked diarization report to {report_path}")
    print_chunked_summary(report)
    passed = bool(report["summary"]["passed"])
    if not passed and args.score_warning_only:
        print("Sortformer chunked score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
