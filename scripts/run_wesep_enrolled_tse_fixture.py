#!/usr/bin/env python3
"""Run WeSep on enrolled target-speaker extraction fixtures.

WeSep is the first practical audio-enrollment TSE candidate for this repo:
the public demo exposes the exact shape we need, mixture audio plus enrollment
audio to extracted target speech. This runner keeps it behind the same JSONL
contract and detractor gates as the oracle/mismatch scaffolds.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

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
from benchmark_enrolled_tse_fixture import (
    DEFAULT_ENROLLMENT_DURATION_S,
    enrollment_contract_report,
    source_clip_audio,
)
from benchmark_target_speaker_extraction_fixture import (
    base_fixture_dir,
    build_passthrough_tse_records,
    human_segments,
    overlap_s,
    read_mono,
    score_tse_predictions,
    segment_samples,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    prepare_multilingual_fixture,
)


DEFAULT_RUN_ID = "fleurs-wesep-enrolled-target-speaker-extraction"
DEFAULT_ADAPTER_ID = "wesep_bsrnn_ecapa_vox1_enrolled_tse_v1"
DEFAULT_LANGUAGE = "english"
DEFAULT_MODEL_SOURCE = (
    "https://www.modelscope.cn/datasets/wenet/wesep_pretrained_models/"
    "resolve/master/bsrnn_ecapa_vox1.tar.gz"
)
DEFAULT_WESEP_REPO = "https://github.com/wenet-e2e/wesep"
DEFAULT_WESEP_PAPER = "https://arxiv.org/abs/2409.15799"
WESEP_RECOMMENDED_ENROLLMENT_S = 5.0
REAL_MODEL_MIN_SEGMENT_SNR_DB = 0.0
REAL_MODEL_MAX_LEVEL_ERROR_DB = 1.0


def match_length(samples: np.ndarray, target_len: int) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.float32)
    if samples.shape[0] == target_len:
        return samples
    if samples.shape[0] > target_len:
        return samples[:target_len]
    return np.pad(samples, (0, target_len - samples.shape[0])).astype(np.float32)


def tensor_to_mono_array(value: Any) -> np.ndarray:
    if value is None:
        return np.zeros((0,), dtype=np.float32)
    if hasattr(value, "detach"):
        value = value.detach().cpu().numpy()
    array = np.asarray(value, dtype=np.float32)
    while array.ndim > 1 and array.shape[0] == 1:
        array = array[0]
    if array.ndim > 1:
        array = np.mean(array, axis=0 if array.shape[0] <= array.shape[-1] else 1)
    return np.asarray(array, dtype=np.float32).reshape(-1)


def write_enrollment_clip(
    fixture_path: Path,
    run_dir: Path,
    segment: dict[str, Any],
    sample_rate_hz: int,
    *,
    enrollment_duration_s: float,
) -> dict[str, Any]:
    clean_audio = source_clip_audio(fixture_path, segment, sample_rate_hz)
    requested_samples = max(1, int(round(enrollment_duration_s * sample_rate_hz)))
    available_duration_s = clean_audio.shape[0] / float(sample_rate_hz)
    enrollment_audio = clean_audio[: min(clean_audio.shape[0], requested_samples)]
    clip_path = run_dir / "enrollment_clips" / f"{segment['speaker_id']}.wav"
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, enrollment_audio, sample_rate_hz, subtype=PCM_SUBTYPE)
    actual_duration_s = enrollment_audio.shape[0] / float(sample_rate_hz)
    return {
        "enrollment_audio_path": str(clip_path.relative_to(run_dir)),
        "enrollment_audio_sha256": sha256_file(clip_path),
        "enrollment_speaker_id": str(segment["speaker_id"]),
        "enrollment_duration_s": round(actual_duration_s, 6),
        "enrollment_available_duration_s": round(available_duration_s, 6),
        "enrollment_level_dbfs": round(dbfs(enrollment_audio), 3),
        "enrollment_kind": "clean_same_speaker_reference_clip",
        "enrollment_recommended_min_s": WESEP_RECOMMENDED_ENROLLMENT_S,
        "enrollment_meets_wesep_demo_recommendation": (
            actual_duration_s >= WESEP_RECOMMENDED_ENROLLMENT_S
        ),
    }


def load_wesep_model(language: str, device: str, *, output_norm: bool, apply_vad: bool) -> Any:
    try:
        import wesep
    except ImportError as exc:
        raise SystemExit(
            "WeSep runner requires the audio-eval-wesep Docker profile."
        ) from exc

    model = wesep.load_model(language)
    if hasattr(model, "set_device"):
        model.set_device(device)
    if hasattr(model, "set_output_norm"):
        model.set_output_norm(output_norm)
    if hasattr(model, "set_vad"):
        model.set_vad(apply_vad)
    return model


def extract_with_model(model: Any, mixture_path: Path, enrollment_path: Path) -> np.ndarray:
    if hasattr(model, "extract_speech"):
        return tensor_to_mono_array(model.extract_speech(str(mixture_path), str(enrollment_path)))
    raise TypeError("WeSep-like model object must expose extract_speech(mixture, enrollment)")


def postprocess_extracted_audio(
    extracted_audio: np.ndarray,
    mixture_audio: np.ndarray,
    enrollment_audio: np.ndarray,
    *,
    polarity_correction: str,
    level_normalization: str,
) -> tuple[np.ndarray, dict[str, Any]]:
    processed = np.asarray(extracted_audio, dtype=np.float32)
    mixture = np.asarray(mixture_audio[: processed.shape[0]], dtype=np.float32)
    details: dict[str, Any] = {
        "polarity_correction": polarity_correction,
        "polarity_multiplier": 1,
        "polarity_decision_source": "none",
        "level_normalization": level_normalization,
        "level_gain_db": 0.0,
        "level_target_dbfs": None,
        "peak_limiter_gain_db": 0.0,
    }

    if polarity_correction == "mixture-correlation" and processed.size and mixture.size:
        dot = float(np.dot(processed[: mixture.shape[0]], mixture))
        if dot < 0.0:
            processed = -processed
            details["polarity_multiplier"] = -1
        details["polarity_decision_source"] = "dot(extracted_audio, mixture_audio)"
        details["polarity_dot_with_mixture"] = round(dot, 9)

    if level_normalization == "enrollment-rms":
        source_rms = rms(processed)
        target_rms = rms(enrollment_audio)
        if source_rms > 1.0e-10 and target_rms > 1.0e-10:
            gain = target_rms / source_rms
            processed = (processed * gain).astype(np.float32)
            details["level_gain_db"] = round(20.0 * np.log10(gain), 3)
            details["level_target_dbfs"] = round(dbfs(enrollment_audio), 3)

    peak = float(np.max(np.abs(processed))) if processed.size else 0.0
    if peak > 0.99:
        limiter_gain = 0.99 / peak
        processed = (processed * limiter_gain).astype(np.float32)
        details["peak_limiter_gain_db"] = round(20.0 * np.log10(limiter_gain), 3)

    return processed.astype(np.float32), details


def build_wesep_enrolled_tse_records(
    annotation: dict[str, Any],
    output_dir: Path,
    run_dir: Path,
    *,
    adapter_id: str,
    language: str,
    device: str,
    enrollment_duration_s: float,
    output_norm: bool,
    apply_vad: bool,
    polarity_correction: str,
    level_normalization: str,
    model: Any | None = None,
) -> list[dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    started = time.perf_counter()
    model = model or load_wesep_model(
        language,
        device,
        output_norm=output_norm,
        apply_vad=apply_vad,
    )
    model_load_ms = (time.perf_counter() - started) * 1000.0

    clip_dir = run_dir / "wesep_enrolled_tse_clips"
    input_dir = run_dir / "wesep_inputs"
    prediction_segments: list[dict[str, Any]] = []
    extraction_latencies: list[float] = []
    enrollment_durations: list[float] = []

    for segment in human_segments(annotation):
        speaker_id = str(segment["speaker_id"])
        stem_audio, stem_rate_hz = read_mono(fixture_path / segment["stem_path"])
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['stem_path']} sample rate mismatch")

        target_audio = segment_samples(stem_audio, segment)
        mixture_audio = segment_samples(mix_audio, segment)
        input_path = input_dir / f"{speaker_id}_mixture.wav"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(input_path, mixture_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        enrollment = write_enrollment_clip(
            fixture_path,
            run_dir,
            segment,
            sample_rate_hz,
            enrollment_duration_s=enrollment_duration_s,
        )
        enrollment_durations.append(float(enrollment["enrollment_duration_s"]))
        enrollment_path = run_dir / str(enrollment["enrollment_audio_path"])
        enrollment_audio, enrollment_rate_hz = read_mono(enrollment_path)
        if enrollment_rate_hz != sample_rate_hz:
            raise ValueError(f"{enrollment_path} sample rate mismatch")

        segment_started = time.perf_counter()
        extracted_audio = extract_with_model(model, input_path, enrollment_path)
        extraction_latency_ms = (time.perf_counter() - segment_started) * 1000.0
        extraction_latencies.append(extraction_latency_ms)
        extracted_audio = match_length(extracted_audio, int(target_audio.shape[0]))
        extracted_audio, postprocess = postprocess_extracted_audio(
            extracted_audio,
            mixture_audio,
            enrollment_audio,
            polarity_correction=polarity_correction,
            level_normalization=level_normalization,
        )

        clip_path = clip_dir / f"{speaker_id}.wav"
        clip_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(clip_path, extracted_audio, sample_rate_hz, subtype=PCM_SUBTYPE)

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
                "output_level_dbfs": round(dbfs(extracted_audio), 3),
                "overlap_s": overlap_s(annotation, segment),
                "extraction_latency_ms": round(extraction_latency_ms, 3),
                **enrollment,
                "metadata": {
                    "kind": "wesep_enrolled_target_speaker_extraction_segment",
                    "model_family": "WeSep",
                    "language": language,
                    "device": device,
                    "target_condition": "clean_audio_enrollment",
                    "enrollment_same_speaker": True,
                    "same_utterance_enrollment_caveat": True,
                    "source_audio": "mixed_fixture_segment",
                    "output_norm": output_norm,
                    "apply_vad": apply_vad,
                    "postprocess": postprocess,
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
                    round(sum(extraction_latencies) / len(extraction_latencies), 3)
                    if extraction_latencies
                    else 0.0
                ),
                "max_separation_or_tse": (
                    round(max(extraction_latencies), 3) if extraction_latencies else 0.0
                ),
            },
            "metadata": {
                "kind": "wesep_enrolled_target_speaker_extraction",
                "model_family": "WeSep",
                "language": language,
                "model_id": "bsrnn_ecapa_vox1",
                "model_source": DEFAULT_MODEL_SOURCE,
                "repo": DEFAULT_WESEP_REPO,
                "paper": DEFAULT_WESEP_PAPER,
                "fixture_kind": "fleurs_multilingual_overlap",
                "contract": "target-speaker extraction JSONL v1 plus enrollment fields",
                "target_condition": "clean_audio_enrollment",
                "enrollment_duration_s": enrollment_duration_s,
                "min_actual_enrollment_duration_s": (
                    round(min(enrollment_durations), 6) if enrollment_durations else 0.0
                ),
                "recommended_enrollment_duration_s": WESEP_RECOMMENDED_ENROLLMENT_S,
                "output_norm": output_norm,
                "apply_vad": apply_vad,
                "postprocess": {
                    "polarity_correction": polarity_correction,
                    "level_normalization": level_normalization,
                    "uses_reference_stems": False,
                    "polarity_decision_source": "mixture_audio",
                    "level_reference_source": "enrollment_audio",
                },
                "detractor_note": (
                    "The public WeSep demo recommends enrollment longer than 5 seconds. "
                    "This fixture uses same-utterance clean source clips and some clips may "
                    "be shorter than that recommendation, so warnings must be interpreted as "
                    "model and fixture evidence rather than final product performance."
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
            "name": "wesep_beats_passthrough_mean_snr",
            "value": float(tse_summary["mean_segment_snr_db"]),
            "threshold": f"> {passthrough_summary['mean_segment_snr_db']} dB passthrough mean SNR",
            "passed": float(tse_summary["mean_segment_snr_db"])
            > float(passthrough_summary["mean_segment_snr_db"]),
        },
        {
            "name": "wesep_beats_passthrough_mean_interferer_reduction",
            "value": float(tse_summary["mean_interferer_reduction_db"]),
            "threshold": (
                f"> {passthrough_summary['mean_interferer_reduction_db']} dB "
                "passthrough mean interferer reduction"
            ),
            "passed": float(tse_summary["mean_interferer_reduction_db"])
            > float(passthrough_summary["mean_interferer_reduction_db"]),
        },
    ]


def real_model_acceptance_gates(
    tse_report: dict[str, Any],
    enrollment_report: dict[str, Any],
    passthrough_report: dict[str, Any],
    prediction: dict[str, Any],
) -> list[dict[str, Any]]:
    tse_summary = tse_report["summary"]
    passthrough_summary = passthrough_report["summary"]
    metadata = prediction.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    postprocess = metadata.get("postprocess", {})
    postprocess = postprocess if isinstance(postprocess, dict) else {}
    enrollment_gates = enrollment_report["summary"].get("quality_gates", [])
    enrollment_passed = all(bool(gate.get("passed")) for gate in enrollment_gates)
    return [
        {
            "name": "tse_real_model_not_oracle",
            "value": {
                "kind": metadata.get("kind"),
                "oracle_upper_bound": bool(metadata.get("oracle_upper_bound", False)),
                "negative_control": bool(metadata.get("negative_control", False)),
            },
            "threshold": "real model output, not oracle upper bound or negative control",
            "passed": not bool(metadata.get("oracle_upper_bound", False))
            and not bool(metadata.get("negative_control", False)),
        },
        {
            "name": "tse_real_model_enrollment_contract_passed",
            "value": bool(enrollment_passed),
            "threshold": "all enrollment metadata/path/hash gates pass",
            "passed": bool(enrollment_passed),
        },
        {
            "name": "tse_real_model_postprocess_declared",
            "value": postprocess,
            "threshold": "runtime-available postprocess; no reference stems",
            "passed": (
                postprocess.get("polarity_correction") == "mixture-correlation"
                and postprocess.get("level_normalization") == "enrollment-rms"
                and postprocess.get("uses_reference_stems") is False
            ),
        },
        {
            "name": "tse_real_model_beats_passthrough_mean_snr",
            "value": float(tse_summary["mean_segment_snr_db"]),
            "threshold": f"> {passthrough_summary['mean_segment_snr_db']} dB passthrough mean SNR",
            "passed": float(tse_summary["mean_segment_snr_db"])
            > float(passthrough_summary["mean_segment_snr_db"]),
        },
        {
            "name": "tse_real_model_beats_passthrough_mean_interferer_reduction",
            "value": float(tse_summary["mean_interferer_reduction_db"]),
            "threshold": (
                f"> {passthrough_summary['mean_interferer_reduction_db']} dB "
                "passthrough mean interferer reduction"
            ),
            "passed": float(tse_summary["mean_interferer_reduction_db"])
            > float(passthrough_summary["mean_interferer_reduction_db"]),
        },
        {
            "name": "tse_real_model_min_segment_snr_floor",
            "value": float(tse_summary["min_segment_snr_db"]),
            "threshold": f">= {REAL_MODEL_MIN_SEGMENT_SNR_DB} dB minimum segment SNR",
            "passed": float(tse_summary["min_segment_snr_db"]) >= REAL_MODEL_MIN_SEGMENT_SNR_DB,
        },
        {
            "name": "tse_real_model_output_level_preserved",
            "value": float(tse_summary["max_abs_level_error_db"]),
            "threshold": f"<= {REAL_MODEL_MAX_LEVEL_ERROR_DB} dB max absolute level error",
            "passed": float(tse_summary["max_abs_level_error_db"]) <= REAL_MODEL_MAX_LEVEL_ERROR_DB,
        },
        {
            "name": "tse_real_model_polarity_invariant_scoring_declared",
            "value": {
                "enabled": bool(tse_summary.get("polarity_invariant_scoring")),
                "inverted_segment_count": int(tse_summary.get("polarity_inverted_segment_count", 0)),
            },
            "threshold": "global waveform polarity handled in scorer",
            "passed": bool(tse_summary.get("polarity_invariant_scoring")),
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
    enrollment_report = enrollment_contract_report(
        prediction,
        run_dir,
        expect_mismatches=False,
    )
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
    real_model_gates = real_model_acceptance_gates(
        tse_report,
        enrollment_report,
        passthrough_report,
        prediction,
    )
    gates = (
        tse_report["summary"]["quality_gates"]
        + enrollment_report["summary"]["quality_gates"]
        + comparison_gates(tse_report, passthrough_report)
        + real_model_gates
    )
    real_model_passed = all(bool(gate["passed"]) for gate in real_model_gates)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_wesep_enrolled_target_speaker_extraction",
        "output_dir": str(output_dir),
        "summary": {
            "passed": real_model_passed,
            "fixture_count": 1,
            "oracle_quality_passed": all(
                bool(gate["passed"]) for gate in tse_report["summary"]["quality_gates"]
            ),
            "real_model_release_candidate_passed": real_model_passed,
            "quality_gates": gates,
        },
        "benchmarks": {
            "target_speaker_extraction": tse_report,
            "enrollment_contract": enrollment_report,
            "mixture_passthrough_lower_bound": passthrough_report,
        },
        "prediction_paths": {
            "target_speaker_extraction": str(prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": prediction["metadata"],
        "detractor_loop": {
            "strongest_objection": (
                "A runnable enrollment-conditioned model can still fail the actual product if "
                "the enrollment is too short, noisy, same-utterance, non-English, or if the model "
                "normalizes output loudness in a way the playback mixer cannot repair."
            ),
            "cheapest_falsifying_benchmark": (
                "Require WeSep to beat mixture passthrough on the FLEURS overlap fixture and then "
                "repeat on a longer same-speaker enrollment fixture before playback integration."
            ),
            "fallback_if_falsified": (
                "Keep WeSep as a comparator and test longer-enrollment candidates such as LLaSE-G1 "
                "or a positive/negative enrollment method before voice-cloned playback."
            ),
        },
    }


class FakeWesepModel:
    def extract_speech(self, mixture_path: str, enrollment_path: str) -> np.ndarray:
        del enrollment_path
        audio, _sample_rate_hz = read_mono(Path(mixture_path))
        return audio * 0.5


def self_test() -> dict[str, Any]:
    sample_rate_hz = 16000
    duration_s = 2.0
    samples = np.arange(int(sample_rate_hz * duration_s), dtype=np.float32) / sample_rate_hz
    speaker_a = 0.12 * np.sin(2.0 * np.pi * 220.0 * samples).astype(np.float32)
    speaker_b = 0.08 * np.sin(2.0 * np.pi * 330.0 * samples).astype(np.float32)
    stem_a = np.zeros_like(samples)
    stem_b = np.zeros_like(samples)
    stem_a[: int(1.4 * sample_rate_hz)] = speaker_a[: int(1.4 * sample_rate_hz)]
    stem_b[int(0.6 * sample_rate_hz) :] = speaker_b[int(0.6 * sample_rate_hz) :]
    mix = stem_a + stem_b

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir) / "audio_eval"
        annotation = {
            "schema_version": 1,
            "fixture_set_id": "self-test-wesep-tse",
            "fixture_id": "self_test_wesep_tse_overlap",
            "description": "self-test WeSep enrolled target speaker extraction fixture",
            "sample_rate_hz": sample_rate_hz,
            "duration_s": duration_s,
            "mix_path": "mix.wav",
            "mix_sha256": "",
            "stems": [],
            "background_noise_dbfs": None,
            "source_license": "generated self-test",
            "source_url": None,
            "detractor_note": "self-test only",
            "segments": [
                {
                    "index": 0,
                    "speaker_id": "speaker_a",
                    "source_kind": "human",
                    "language_code": "en-US",
                    "voice_profile": "self_test_a",
                    "start_s": 0.0,
                    "end_s": 1.4,
                    "start_sample": 0,
                    "end_sample": int(1.4 * sample_rate_hz),
                    "level_dbfs": -21.0,
                    "stem_path": "stems/speaker_a.wav",
                    "source_clip_path": "source_clips/speaker_a.wav",
                },
                {
                    "index": 1,
                    "speaker_id": "speaker_b",
                    "source_kind": "human",
                    "language_code": "es-419",
                    "voice_profile": "self_test_b",
                    "start_s": 0.6,
                    "end_s": 2.0,
                    "start_sample": int(0.6 * sample_rate_hz),
                    "end_sample": int(2.0 * sample_rate_hz),
                    "level_dbfs": -24.0,
                    "stem_path": "stems/speaker_b.wav",
                    "source_clip_path": "source_clips/speaker_b.wav",
                },
            ],
        }
        target_dir = base_fixture_dir(output_dir, annotation)
        (target_dir / "stems").mkdir(parents=True, exist_ok=True)
        (target_dir / "source_clips").mkdir(parents=True, exist_ok=True)
        sf.write(target_dir / "mix.wav", mix, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_a.wav", stem_a, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(target_dir / "stems" / "speaker_b.wav", stem_b, sample_rate_hz, subtype=PCM_SUBTYPE)
        sf.write(
            target_dir / "source_clips" / "speaker_a.wav",
            speaker_a[: int(1.4 * sample_rate_hz)],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        sf.write(
            target_dir / "source_clips" / "speaker_b.wav",
            speaker_b[int(0.6 * sample_rate_hz) :],
            sample_rate_hz,
            subtype=PCM_SUBTYPE,
        )
        annotation["mix_sha256"] = sha256_file(target_dir / "mix.wav")
        annotation["stems"] = [
            {
                "track_id": "speaker_a",
                "path": "stems/speaker_a.wav",
                "sha256": sha256_file(target_dir / "stems" / "speaker_a.wav"),
            },
            {
                "track_id": "speaker_b",
                "path": "stems/speaker_b.wav",
                "sha256": sha256_file(target_dir / "stems" / "speaker_b.wav"),
            },
        ]

        run_dir = output_dir / "runs" / "self-test-wesep-enrolled"
        prediction_path = run_dir / "wesep_enrolled_tse_predictions.jsonl"
        record = build_wesep_enrolled_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=DEFAULT_ADAPTER_ID,
            language=DEFAULT_LANGUAGE,
            device="cpu",
            enrollment_duration_s=DEFAULT_ENROLLMENT_DURATION_S,
            output_norm=False,
            apply_vad=False,
            polarity_correction="mixture-correlation",
            level_normalization="enrollment-rms",
            model=FakeWesepModel(),
        )[0]
        write_jsonl([record], prediction_path)
        report = build_report(annotation, output_dir, record, prediction_path)
        enrollment_summary = report["benchmarks"]["enrollment_contract"]["summary"]
        if int(enrollment_summary["enrollment_path_count"]) != 2:
            raise RuntimeError("self-test expected enrollment paths for both speakers")
        if int(report["benchmarks"]["target_speaker_extraction"]["summary"]["prediction_count"]) != 2:
            raise RuntimeError("self-test expected extracted clips for both speakers")
        return {
            "prediction_count": report["benchmarks"]["target_speaker_extraction"]["summary"][
                "prediction_count"
            ],
            "enrollment_path_count": enrollment_summary["enrollment_path_count"],
            "quality_gate_count": len(report["summary"]["quality_gates"]),
        }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    tse_summary = report["benchmarks"]["target_speaker_extraction"]["summary"]
    passthrough_summary = report["benchmarks"]["mixture_passthrough_lower_bound"]["summary"]
    enrollment_summary = report["benchmarks"]["enrollment_contract"]["summary"]
    print(f"WeSep enrolled target-speaker extraction {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  WeSep diagnostics: "
        f"mean_snr_db={tse_summary['mean_segment_snr_db']} "
        f"mean_interferer_reduction_db={tse_summary['mean_interferer_reduction_db']} "
        f"passthrough_mean_snr_db={passthrough_summary['mean_segment_snr_db']} "
        f"enrollment_mismatches={enrollment_summary['mismatched_enrollment_count']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run WeSep on enrolled FLEURS overlap TSE")
    parser.add_argument("--self-test", action="store_true", help="validate WeSep contract helpers only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--language", default=DEFAULT_LANGUAGE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--enrollment-duration-s", type=float, default=WESEP_RECOMMENDED_ENROLLMENT_S)
    parser.add_argument("--output-norm", action="store_true")
    parser.add_argument("--apply-vad", action="store_true")
    parser.add_argument(
        "--polarity-correction",
        choices=["none", "mixture-correlation"],
        default="mixture-correlation",
    )
    parser.add_argument(
        "--level-normalization",
        choices=["none", "enrollment-rms"],
        default="enrollment-rms",
    )
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
        report = self_test()
        print("WeSep enrolled target-speaker extraction contract self-test PASS")
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
    prediction_path = run_dir / "wesep_enrolled_tse_predictions.jsonl"
    records = build_wesep_enrolled_tse_records(
        annotation,
        output_dir,
        run_dir,
        adapter_id=args.adapter_id,
        language=args.language,
        device=args.device,
        enrollment_duration_s=args.enrollment_duration_s,
        output_norm=args.output_norm,
        apply_vad=args.apply_vad,
        polarity_correction=args.polarity_correction,
        level_normalization=args.level_normalization,
    )
    write_jsonl(records, prediction_path)
    report = build_report(annotation, output_dir, records[0], prediction_path)
    report_path = args.report.resolve() if args.report else run_dir / "wesep-enrolled-tse-report.json"
    write_report(report, report_path)
    print(f"wrote WeSep enrolled TSE predictions to {prediction_path}")
    print(f"wrote WeSep enrolled TSE report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


if __name__ == "__main__":
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    raise SystemExit(main())
