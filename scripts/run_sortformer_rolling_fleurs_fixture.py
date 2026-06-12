"""Run NVIDIA Sortformer statefully on the multilingual FLEURS overlap fixture."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from audio_eval_harness import DEFAULT_OUTPUT_DIR, write_report
from benchmark_chunked_diarization_fixture import build_chunked_report, print_chunked_summary
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    prepare_multilingual_fixture,
)
from run_sortformer_online_real_speech_fixture import (
    OUTPUT_FRAME_S,
    apply_streaming_profile,
    input_buffer_latency_s,
)
from run_sortformer_real_speech_fixture import (
    DEFAULT_MODEL,
    env_token,
    load_sortformer_model,
    should_require_token,
)
from run_sortformer_rolling_real_speech_fixture import DEFAULT_RAW_CHUNK_S, run_rolling_steps


DEFAULT_RUN_ID = "sortformer-streaming-4spk-v2-1-fleurs-rolling-pcm"
DEFAULT_CHUNK_LEN = 20
DEFAULT_CHUNK_RIGHT_CONTEXT = 20


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run NVIDIA Sortformer from rolling raw PCM chunks on FLEURS"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument(
        "--latency-profile",
        choices=["low-latency", "high-latency", "checkpoint"],
        default="low-latency",
    )
    parser.add_argument("--chunk-len", type=int, default=DEFAULT_CHUNK_LEN)
    parser.add_argument("--chunk-right-context", type=int, default=DEFAULT_CHUNK_RIGHT_CONTEXT)
    parser.add_argument("--fifo-len", type=int)
    parser.add_argument("--spkcache-update-period", type=int)
    parser.add_argument("--spkcache-len", type=int)
    parser.add_argument("--raw-chunk-s", type=float, default=DEFAULT_RAW_CHUNK_S)
    parser.add_argument("--postprocessing-yaml")
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def annotate_records(
    records: list[dict[str, Any]],
    *,
    token_source: str,
    fixture_kind: str,
) -> None:
    for record in records:
        metadata = record.setdefault("metadata", {})
        metadata["token_source"] = token_source
        metadata["fixture_kind"] = fixture_kind
        metadata["segmentation_prior"] = "sortformer_raw_pcm_rolling_stateful"
        metadata["uses_oracle_diarization"] = False


def add_streaming_metrics(
    report: dict[str, Any],
    annotation: dict[str, Any],
    records: list[dict[str, Any]],
    streaming_config: dict[str, int | str],
    raw_chunk_s: float,
) -> None:
    latency_threshold_s = input_buffer_latency_s(streaming_config)
    feature_extraction_ms = sum(
        float(record["model_layer_latency_ms"].get("feature_extraction", 0.0))
        for record in records
    )
    online_processing_ms = float(records[-1]["model_layer_latency_ms"].get("diarization", 0.0))
    total_model_ms = round(feature_extraction_ms + online_processing_ms, 3)
    max_future_samples_used = max(
        int(record["metadata"].get("future_samples_used", 0))
        for record in records
    )

    report["input_buffer_latency_s"] = latency_threshold_s
    report["streaming_config"] = streaming_config
    report["summary"]["streaming_metrics"]["input_buffer_latency_s"] = latency_threshold_s
    report["summary"]["streaming_metrics"]["rolling_pcm_step_count"] = len(records)
    report["summary"]["streaming_metrics"]["raw_chunk_s"] = raw_chunk_s
    report["summary"]["streaming_metrics"]["raw_chunks_read"] = int(
        records[-1]["metadata"]["raw_chunks_read"]
    )
    report["summary"]["streaming_metrics"]["max_future_samples_used"] = max_future_samples_used
    report["summary"]["streaming_metrics"]["causality_ok"] = max_future_samples_used == 0
    report["summary"]["streaming_metrics"]["feature_extraction_ms"] = round(feature_extraction_ms, 3)
    report["summary"]["streaming_metrics"]["online_processing_ms"] = round(online_processing_ms, 3)
    report["summary"]["streaming_metrics"]["model_realtime_factor"] = round(
        total_model_ms / (float(annotation["duration_s"]) * 1000.0),
        6,
    )


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

    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        max_stream_mb=args.max_stream_mb,
    )
    run_dir = output_dir / "runs" / args.run_id
    diar_model = load_sortformer_model(args.model, args.model_path, token, args.device)
    streaming_config = apply_streaming_profile(diar_model, args)
    records = run_rolling_steps(diar_model, annotation, output_dir, args, streaming_config)
    if not records:
        raise RuntimeError("Sortformer rolling FLEURS run produced no records")
    annotate_records(
        records,
        token_source=token_source or "none",
        fixture_kind="fleurs_multilingual_overlap",
    )

    latency_threshold_s = input_buffer_latency_s(streaming_config)
    report_path = args.report.resolve() if args.report else run_dir / "rolling-diarization-report.json"
    report = build_chunked_report(
        annotation,
        records,
        output_dir=output_dir,
        run_id=args.run_id,
        chunk_predictions_path=run_dir / "rolling_predictions.jsonl",
        final_predictions_path=run_dir / "predictions.jsonl",
        strict_oracle=False,
        chunk_s=float(streaming_config.get("chunk_len", 0)) * OUTPUT_FRAME_S,
        hop_s=float(streaming_config.get("chunk_len", 0)) * OUTPUT_FRAME_S,
        streaming_mode="raw_pcm_rolling_stateful",
        step_unit="rolling PCM steps",
        latency_threshold_ms=(
            None if latency_threshold_s is None else round(latency_threshold_s * 1000.0, 3)
        ),
    )
    add_streaming_metrics(report, annotation, records, streaming_config, args.raw_chunk_s)
    report["detractor_loop"]["strongest_objection"] = (
        "This is non-oracle rolling diarization over FLEURS fixture audio, but still disk-backed "
        "read speech. Speaker label mapping appears only in scorer diagnostics; runtime records "
        "keep Sortformer's labels."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Feed the same diarization records into Whisper after accepted TSE, then replace the "
        "fixture with a consented real room recording and speaker re-entry."
    )
    report["detractor_loop"]["fallback_if_falsified"] = (
        "Keep streaming translation blocked until a non-oracle diarizer produces usable windows "
        "on multilingual overlap audio."
    )
    write_report(report, report_path)
    print(f"wrote Sortformer rolling FLEURS diarization report to {report_path}")
    print_chunked_summary(report)
    passed = bool(report["summary"]["passed"]) and (
        int(report["summary"]["streaming_metrics"].get("max_future_samples_used", 1)) == 0
    )
    if not passed and args.score_warning_only:
        print("Sortformer rolling FLEURS gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
