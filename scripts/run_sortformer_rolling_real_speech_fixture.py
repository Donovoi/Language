#!/usr/bin/env python3
"""Run NVIDIA Sortformer statefully from rolling raw PCM fixture chunks."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import numpy as np
import soundfile as sf

from audio_eval_harness import DEFAULT_OUTPUT_DIR, write_report
from benchmark_chunked_diarization_fixture import build_chunked_report, print_chunked_summary
from prepare_real_speech_fixture import prepare_real_speech_fixture
from run_pyannote_diarization_fixture import fixture_mix_path
from run_sortformer_online_real_speech_fixture import (
    OUTPUT_FRAME_S,
    apply_streaming_profile,
    input_buffer_latency_s,
    output_end_s,
)
from run_sortformer_real_speech_fixture import (
    DEFAULT_MODEL,
    env_token,
    load_sortformer_model,
    should_require_token,
    sortformer_segments,
)


DEFAULT_RUN_ID = "sortformer-streaming-4spk-v2-1-real-speech-rolling-pcm"
DEFAULT_RAW_CHUNK_S = 0.08


@dataclass(frozen=True)
class RollingPcmWindow:
    step_index: int
    output_start_s: float
    target_output_end_s: float
    input_start_s: float
    input_end_s: float
    input_start_sample: int
    input_end_sample: int
    available_end_sample: int
    raw_chunks_read: int
    left_offset: int
    right_offset: int
    samples: np.ndarray


class RollingPcmReader:
    """Read mono PCM in arrival order while allowing windowed model buffers."""

    def __init__(self, path: Path, raw_chunk_samples: int) -> None:
        self._handle = sf.SoundFile(path)
        self.sample_rate_hz = int(self._handle.samplerate)
        self.raw_chunk_samples = raw_chunk_samples
        self.available_end_sample = 0
        self.raw_chunks_read = 0
        self._chunks: list[np.ndarray] = []

    def close(self) -> None:
        self._handle.close()

    def read_until(self, end_sample: int) -> None:
        while self.available_end_sample < end_sample:
            frames = min(self.raw_chunk_samples, end_sample - self.available_end_sample)
            if frames <= 0:
                break
            data = self._handle.read(frames=frames, dtype="float32", always_2d=False)
            if len(data) == 0:
                break
            if getattr(data, "ndim", 1) > 1:
                data = data.mean(axis=1)
            chunk = np.asarray(data, dtype=np.float32)
            self._chunks.append(chunk)
            self.available_end_sample += int(chunk.shape[0])
            self.raw_chunks_read += 1

    def window(self, start_sample: int, end_sample: int) -> np.ndarray:
        if end_sample > self.available_end_sample:
            raise ValueError("rolling PCM window requested samples that have not arrived")
        if start_sample < 0 or end_sample <= start_sample:
            raise ValueError("invalid rolling PCM window")
        joined = np.concatenate(self._chunks) if self._chunks else np.zeros((0,), dtype=np.float32)
        return np.asarray(joined[start_sample:end_sample], dtype=np.float32)


def _sample_index(seconds: float, sample_rate_hz: int) -> int:
    return int(round(seconds * sample_rate_hz))


def _feature_offset_seconds_to_frames(seconds: float, feature_frame_s: float) -> int:
    return int(round(max(0.0, seconds) / feature_frame_s))


def _streaming_int(streaming_config: dict[str, int | str], key: str) -> int:
    value = streaming_config[key]
    if not isinstance(value, int):
        raise ValueError(f"streaming config {key} must be an integer")
    return value


def rolling_pcm_windows(
    mix_path: Path,
    *,
    sample_rate_hz: int,
    duration_s: float,
    streaming_config: dict[str, int | str],
    chunk_left_context: int,
    encoder_subsampling: int,
    raw_chunk_s: float,
) -> Iterator[RollingPcmWindow]:
    raw_chunk_samples = max(1, _sample_index(raw_chunk_s, sample_rate_hz))
    feature_frame_s = OUTPUT_FRAME_S / float(encoder_subsampling)
    chunk_len = _streaming_int(streaming_config, "chunk_len")
    chunk_right_context = _streaming_int(streaming_config, "chunk_right_context")
    chunk_output_s = chunk_len * OUTPUT_FRAME_S
    right_context_s = chunk_right_context * OUTPUT_FRAME_S
    left_context_s = chunk_left_context * OUTPUT_FRAME_S
    duration_samples = _sample_index(duration_s, sample_rate_hz)

    reader = RollingPcmReader(mix_path, raw_chunk_samples)
    try:
        if reader.sample_rate_hz != sample_rate_hz:
            raise ValueError(
                f"expected {sample_rate_hz} Hz fixture audio, got {reader.sample_rate_hz} Hz"
            )

        step_index = 0
        while True:
            output_start_s = round(step_index * chunk_output_s, 6)
            if output_start_s >= duration_s:
                break
            target_output_end_s = min(duration_s, round((step_index + 1) * chunk_output_s, 6))
            input_start_s = max(0.0, round(output_start_s - left_context_s, 6))
            input_end_s = min(duration_s, round(target_output_end_s + right_context_s, 6))
            input_start_sample = _sample_index(input_start_s, sample_rate_hz)
            input_end_sample = min(duration_samples, _sample_index(input_end_s, sample_rate_hz))

            reader.read_until(input_end_sample)
            samples = reader.window(input_start_sample, input_end_sample)
            actual_input_end_s = round(input_end_sample / float(sample_rate_hz), 6)
            actual_input_start_s = round(input_start_sample / float(sample_rate_hz), 6)
            left_offset = _feature_offset_seconds_to_frames(
                output_start_s - actual_input_start_s,
                feature_frame_s,
            )
            right_offset = _feature_offset_seconds_to_frames(
                actual_input_end_s - target_output_end_s,
                feature_frame_s,
            )

            yield RollingPcmWindow(
                step_index=step_index,
                output_start_s=output_start_s,
                target_output_end_s=target_output_end_s,
                input_start_s=actual_input_start_s,
                input_end_s=actual_input_end_s,
                input_start_sample=input_start_sample,
                input_end_sample=input_end_sample,
                available_end_sample=reader.available_end_sample,
                raw_chunks_read=reader.raw_chunks_read,
                left_offset=left_offset,
                right_offset=right_offset,
                samples=samples,
            )
            step_index += 1
    finally:
        reader.close()


def run_rolling_steps(
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
        raise SystemExit("Sortformer rolling runner requires torch and NeMo diarization utilities.") from exc

    sample_rate_hz = int(annotation["sample_rate_hz"])
    duration_s = float(annotation["duration_s"])
    chunk_left_context = int(getattr(diar_model.sortformer_modules, "chunk_left_context", 1))
    encoder_subsampling = int(diar_model.encoder.subsampling_factor)
    state = diar_model.sortformer_modules.init_streaming_state(
        batch_size=1,
        async_streaming=diar_model.async_streaming,
        device=diar_model.device,
    )
    total_preds = torch.zeros((1, 0, diar_model.sortformer_modules.n_spk), device=diar_model.device)
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
    feature_extraction_total_ms = 0.0
    mix_path = fixture_mix_path(output_dir, annotation)
    for window in rolling_pcm_windows(
        mix_path,
        sample_rate_hz=sample_rate_hz,
        duration_s=duration_s,
        streaming_config=streaming_config,
        chunk_left_context=chunk_left_context,
        encoder_subsampling=encoder_subsampling,
        raw_chunk_s=args.raw_chunk_s,
    ):
        audio_signal = torch.tensor(window.samples, dtype=torch.float32, device=diar_model.device).unsqueeze(0)
        audio_signal_length = torch.tensor([audio_signal.shape[1]], dtype=torch.long, device=diar_model.device)

        feature_started = time.perf_counter()
        with torch.no_grad():
            processed_signal, processed_signal_length = diar_model.process_signal(
                audio_signal=audio_signal,
                audio_signal_length=audio_signal_length,
            )
            processed_signal = processed_signal[:, :, : int(processed_signal_length.max())].transpose(1, 2)
        feature_latency_ms = (time.perf_counter() - feature_started) * 1000.0
        feature_extraction_total_ms += feature_latency_ms

        step_started = time.perf_counter()
        with torch.no_grad():
            state, total_preds = diar_model.forward_streaming_step(
                processed_signal=processed_signal,
                processed_signal_length=processed_signal_length,
                streaming_state=state,
                total_preds=total_preds,
                left_offset=window.left_offset,
                right_offset=window.right_offset,
            )
        step_latency_ms = (time.perf_counter() - step_started) * 1000.0
        output_end = output_end_s(int(total_preds.shape[1]), duration_s)
        diar_lines = diar_model._diarize_output_processing(
            total_preds.to("cpu"),
            [annotation["fixture_id"]],
            diarize_cfg,
        )[0]
        future_samples_used = max(0, window.input_end_sample - window.available_end_sample)

        records.append(
            {
                "schema_version": 1,
                "fixture_id": annotation["fixture_id"],
                "adapter_id": args.adapter_id,
                "segments": sortformer_segments(diar_lines),
                "model_layer_latency_ms": {
                    "feature_extraction": round(feature_latency_ms, 3),
                    "feature_extraction_cumulative": round(feature_extraction_total_ms, 3),
                    "streaming_step": round(step_latency_ms, 3),
                    "diarization": round((time.perf_counter() - online_started) * 1000.0, 3),
                },
                "metadata": {
                    "model": args.model,
                    "model_path": None if args.model_path is None else str(args.model_path),
                    "device": args.device,
                    "fixture_kind": "real_speech_mixed_overlap",
                    "streaming_mode": "raw_pcm_rolling_stateful",
                    "nemo_entrypoint": (
                        "SortformerEncLabelModel.process_signal + "
                        "SortformerEncLabelModel.forward_streaming_step"
                    ),
                    "latency_profile": args.latency_profile,
                    "streaming_config": streaming_config,
                    "input_buffer_latency_s": input_buffer_latency_s(streaming_config),
                    "sample_rate_hz": sample_rate_hz,
                    "raw_chunk_s": args.raw_chunk_s,
                    "raw_chunks_read": window.raw_chunks_read,
                    "step_index": window.step_index,
                    "chunk_index": window.step_index,
                    "chunk_start_s": 0.0,
                    "chunk_end_s": window.input_end_s,
                    "output_start_s": window.output_start_s,
                    "target_output_end_s": window.target_output_end_s,
                    "output_end_s": output_end,
                    "input_start_s": window.input_start_s,
                    "input_end_s": window.input_end_s,
                    "input_start_sample": window.input_start_sample,
                    "input_end_sample": window.input_end_sample,
                    "available_end_sample": window.available_end_sample,
                    "future_samples_used": future_samples_used,
                    "causality_ok": future_samples_used == 0,
                    "right_context_offset": window.right_offset,
                    "left_context_offset": window.left_offset,
                    "feature_chunk_frames": int(processed_signal.shape[1]),
                    "feature_chunk_lengths": [int(item) for item in processed_signal_length.detach().cpu().tolist()],
                    "prediction_frames": int(total_preds.shape[1]),
                    "max_speakers": 4,
                },
            }
        )

    return records


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run NVIDIA Sortformer from rolling raw PCM chunks")
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
    parser.add_argument("--raw-chunk-s", type=float, default=DEFAULT_RAW_CHUNK_S)
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
    records = run_rolling_steps(diar_model, annotation, output_dir, args, streaming_config)
    for record in records:
        record["metadata"]["token_source"] = token_source or "none"

    latency_threshold_s = input_buffer_latency_s(streaming_config)
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "rolling-diarization-report.json"
    )
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
        latency_threshold_ms=(None if latency_threshold_s is None else round(latency_threshold_s * 1000.0, 3)),
    )
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
    report["summary"]["streaming_metrics"]["raw_chunk_s"] = args.raw_chunk_s
    report["summary"]["streaming_metrics"]["raw_chunks_read"] = int(records[-1]["metadata"]["raw_chunks_read"])
    report["summary"]["streaming_metrics"]["max_future_samples_used"] = max_future_samples_used
    report["summary"]["streaming_metrics"]["causality_ok"] = max_future_samples_used == 0
    report["summary"]["streaming_metrics"]["feature_extraction_ms"] = round(feature_extraction_ms, 3)
    report["summary"]["streaming_metrics"]["online_processing_ms"] = round(online_processing_ms, 3)
    report["summary"]["streaming_metrics"]["model_realtime_factor"] = round(
        total_model_ms / (float(annotation["duration_s"]) * 1000.0),
        6,
    )
    report["detractor_loop"]["strongest_objection"] = (
        "This feeds Sortformer rolling raw PCM windows and extracts features per available input "
        "buffer, so it removes the whole-fixture feature-extraction shortcut. It is still a clean "
        "LibriSpeech fixture read from disk, not a real microphone, noisy room, non-English talker, "
        "or translated playback/suppression loop."
    )
    report["detractor_loop"]["cheapest_falsifying_benchmark"] = (
        "Replay or capture a consented room recording through the same rolling PCM path, with "
        "measured microphone chunks, speaker re-entry, overlap, playback loopback, and at least one "
        "non-English speaker."
    )
    report["detractor_loop"]["fallback_if_falsified"] = (
        "Keep live output in captions or uncertainty-marked speaker lanes until raw microphone "
        "capture, diarization, and playback-loop reports pass together."
    )
    write_report(report, report_path)
    print(f"wrote Sortformer rolling PCM diarization report to {report_path}")
    print_chunked_summary(report)
    passed = bool(report["summary"]["passed"]) and max_future_samples_used == 0
    if not passed and args.score_warning_only:
        print("Sortformer rolling PCM score gates failed, but --score-warning-only was set")
        return 0
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
