#!/usr/bin/env python3
"""Run SpeechBrain SepFormer WHAMR on the FLEURS overlap fixture.

This is a real separator spike, not a production target-speaker extraction
adapter. SepFormer WHAMR is a blind two-speaker separator, so this harness uses
oracle fixture stems only to assign the separated output stream to each target
speaker for measurement. The output still uses the shared TSE JSONL contract so
downstream Whisper checks can compare real separators against oracle and
passthrough controls.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    analyze_fixture,
    dbfs,
    rms,
    sha256_file,
    write_jsonl,
    write_report,
)
from benchmark_target_speaker_extraction_fixture import (
    base_fixture_dir,
    build_passthrough_tse_records,
    human_segments,
    overlap_s,
    ratio_db,
    read_mono,
    score_tse_predictions,
    segment_samples,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    prepare_multilingual_fixture,
)


DEFAULT_RUN_ID = "fleurs-speechbrain-sepformer-whamr-tse"
DEFAULT_ADAPTER_ID = "speechbrain_sepformer_whamr_blind_separator_v1"
DEFAULT_MODEL_ID = "speechbrain/sepformer-whamr"
DEFAULT_MODEL_SAMPLE_RATE_HZ = 8000


def resample_audio(samples: np.ndarray, source_rate_hz: int, target_rate_hz: int) -> np.ndarray:
    if int(source_rate_hz) == int(target_rate_hz):
        return np.asarray(samples, dtype=np.float32)
    divisor = math.gcd(int(source_rate_hz), int(target_rate_hz))
    return resample_poly(
        samples,
        int(target_rate_hz) // divisor,
        int(source_rate_hz) // divisor,
    ).astype(np.float32)


def match_length(samples: np.ndarray, target_len: int) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.shape[0] == target_len:
        return samples
    if samples.shape[0] > target_len:
        return samples[:target_len]
    return np.pad(samples, (0, target_len - samples.shape[0])).astype(np.float32)


def candidate_sources_from_tensor(est_sources: Any) -> list[np.ndarray]:
    if hasattr(est_sources, "detach"):
        est_sources = est_sources.detach().cpu().numpy()
    array = np.asarray(est_sources, dtype=np.float32)
    while array.ndim > 2 and array.shape[0] == 1:
        array = array[0]
    if array.ndim == 1:
        return [array.astype(np.float32)]
    if array.ndim != 2:
        raise ValueError(f"unsupported separated source tensor shape: {array.shape}")
    if array.shape[0] <= 8 and array.shape[1] > array.shape[0]:
        array = array.T
    return [array[:, index].astype(np.float32) for index in range(array.shape[1])]


def segment_snr_db(estimate: np.ndarray, reference: np.ndarray) -> float:
    length = min(int(estimate.shape[0]), int(reference.shape[0]))
    if length <= 0:
        return float("-inf")
    estimate_aligned = estimate[:length]
    reference_aligned = reference[:length]
    residual = estimate_aligned - reference_aligned
    return round(ratio_db(rms(reference_aligned), rms(residual)), 3)


def select_best_candidate(
    candidates: list[np.ndarray],
    reference_audio: np.ndarray,
) -> tuple[int, np.ndarray, float]:
    if not candidates:
        raise ValueError("separator produced no candidate sources")
    scored = [
        (index, candidate, segment_snr_db(candidate, reference_audio))
        for index, candidate in enumerate(candidates)
    ]
    index, candidate, score = max(scored, key=lambda item: item[2])
    return index, match_length(candidate, int(reference_audio.shape[0])), score


def load_sepformer_model(model_id: str, device: str, savedir: Path) -> Any:
    try:
        from speechbrain.inference.separation import SepformerSeparation
    except ImportError:
        try:
            from speechbrain.pretrained.interfaces import SepformerSeparation
        except ImportError as exc:
            raise SystemExit(
                "SpeechBrain SepFormer runner requires the audio-eval-speechbrain-sepformer "
                "Docker profile."
            ) from exc

    run_opts = {"device": device} if device else None
    kwargs: dict[str, Any] = {"source": model_id, "savedir": str(savedir)}
    if run_opts is not None:
        kwargs["run_opts"] = run_opts
    return SepformerSeparation.from_hparams(**kwargs)


def default_model_cache_dir(output_dir: Path, model_id: str) -> Path:
    cache_root = os.environ.get("SPEECHBRAIN_CACHE_DIR") or os.environ.get("HF_HOME")
    if cache_root:
        return Path(cache_root) / "speechbrain" / model_id.replace("/", "--")
    return output_dir / "model_cache" / "speechbrain" / model_id.replace("/", "--")


def run_separator_on_segment(
    model: Any,
    mixture_audio: np.ndarray,
    sample_rate_hz: int,
    *,
    model_sample_rate_hz: int,
    input_path: Path,
) -> list[np.ndarray]:
    model_input = resample_audio(mixture_audio, sample_rate_hz, model_sample_rate_hz)
    input_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(input_path, model_input, model_sample_rate_hz, subtype=PCM_SUBTYPE)
    est_sources = model.separate_file(path=str(input_path))
    candidates_8k = candidate_sources_from_tensor(est_sources)
    return [
        resample_audio(candidate, model_sample_rate_hz, sample_rate_hz)
        for candidate in candidates_8k
    ]


def build_speechbrain_sepformer_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str,
    model_id: str,
    model_sample_rate_hz: int,
    device: str,
    model_cache_dir: Path,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    started = time.perf_counter()
    model = load_sepformer_model(model_id, device, model_cache_dir)
    model_load_ms = (time.perf_counter() - started) * 1000.0

    clip_dir = run_dir / "speechbrain_sepformer_tse_clips"
    input_dir = run_dir / "speechbrain_sepformer_inputs_8k"
    prediction_segments: list[dict[str, Any]] = []
    separation_latencies: list[float] = []

    for segment in human_segments(annotation):
        speaker_id = str(segment["speaker_id"])
        stem_audio, stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['stem_path']} sample rate mismatch")

        target_audio = segment_samples(stem_audio, segment)
        mixture_audio = segment_samples(mix_audio, segment)
        segment_started = time.perf_counter()
        candidates = run_separator_on_segment(
            model,
            mixture_audio,
            sample_rate_hz,
            model_sample_rate_hz=model_sample_rate_hz,
            input_path=input_dir / f"{speaker_id}.wav",
        )
        separation_latency_ms = (time.perf_counter() - segment_started) * 1000.0
        separation_latencies.append(separation_latency_ms)
        candidate_index, selected_audio, selection_snr_db = select_best_candidate(
            candidates,
            target_audio,
        )

        clip_path = clip_dir / f"{speaker_id}.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip_path, selected_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        prediction_segments.append(
            {
                "speaker_id": speaker_id,
                "target_speaker_id": speaker_id,
                "start_s": segment["start_s"],
                "end_s": segment["end_s"],
                "extracted_audio_path": str(clip_path.relative_to(run_dir)),
                "extracted_audio_sha256": sha256_file(clip_path),
                "source_mix_path": annotation["mix_path"],
                "reference_stem_path": segment["stem_path"],
                "input_level_dbfs": round(dbfs(mixture_audio), 3),
                "target_level_dbfs": round(dbfs(target_audio), 3),
                "output_level_dbfs": round(dbfs(selected_audio), 3),
                "overlap_s": overlap_s(annotation, segment),
                "extraction_latency_ms": round(separation_latency_ms, 3),
                "metadata": {
                    "kind": "speechbrain_sepformer_whamr_blind_separation_segment",
                    "model_id": model_id,
                    "model_sample_rate_hz": model_sample_rate_hz,
                    "candidate_count": len(candidates),
                    "selected_candidate_index": candidate_index,
                    "selection_method": "oracle_best_segment_snr_against_fixture_stem",
                    "selection_snr_db": selection_snr_db,
                    "target_condition": "oracle_assignment_after_blind_separation",
                    "source_audio": "mixed_fixture_segment",
                    "blind_separation_not_tse": True,
                    "length_aligned_to_reference": True,
                },
            }
        )

    return [
        {
            "schema_version": 1,
            "fixture_id": annotation["fixture_id"],
            "adapter_id": adapter_id,
            "segments": prediction_segments,
            "model_layer_latency_ms": {
                "model_load": round(model_load_ms, 3),
                "mean_separation_or_tse": (
                    round(sum(separation_latencies) / len(separation_latencies), 3)
                    if separation_latencies
                    else 0.0
                ),
                "max_separation_or_tse": (
                    round(max(separation_latencies), 3) if separation_latencies else 0.0
                ),
            },
            "metadata": {
                "kind": "speechbrain_sepformer_whamr_blind_separation",
                "model_id": model_id,
                "model_family": "SepFormer",
                "model_source": "https://huggingface.co/speechbrain/sepformer-whamr",
                "paper": "https://arxiv.org/abs/2010.13154",
                "license": "apache-2.0",
                "trained_dataset": "WHAMR",
                "reported_test_si_snri_db": 13.7,
                "reported_test_sdri_db": 12.7,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1",
                "blind_separation_not_tse": True,
                "oracle_assignment": "best separated stream selected against fixture stem",
                "detractor_note": (
                    "SepFormer WHAMR is a blind two-speaker separator trained on 8 kHz "
                    "WHAMR mixtures. This benchmark uses oracle fixture stems only to map "
                    "separated streams to target speakers and does not prove enrollment, "
                    "speaker locking, causal streaming, or playback suppression."
                ),
            },
        }
    ]


def comparison_gates(
    tse_report: dict[str, Any],
    passthrough_report: dict[str, Any],
) -> list[dict[str, Any]]:
    tse_summary = tse_report["summary"]
    passthrough_summary = passthrough_report["summary"]
    return [
        {
            "name": "sepformer_beats_passthrough_mean_snr",
            "value": float(tse_summary["mean_segment_snr_db"]),
            "threshold": f"> {passthrough_summary['mean_segment_snr_db']} dB passthrough mean SNR",
            "passed": float(tse_summary["mean_segment_snr_db"])
            > float(passthrough_summary["mean_segment_snr_db"]),
        },
        {
            "name": "sepformer_beats_passthrough_mean_interferer_reduction",
            "value": float(tse_summary["mean_interferer_reduction_db"]),
            "threshold": (
                f"> {passthrough_summary['mean_interferer_reduction_db']} dB "
                "passthrough mean interferer reduction"
            ),
            "passed": float(tse_summary["mean_interferer_reduction_db"])
            > float(passthrough_summary["mean_interferer_reduction_db"]),
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    prediction: dict[str, Any],
    prediction_path: Path,
) -> dict[str, Any]:
    run_dir = prediction_path.parent
    tse_report = score_tse_predictions(annotation, output_dir, prediction, run_dir)
    passthrough_run_dir = run_dir / "baselines" / "mixture_passthrough"
    passthrough_prediction = build_passthrough_tse_records(
        annotation,
        output_dir,
        passthrough_run_dir,
    )[0]
    passthrough_report = score_tse_predictions(
        annotation,
        output_dir,
        passthrough_prediction,
        passthrough_run_dir,
    )
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = tse_report["summary"]["quality_gates"] + comparison_gates(
        tse_report,
        passthrough_report,
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_speechbrain_sepformer_whamr_blind_separation",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "target_speaker_extraction": tse_report,
            "mixture_passthrough_lower_bound": passthrough_report,
        },
        "prediction_paths": {
            "target_speaker_extraction": str(prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "SepFormer WHAMR is not target-conditioned and is not causal. The oracle "
                "stream assignment used here is an evaluation convenience, so a strong score "
                "would only prove that blind separation can help this fixture, not that the "
                "runtime app can lock onto a requested speaker."
            ),
            "cheapest_falsifying_benchmark": (
                "Require the separator to beat mixture passthrough on SNR and downstream "
                "Whisper token F1 without oracle stream assignment, then repeat on longer "
                "crowd/noise fixtures with more than two active speakers."
            ),
            "fallback_if_falsified": (
                "Keep SepFormer as an offline benchmark baseline and move implementation "
                "priority to target-conditioned extraction or neural beamforming."
            ),
        },
    }


def self_test() -> dict[str, Any]:
    sample_rate_hz = 16000
    duration_s = 1.0
    samples = np.arange(int(sample_rate_hz * duration_s), dtype=np.float32) / sample_rate_hz
    target = 0.1 * np.sin(2.0 * np.pi * 220.0 * samples).astype(np.float32)
    interferer = 0.1 * np.sin(2.0 * np.pi * 330.0 * samples).astype(np.float32)
    target_8k = resample_audio(target, sample_rate_hz, DEFAULT_MODEL_SAMPLE_RATE_HZ)
    interferer_8k = resample_audio(interferer, sample_rate_hz, DEFAULT_MODEL_SAMPLE_RATE_HZ)
    fake_tensor = np.stack([interferer_8k, target_8k], axis=1)[np.newaxis, :, :]
    candidates = [
        resample_audio(candidate, DEFAULT_MODEL_SAMPLE_RATE_HZ, sample_rate_hz)
        for candidate in candidate_sources_from_tensor(fake_tensor)
    ]
    index, selected, score = select_best_candidate(candidates, target)
    if index != 1:
        raise RuntimeError("self-test expected oracle assignment to select target candidate")
    if selected.shape[0] != target.shape[0]:
        raise RuntimeError("self-test expected selected candidate to be length-aligned")
    if score < 40.0:
        raise RuntimeError("self-test expected high SNR for matching target candidate")

    padded = match_length(target[:100], 150)
    trimmed = match_length(target[:200], 150)
    if padded.shape[0] != 150 or trimmed.shape[0] != 150:
        raise RuntimeError("self-test expected match_length to pad and trim")
    return {
        "candidate_count": len(candidates),
        "selected_candidate_index": index,
        "selection_snr_db": score,
        "length_alignment": "pass",
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    tse_summary = report["benchmarks"]["target_speaker_extraction"]["summary"]
    passthrough_summary = report["benchmarks"]["mixture_passthrough_lower_bound"]["summary"]
    print(f"SpeechBrain SepFormer TSE fixture {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  separator diagnostics: "
        f"mean_snr_db={tse_summary['mean_segment_snr_db']} "
        f"mean_interferer_reduction_db={tse_summary['mean_interferer_reduction_db']} "
        f"passthrough_mean_snr_db={passthrough_summary['mean_segment_snr_db']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run SpeechBrain SepFormer WHAMR on FLEURS overlap")
    parser.add_argument("--self-test", action="store_true", help="validate separator contract helpers only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--model-sample-rate-hz", type=int, default=DEFAULT_MODEL_SAMPLE_RATE_HZ)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--model-cache-dir", type=Path, default=None)
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument(
        "--score-warning-only",
        action="store_true",
        help="write measured report but exit 0 even when separator quality gates warn",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        report = self_test()
        print("SpeechBrain SepFormer contract self-test PASS")
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
    prediction_path = run_dir / "speechbrain_sepformer_tse_predictions.jsonl"
    model_cache_dir = (
        args.model_cache_dir.resolve()
        if args.model_cache_dir
        else default_model_cache_dir(output_dir, args.model_id)
    )
    records = build_speechbrain_sepformer_tse_records(
        annotation,
        output_dir,
        run_dir,
        adapter_id=args.adapter_id,
        model_id=args.model_id,
        model_sample_rate_hz=args.model_sample_rate_hz,
        device=args.device,
        model_cache_dir=model_cache_dir,
    )
    write_jsonl(records, prediction_path)
    report = build_report(annotation, output_dir, records[0], prediction_path)
    report_path = args.report.resolve() if args.report else run_dir / "speechbrain-sepformer-tse-report.json"
    write_report(report, report_path)
    print(f"wrote SpeechBrain SepFormer TSE predictions to {prediction_path}")
    print(f"wrote SpeechBrain SepFormer TSE report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
