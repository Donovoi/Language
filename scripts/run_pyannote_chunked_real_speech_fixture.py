#!/usr/bin/env python3
"""Run pyannote on a tiny real-speech fixture with prefix chunks."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

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
from run_pyannote_diarization_fixture import (
    DEFAULT_MODEL,
    diarization_segments,
    env_token,
    extract_diarization,
    fixture_mix_path,
    human_speaker_count,
    load_pyannote_pipeline,
    should_require_token,
)


DEFAULT_RUN_ID = "pyannote-community-1-real-speech-chunked"


def run_chunk(
    pipeline: object,
    prefix_path: Path,
    annotation: dict[str, object],
    args: argparse.Namespace,
    chunk_index: int,
    chunk_end_s: float,
) -> dict[str, object]:
    kwargs: dict[str, object] = {}
    if args.num_speakers_from_truth:
        kwargs["num_speakers"] = human_speaker_count(annotation)
    if args.min_speakers is not None:
        kwargs["min_speakers"] = args.min_speakers
    if args.max_speakers is not None:
        kwargs["max_speakers"] = args.max_speakers

    started = time.perf_counter()
    output = pipeline(str(prefix_path), **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    diarization = extract_diarization(output, args.exclusive)
    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": args.adapter_id,
        "segments": diarization_segments(diarization),
        "model_layer_latency_ms": {
            "diarization": round(elapsed_ms, 3),
        },
        "metadata": {
            "model": args.model,
            "device": args.device,
            "exclusive": bool(args.exclusive),
            "num_speakers_from_truth": bool(args.num_speakers_from_truth),
            "min_speakers": args.min_speakers,
            "max_speakers": args.max_speakers,
            "fixture_kind": "real_speech_mixed_overlap",
            "streaming_mode": "prefix_chunk",
            "chunk_index": chunk_index,
            "chunk_start_s": 0.0,
            "chunk_end_s": chunk_end_s,
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run pyannote on prefix chunks")
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
    if should_require_token(args.model) and not token and not args.allow_no_token:
        raise SystemExit(
            "pyannote Community-1 requires accepting Hugging Face model conditions and setting "
            "HF_TOKEN or HUGGINGFACE_TOKEN. Use --allow-no-token only for a local/offline model path."
        )

    annotation = prepare_real_speech_fixture(output_dir=output_dir)
    windows = prefix_chunk_windows(float(annotation["duration_s"]), args.chunk_s, args.hop_s)
    run_dir = output_dir / "runs" / args.run_id
    chunk_dir = run_dir / "chunk_audio"
    chunk_dir.mkdir(parents=True, exist_ok=True)
    mix_audio, sample_rate_hz = sf.read(fixture_mix_path(output_dir, annotation), dtype="float32")
    if getattr(mix_audio, "ndim", 1) > 1:
        mix_audio = mix_audio.mean(axis=1)

    pipeline = load_pyannote_pipeline(args.model, token, args.device)
    chunk_records: list[dict[str, object]] = []
    for window in windows:
        end_frame = int(round(window.end_s * sample_rate_hz))
        prefix_path = chunk_dir / f"prefix_{window.index:03d}_{window.end_s:.3f}s.wav"
        sf.write(prefix_path, mix_audio[:end_frame], sample_rate_hz, subtype=PCM_SUBTYPE)
        record = run_chunk(
            pipeline,
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
        "Pyannote is being run repeatedly on growing prefixes, which is a useful streaming proxy "
        "but not a causal online diarizer or an end-to-end realtime loop."
    )
    from audio_eval_harness import write_report

    write_report(report, report_path)
    print(f"wrote pyannote chunked diarization report to {report_path}")
    print_chunked_summary(report)
    passed = bool(report["summary"]["passed"])
    if not passed and args.score_warning_only:
        print("pyannote chunked score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
