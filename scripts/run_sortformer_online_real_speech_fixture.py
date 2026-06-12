#!/usr/bin/env python3
"""Run NVIDIA Sortformer statefully on the tiny real-speech overlap fixture."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from audio_eval_harness import DEFAULT_OUTPUT_DIR, write_report
from benchmark_chunked_diarization_fixture import build_chunked_report, print_chunked_summary
from prepare_real_speech_fixture import prepare_real_speech_fixture
from run_pyannote_diarization_fixture import fixture_mix_path
from run_sortformer_real_speech_fixture import (
    DEFAULT_MODEL,
    env_token,
    load_sortformer_model,
    should_require_token,
    sortformer_segments,
)


DEFAULT_RUN_ID = "sortformer-streaming-4spk-v2-1-real-speech-online"
OUTPUT_FRAME_S = 0.08

STREAMING_PROFILES = {
    "low-latency": {
        "chunk_len": 6,
        "chunk_right_context": 7,
        "fifo_len": 188,
        "spkcache_update_period": 144,
        "spkcache_len": 188,
    },
    "high-latency": {
        "chunk_len": 340,
        "chunk_right_context": 40,
        "fifo_len": 40,
        "spkcache_update_period": 300,
        "spkcache_len": 188,
    },
}


def apply_streaming_profile(diar_model: Any, args: argparse.Namespace) -> dict[str, int | str]:
    profile = dict(STREAMING_PROFILES.get(args.latency_profile, {}))
    if args.chunk_len is not None:
        profile["chunk_len"] = args.chunk_len
    if args.chunk_right_context is not None:
        profile["chunk_right_context"] = args.chunk_right_context
    if args.fifo_len is not None:
        profile["fifo_len"] = args.fifo_len
    if args.spkcache_update_period is not None:
        profile["spkcache_update_period"] = args.spkcache_update_period
    if args.spkcache_len is not None:
        profile["spkcache_len"] = args.spkcache_len

    for name, value in profile.items():
        setattr(diar_model.sortformer_modules, name, int(value))
    if profile:
        diar_model.sortformer_modules._check_streaming_parameters()
    profile["latency_profile"] = args.latency_profile
    return profile


def output_end_s(total_pred_frames: int, duration_s: float) -> float:
    return min(duration_s, round(float(total_pred_frames) * OUTPUT_FRAME_S, 6))


def observed_end_s(output_end: float, right_offset: int, encoder_subsampling: int, duration_s: float) -> float:
    right_context_s = round(float(right_offset) / float(encoder_subsampling) * OUTPUT_FRAME_S, 6)
    return min(duration_s, round(output_end + right_context_s, 6))


def input_buffer_latency_s(streaming_config: dict[str, int | str]) -> float | None:
    chunk_len = streaming_config.get("chunk_len")
    chunk_right_context = streaming_config.get("chunk_right_context")
    if not isinstance(chunk_len, int) or not isinstance(chunk_right_context, int):
        return None
    return round(float(chunk_len + chunk_right_context) * OUTPUT_FRAME_S, 6)


def run_online_steps(
    diar_model: Any,
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
    streaming_config: dict[str, int | str],
) -> list[dict[str, Any]]:
    try:
        import torch
        from nemo.collections.asr.parts.mixins.diarization import DiarizeConfig
        from nemo.collections.asr.parts.utils.vad_utils import load_postprocessing_from_yaml
    except ImportError as exc:
        raise SystemExit("Sortformer online runner requires torch and NeMo diarization utilities.") from exc

    mix_audio, sample_rate_hz = sf.read(fixture_mix_path(output_dir, annotation), dtype="float32")
    if getattr(mix_audio, "ndim", 1) > 1:
        mix_audio = mix_audio.mean(axis=1)
    audio_signal = torch.tensor(mix_audio, dtype=torch.float32, device=diar_model.device).unsqueeze(0)
    audio_signal_length = torch.tensor([audio_signal.shape[1]], dtype=torch.long, device=diar_model.device)
    duration_s = float(annotation["duration_s"])

    feature_started = time.perf_counter()
    with torch.no_grad():
        processed_signal, processed_signal_length = diar_model.process_signal(
            audio_signal=audio_signal,
            audio_signal_length=audio_signal_length,
        )
    feature_extraction_ms = (time.perf_counter() - feature_started) * 1000.0
    processed_signal = processed_signal[:, :, : int(processed_signal_length.max())]

    state = diar_model.sortformer_modules.init_streaming_state(
        batch_size=1,
        async_streaming=diar_model.async_streaming,
        device=diar_model.device,
    )
    total_preds = torch.zeros((1, 0, diar_model.sortformer_modules.n_spk), device=diar_model.device)
    signal_offset = torch.zeros((1,), dtype=torch.long, device=diar_model.device)
    streaming_loader = diar_model.sortformer_modules.streaming_feat_loader(
        feat_seq=processed_signal,
        feat_seq_length=processed_signal_length,
        feat_seq_offset=signal_offset,
    )
    diarize_cfg = DiarizeConfig(
        batch_size=1,
        num_workers=0,
        verbose=False,
        include_tensor_outputs=False,
        postprocessing_yaml=args.postprocessing_yaml,
        postprocessing_params=load_postprocessing_from_yaml(args.postprocessing_yaml),
    )
    diar_model._diarize_audio_rttm_map = {annotation["fixture_id"]: {"offset": 0.0}}

    records: list[dict[str, Any]] = []
    online_started = time.perf_counter()
    for step_index, (chunk_index, chunk_feat, feat_lengths, left_offset, right_offset) in enumerate(streaming_loader):
        step_started = time.perf_counter()
        with torch.no_grad():
            state, total_preds = diar_model.forward_streaming_step(
                processed_signal=chunk_feat,
                processed_signal_length=feat_lengths,
                streaming_state=state,
                total_preds=total_preds,
                left_offset=left_offset,
                right_offset=right_offset,
            )
        step_latency_ms = (time.perf_counter() - step_started) * 1000.0
        output_end = output_end_s(int(total_preds.shape[1]), duration_s)
        observed_end = observed_end_s(
            output_end,
            right_offset=int(right_offset),
            encoder_subsampling=int(diar_model.encoder.subsampling_factor),
            duration_s=duration_s,
        )
        diar_lines = diar_model._diarize_output_processing(
            total_preds.to("cpu"),
            [annotation["fixture_id"]],
            diarize_cfg,
        )[0]

        records.append(
            {
                "schema_version": 1,
                "fixture_id": annotation["fixture_id"],
                "adapter_id": args.adapter_id,
                "segments": sortformer_segments(diar_lines),
                "model_layer_latency_ms": {
                    "feature_extraction": round(feature_extraction_ms, 3) if step_index == 0 else 0.0,
                    "streaming_step": round(step_latency_ms, 3),
                    "diarization": round((time.perf_counter() - online_started) * 1000.0, 3),
                },
                "metadata": {
                    "model": args.model,
                    "model_path": None if args.model_path is None else str(args.model_path),
                    "device": args.device,
                    "fixture_kind": "real_speech_mixed_overlap",
                    "streaming_mode": "online_stateful",
                    "nemo_entrypoint": "SortformerEncLabelModel.forward_streaming_step",
                    "latency_profile": args.latency_profile,
                    "streaming_config": streaming_config,
                    "input_buffer_latency_s": input_buffer_latency_s(streaming_config),
                    "sample_rate_hz": int(sample_rate_hz),
                    "step_index": step_index,
                    "chunk_index": int(chunk_index),
                    "chunk_start_s": 0.0,
                    "chunk_end_s": observed_end,
                    "output_end_s": output_end,
                    "right_context_offset": int(right_offset),
                    "left_context_offset": int(left_offset),
                    "feature_chunk_frames": int(chunk_feat.shape[1]),
                    "feature_chunk_lengths": [int(item) for item in feat_lengths.detach().cpu().tolist()],
                    "prediction_frames": int(total_preds.shape[1]),
                    "max_speakers": 4,
                },
            }
        )

    return records


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NVIDIA Sortformer through stateful online steps")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--adapter-id")
    parser.add_argument("--hf-token")
    parser.add_argument("--allow-no-token", action="store_true")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--latency-profile", choices=["low-latency", "high-latency", "checkpoint"], default="low-latency")
    parser.add_argument("--chunk-len", type=int)
    parser.add_argument("--chunk-right-context", type=int)
    parser.add_argument("--fifo-len", type=int)
    parser.add_argument("--spkcache-update-period", type=int)
    parser.add_argument("--spkcache-len", type=int)
    parser.add_argument("--postprocessing-yaml")
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
    run_dir = output_dir / "runs" / args.run_id
    diar_model = load_sortformer_model(args.model, args.model_path, token, args.device)
    streaming_config = apply_streaming_profile(diar_model, args)
    records = run_online_steps(diar_model, annotation, output_dir, args, streaming_config)
    for record in records:
        record["metadata"]["token_source"] = token_source or "none"

    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "online-diarization-report.json"
    )
    report = build_chunked_report(
        annotation,
        records,
        output_dir=output_dir,
        run_id=args.run_id,
        chunk_predictions_path=run_dir / "online_predictions.jsonl",
        final_predictions_path=run_dir / "predictions.jsonl",
        strict_oracle=False,
        chunk_s=float(streaming_config.get("chunk_len", 0)) * OUTPUT_FRAME_S,
        hop_s=float(streaming_config.get("chunk_len", 0)) * OUTPUT_FRAME_S,
        streaming_mode="online_stateful",
        step_unit="online steps",
        latency_threshold_ms=(
            None
            if input_buffer_latency_s(streaming_config) is None
            else round(float(input_buffer_latency_s(streaming_config)) * 1000.0, 3)
        ),
    )
    report["input_buffer_latency_s"] = input_buffer_latency_s(streaming_config)
    report["streaming_config"] = streaming_config
    report["summary"]["streaming_metrics"]["input_buffer_latency_s"] = input_buffer_latency_s(streaming_config)
    feature_extraction_ms = float(records[0]["model_layer_latency_ms"].get("feature_extraction", 0.0))
    online_processing_ms = float(records[-1]["model_layer_latency_ms"].get("diarization", 0.0))
    total_model_ms = round(feature_extraction_ms + online_processing_ms, 3)
    report["summary"]["streaming_metrics"]["online_step_count"] = len(records)
    report["summary"]["streaming_metrics"]["feature_extraction_ms"] = round(feature_extraction_ms, 3)
    report["summary"]["streaming_metrics"]["online_processing_ms"] = round(online_processing_ms, 3)
    report["summary"]["streaming_metrics"]["model_realtime_factor"] = round(
        total_model_ms / (float(annotation["duration_s"]) * 1000.0),
        6,
    )
    report["detractor_loop"]["strongest_objection"] = (
        "This uses Sortformer's stateful forward_streaming_step path and AOSC state, but it still "
        "extracts features from the whole fixture before stepping. It is stronger than prefix "
        "reprocessing, but it does not prove microphone capture, rolling raw-audio preprocessing, "
        "or end-to-end translated playback."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Feed raw microphone chunks through rolling preprocessing, then compare this same report "
        "against a consented local room recording with speaker re-entry and overlap."
    )
    report["detractor_loop"]["fallback_if_falsified"] = (
        "Keep Sortformer as a benchmark adapter and fall back to offline diarization or UI-visible "
        "overlap uncertainty until rolling online capture passes."
    )
    write_report(report, report_path)
    print(f"wrote Sortformer online diarization report to {report_path}")
    print_chunked_summary(report)
    passed = bool(report["summary"]["passed"])
    if not passed and args.score_warning_only:
        print("Sortformer online score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
