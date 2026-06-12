#!/usr/bin/env python3
"""Run a host real-room playback/suppression loopback benchmark.

This script uses PortAudio through sounddevice because Docker cannot reliably
access Windows speakers and microphones. It plays known source-speech and
translated-fallback references through the host output device, records the room
with the host microphone, and writes the release-gate report for measured source
residual and translated-output distortion.

The benchmark is intentionally conservative. It only passes when measured source
residual reduction clears the configured threshold; otherwise it writes a report
that says suppression is unavailable instead of pretending cancellation worked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "real-room-playback-suppression"
DEFAULT_DEVICE_QUALIFICATION_RUN_ID = "real-room-device-qualification"
DEFAULT_DEVICE_SWEEP_RUN_ID = "real-room-device-sweep"
DEFAULT_ROUTE_PROBE_RUN_ID = "real-room-route-probe"
DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID = "real-room-route-probe-sweep"
DEFAULT_ADAPTER_ID = "host_portaudio_stereo_antiphase_room_loopback_v1"
DEFAULT_DEVICE_QUALIFICATION_ADAPTER_ID = "host_portaudio_room_reference_qualification_v1"
DEFAULT_DEVICE_SWEEP_ADAPTER_ID = "host_portaudio_room_reference_device_sweep_v1"
DEFAULT_ROUTE_PROBE_ADAPTER_ID = "host_portaudio_route_probe_sentinel_v1"
DEFAULT_ROUTE_PROBE_SWEEP_ADAPTER_ID = "host_portaudio_route_probe_sentinel_sweep_v1"
DEFAULT_TTS_REPORT = (
    DEFAULT_OUTPUT_DIR / "runs/same-voice-tts/voice-clone-report.json"
)
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_GAP_S = 0.35
DEFAULT_PLAYBACK_GAIN_DB = -18.0
DEFAULT_CANCEL_GAIN = "auto"
DEFAULT_MIN_SOURCE_REDUCTION_DB = 6.0
DEFAULT_MIN_TRANSLATED_CORRELATION = 0.30
DEFAULT_MAX_TRANSLATED_DISTORTION_DB = 12.0
DEFAULT_MIN_ROOM_CALIBRATION_DBFS = -60.0
DEFAULT_MIN_CALIBRATION_CORRELATION = 0.30
DEFAULT_MAX_CALIBRATION_DISTORTION_DB = 12.0
DEFAULT_MAX_ALIGNMENT_LAG_MS = 500.0
DEFAULT_MAX_PEAK_DBFS = -0.1
DEFAULT_QUALIFICATION_MAX_REFERENCE_DURATION_S = 0.0
DEFAULT_SWEEP_MAX_REFERENCE_DURATION_S = 3.0
DEFAULT_SWEEP_MAX_PAIRS = 12
DEFAULT_ROUTE_PROBE_DURATION_S = 2.0
DEFAULT_ROUTE_PROBE_SWEEP_SAMPLE_RATES = (DEFAULT_SAMPLE_RATE_HZ, 48000)
DEFAULT_ROUTE_PROBE_SWEEP_CHANNEL_CONFIGS = ((1, 2), (2, 2))
DEFAULT_ROUTE_PROBE_SWEEP_MAX_ATTEMPTS = 24
DEFAULT_MIN_ROUTE_PROBE_CONFIDENCE = 0.45
DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB = 18.0
PCM_SUBTYPE = "PCM_16"
MEASUREMENT_KIND = "real_room_loopback"
SUPPRESSION_CLAIM_TRUE = "true_source_cancellation"
SUPPRESSION_CLAIM_UNAVAILABLE = "suppression_unavailable_measured"


def import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised on hosts without PortAudio deps.
        raise RuntimeError("Install sounddevice to run host room loopback checks") from exc
    return sd


def db_to_linear(db_value: float) -> float:
    return float(10.0 ** (db_value / 20.0))


def linear_to_db(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return float(20.0 * math.log10(value))


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def dbfs(samples: np.ndarray) -> float:
    return linear_to_db(rms(samples))


def peak_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return float("-inf")
    return linear_to_db(float(np.max(np.abs(samples))))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return "".join(char if char in allowed else "_" for char in value)


def read_mono_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate_hz = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"{path} must be PCM_16 WAV for this host runner")
    audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1).astype(np.float32)
    return audio.astype(np.float32), int(sample_rate_hz)


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(samples, -1.0, 1.0)
    pcm = np.round(clipped * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm.tobytes())


def resample_to_rate(audio: np.ndarray, source_rate_hz: int, target_rate_hz: int) -> np.ndarray:
    if source_rate_hz == target_rate_hz:
        return audio.astype(np.float32)
    try:
        from scipy.signal import resample_poly
    except ImportError as exc:
        raise RuntimeError("scipy is required when WAV sample rates need resampling") from exc
    gcd = math.gcd(int(source_rate_hz), int(target_rate_hz))
    return resample_poly(audio, int(target_rate_hz // gcd), int(source_rate_hz // gcd)).astype(
        np.float32
    )


def scale_to_peak_limit(samples: np.ndarray, max_peak_dbfs: float) -> np.ndarray:
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    limit = db_to_linear(max_peak_dbfs)
    if peak > limit:
        return (samples * (limit / peak)).astype(np.float32)
    return samples.astype(np.float32)


def list_devices() -> int:
    sd = import_sounddevice()
    print(sd.query_devices())
    return 0


def device_path_fingerprint(
    device_info: dict[str, Any],
    *,
    sample_rate_hz: int,
    input_channels: int,
    output_channels: int = 2,
) -> str:
    payload = {
        "device": device_info,
        "input_channels": int(input_channels),
        "output_channels": int(output_channels),
        "sample_rate_hz": int(sample_rate_hz),
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def device_path_identity_recorded(
    device_info: dict[str, Any],
    *,
    input_channels: int,
    output_channels: int = 2,
) -> bool:
    input_device = device_info.get("input_device", {})
    output_device = device_info.get("output_device", {})
    if not isinstance(input_device, dict) or not isinstance(output_device, dict):
        return False
    required = ("name", "hostapi", "hostapi_name", "max_input_channels", "max_output_channels")
    for key in required:
        if input_device.get(key) is None or output_device.get(key) is None:
            return False
    try:
        if int(input_device.get("max_input_channels", 0)) < int(input_channels):
            return False
        if int(output_device.get("max_output_channels", 0)) < int(output_channels):
            return False
    except (TypeError, ValueError):
        return False
    return True


def load_tts_segments(report_path: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    benchmark = report.get("benchmarks", {}).get("same_voice_or_fallback_tts", {})
    segments = benchmark.get("segments", []) if isinstance(benchmark, dict) else []
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"{report_path} does not contain fallback TTS segments")
    return [segment for segment in segments if isinstance(segment, dict)]


def resolve_report_path(report_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty artifact path")
    path = Path(value)
    if path.is_absolute():
        return path
    beside = report_path.parent / path
    if beside.exists():
        return beside
    return path


def build_reference_tracks(
    tts_report_path: Path,
    sample_rate_hz: int,
    gap_s: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    source_parts: list[np.ndarray] = []
    translated_parts: list[np.ndarray] = []
    gap = np.zeros(max(0, int(round(gap_s * sample_rate_hz))), dtype=np.float32)
    segment_records: list[dict[str, Any]] = []
    cursor = 0
    for index, segment in enumerate(load_tts_segments(tts_report_path)):
        source_path = resolve_report_path(tts_report_path, segment.get("reference_audio_path"))
        translated_path = resolve_report_path(tts_report_path, segment.get("tts_output_path"))
        source_audio, source_rate_hz = read_mono_wav(source_path)
        translated_audio, translated_rate_hz = read_mono_wav(translated_path)
        source_audio = resample_to_rate(source_audio, source_rate_hz, sample_rate_hz)
        translated_audio = resample_to_rate(translated_audio, translated_rate_hz, sample_rate_hz)
        frame_count = max(int(source_audio.size), int(translated_audio.size))
        source_window = np.zeros(frame_count, dtype=np.float32)
        translated_window = np.zeros(frame_count, dtype=np.float32)
        source_window[: source_audio.size] = source_audio
        translated_window[: translated_audio.size] = translated_audio
        source_parts.append(source_window)
        translated_parts.append(translated_window)
        source_parts.append(gap)
        translated_parts.append(gap)
        segment_records.append(
            {
                "segment_index": index,
                "speaker_id": segment.get("speaker_id"),
                "source_language_code": segment.get("source_language_code"),
                "target_language_code": "en",
                "translated_text": segment.get("translated_text"),
                "start_sample": cursor,
                "end_sample": cursor + frame_count,
                "source_reference_path": str(source_path),
                "translated_reference_path": str(translated_path),
                "source_reference_sha256": sha256_file(source_path),
                "translated_reference_sha256": sha256_file(translated_path),
            }
        )
        cursor += frame_count + gap.size
    source_track = np.concatenate(source_parts) if source_parts else np.zeros(0, dtype=np.float32)
    translated_track = (
        np.concatenate(translated_parts) if translated_parts else np.zeros(0, dtype=np.float32)
    )
    return source_track.astype(np.float32), translated_track.astype(np.float32), segment_records


def limit_reference_duration(
    source_track: np.ndarray,
    translated_track: np.ndarray,
    segments: list[dict[str, Any]],
    *,
    sample_rate_hz: int,
    max_duration_s: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]], float]:
    if max_duration_s <= 0.0:
        duration_s = max(float(source_track.size), float(translated_track.size)) / float(sample_rate_hz)
        return source_track, translated_track, segments, duration_s
    max_samples = max(1, int(round(float(max_duration_s) * float(sample_rate_hz))))
    limited_segments: list[dict[str, Any]] = []
    for segment in segments:
        start_sample = int(segment.get("start_sample", 0))
        end_sample = int(segment.get("end_sample", 0))
        if start_sample >= max_samples:
            continue
        clipped = dict(segment)
        clipped["end_sample"] = min(end_sample, max_samples)
        if end_sample > max_samples:
            clipped["truncated_for_triage"] = True
        limited_segments.append(clipped)
    duration_s = max(float(min(source_track.size, max_samples)), float(min(translated_track.size, max_samples))) / float(
        sample_rate_hz
    )
    return (
        source_track[:max_samples].astype(np.float32),
        translated_track[:max_samples].astype(np.float32),
        limited_segments,
        duration_s,
    )


def stereo(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    frame_count = max(int(left.size), int(right.size))
    out = np.zeros((frame_count, 2), dtype=np.float32)
    out[: left.size, 0] = left
    out[: right.size, 1] = right
    return out


def mono_playback(samples: np.ndarray, channels: int = 2) -> np.ndarray:
    channel_count = max(1, int(channels))
    mono = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
    return np.repeat(mono, channel_count, axis=1).astype(np.float32)


def record_playback(
    playback: np.ndarray,
    *,
    sample_rate_hz: int,
    input_device: int | str | None,
    output_device: int | str | None,
    input_channels: int,
) -> tuple[np.ndarray, float]:
    sd = import_sounddevice()
    device = (input_device, output_device)
    start = time.perf_counter()
    recording = sd.playrec(
        playback,
        samplerate=sample_rate_hz,
        channels=input_channels,
        dtype="float32",
        device=device,
        blocking=True,
    )
    elapsed_s = time.perf_counter() - start
    if getattr(recording, "ndim", 1) > 1:
        recording = recording.mean(axis=1)
    return np.asarray(recording, dtype=np.float32), elapsed_s


def projection_gain(target: np.ndarray, reference: np.ndarray) -> float:
    frame_count = min(int(target.size), int(reference.size))
    if frame_count <= 0:
        return 0.0
    target = target[:frame_count].astype(np.float64)
    reference = reference[:frame_count].astype(np.float64)
    denominator = float(np.dot(reference, reference))
    if denominator <= 1.0e-12:
        return 0.0
    return float(np.dot(target, reference) / denominator)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    frame_count = min(int(a.size), int(b.size))
    if frame_count <= 1:
        return 0.0
    x = a[:frame_count].astype(np.float64)
    y = b[:frame_count].astype(np.float64)
    x = x - float(np.mean(x))
    y = y - float(np.mean(y))
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denominator <= 1.0e-12:
        return 0.0
    return float(np.dot(x, y) / denominator)


def distortion_db(measured: np.ndarray, reference: np.ndarray) -> float:
    frame_count = min(int(measured.size), int(reference.size))
    if frame_count <= 0:
        return float("inf")
    measured = measured[:frame_count]
    reference = reference[:frame_count]
    gain = projection_gain(measured, reference)
    aligned = reference * gain
    error = measured - aligned
    return linear_to_db((rms(error) + 1.0e-12) / (rms(aligned) + 1.0e-12))


def align_pair(a: np.ndarray, b: np.ndarray, lag_samples: int) -> tuple[np.ndarray, np.ndarray]:
    frame_count = min(int(a.size), int(b.size))
    if frame_count <= 0:
        return a[:0], b[:0]
    if lag_samples > 0:
        lag = min(lag_samples, frame_count)
        count = min(int(a.size) - lag, int(b.size))
        return a[lag : lag + count], b[:count]
    if lag_samples < 0:
        lag = min(-lag_samples, frame_count)
        count = min(int(a.size), int(b.size) - lag)
        return a[:count], b[lag : lag + count]
    count = frame_count
    return a[:count], b[:count]


def best_alignment_lag_samples(
    measured: np.ndarray,
    reference: np.ndarray,
    sample_rate_hz: int,
    max_lag_ms: float,
    *,
    stride: int = 64,
) -> int:
    max_lag_samples = max(0, int(round(float(sample_rate_hz) * float(max_lag_ms) / 1000.0)))
    frame_count = min(int(measured.size), int(reference.size))
    if frame_count <= stride * 2 or max_lag_samples <= 0:
        return 0
    x = measured[:frame_count:stride].astype(np.float64)
    y = reference[:frame_count:stride].astype(np.float64)
    x -= float(np.mean(x))
    y -= float(np.mean(y))
    max_lag_steps = min(max_lag_samples // stride, max(0, min(x.size, y.size) - 2))
    best_lag_steps = 0
    best_score = float("-inf")
    for lag_steps in range(-max_lag_steps, max_lag_steps + 1):
        if lag_steps > 0:
            a = x[lag_steps:]
            b = y[: a.size]
        elif lag_steps < 0:
            a = x[: x.size + lag_steps]
            b = y[-lag_steps : -lag_steps + a.size]
        else:
            a = x
            b = y[: a.size]
        if a.size <= 1:
            continue
        denominator = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
        if denominator <= 1.0e-12:
            continue
        score = abs(float(np.dot(a, b) / denominator))
        if score > best_score:
            best_score = score
            best_lag_steps = lag_steps
    return int(best_lag_steps * stride)


def quality_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    reduction = float(summary["source_residual_reduction_db"])
    distortion = float(summary["translated_output_distortion_db"])
    translated_corr = float(summary["translated_output_correlation"])
    source_calibration = float(summary["source_calibration_dbfs"])
    translated_calibration = float(summary["translated_reference_dbfs"])
    source_calibration_corr = float(summary["source_calibration_reference_correlation"])
    source_calibration_distortion = float(summary["source_calibration_reference_distortion_db"])
    translated_calibration_corr = float(summary["translated_calibration_reference_correlation"])
    translated_calibration_distortion = float(summary["translated_calibration_reference_distortion_db"])
    hashes = bool(summary["all_artifact_hashes_present"])
    claim = summary["suppression_claim"]
    device_identity = bool(summary["device_path_identity_recorded"])
    device_fingerprint = str(summary["device_path_fingerprint"])
    source_ok = math.isfinite(reduction) and reduction >= float(args.min_source_reduction_db)
    translated_ok = (
        math.isfinite(distortion)
        and distortion <= float(args.max_translated_distortion_db)
        and translated_corr >= float(args.min_translated_correlation)
    )
    calibration_ok = (
        math.isfinite(source_calibration)
        and math.isfinite(translated_calibration)
        and source_calibration >= float(args.min_room_calibration_dbfs)
        and translated_calibration >= float(args.min_room_calibration_dbfs)
    )
    calibration_fidelity_ok = (
        math.isfinite(source_calibration_distortion)
        and math.isfinite(translated_calibration_distortion)
        and source_calibration_distortion <= float(args.max_calibration_distortion_db)
        and translated_calibration_distortion <= float(args.max_calibration_distortion_db)
        and source_calibration_corr >= float(args.min_calibration_correlation)
        and translated_calibration_corr >= float(args.min_calibration_correlation)
    )
    return [
        {
            "name": "room_loopback_recorded",
            "passed": bool(summary["room_loopback_recorded"]),
            "threshold": "host speaker playback captured by host microphone",
            "value": summary["room_loopback_recorded"],
        },
        {
            "name": "device_path_identity_recorded",
            "passed": device_identity and len(device_fingerprint) == 64,
            "threshold": "input/output device identity, channels, sample rate, and fingerprint recorded",
            "value": {
                "device_path_fingerprint": device_fingerprint,
                "device_path_identity_recorded": device_identity,
            },
        },
        {
            "name": "calibration_recordings_audible",
            "passed": calibration_ok,
            "threshold": (
                f"source and translated calibration recordings >= "
                f"{float(args.min_room_calibration_dbfs):.3f} dBFS"
            ),
            "value": {
                "source_calibration_dbfs": source_calibration,
                "translated_reference_dbfs": translated_calibration,
            },
        },
        {
            "name": "calibration_reference_fidelity",
            "passed": calibration_fidelity_ok,
            "threshold": (
                f"calibration/reference correlation >= {float(args.min_calibration_correlation):.3f} "
                f"and distortion <= {float(args.max_calibration_distortion_db):.3f} dB"
            ),
            "value": {
                "source_calibration_reference_correlation": source_calibration_corr,
                "source_calibration_reference_distortion_db": source_calibration_distortion,
                "translated_calibration_reference_correlation": translated_calibration_corr,
                "translated_calibration_reference_distortion_db": translated_calibration_distortion,
            },
        },
        {
            "name": "source_residual_measured",
            "passed": source_ok,
            "threshold": f">= {float(args.min_source_reduction_db):.3f} dB residual reduction",
            "value": reduction,
        },
        {
            "name": "translated_output_not_distorted",
            "passed": translated_ok,
            "threshold": (
                f"distortion <= {float(args.max_translated_distortion_db):.3f} dB and "
                f"correlation >= {float(args.min_translated_correlation):.3f}"
            ),
            "value": {
                "translated_output_correlation": translated_corr,
                "translated_output_distortion_db": distortion,
            },
        },
        {
            "name": "suppression_claim_matches_measurement",
            "passed": (
                (
                    claim == SUPPRESSION_CLAIM_TRUE
                    and source_ok
                    and translated_ok
                    and calibration_ok
                    and calibration_fidelity_ok
                )
                or (
                    claim == SUPPRESSION_CLAIM_UNAVAILABLE
                    and not (source_ok and translated_ok and calibration_ok and calibration_fidelity_ok)
                )
            ),
            "threshold": (
                "claim must match measured source residual reduction, translated-output "
                "preservation, and calibration fidelity"
            ),
            "value": {
                "source_residual_reduction_db": reduction,
                "suppression_claim": claim,
                "translated_output_correlation": translated_corr,
                "translated_output_distortion_db": distortion,
            },
        },
        {
            "name": "room_suppression_artifacts_hashed",
            "passed": hashes,
            "threshold": "all room loopback WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
    ]


def calibration_reference_metrics(
    recording: np.ndarray,
    reference: np.ndarray,
    sample_rate_hz: int,
    max_lag_ms: float,
) -> dict[str, float | int]:
    lag_samples = best_alignment_lag_samples(recording, reference, sample_rate_hz, max_lag_ms)
    aligned_recording, aligned_reference = align_pair(recording, reference, lag_samples)
    return {
        "correlation": round(correlation(aligned_recording, aligned_reference), 6),
        "distortion_db": round(distortion_db(aligned_recording, aligned_reference), 3),
        "lag_samples": lag_samples,
        "recording_dbfs": round(dbfs(recording), 3),
    }


def build_route_probe_signal(sample_rate_hz: int, duration_s: float) -> np.ndarray:
    frame_count = max(1, int(round(float(sample_rate_hz) * float(duration_s))))
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    sweep_duration = max(float(duration_s), 1.0 / float(sample_rate_hz))
    start_hz = 350.0
    end_hz = min(4200.0, float(sample_rate_hz) * 0.42)
    slope = (end_hz - start_hz) / sweep_duration
    phase = 2.0 * math.pi * (start_hz * t + 0.5 * slope * t * t)
    signal = np.sin(phase).astype(np.float32)
    fade_samples = min(frame_count // 2, max(1, int(round(0.035 * float(sample_rate_hz)))))
    if fade_samples > 1:
        ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        signal[:fade_samples] *= ramp
        signal[-fade_samples:] *= ramp[::-1]
    return signal.astype(np.float32)


def route_probe_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    confidence = float(summary["route_probe_reference_confidence"])
    distortion = float(summary["route_probe_reference_distortion_db"])
    level = float(summary["route_probe_recording_dbfs"])
    clipped = int(summary["route_probe_clipped_sample_count"])
    hashes = bool(summary["all_artifact_hashes_present"])
    reference_clone = bool(summary.get("route_probe_recording_matches_reference"))
    device_identity = bool(summary["device_path_identity_recorded"])
    device_fingerprint = str(summary["device_path_fingerprint"])
    audible = math.isfinite(level) and level >= float(args.min_room_calibration_dbfs)
    confidence_ok = math.isfinite(confidence) and confidence >= float(args.min_route_probe_confidence)
    distortion_ok = math.isfinite(distortion) and distortion <= float(args.max_route_probe_distortion_db)
    return [
        {
            "name": "route_probe_device_identity_recorded",
            "passed": device_identity and len(device_fingerprint) == 64,
            "threshold": "input/output device identity, channels, sample rate, and fingerprint recorded",
            "value": {
                "device_path_fingerprint": device_fingerprint,
                "device_path_identity_recorded": device_identity,
            },
        },
        {
            "name": "route_probe_recording_audible",
            "passed": audible,
            "threshold": f"recording >= {float(args.min_room_calibration_dbfs):.3f} dBFS",
            "value": level,
        },
        {
            "name": "route_probe_reference_confident",
            "passed": confidence_ok,
            "threshold": f"matched reference confidence >= {float(args.min_route_probe_confidence):.3f}",
            "value": confidence,
        },
        {
            "name": "route_probe_distortion_bounded",
            "passed": distortion_ok,
            "threshold": f"distortion <= {float(args.max_route_probe_distortion_db):.3f} dB",
            "value": distortion,
        },
        {
            "name": "route_probe_not_clipped",
            "passed": clipped == 0,
            "threshold": "no PCM samples at full-scale clipping",
            "value": clipped,
        },
        {
            "name": "route_probe_artifacts_hashed",
            "passed": hashes,
            "threshold": "route probe reference and recording WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "route_probe_recording_not_reference_clone",
            "passed": not reference_clone,
            "threshold": "recording artifact must not be byte-identical to the generated reference",
            "value": reference_clone,
        },
    ]


def device_qualification_gates(
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    source_level = float(summary["source_calibration_dbfs"])
    translated_level = float(summary["translated_reference_dbfs"])
    source_corr = float(summary["source_calibration_reference_correlation"])
    source_distortion = float(summary["source_calibration_reference_distortion_db"])
    translated_corr = float(summary["translated_calibration_reference_correlation"])
    translated_distortion = float(summary["translated_calibration_reference_distortion_db"])
    hashes = bool(summary["all_artifact_hashes_present"])
    device_identity = bool(summary["device_path_identity_recorded"])
    device_fingerprint = str(summary["device_path_fingerprint"])
    audible = (
        math.isfinite(source_level)
        and math.isfinite(translated_level)
        and source_level >= float(args.min_room_calibration_dbfs)
        and translated_level >= float(args.min_room_calibration_dbfs)
    )
    source_fidelity = (
        math.isfinite(source_distortion)
        and source_distortion <= float(args.max_calibration_distortion_db)
        and source_corr >= float(args.min_calibration_correlation)
    )
    translated_fidelity = (
        math.isfinite(translated_distortion)
        and translated_distortion <= float(args.max_calibration_distortion_db)
        and translated_corr >= float(args.min_calibration_correlation)
    )
    return [
        {
            "name": "device_path_identity_recorded",
            "passed": device_identity and len(device_fingerprint) == 64,
            "threshold": "input/output device identity, channels, sample rate, and fingerprint recorded",
            "value": {
                "device_path_fingerprint": device_fingerprint,
                "device_path_identity_recorded": device_identity,
            },
        },
        {
            "name": "device_calibration_recordings_audible",
            "passed": audible,
            "threshold": (
                f"source and translated calibration recordings >= "
                f"{float(args.min_room_calibration_dbfs):.3f} dBFS"
            ),
            "value": {
                "source_calibration_dbfs": source_level,
                "translated_reference_dbfs": translated_level,
            },
        },
        {
            "name": "device_source_reference_fidelity",
            "passed": source_fidelity,
            "threshold": (
                f"source calibration/reference correlation >= "
                f"{float(args.min_calibration_correlation):.3f} and distortion <= "
                f"{float(args.max_calibration_distortion_db):.3f} dB"
            ),
            "value": {
                "source_calibration_reference_correlation": source_corr,
                "source_calibration_reference_distortion_db": source_distortion,
            },
        },
        {
            "name": "device_translated_reference_fidelity",
            "passed": translated_fidelity,
            "threshold": (
                f"translated calibration/reference correlation >= "
                f"{float(args.min_calibration_correlation):.3f} and distortion <= "
                f"{float(args.max_calibration_distortion_db):.3f} dB"
            ),
            "value": {
                "translated_calibration_reference_correlation": translated_corr,
                "translated_calibration_reference_distortion_db": translated_distortion,
            },
        },
        {
            "name": "device_reference_fidelity_passed",
            "passed": source_fidelity and translated_fidelity,
            "threshold": "source and translated references are preserved by the device path",
            "value": {
                "source_reference_fidelity_passed": source_fidelity,
                "translated_reference_fidelity_passed": translated_fidelity,
            },
        },
        {
            "name": "device_qualification_artifacts_hashed",
            "passed": hashes,
            "threshold": "all qualification WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
    ]


def run_device_qualification(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rate_hz = int(args.sample_rate_hz)
    source_track, translated_track, segments = build_reference_tracks(
        Path(args.tts_report),
        sample_rate_hz,
        float(args.gap_s),
    )
    source_track, translated_track, segments, reference_duration_s = limit_reference_duration(
        source_track,
        translated_track,
        segments,
        sample_rate_hz=sample_rate_hz,
        max_duration_s=float(args.max_reference_duration_s),
    )
    gain = db_to_linear(float(args.playback_gain_db))
    source_track = scale_to_peak_limit(source_track * gain, float(args.max_peak_dbfs))
    translated_track = scale_to_peak_limit(translated_track * gain, float(args.max_peak_dbfs))

    source_reference_path = run_dir / "source_reference_playback.wav"
    translated_reference_path = run_dir / "translated_reference_playback.wav"
    write_mono_wav(source_reference_path, source_track, sample_rate_hz)
    write_mono_wav(translated_reference_path, translated_track, sample_rate_hz)

    input_device = parse_device(args.input_device)
    output_device = parse_device(args.output_device)
    device_info = {
        "input_device": device_snapshot(sd, input_device, input=True),
        "output_device": device_snapshot(sd, output_device, input=False),
    }
    fingerprint = device_path_fingerprint(
        device_info,
        sample_rate_hz=sample_rate_hz,
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )

    print("Playing source reference for device-path qualification...")
    source_recording, source_elapsed_s = record_playback(
        mono_playback(source_track, int(args.output_channels)),
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )
    time.sleep(float(args.pause_s))
    print("Playing translated reference for device-path qualification...")
    translated_recording, translated_elapsed_s = record_playback(
        mono_playback(translated_track, int(args.output_channels)),
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )

    source_recording_path = run_dir / "source_only_room_recording.wav"
    translated_recording_path = run_dir / "translated_only_room_recording.wav"
    write_mono_wav(source_recording_path, source_recording, sample_rate_hz)
    write_mono_wav(translated_recording_path, translated_recording, sample_rate_hz)

    source_metrics = calibration_reference_metrics(
        source_recording,
        source_track,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    translated_metrics = calibration_reference_metrics(
        translated_recording,
        translated_track,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    artifact_paths = {
        "source_only_room_recording": str(source_recording_path),
        "source_reference": str(source_reference_path),
        "translated_only_room_recording": str(translated_recording_path),
        "translated_playback_reference": str(translated_reference_path),
    }
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "device_path_fingerprint": fingerprint,
        "device_path_identity_recorded": device_path_identity_recorded(
            device_info,
            input_channels=int(args.input_channels),
            output_channels=int(args.output_channels),
        ),
        "input_channels": int(args.input_channels),
        "max_alignment_lag_ms": float(args.max_alignment_lag_ms),
        "measurement_kind": "real_room_device_qualification",
        "max_reference_duration_s": float(args.max_reference_duration_s),
        "output_channels": int(args.output_channels),
        "playback_gain_db": float(args.playback_gain_db),
        "reference_duration_s": round(reference_duration_s, 3),
        "sample_rate_hz": sample_rate_hz,
        "source_calibration_dbfs": source_metrics["recording_dbfs"],
        "source_calibration_reference_correlation": source_metrics["correlation"],
        "source_calibration_reference_distortion_db": source_metrics["distortion_db"],
        "source_calibration_reference_lag_samples": source_metrics["lag_samples"],
        "source_elapsed_s": round(source_elapsed_s, 3),
        "translated_calibration_reference_correlation": translated_metrics["correlation"],
        "translated_calibration_reference_distortion_db": translated_metrics["distortion_db"],
        "translated_calibration_reference_lag_samples": translated_metrics["lag_samples"],
        "translated_elapsed_s": round(translated_elapsed_s, 3),
        "translated_reference_dbfs": translated_metrics["recording_dbfs"],
    }
    gates = device_qualification_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_room_device_qualification",
        "measurement_kind": "real_room_device_qualification",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "release_proof": False,
            "quality_gates": gates,
        },
        "benchmarks": {
            "room_device_qualification": {
                "adapter_id": args.adapter_id,
                "device": device_info,
                "segments": segments,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "detractor_loop": {
            "strongest_objection": (
                "This qualification only proves whether the device path can preserve known "
                "playback references. It does not prove source cancellation."
            ),
            "verdict": (
                "Run this before real-room suppression checks; failing device qualification means "
                "the selected input/output path is not suitable for release evidence."
            ),
        },
    }
    report_path = run_dir / "room-device-qualification-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"real-room device qualification {status}: "
        f"source_corr={summary['source_calibration_reference_correlation']}, "
        f"translated_corr={summary['translated_calibration_reference_correlation']}"
    )
    print(f"wrote real-room device qualification report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def run_route_probe(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rate_hz = int(args.sample_rate_hz)
    reference = build_route_probe_signal(sample_rate_hz, float(args.duration_s))
    gain = db_to_linear(float(args.playback_gain_db))
    reference = scale_to_peak_limit(reference * gain, float(args.max_peak_dbfs))
    reference_path = run_dir / "route_probe_reference.wav"
    write_mono_wav(reference_path, reference, sample_rate_hz)

    input_device = parse_device(args.input_device)
    output_device = parse_device(args.output_device)
    device_info = {
        "input_device": device_snapshot(sd, input_device, input=True),
        "output_device": device_snapshot(sd, output_device, input=False),
    }
    fingerprint = device_path_fingerprint(
        device_info,
        sample_rate_hz=sample_rate_hz,
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )

    print("Playing route probe sentinel for input/output path validation...")
    try:
        recording, elapsed_s = record_playback(
            mono_playback(reference, int(args.output_channels)),
            sample_rate_hz=sample_rate_hz,
            input_device=input_device,
            output_device=output_device,
            input_channels=int(args.input_channels),
        )
    except Exception as exc:  # pragma: no cover - depends on host device failures.
        artifact_paths = {"route_probe_reference": str(reference_path)}
        artifact_hashes = {"route_probe_reference": sha256_file(reference_path)}
        summary = {
            "all_artifact_hashes_present": False,
            "device_path_fingerprint": fingerprint,
            "device_path_identity_recorded": device_path_identity_recorded(
                device_info,
                input_channels=int(args.input_channels),
                output_channels=int(args.output_channels),
            ),
            "duration_s": float(args.duration_s),
            "error": str(exc),
            "input_channels": int(args.input_channels),
            "measurement_kind": "real_room_route_probe_triage",
            "output_channels": int(args.output_channels),
            "playback_gain_db": float(args.playback_gain_db),
            "release_proof": False,
            "sample_rate_hz": sample_rate_hz,
        }
        gates = [
            {
                "name": "route_probe_stream_opened",
                "passed": False,
                "threshold": "PortAudio duplex stream opens for selected input/output route",
                "value": str(exc),
            }
        ]
        report = {
            "schema_version": 1,
            "generated_at_unix": int(time.time()),
            "fixture_kind": "real_room_route_probe",
            "measurement_kind": "real_room_route_probe_triage",
            "output_dir": str(args.output_dir),
            "release_proof": False,
            "summary": {
                "passed": False,
                "quality_gates": gates,
                "release_proof": False,
            },
            "benchmarks": {
                "room_route_probe": {
                    "adapter_id": args.adapter_id,
                    "device": device_info,
                    "summary": summary,
                }
            },
            "artifact_paths": artifact_paths,
            "artifact_hashes": artifact_hashes,
            "detractor_loop": {
                "strongest_objection": "The selected host route could not open as a duplex stream.",
                "verdict": "Choose another input/output route before speech qualification.",
            },
        }
        report_path = run_dir / "route-probe-report.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"real-room route probe ERROR: {exc}")
        print(f"wrote real-room route probe report to {report_path}")
        return 0 if args.score_warning_only else 1
    recording_path = run_dir / "route_probe_recording.wav"
    write_mono_wav(recording_path, recording, sample_rate_hz)

    metrics = calibration_reference_metrics(
        recording,
        reference,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    lag_samples = int(metrics["lag_samples"])
    aligned_recording, aligned_reference = align_pair(recording, reference, lag_samples)
    gain_value = projection_gain(aligned_recording, aligned_reference)
    confidence = abs(float(metrics["correlation"]))
    clipped_sample_count = int(np.sum(np.abs(recording) >= 0.999969))
    artifact_paths = {
        "route_probe_recording": str(recording_path),
        "route_probe_reference": str(reference_path),
    }
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "device_path_fingerprint": fingerprint,
        "device_path_identity_recorded": device_path_identity_recorded(
            device_info,
            input_channels=int(args.input_channels),
            output_channels=int(args.output_channels),
        ),
        "duration_s": float(args.duration_s),
        "elapsed_s": round(elapsed_s, 3),
        "input_channels": int(args.input_channels),
        "max_alignment_lag_ms": float(args.max_alignment_lag_ms),
        "measurement_kind": "real_room_route_probe_triage",
        "output_channels": int(args.output_channels),
        "playback_gain_db": float(args.playback_gain_db),
        "release_proof": False,
        "route_probe_clipped_sample_count": clipped_sample_count,
        "route_probe_gain_db": round(linear_to_db(abs(gain_value)), 3)
        if gain_value != 0.0
        else float("-inf"),
        "route_probe_lag_samples": lag_samples,
        "route_probe_lag_ms": round(lag_samples * 1000.0 / float(sample_rate_hz), 3),
        "route_probe_peak_dbfs": round(peak_dbfs(recording), 3),
        "route_probe_recording_dbfs": metrics["recording_dbfs"],
        "route_probe_recording_matches_reference": (
            artifact_hashes.get("route_probe_recording")
            == artifact_hashes.get("route_probe_reference")
        ),
        "route_probe_reference_confidence": round(confidence, 6),
        "route_probe_reference_correlation": metrics["correlation"],
        "route_probe_reference_distortion_db": metrics["distortion_db"],
        "sample_rate_hz": sample_rate_hz,
    }
    gates = route_probe_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_room_route_probe",
        "measurement_kind": "real_room_route_probe_triage",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": False,
        },
        "benchmarks": {
            "room_route_probe": {
                "adapter_id": args.adapter_id,
                "device": device_info,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "detractor_loop": {
            "strongest_objection": (
                "A chirp route probe can pass while speech still fails under AGC, noise "
                "suppression, or echo processing."
            ),
            "verdict": (
                "Use this only before speech qualification. It proves route sanity, not "
                "translated playback quality or source cancellation."
            ),
        },
    }
    report_path = run_dir / "route-probe-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"real-room route probe {status}: "
        f"confidence={summary['route_probe_reference_confidence']}, "
        f"lag_ms={summary['route_probe_lag_ms']}"
    )
    print(f"wrote real-room route probe report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def run_check(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rate_hz = int(args.sample_rate_hz)
    source_track, translated_track, segments = build_reference_tracks(
        Path(args.tts_report),
        sample_rate_hz,
        float(args.gap_s),
    )
    gain = db_to_linear(float(args.playback_gain_db))
    source_track = scale_to_peak_limit(source_track * gain, float(args.max_peak_dbfs))
    translated_track = scale_to_peak_limit(translated_track * gain, float(args.max_peak_dbfs))

    source_reference_path = run_dir / "source_reference_playback.wav"
    translated_reference_path = run_dir / "translated_reference_playback.wav"
    write_mono_wav(source_reference_path, source_track, sample_rate_hz)
    write_mono_wav(translated_reference_path, translated_track, sample_rate_hz)

    input_device = parse_device(args.input_device)
    output_device = parse_device(args.output_device)
    device_info = {
        "input_device": device_snapshot(sd, input_device, input=True),
        "output_device": device_snapshot(sd, output_device, input=False),
    }
    fingerprint = device_path_fingerprint(
        device_info,
        sample_rate_hz=sample_rate_hz,
        input_channels=int(args.input_channels),
        output_channels=2,
    )

    print("Playing source reference for room calibration...")
    source_left_recording, source_left_elapsed_s = record_playback(
        stereo(source_track, np.zeros_like(source_track)),
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )
    time.sleep(float(args.pause_s))
    print("Playing opposite-channel source reference for cancellation calibration...")
    source_right_recording, source_right_elapsed_s = record_playback(
        stereo(np.zeros_like(source_track), source_track),
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )
    time.sleep(float(args.pause_s))
    print("Playing translated reference for room distortion calibration...")
    translated_recording, translated_elapsed_s = record_playback(
        mono_playback(translated_track),
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )
    time.sleep(float(args.pause_s))
    cancel_gain = resolve_cancel_gain(args.cancel_gain, source_left_recording, source_right_recording)
    print("Playing stereo source plus anti-source translated loopback...")
    cancellation_playback = stereo(
        source_track + translated_track * 0.5,
        translated_track * 0.5 - source_track * cancel_gain,
    )
    cancellation_playback = scale_to_peak_limit(cancellation_playback, float(args.max_peak_dbfs))
    cancellation_recording, cancellation_elapsed_s = record_playback(
        cancellation_playback,
        sample_rate_hz=sample_rate_hz,
        input_device=input_device,
        output_device=output_device,
        input_channels=int(args.input_channels),
    )

    source_recording_path = run_dir / "source_only_room_recording.wav"
    source_right_recording_path = run_dir / "source_opposite_channel_room_recording.wav"
    translated_recording_path = run_dir / "translated_only_room_recording.wav"
    loopback_recording_path = run_dir / "room_loopback_recording.wav"
    cancellation_playback_path = run_dir / "stereo_cancellation_playback_render.wav"
    write_mono_wav(source_recording_path, source_left_recording, sample_rate_hz)
    write_mono_wav(source_right_recording_path, source_right_recording, sample_rate_hz)
    write_mono_wav(translated_recording_path, translated_recording, sample_rate_hz)
    write_mono_wav(loopback_recording_path, cancellation_recording, sample_rate_hz)
    write_mono_wav(cancellation_playback_path, cancellation_playback.mean(axis=1), sample_rate_hz)

    source_alignment_lag_samples = best_alignment_lag_samples(
        cancellation_recording,
        source_left_recording,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    aligned_cancellation, aligned_source = align_pair(
        cancellation_recording,
        source_left_recording,
        source_alignment_lag_samples,
    )
    raw_residual_gain = projection_gain(aligned_cancellation, aligned_source)
    residual_gain = abs(raw_residual_gain)
    source_reduction_db = -linear_to_db(residual_gain) if residual_gain > 0.0 else 120.0
    source_residual_estimate = aligned_source * raw_residual_gain
    translated_component = aligned_cancellation - source_residual_estimate
    translated_alignment_lag_samples = best_alignment_lag_samples(
        translated_component,
        translated_recording,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    aligned_translated_component, aligned_translated_recording = align_pair(
        translated_component,
        translated_recording,
        translated_alignment_lag_samples,
    )
    translated_corr = correlation(aligned_translated_component, aligned_translated_recording)
    translated_distortion_db = distortion_db(aligned_translated_component, aligned_translated_recording)
    source_calibration_reference_lag_samples = best_alignment_lag_samples(
        source_left_recording,
        source_track,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    aligned_source_recording, aligned_source_reference = align_pair(
        source_left_recording,
        source_track,
        source_calibration_reference_lag_samples,
    )
    translated_calibration_reference_lag_samples = best_alignment_lag_samples(
        translated_recording,
        translated_track,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    aligned_translated_recording_ref, aligned_translated_reference = align_pair(
        translated_recording,
        translated_track,
        translated_calibration_reference_lag_samples,
    )
    source_residual_dbfs = dbfs(source_residual_estimate)
    source_calibration_dbfs = dbfs(source_left_recording)
    translated_reference_dbfs = dbfs(translated_recording)
    source_ok = source_reduction_db >= float(args.min_source_reduction_db)
    translated_ok = (
        translated_distortion_db <= float(args.max_translated_distortion_db)
        and translated_corr >= float(args.min_translated_correlation)
    )
    source_calibration_corr = correlation(aligned_source_recording, aligned_source_reference)
    source_calibration_distortion = distortion_db(aligned_source_recording, aligned_source_reference)
    translated_calibration_corr = correlation(
        aligned_translated_recording_ref,
        aligned_translated_reference,
    )
    translated_calibration_distortion = distortion_db(
        aligned_translated_recording_ref,
        aligned_translated_reference,
    )
    calibration_ok = (
        source_calibration_dbfs >= float(args.min_room_calibration_dbfs)
        and translated_reference_dbfs >= float(args.min_room_calibration_dbfs)
    )
    calibration_fidelity_ok = (
        source_calibration_distortion <= float(args.max_calibration_distortion_db)
        and translated_calibration_distortion <= float(args.max_calibration_distortion_db)
        and source_calibration_corr >= float(args.min_calibration_correlation)
        and translated_calibration_corr >= float(args.min_calibration_correlation)
    )
    suppression_claim = (
        SUPPRESSION_CLAIM_TRUE
        if source_ok and translated_ok and calibration_ok and calibration_fidelity_ok
        else SUPPRESSION_CLAIM_UNAVAILABLE
    )

    artifact_paths = {
        "cancellation_playback_render": str(cancellation_playback_path),
        "room_loopback_recording": str(loopback_recording_path),
        "source_only_room_recording": str(source_recording_path),
        "source_opposite_channel_room_recording": str(source_right_recording_path),
        "source_reference": str(source_reference_path),
        "translated_only_room_recording": str(translated_recording_path),
        "translated_playback_reference": str(translated_reference_path),
    }
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "cancel_gain": round(cancel_gain, 6),
        "cancel_gain_mode": str(args.cancel_gain),
        "device_path_fingerprint": fingerprint,
        "device_path_identity_recorded": device_path_identity_recorded(
            device_info,
            input_channels=int(args.input_channels),
            output_channels=2,
        ),
        "input_channels": int(args.input_channels),
        "measurement_kind": MEASUREMENT_KIND,
        "output_channels": 2,
        "playback_gain_db": float(args.playback_gain_db),
        "room_loopback_recorded": True,
        "sample_rate_hz": sample_rate_hz,
        "source_calibration_dbfs": round(source_calibration_dbfs, 3),
        "source_calibration_reference_correlation": round(source_calibration_corr, 6),
        "source_calibration_reference_distortion_db": round(source_calibration_distortion, 3),
        "source_calibration_reference_lag_samples": source_calibration_reference_lag_samples,
        "source_residual_dbfs": round(source_residual_dbfs, 3),
        "source_residual_gain": round(residual_gain, 6),
        "source_residual_reduction_db": round(source_reduction_db, 3),
        "suppression_claim": suppression_claim,
        "translated_audio_is_surrogate": False,
        "translated_calibration_reference_correlation": round(translated_calibration_corr, 6),
        "translated_calibration_reference_distortion_db": round(translated_calibration_distortion, 3),
        "translated_calibration_reference_lag_samples": translated_calibration_reference_lag_samples,
        "translated_output_correlation": round(translated_corr, 6),
        "translated_output_distortion_db": round(translated_distortion_db, 3),
        "translated_reference_dbfs": round(translated_reference_dbfs, 3),
        "source_elapsed_s": round(source_left_elapsed_s, 3),
        "source_opposite_channel_elapsed_s": round(source_right_elapsed_s, 3),
        "translated_elapsed_s": round(translated_elapsed_s, 3),
        "loopback_elapsed_s": round(cancellation_elapsed_s, 3),
        "max_alignment_lag_ms": float(args.max_alignment_lag_ms),
        "source_alignment_lag_samples": source_alignment_lag_samples,
        "translated_alignment_lag_samples": translated_alignment_lag_samples,
    }
    gates = quality_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_room_playback_suppression",
        "output_dir": str(args.output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
        },
        "benchmarks": {
            "room_playback_suppression": {
                "adapter_id": args.adapter_id,
                "device": device_info,
                "segments": segments,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "detractor_loop": {
            "strongest_objection": (
                "This is a constrained loudspeaker/microphone loopback with known source reference. "
                "It does not prove arbitrary live-human voice cancellation in all listener positions."
            ),
            "verdict": (
                "Pass only means this host/device/room measured enough residual reduction for the "
                "configured loopback. Failures must fall back to translated overlay diagnostics."
            ),
        },
    }
    report_path = run_dir / "room-playback-suppression-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"real-room playback suppression {status}: "
        f"source_reduction={summary['source_residual_reduction_db']} dB, "
        f"translated_corr={summary['translated_output_correlation']}"
    )
    print(f"wrote real-room playback suppression report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def parse_device(value: str | None) -> int | str | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return value


def parse_pair(value: str) -> tuple[str, str]:
    for separator in (":", ","):
        if separator in value:
            left, right = value.split(separator, 1)
            left = left.strip()
            right = right.strip()
            if left and right:
                return left, right
    raise argparse.ArgumentTypeError("device pair must be INPUT:OUTPUT, for example 12:10")


def parse_channel_config(value: str) -> tuple[int, int]:
    for separator in (":", ","):
        if separator in value:
            left, right = value.split(separator, 1)
            try:
                input_channels = int(left.strip())
                output_channels = int(right.strip())
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    "channel config must be INPUT:OUTPUT, for example 1:2"
                ) from exc
            if input_channels > 0 and output_channels > 0:
                return input_channels, output_channels
    raise argparse.ArgumentTypeError("channel config must be INPUT:OUTPUT, for example 1:2")


def hostapi_name(sd: Any, hostapi_index: Any) -> str | None:
    if hostapi_index is None:
        return None
    try:
        return sd.query_hostapis(hostapi_index).get("name")
    except Exception:  # pragma: no cover - host API metadata is best-effort diagnostics.
        return None


def hostapi_matches(info: dict[str, Any], name: str | None, filters: list[str]) -> bool:
    if not filters:
        return True
    hostapi_index = str(info.get("hostapi", "")).lower()
    hostapi_label = (name or "").lower()
    return any(item.lower() in {hostapi_index, hostapi_label} or item.lower() in hostapi_label for item in filters)


def candidate_device_pairs(
    sd: Any,
    *,
    input_channels: int,
    output_channels: int,
    hostapis: list[str],
    include_cross_hostapi: bool,
    max_pairs: int,
) -> list[dict[str, Any]]:
    devices = list(enumerate(sd.query_devices()))
    inputs: list[tuple[int, dict[str, Any], str | None]] = []
    outputs: list[tuple[int, dict[str, Any], str | None]] = []
    for index, info in devices:
        if not isinstance(info, dict):
            continue
        api_name = hostapi_name(sd, info.get("hostapi"))
        if not hostapi_matches(info, api_name, hostapis):
            continue
        if int(info.get("max_input_channels") or 0) >= int(input_channels):
            inputs.append((index, info, api_name))
        if int(info.get("max_output_channels") or 0) >= int(output_channels):
            outputs.append((index, info, api_name))

    try:
        default_input, default_output = sd.default.device
    except Exception:  # pragma: no cover - defensive host diagnostic.
        default_input, default_output = None, None

    def api_rank(name: str | None) -> int:
        label = (name or "").lower()
        if "wasapi" in label:
            return 0
        if "directsound" in label:
            return 1
        if "mme" in label:
            return 2
        if "wdm" in label:
            return 3
        return 4

    pairs: list[dict[str, Any]] = []
    for input_index, input_info, input_api_name in inputs:
        for output_index, output_info, output_api_name in outputs:
            if not include_cross_hostapi and input_info.get("hostapi") != output_info.get("hostapi"):
                continue
            pairs.append(
                {
                    "input_device": input_index,
                    "input_name": input_info.get("name"),
                    "input_hostapi": input_info.get("hostapi"),
                    "input_hostapi_name": input_api_name,
                    "output_device": output_index,
                    "output_name": output_info.get("name"),
                    "output_hostapi": output_info.get("hostapi"),
                    "output_hostapi_name": output_api_name,
                    "source": "auto",
                }
            )

    pairs.sort(
        key=lambda item: (
            0 if item["input_device"] == default_input and item["output_device"] == default_output else 1,
            api_rank(item.get("input_hostapi_name")),
            item.get("input_hostapi_name") != item.get("output_hostapi_name"),
            str(item.get("input_name") or ""),
            str(item.get("output_name") or ""),
        )
    )
    if max_pairs > 0:
        return pairs[:max_pairs]
    return pairs


def device_snapshot(sd: Any, device: int | str | None, *, input: bool) -> dict[str, Any]:
    try:
        if device is None:
            index = sd.default.device[0 if input else 1]
            info = sd.query_devices(index)
        else:
            index = device if isinstance(device, int) else None
            info = sd.query_devices(device)
        hostapi_index = info.get("hostapi")
        hostapi = sd.query_hostapis(hostapi_index) if hostapi_index is not None else {}
    except Exception as exc:  # pragma: no cover - defensive host diagnostic.
        return {"error": str(exc), "requested_device": device}
    return {
        "default_samplerate": info.get("default_samplerate"),
        "default": device is None,
        "default_high_input_latency": info.get("default_high_input_latency"),
        "default_high_output_latency": info.get("default_high_output_latency"),
        "default_low_input_latency": info.get("default_low_input_latency"),
        "default_low_output_latency": info.get("default_low_output_latency"),
        "hostapi": info.get("hostapi"),
        "hostapi_name": hostapi.get("name"),
        "max_input_channels": info.get("max_input_channels"),
        "max_output_channels": info.get("max_output_channels"),
        "name": info.get("name"),
        "requested_device": device,
        "resolved_device_index": index,
    }


def report_float(value: Any, digits: int = 6) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


def route_probe_attempt_metrics(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    sample_rate_hz = max(1, int(summary.get("sample_rate_hz") or args.sample_rate_hz))
    lag_ms = (
        abs(float(summary.get("route_probe_lag_samples", 0))) * 1000.0 / sample_rate_hz
    )
    level = float(summary.get("route_probe_recording_dbfs", float("-inf")))
    confidence = float(summary.get("route_probe_reference_confidence", float("-inf")))
    correlation_value = float(summary.get("route_probe_reference_correlation", float("-inf")))
    distortion = float(summary.get("route_probe_reference_distortion_db", float("inf")))
    peak = float(summary.get("route_probe_peak_dbfs", float("-inf")))
    clipped = int(summary.get("route_probe_clipped_sample_count") or 0)
    return {
        "device_path_fingerprint": summary.get("device_path_fingerprint"),
        "input_channels": int(summary.get("input_channels") or args.input_channels),
        "lag_ms": report_float(lag_ms, 3),
        "margin_to_threshold": {
            "recording_level_db": report_float(
                level - float(args.min_room_calibration_dbfs),
                3,
            ),
            "reference_confidence": report_float(
                confidence - float(args.min_route_probe_confidence),
                6,
            ),
            "reference_distortion_db": report_float(
                float(args.max_route_probe_distortion_db) - distortion,
                3,
            ),
            "alignment_lag_ms": report_float(float(args.max_alignment_lag_ms) - lag_ms, 3),
            "clipped_samples": report_float(-float(clipped), 3),
        },
        "output_channels": int(summary.get("output_channels") or args.output_channels),
        "route_probe_clipped_sample_count": clipped,
        "route_probe_gain_db": report_float(summary.get("route_probe_gain_db"), 3),
        "route_probe_lag_samples": int(summary.get("route_probe_lag_samples") or 0),
        "route_probe_peak_dbfs": report_float(peak, 3),
        "route_probe_recording_dbfs": report_float(level, 3),
        "route_probe_recording_matches_reference": bool(
            summary.get("route_probe_recording_matches_reference")
        ),
        "route_probe_reference_confidence": report_float(confidence, 6),
        "route_probe_reference_correlation": report_float(correlation_value, 6),
        "route_probe_reference_distortion_db": report_float(distortion, 3),
        "sample_rate_hz": sample_rate_hz,
    }


def route_probe_score(metrics: dict[str, Any]) -> float:
    margins = metrics.get("margin_to_threshold", {})
    score = 0.0
    confidence = metrics.get("route_probe_reference_confidence")
    if isinstance(confidence, (int, float)):
        score += float(confidence) * 20.0
    for value in margins.values():
        if isinstance(value, (int, float)):
            score += max(-100.0, min(100.0, float(value)))
    return score


def qualification_attempt_metrics(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    sample_rate_hz = max(1, int(summary.get("sample_rate_hz") or args.sample_rate_hz))
    source_lag_ms = abs(float(summary.get("source_calibration_reference_lag_samples", 0))) * 1000.0 / sample_rate_hz
    translated_lag_ms = (
        abs(float(summary.get("translated_calibration_reference_lag_samples", 0))) * 1000.0 / sample_rate_hz
    )
    max_lag_ms = max(source_lag_ms, translated_lag_ms)
    source_level = float(summary.get("source_calibration_dbfs", float("-inf")))
    translated_level = float(summary.get("translated_reference_dbfs", float("-inf")))
    source_corr = float(summary.get("source_calibration_reference_correlation", float("-inf")))
    translated_corr = float(summary.get("translated_calibration_reference_correlation", float("-inf")))
    source_distortion = float(summary.get("source_calibration_reference_distortion_db", float("inf")))
    translated_distortion = float(
        summary.get("translated_calibration_reference_distortion_db", float("inf"))
    )
    return {
        "device_path_fingerprint": summary.get("device_path_fingerprint"),
        "input_channels": int(summary.get("input_channels") or args.input_channels),
        "lag_ms": {
            "source": report_float(source_lag_ms, 3),
            "translated": report_float(translated_lag_ms, 3),
            "worst": report_float(max_lag_ms, 3),
        },
        "margin_to_threshold": {
            "source_level_db": report_float(source_level - float(args.min_room_calibration_dbfs), 3),
            "translated_level_db": report_float(
                translated_level - float(args.min_room_calibration_dbfs), 3
            ),
            "source_correlation": report_float(
                source_corr - float(args.min_calibration_correlation), 6
            ),
            "translated_correlation": report_float(
                translated_corr - float(args.min_calibration_correlation), 6
            ),
            "source_distortion_db": report_float(
                float(args.max_calibration_distortion_db) - source_distortion, 3
            ),
            "translated_distortion_db": report_float(
                float(args.max_calibration_distortion_db) - translated_distortion, 3
            ),
            "alignment_lag_ms": report_float(float(args.max_alignment_lag_ms) - max_lag_ms, 3),
        },
        "output_channels": int(summary.get("output_channels") or args.output_channels),
        "sample_rate_hz": sample_rate_hz,
        "source_calibration_dbfs": report_float(source_level, 3),
        "source_calibration_reference_correlation": report_float(source_corr, 6),
        "source_calibration_reference_distortion_db": report_float(source_distortion, 3),
        "translated_calibration_reference_correlation": report_float(translated_corr, 6),
        "translated_calibration_reference_distortion_db": report_float(translated_distortion, 3),
        "translated_reference_dbfs": report_float(translated_level, 3),
    }


def sweep_score(metrics: dict[str, Any]) -> float:
    margins = metrics.get("margin_to_threshold", {})
    score = 0.0
    for value in margins.values():
        if isinstance(value, (int, float)):
            score += max(-100.0, min(100.0, float(value)))
    return score


def run_route_probe_sweep(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rates = list(dict.fromkeys(int(value) for value in args.sample_rate_hz))
    channel_configs = list(
        dict.fromkeys(tuple(config) for config in args.channel_config)
    )

    configs: list[dict[str, Any]] = []
    for sample_rate_hz in sample_rates:
        for input_channels, output_channels in channel_configs:
            if args.pair:
                pairs = [
                    {
                        "input_device": input_device,
                        "output_device": output_device,
                        "source": "explicit",
                    }
                    for input_device, output_device in args.pair
                ]
            else:
                pairs = candidate_device_pairs(
                    sd,
                    input_channels=int(input_channels),
                    output_channels=int(output_channels),
                    hostapis=list(args.hostapi or []),
                    include_cross_hostapi=bool(args.include_cross_hostapi),
                    max_pairs=int(args.max_pairs),
                )
            for pair in pairs:
                configs.append(
                    {
                        "input_channels": int(input_channels),
                        "output_channels": int(output_channels),
                        "pair": pair,
                        "sample_rate_hz": int(sample_rate_hz),
                    }
                )
                if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
                    break
            if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
                break
        if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
            break

    attempts: list[dict[str, Any]] = []
    for index, config in enumerate(configs, start=1):
        pair = config["pair"]
        input_device = str(pair["input_device"])
        output_device = str(pair["output_device"])
        input_channels = int(config["input_channels"])
        output_channels = int(config["output_channels"])
        sample_rate_hz = int(config["sample_rate_hz"])
        attempt_id = (
            f"attempt-{index:02d}-sr-{sample_rate_hz}-in-ch-{input_channels}-"
            f"out-ch-{output_channels}-in-{safe_id(input_device)}-out-{safe_id(output_device)}"
        )
        child_run_id = f"{args.run_id}/{attempt_id}"
        child_args = argparse.Namespace(**vars(args))
        child_args.command = "probe-route"
        child_args.run_id = child_run_id
        child_args.adapter_id = DEFAULT_ROUTE_PROBE_ADAPTER_ID
        child_args.sample_rate_hz = sample_rate_hz
        child_args.input_device = input_device
        child_args.output_device = output_device
        child_args.input_channels = input_channels
        child_args.output_channels = output_channels
        child_args.score_warning_only = True
        report_path = Path(args.output_dir) / "runs" / child_run_id / "route-probe-report.json"
        attempt: dict[str, Any] = {
            "attempt_id": attempt_id,
            "duration_s": float(args.duration_s),
            "input_channels": input_channels,
            "input_device": input_device,
            "input_hostapi_name": pair.get("input_hostapi_name"),
            "input_name": pair.get("input_name"),
            "output_channels": output_channels,
            "output_device": output_device,
            "output_hostapi_name": pair.get("output_hostapi_name"),
            "output_name": pair.get("output_name"),
            "pair_source": pair.get("source"),
            "playback_gain_db": float(args.playback_gain_db),
            "report_path": str(report_path),
            "sample_rate_hz": sample_rate_hz,
        }
        try:
            run_route_probe(child_args)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            benchmark = report.get("benchmarks", {}).get("room_route_probe", {})
            summary = benchmark.get("summary", {}) if isinstance(benchmark, dict) else {}
            gates = report.get("summary", {}).get("quality_gates", [])
            artifact_paths = report.get("artifact_paths", {})
            artifact_hashes = report.get("artifact_hashes", {})
            failed_gates = [
                str(gate.get("name"))
                for gate in gates
                if isinstance(gate, dict) and not bool(gate.get("passed"))
            ]
            metrics = route_probe_attempt_metrics(summary, child_args)
            passed = bool(report.get("summary", {}).get("passed")) and not failed_gates
            attempt.update(
                {
                    "artifact_hashes": artifact_hashes if isinstance(artifact_hashes, dict) else {},
                    "artifact_paths": artifact_paths if isinstance(artifact_paths, dict) else {},
                    "device": benchmark.get("device") if isinstance(benchmark, dict) else None,
                    "failed_gates": failed_gates,
                    "metrics": metrics,
                    "passed": passed,
                    "quality_gates": gates,
                    "score": report_float(route_probe_score(metrics), 6),
                    "status": "pass" if passed else "fail",
                }
            )
        except Exception as exc:  # pragma: no cover - depends on host device failures.
            attempt.update(
                {
                    "error": str(exc),
                    "failed_gates": ["route_probe_attempt_error"],
                    "passed": False,
                    "score": None,
                    "status": "error",
                }
            )
        attempts.append(attempt)

    candidates = [attempt for attempt in attempts if bool(attempt.get("passed"))]
    scored_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("score"), (int, float))
    ]
    candidate_attempt = None
    best_scored_attempt = None
    if candidates:
        candidate_attempt = max(candidates, key=lambda item: float(item.get("score") or 0.0))
    if scored_attempts:
        best_scored_attempt = max(scored_attempts, key=lambda item: float(item.get("score") or 0.0))

    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_room_route_probe_sweep",
        "measurement_kind": "real_room_route_probe_sweep_triage",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "attempted_config_count": len(attempts),
            "best_scored_attempt_id": (
                best_scored_attempt.get("attempt_id") if best_scored_attempt else None
            ),
            "candidate_attempt_id": candidate_attempt.get("attempt_id") if candidate_attempt else None,
            "channel_configs": [
                {"input_channels": item[0], "output_channels": item[1]} for item in channel_configs
            ],
            "release_proof": False,
            "sample_rates_hz": sample_rates,
            "triage_candidate_found": bool(candidates),
        },
        "benchmarks": {
            "room_route_probe_sweep": {
                "adapter_id": args.adapter_id,
                "attempts": attempts,
                "best_scored_attempt": best_scored_attempt,
                "candidate_attempt": candidate_attempt,
                "required_follow_up": (
                    "Rerun a passing sentinel route with qualify-device and then the full "
                    "real-room playback suppression check. Route sweep output is not release evidence."
                ),
            }
        },
        "detractor_loop": {
            "strongest_objection": (
                "A chirp sweep can find a route that preserves a probe while still failing "
                "speech playback, channel routing, AGC, or echo-processing behavior."
            ),
            "verdict": (
                "This is only a route triage artifact. It records every attempted "
                "configuration and keeps release_proof=false."
            ),
        },
    }
    report_path = run_dir / "route-probe-sweep-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "CANDIDATE" if candidates else "NO-CANDIDATE"
    print(
        f"real-room route probe sweep {status}: attempts={len(attempts)}, "
        f"candidate_found={bool(candidates)}"
    )
    print(f"wrote real-room route probe sweep report to {report_path}")
    return 0 if candidates or args.score_warning_only else 1


def run_device_sweep(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.pair:
        pairs = [
            {
                "input_device": input_device,
                "output_device": output_device,
                "source": "explicit",
            }
            for input_device, output_device in args.pair
        ]
        if int(args.max_pairs) > 0:
            pairs = pairs[: int(args.max_pairs)]
    else:
        pairs = candidate_device_pairs(
            sd,
            input_channels=int(args.input_channels),
            output_channels=int(args.output_channels),
            hostapis=list(args.hostapi or []),
            include_cross_hostapi=bool(args.include_cross_hostapi),
            max_pairs=int(args.max_pairs),
        )

    attempts: list[dict[str, Any]] = []
    for index, pair in enumerate(pairs, start=1):
        input_device = str(pair["input_device"])
        output_device = str(pair["output_device"])
        attempt_id = (
            f"attempt-{index:02d}-in-{safe_id(input_device)}-out-{safe_id(output_device)}"
        )
        child_run_id = f"{args.run_id}/{attempt_id}"
        child_args = argparse.Namespace(**vars(args))
        child_args.command = "qualify-device"
        child_args.run_id = child_run_id
        child_args.adapter_id = DEFAULT_DEVICE_QUALIFICATION_ADAPTER_ID
        child_args.input_device = input_device
        child_args.output_device = output_device
        child_args.score_warning_only = True
        report_path = Path(args.output_dir) / "runs" / child_run_id / "room-device-qualification-report.json"
        attempt: dict[str, Any] = {
            "attempt_id": attempt_id,
            "input_device": input_device,
            "output_device": output_device,
            "pair_source": pair.get("source"),
            "report_path": str(report_path),
            "sample_rate_hz": int(args.sample_rate_hz),
            "max_reference_duration_s": float(args.max_reference_duration_s),
            "output_channels": int(args.output_channels),
            "playback_gain_db": float(args.playback_gain_db),
        }
        try:
            run_device_qualification(child_args)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            benchmark = report.get("benchmarks", {}).get("room_device_qualification", {})
            summary = benchmark.get("summary", {}) if isinstance(benchmark, dict) else {}
            gates = report.get("summary", {}).get("quality_gates", [])
            artifact_paths = report.get("artifact_paths", {})
            artifact_hashes = report.get("artifact_hashes", {})
            failed_gates = [
                str(gate.get("name"))
                for gate in gates
                if isinstance(gate, dict) and not bool(gate.get("passed"))
            ]
            metrics = qualification_attempt_metrics(summary, args)
            attempt.update(
                {
                    "artifact_hashes": artifact_hashes if isinstance(artifact_hashes, dict) else {},
                    "artifact_paths": artifact_paths if isinstance(artifact_paths, dict) else {},
                    "device": benchmark.get("device") if isinstance(benchmark, dict) else None,
                    "failed_gates": failed_gates,
                    "metrics": metrics,
                    "passed": not failed_gates,
                    "quality_gates": gates,
                    "score": report_float(sweep_score(metrics), 6),
                    "status": "pass" if not failed_gates else "fail",
                }
            )
        except Exception as exc:  # pragma: no cover - depends on host device failures.
            attempt.update(
                {
                    "error": str(exc),
                    "failed_gates": ["device_path_unusable"],
                    "passed": False,
                    "score": None,
                    "status": "error",
                }
            )
        attempts.append(attempt)

    candidates = [attempt for attempt in attempts if bool(attempt.get("passed"))]
    scored_attempts = [
        attempt
        for attempt in attempts
        if isinstance(attempt.get("score"), (int, float))
    ]
    candidate_attempt = None
    best_scored_attempt = None
    if candidates:
        candidate_attempt = max(candidates, key=lambda item: float(item.get("score") or 0.0))
    if scored_attempts:
        best_scored_attempt = max(scored_attempts, key=lambda item: float(item.get("score") or 0.0))

    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_room_device_sweep",
        "measurement_kind": "real_room_device_sweep_triage",
        "release_proof": False,
        "output_dir": str(args.output_dir),
        "summary": {
            "attempted_config_count": len(attempts),
            "best_scored_attempt_id": (
                best_scored_attempt.get("attempt_id") if best_scored_attempt else None
            ),
            "candidate_attempt_id": candidate_attempt.get("attempt_id") if candidate_attempt else None,
            "release_proof": False,
            "triage_candidate_found": bool(candidates),
        },
        "benchmarks": {
            "room_device_sweep": {
                "adapter_id": args.adapter_id,
                "attempts": attempts,
                "best_scored_attempt": best_scored_attempt,
                "candidate_attempt": candidate_attempt,
                "required_follow_up": (
                    "Rerun the selected device path with the full real-room playback suppression "
                    "check and then run scripts/release_audio_gate.py. Sweep output is not release evidence."
                ),
            }
        },
        "detractor_loop": {
            "strongest_objection": (
                "A short sweep can accidentally select a route that only preserves a tiny slice "
                "or passes because of metric shopping."
            ),
            "verdict": (
                "This report is only a bounded triage artifact. It records every attempted "
                "config and keeps release_proof=false."
            ),
        },
    }
    report_path = run_dir / "device-sweep-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "CANDIDATE" if candidates else "NO-CANDIDATE"
    print(
        f"real-room device sweep {status}: attempts={len(attempts)}, "
        f"candidate_found={bool(candidates)}"
    )
    print(f"wrote real-room device sweep report to {report_path}")
    return 0 if candidates or args.score_warning_only else 1


def resolve_cancel_gain(
    value: str,
    source_left_recording: np.ndarray,
    source_right_recording: np.ndarray,
) -> float:
    if value != "auto":
        return float(value)
    gain = projection_gain(source_left_recording, source_right_recording)
    if not math.isfinite(gain):
        return 0.0
    return max(-2.0, min(2.0, gain))


def self_test() -> int:
    sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
    t = np.arange(sample_rate_hz, dtype=np.float64) / float(sample_rate_hz)
    source = np.sin(2.0 * math.pi * 220.0 * t).astype(np.float32) * 0.05
    translated = np.sin(2.0 * math.pi * 330.0 * t).astype(np.float32) * 0.05
    cancellation = translated + source * db_to_linear(-8.0)
    summary = {
        "all_artifact_hashes_present": True,
        "device_path_fingerprint": "0" * 64,
        "device_path_identity_recorded": True,
        "measurement_kind": MEASUREMENT_KIND,
        "room_loopback_recorded": True,
        "source_residual_dbfs": round(dbfs(cancellation * db_to_linear(-8.0)), 3),
        "source_residual_reduction_db": 8.0,
        "source_calibration_dbfs": round(dbfs(source), 3),
        "source_calibration_reference_correlation": 1.0,
        "source_calibration_reference_distortion_db": 0.0,
        "suppression_claim": SUPPRESSION_CLAIM_TRUE,
        "translated_audio_is_surrogate": False,
        "translated_calibration_reference_correlation": 1.0,
        "translated_calibration_reference_distortion_db": 0.0,
        "translated_output_correlation": round(correlation(cancellation, translated), 6),
        "translated_output_distortion_db": round(distortion_db(cancellation, translated), 3),
        "translated_reference_dbfs": round(dbfs(translated), 3),
    }
    args = argparse.Namespace(
        max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
        max_calibration_distortion_db=DEFAULT_MAX_CALIBRATION_DISTORTION_DB,
        min_room_calibration_dbfs=DEFAULT_MIN_ROOM_CALIBRATION_DBFS,
        min_calibration_correlation=DEFAULT_MIN_CALIBRATION_CORRELATION,
        min_source_reduction_db=DEFAULT_MIN_SOURCE_REDUCTION_DB,
        min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    gates = quality_gates(summary, args)
    if not all(bool(gate["passed"]) for gate in gates):
        raise RuntimeError(f"expected self-test room gates to pass: {gates}")
    route_summary = {
        "all_artifact_hashes_present": True,
        "device_path_fingerprint": "0" * 64,
        "device_path_identity_recorded": True,
        "route_probe_clipped_sample_count": 0,
        "route_probe_recording_dbfs": -20.0,
        "route_probe_recording_matches_reference": False,
        "route_probe_reference_confidence": 0.95,
        "route_probe_reference_distortion_db": 3.0,
    }
    route_args = argparse.Namespace(
        max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
        min_room_calibration_dbfs=DEFAULT_MIN_ROOM_CALIBRATION_DBFS,
        min_route_probe_confidence=DEFAULT_MIN_ROUTE_PROBE_CONFIDENCE,
    )
    route_gates = route_probe_gates(route_summary, route_args)
    if not all(bool(gate["passed"]) for gate in route_gates):
        raise RuntimeError(f"expected self-test route probe gates to pass: {route_gates}")
    clone_summary = dict(route_summary)
    clone_summary["route_probe_recording_matches_reference"] = True
    clone_gates = route_probe_gates(clone_summary, route_args)
    if all(bool(gate["passed"]) for gate in clone_gates):
        raise RuntimeError("expected reference-clone route probe gates to fail")
    print("real-room playback suppression contract self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run host real-room playback/suppression loopback")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-devices", help="list PortAudio input/output devices")
    subparsers.add_parser("self-test", help="validate scoring gates without audio hardware")
    probe = subparsers.add_parser(
        "probe-route",
        help="play a chirp sentinel and verify the input/output route before speech checks",
    )
    probe.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    probe.add_argument("--run-id", default=DEFAULT_ROUTE_PROBE_RUN_ID)
    probe.add_argument("--adapter-id", default=DEFAULT_ROUTE_PROBE_ADAPTER_ID)
    probe.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    probe.add_argument("--duration-s", type=float, default=DEFAULT_ROUTE_PROBE_DURATION_S)
    probe.add_argument("--input-device")
    probe.add_argument("--output-device")
    probe.add_argument("--input-channels", type=int, default=1)
    probe.add_argument("--output-channels", type=int, default=2)
    probe.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    probe.add_argument("--min-room-calibration-dbfs", type=float, default=DEFAULT_MIN_ROOM_CALIBRATION_DBFS)
    probe.add_argument("--min-route-probe-confidence", type=float, default=DEFAULT_MIN_ROUTE_PROBE_CONFIDENCE)
    probe.add_argument("--max-route-probe-distortion-db", type=float, default=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB)
    probe.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    probe.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    probe.add_argument("--score-warning-only", action="store_true")
    route_sweep = subparsers.add_parser(
        "sweep-routes",
        help="try bounded input/output/sample-rate/channel routes with chirp sentinel reports",
    )
    route_sweep.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    route_sweep.add_argument("--run-id", default=DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID)
    route_sweep.add_argument("--adapter-id", default=DEFAULT_ROUTE_PROBE_SWEEP_ADAPTER_ID)
    route_sweep.add_argument("--sample-rate-hz", type=int, action="append")
    route_sweep.add_argument("--duration-s", type=float, default=DEFAULT_ROUTE_PROBE_DURATION_S)
    route_sweep.add_argument("--channel-config", type=parse_channel_config, action="append")
    route_sweep.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    route_sweep.add_argument("--min-room-calibration-dbfs", type=float, default=DEFAULT_MIN_ROOM_CALIBRATION_DBFS)
    route_sweep.add_argument("--min-route-probe-confidence", type=float, default=DEFAULT_MIN_ROUTE_PROBE_CONFIDENCE)
    route_sweep.add_argument("--max-route-probe-distortion-db", type=float, default=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB)
    route_sweep.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    route_sweep.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    route_sweep.add_argument("--max-pairs", type=int, default=DEFAULT_SWEEP_MAX_PAIRS)
    route_sweep.add_argument("--max-attempts", type=int, default=DEFAULT_ROUTE_PROBE_SWEEP_MAX_ATTEMPTS)
    route_sweep.add_argument("--hostapi", action="append", default=[])
    route_sweep.add_argument("--include-cross-hostapi", action="store_true")
    route_sweep.add_argument("--pair", type=parse_pair, action="append")
    route_sweep.add_argument("--score-warning-only", action="store_true")
    qualify = subparsers.add_parser(
        "qualify-device",
        help="play source/translated references and verify the device path preserves them",
    )
    qualify.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    qualify.add_argument("--run-id", default=DEFAULT_DEVICE_QUALIFICATION_RUN_ID)
    qualify.add_argument("--adapter-id", default=DEFAULT_DEVICE_QUALIFICATION_ADAPTER_ID)
    qualify.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    qualify.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    qualify.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    qualify.add_argument("--input-device")
    qualify.add_argument("--output-device")
    qualify.add_argument("--input-channels", type=int, default=1)
    qualify.add_argument("--output-channels", type=int, default=2)
    qualify.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    qualify.add_argument("--pause-s", type=float, default=0.5)
    qualify.add_argument("--min-room-calibration-dbfs", type=float, default=DEFAULT_MIN_ROOM_CALIBRATION_DBFS)
    qualify.add_argument("--min-calibration-correlation", type=float, default=DEFAULT_MIN_CALIBRATION_CORRELATION)
    qualify.add_argument("--max-calibration-distortion-db", type=float, default=DEFAULT_MAX_CALIBRATION_DISTORTION_DB)
    qualify.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    qualify.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    qualify.add_argument(
        "--max-reference-duration-s",
        type=float,
        default=DEFAULT_QUALIFICATION_MAX_REFERENCE_DURATION_S,
        help="0 means use the full reference track; positive values are triage only",
    )
    qualify.add_argument("--score-warning-only", action="store_true")
    sweep = subparsers.add_parser(
        "sweep-devices",
        help="try bounded input/output device pairs with short qualification reports",
    )
    sweep.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    sweep.add_argument("--run-id", default=DEFAULT_DEVICE_SWEEP_RUN_ID)
    sweep.add_argument("--adapter-id", default=DEFAULT_DEVICE_SWEEP_ADAPTER_ID)
    sweep.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    sweep.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    sweep.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    sweep.add_argument("--input-channels", type=int, default=1)
    sweep.add_argument("--output-channels", type=int, default=2)
    sweep.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    sweep.add_argument("--pause-s", type=float, default=0.5)
    sweep.add_argument("--min-room-calibration-dbfs", type=float, default=DEFAULT_MIN_ROOM_CALIBRATION_DBFS)
    sweep.add_argument("--min-calibration-correlation", type=float, default=DEFAULT_MIN_CALIBRATION_CORRELATION)
    sweep.add_argument("--max-calibration-distortion-db", type=float, default=DEFAULT_MAX_CALIBRATION_DISTORTION_DB)
    sweep.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    sweep.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    sweep.add_argument("--max-reference-duration-s", type=float, default=DEFAULT_SWEEP_MAX_REFERENCE_DURATION_S)
    sweep.add_argument("--max-pairs", type=int, default=DEFAULT_SWEEP_MAX_PAIRS)
    sweep.add_argument("--hostapi", action="append", default=[])
    sweep.add_argument("--include-cross-hostapi", action="store_true")
    sweep.add_argument("--pair", type=parse_pair, action="append")
    sweep.add_argument("--score-warning-only", action="store_true")
    check = subparsers.add_parser("check", help="play references, record room loopback, and score")
    check.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    check.add_argument("--run-id", default=DEFAULT_RUN_ID)
    check.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    check.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    check.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    check.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    check.add_argument("--input-device")
    check.add_argument("--output-device")
    check.add_argument("--input-channels", type=int, default=1)
    check.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    check.add_argument("--cancel-gain", default=DEFAULT_CANCEL_GAIN)
    check.add_argument("--pause-s", type=float, default=0.5)
    check.add_argument("--min-source-reduction-db", type=float, default=DEFAULT_MIN_SOURCE_REDUCTION_DB)
    check.add_argument("--min-translated-correlation", type=float, default=DEFAULT_MIN_TRANSLATED_CORRELATION)
    check.add_argument("--max-translated-distortion-db", type=float, default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB)
    check.add_argument("--min-room-calibration-dbfs", type=float, default=DEFAULT_MIN_ROOM_CALIBRATION_DBFS)
    check.add_argument("--min-calibration-correlation", type=float, default=DEFAULT_MIN_CALIBRATION_CORRELATION)
    check.add_argument("--max-calibration-distortion-db", type=float, default=DEFAULT_MAX_CALIBRATION_DISTORTION_DB)
    check.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    check.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    check.add_argument("--score-warning-only", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "sweep-routes":
        if args.sample_rate_hz is None:
            args.sample_rate_hz = list(DEFAULT_ROUTE_PROBE_SWEEP_SAMPLE_RATES)
        if args.channel_config is None:
            args.channel_config = list(DEFAULT_ROUTE_PROBE_SWEEP_CHANNEL_CONFIGS)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "list-devices":
        return list_devices()
    if args.command == "self-test":
        return self_test()
    if args.command == "probe-route":
        return run_route_probe(args)
    if args.command == "sweep-routes":
        return run_route_probe_sweep(args)
    if args.command == "qualify-device":
        return run_device_qualification(args)
    if args.command == "sweep-devices":
        return run_device_sweep(args)
    if args.command == "check":
        return run_check(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
