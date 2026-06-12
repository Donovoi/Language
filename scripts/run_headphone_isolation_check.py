#!/usr/bin/env python3
"""Score measured headphone/earpiece source isolation.

This is an alternate release-evidence path for listener-local source reduction.
It does not claim room-wide source cancellation. It requires measured listener-ear
recordings with and without the headphone/earpiece isolation path, plus a separate
translated-playback fidelity recording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "headphone-earpiece-isolation"
DEFAULT_ROUTE_PROBE_RUN_ID = "headphone-earpiece-route-probe"
DEFAULT_ADAPTER_ID = "listener_headphone_earpiece_isolation_measurement_v1"
DEFAULT_ROUTE_PROBE_ADAPTER_ID = "listener_headphone_earpiece_route_probe_v1"
DEFAULT_TTS_REPORT = DEFAULT_OUTPUT_DIR / "runs/same-voice-tts/voice-clone-report.json"
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_CAPTURE_OUTPUT_CHANNELS = 2
DEFAULT_CAPTURE_INPUT_CHANNELS = 1
DEFAULT_GAP_S = 0.35
DEFAULT_LEAD_S = 0.25
DEFAULT_TAIL_S = 0.25
DEFAULT_PLAYBACK_GAIN_DB = -18.0
DEFAULT_MAX_PEAK_DBFS = -0.1
DEFAULT_ROUTE_PROBE_DURATION_S = 1.0
DEFAULT_MIN_ROUTE_PROBE_CORRELATION = 0.30
DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB = 24.0
DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES = 0
DEFAULT_MIN_SOURCE_OPEN_DBFS = -60.0
DEFAULT_MIN_TRANSLATED_DBFS = -60.0
DEFAULT_MIN_SOURCE_OPEN_CORRELATION = 0.30
DEFAULT_MIN_TRANSLATED_CORRELATION = 0.30
DEFAULT_MIN_SOURCE_ISOLATION_DB = 12.0
DEFAULT_MIN_MEASUREMENT_DURATION_S = 1.0
DEFAULT_MAX_TRANSLATED_DISTORTION_DB = 12.0
DEFAULT_MAX_ALIGNMENT_LAG_MS = 500.0
FIXTURE_KIND = "headphone_earpiece_isolation"
BENCHMARK_NAME = "headphone_earpiece_isolation"
MEASUREMENT_KIND = "headphone_earpiece_isolation"
SUPPRESSION_MODE = "HEADPHONE_ISOLATED"
SUPPRESSION_CLAIM = "headphone_isolated_not_true_cancellation"
CAPTURE_BACKEND_EXTERNAL = "external_wav_measurement"
CAPTURE_BACKEND_PORTAUDIO = "sounddevice_portaudio_guided_playrec"
CAPTURE_SOURCE_KIND_EXTERNAL = "external_listener_ear_wav_measurement"
CAPTURE_SOURCE_KIND_PORTAUDIO = "host_guided_listener_ear_playrec_measurement"
CAPTURE_BACKENDS = {CAPTURE_BACKEND_EXTERNAL, CAPTURE_BACKEND_PORTAUDIO}
CAPTURE_SOURCE_KINDS = {CAPTURE_SOURCE_KIND_EXTERNAL, CAPTURE_SOURCE_KIND_PORTAUDIO}
PLACEHOLDER_LABEL_PREFIXES = ("unspecified", "unknown", "todo", "placeholder")


def linear_to_db(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return float(20.0 * math.log10(value))


def db_to_linear(value: float) -> float:
    return float(10.0 ** (value / 20.0))


def import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised on hosts without PortAudio deps.
        raise RuntimeError(
            "sounddevice is required for guided host capture. "
            "Install with: python -m pip install sounddevice numpy"
        ) from exc
    return sd


def list_devices() -> int:
    sd = import_sounddevice()
    print(sd.query_devices())
    return 0


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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def specific_label(value: Any) -> bool:
    text = str(value).strip()
    return bool(text) and not text.lower().startswith(PLACEHOLDER_LABEL_PREFIXES)


def parse_device_selector(value: Any) -> int | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def measurement_identity_fingerprint(
    *,
    artifact_hashes: dict[str, str],
    headphone_device_label: str,
    isolation_fixture_label: str,
    measurement_microphone_label: str,
    sample_rate_hz: int,
) -> str:
    payload = {
        "artifact_hashes": artifact_hashes,
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "measurement_kind": MEASUREMENT_KIND,
        "measurement_microphone_label": measurement_microphone_label,
        "sample_rate_hz": int(sample_rate_hz),
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_mono_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate_hz = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"{path} must be PCM_16 WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.float32)
    if samples.size <= 0:
        raise ValueError(f"{path} must contain frames")
    return samples.astype(np.float32), int(sample_rate_hz)


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm.tobytes())


def resample_to_rate(audio: np.ndarray, source_rate_hz: int, target_rate_hz: int) -> np.ndarray:
    if source_rate_hz == target_rate_hz:
        return audio.astype(np.float32)
    if audio.size == 0:
        return audio.astype(np.float32)
    source_positions = np.linspace(0.0, 1.0, int(audio.size), endpoint=False)
    target_size = max(1, int(round(float(audio.size) * float(target_rate_hz) / float(source_rate_hz))))
    target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
    return np.interp(target_positions, source_positions, audio.astype(np.float64)).astype(np.float32)


def apply_playback_gain(samples: np.ndarray, gain_db: float, max_peak_dbfs: float) -> np.ndarray:
    scaled = np.asarray(samples, dtype=np.float32) * db_to_linear(float(gain_db))
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    limit = db_to_linear(float(max_peak_dbfs))
    if peak > limit and peak > 0.0:
        scaled = scaled * (limit / peak)
    return scaled.astype(np.float32)


def add_padding(samples: np.ndarray, sample_rate_hz: int, lead_s: float, tail_s: float) -> np.ndarray:
    lead = np.zeros(max(0, int(round(float(lead_s) * float(sample_rate_hz)))), dtype=np.float32)
    tail = np.zeros(max(0, int(round(float(tail_s) * float(sample_rate_hz)))), dtype=np.float32)
    return np.concatenate([lead, np.asarray(samples, dtype=np.float32), tail]).astype(np.float32)


def mono_playback(samples: np.ndarray, channels: int) -> np.ndarray:
    channel_count = max(1, int(channels))
    mono = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
    return np.repeat(mono, channel_count, axis=1).astype(np.float32)


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


def load_tts_segments(report_path: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    benchmark = report.get("benchmarks", {}).get("same_voice_or_fallback_tts", {})
    segments = benchmark.get("segments", []) if isinstance(benchmark, dict) else []
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"{report_path} does not contain same_voice_or_fallback_tts segments")
    return [segment for segment in segments if isinstance(segment, dict)]


def build_tts_reference_tracks(
    report_path: Path,
    sample_rate_hz: int,
    gap_s: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    source_parts: list[np.ndarray] = []
    translated_parts: list[np.ndarray] = []
    gap = np.zeros(max(0, int(round(float(gap_s) * float(sample_rate_hz)))), dtype=np.float32)
    segment_records: list[dict[str, Any]] = []
    cursor = 0
    for index, segment in enumerate(load_tts_segments(report_path)):
        source_path = resolve_report_path(report_path, segment.get("reference_audio_path"))
        translated_path = resolve_report_path(report_path, segment.get("tts_output_path"))
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
                "start_sample": cursor,
                "end_sample": cursor + frame_count,
                "source_reference_path": str(source_path),
                "source_reference_sha256": sha256_file(source_path),
                "translated_reference_path": str(translated_path),
                "translated_reference_sha256": sha256_file(translated_path),
            }
        )
        cursor += frame_count + gap.size
    source_track = np.concatenate(source_parts) if source_parts else np.zeros(0, dtype=np.float32)
    translated_track = np.concatenate(translated_parts) if translated_parts else np.zeros(0, dtype=np.float32)
    return source_track.astype(np.float32), translated_track.astype(np.float32), segment_records


def limit_track_pair(
    source_track: np.ndarray,
    translated_track: np.ndarray,
    *,
    sample_rate_hz: int,
    max_duration_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    if max_duration_s <= 0.0:
        return source_track.astype(np.float32), translated_track.astype(np.float32)
    max_samples = max(1, int(round(float(max_duration_s) * float(sample_rate_hz))))
    return source_track[:max_samples].astype(np.float32), translated_track[:max_samples].astype(np.float32)


def build_route_probe_signal(sample_rate_hz: int, duration_s: float) -> np.ndarray:
    frame_count = max(1, int(round(float(sample_rate_hz) * float(duration_s))))
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    start_hz = 420.0
    end_hz = min(3600.0, float(sample_rate_hz) * 0.40)
    slope = (end_hz - start_hz) / max(float(duration_s), 1.0 / float(sample_rate_hz))
    phase = 2.0 * math.pi * (start_hz * t + 0.5 * slope * t * t)
    signal = np.sin(phase).astype(np.float32) * 0.35
    fade_samples = min(frame_count // 2, max(1, int(round(0.025 * float(sample_rate_hz)))))
    if fade_samples > 1:
        ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        signal[:fade_samples] *= ramp
        signal[-fade_samples:] *= ramp[::-1]
    return signal.astype(np.float32)


def portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
    sd = import_sounddevice()
    info = sd.query_devices(device, kind=kind)
    hostapi = sd.query_hostapis(int(info["hostapi"]))
    return {
        "default": device is None,
        "default_samplerate": float(info["default_samplerate"]),
        "hostapi": int(info["hostapi"]),
        "hostapi_name": str(hostapi.get("name", "")),
        "index": int(info.get("index", -1)),
        "max_input_channels": int(info["max_input_channels"]),
        "max_output_channels": int(info["max_output_channels"]),
        "name": str(info["name"]),
        "requested_device": device,
    }


def measurement_device_fingerprint(
    *,
    device_info: dict[str, Any],
    sample_rate_hz: int,
    input_channels: int,
    output_channels: int,
) -> str:
    payload = {
        "device_info": device_info,
        "input_channels": int(input_channels),
        "output_channels": int(output_channels),
        "sample_rate_hz": int(sample_rate_hz),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_playback(
    playback: np.ndarray,
    *,
    sample_rate_hz: int,
    input_device: int | str | None,
    output_device: int | str | None,
    input_channels: int,
) -> tuple[np.ndarray, float]:
    sd = import_sounddevice()
    start = time.perf_counter()
    recording = sd.playrec(
        playback,
        samplerate=sample_rate_hz,
        channels=max(1, int(input_channels)),
        dtype="float32",
        device=(input_device, output_device),
        blocking=True,
    )
    elapsed_s = time.perf_counter() - start
    if getattr(recording, "ndim", 1) > 1:
        recording = recording.mean(axis=1)
    return np.asarray(recording, dtype=np.float32), elapsed_s


def recording_diagnostics(samples: np.ndarray, sample_rate_hz: int) -> dict[str, Any]:
    clipped = int(np.count_nonzero(np.abs(samples) >= 0.999))
    return {
        "clipped_sample_count": clipped,
        "duration_s": round(float(samples.size) / float(sample_rate_hz), 6),
        "peak_dbfs": round(peak_dbfs(samples), 3),
        "rms_dbfs": round(dbfs(samples), 3),
    }


def portaudio_output_signature(device_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "hostapi": device_info.get("hostapi"),
        "hostapi_name": device_info.get("hostapi_name"),
        "index": device_info.get("index"),
        "name": device_info.get("name"),
    }


def wait_for_operator(message: str, *, non_interactive: bool) -> None:
    print(message)
    if not non_interactive:
        input("Press Enter when ready...")


def write_capture_failure_report(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    capture_context: dict[str, Any],
    artifact_paths: dict[str, str],
    error: Exception,
) -> Path:
    artifact_hashes = {
        key: sha256_file(Path(value))
        for key, value in artifact_paths.items()
        if Path(value).exists()
    }
    summary = {
        "capture_backend": CAPTURE_BACKEND_PORTAUDIO,
        "capture_error": str(error),
        "capture_error_type": type(error).__name__,
        "capture_source_kind": CAPTURE_SOURCE_KIND_PORTAUDIO,
        "measurement_kind": MEASUREMENT_KIND,
        "quality_gates": [
            {
                "name": "headphone_guided_capture_completed",
                "passed": False,
                "threshold": "all three guided host capture steps complete",
                "value": {
                    "capture_error": str(error),
                    "capture_error_type": type(error).__name__,
                },
            }
        ],
        "release_proof": False,
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
    }
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": FIXTURE_KIND,
        "measurement_kind": MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": False,
            "quality_gates": summary["quality_gates"],
            "release_proof": False,
        },
        "benchmarks": {
            BENCHMARK_NAME: {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "capture": capture_context,
        "detractor_loop": {
            "strongest_objection": (
                "A failed guided capture cannot satisfy playback source-suppression evidence."
            ),
            "verdict": "Use this as route triage only; fix devices/sample rate before release gating.",
        },
    }
    report_path = run_dir / "headphone-isolation-report.json"
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def route_probe_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    def finite_float(name: str) -> float | None:
        value = summary.get(name)
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    def finite_nested_float(route_name: str, field_name: str) -> float | None:
        recording = summary.get(f"{route_name}_route_recording")
        if not isinstance(recording, dict):
            return None
        value = recording.get(field_name)
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    def nested_int(route_name: str, field_name: str) -> int | None:
        recording = summary.get(f"{route_name}_route_recording")
        if not isinstance(recording, dict):
            return None
        value = recording.get(field_name)
        if value is None:
            return None
        return int(value)

    source_opened = bool(summary.get("source_route_opened"))
    headphone_opened = bool(summary.get("headphone_route_opened"))
    source_clone = bool(summary.get("source_route_recording_matches_reference"))
    headphone_clone = bool(summary.get("headphone_route_recording_matches_reference"))
    hashes = bool(summary.get("all_artifact_hashes_present"))
    source_corr = finite_float("source_route_reference_correlation")
    headphone_corr = finite_float("headphone_route_reference_correlation")
    source_confidence = finite_float("source_route_reference_confidence")
    headphone_confidence = finite_float("headphone_route_reference_confidence")
    source_distortion = finite_float("source_route_reference_distortion_db")
    headphone_distortion = finite_float("headphone_route_reference_distortion_db")
    source_level = finite_float("source_route_recording_dbfs")
    headphone_level = finite_float("headphone_route_recording_dbfs")
    source_gain = finite_float("source_route_gain_db")
    headphone_gain = finite_float("headphone_route_gain_db")
    source_lag = summary.get("source_route_reference_lag_samples")
    headphone_lag = summary.get("headphone_route_reference_lag_samples")
    source_peak = finite_nested_float("source", "peak_dbfs")
    headphone_peak = finite_nested_float("headphone", "peak_dbfs")
    source_clipped = nested_int("source", "clipped_sample_count")
    headphone_clipped = nested_int("headphone", "clipped_sample_count")
    source_info = dict(summary.get("device_info", {}).get("source_output_device", {}))
    headphone_info = dict(summary.get("device_info", {}).get("headphone_output_device", {}))
    source_signature = portaudio_output_signature(source_info)
    headphone_signature = portaudio_output_signature(headphone_info)
    shared_output_allowed = bool(getattr(args, "allow_shared_output_device", False))
    outputs_distinct = shared_output_allowed or source_signature != headphone_signature
    min_corr = float(args.min_route_probe_correlation)
    max_distortion = float(args.max_route_probe_distortion_db)
    min_level = float(args.min_route_probe_dbfs)
    max_clipped = int(getattr(args, "max_route_probe_clipped_samples", DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES))
    return [
        {
            "name": "headphone_route_probe_not_release_proof",
            "passed": summary.get("release_proof") is False,
            "threshold": "route probes are triage only",
            "value": summary.get("release_proof"),
        },
        {
            "name": "headphone_route_outputs_distinct",
            "passed": outputs_distinct,
            "threshold": "source output and headphone output resolve to distinct PortAudio devices",
            "value": {
                "allow_shared_output_device": shared_output_allowed,
                "headphone_output_signature": headphone_signature,
                "source_output_signature": source_signature,
            },
        },
        {
            "name": "headphone_source_route_opened",
            "passed": source_opened,
            "threshold": "measurement input and source output can open a duplex stream",
            "value": summary.get("source_route_error") or source_opened,
        },
        {
            "name": "headphone_output_route_opened",
            "passed": headphone_opened,
            "threshold": "measurement input and headphone output can open a duplex stream",
            "value": summary.get("headphone_route_error") or headphone_opened,
        },
        {
            "name": "headphone_source_route_reference_fidelity",
            "passed": (
                source_confidence is not None
                and source_distortion is not None
                and source_level is not None
                and source_confidence >= min_corr
                and source_distortion <= max_distortion
                and source_level >= min_level
            ),
            "threshold": (
                f"source route abs(correlation) >= {min_corr:.3f}, distortion <= {max_distortion:.3f} dB, "
                f"level >= {min_level:.3f} dBFS"
            ),
            "value": {
                "source_route_gain_db": source_gain,
                "source_route_peak_dbfs": source_peak,
                "source_route_reference_confidence": source_confidence,
                "source_route_reference_correlation": source_corr,
                "source_route_reference_distortion_db": source_distortion,
                "source_route_reference_lag_samples": source_lag,
                "source_route_recording_dbfs": source_level,
            },
        },
        {
            "name": "headphone_output_route_reference_fidelity",
            "passed": (
                headphone_confidence is not None
                and headphone_distortion is not None
                and headphone_level is not None
                and headphone_confidence >= min_corr
                and headphone_distortion <= max_distortion
                and headphone_level >= min_level
            ),
            "threshold": (
                f"headphone route abs(correlation) >= {min_corr:.3f}, distortion <= {max_distortion:.3f} dB, "
                f"level >= {min_level:.3f} dBFS"
            ),
            "value": {
                "headphone_route_gain_db": headphone_gain,
                "headphone_route_peak_dbfs": headphone_peak,
                "headphone_route_reference_confidence": headphone_confidence,
                "headphone_route_reference_correlation": headphone_corr,
                "headphone_route_reference_distortion_db": headphone_distortion,
                "headphone_route_reference_lag_samples": headphone_lag,
                "headphone_route_recording_dbfs": headphone_level,
            },
        },
        {
            "name": "headphone_source_route_not_clipped",
            "passed": source_clipped is not None and source_clipped <= max_clipped,
            "threshold": f"source route clipped samples <= {max_clipped}",
            "value": source_clipped,
        },
        {
            "name": "headphone_output_route_not_clipped",
            "passed": headphone_clipped is not None and headphone_clipped <= max_clipped,
            "threshold": f"headphone route clipped samples <= {max_clipped}",
            "value": headphone_clipped,
        },
        {
            "name": "headphone_route_probe_artifacts_hashed",
            "passed": hashes,
            "threshold": "route probe reference and recording artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "headphone_route_recordings_not_reference_clones",
            "passed": not (source_clone or headphone_clone),
            "threshold": "route probe recordings must not be byte-identical to generated references",
            "value": {
                "headphone_route_recording_matches_reference": headphone_clone,
                "source_route_recording_matches_reference": source_clone,
            },
        },
    ]


def route_probe(args: argparse.Namespace) -> int:
    measurement_input_device = parse_device_selector(args.measurement_input_device)
    source_output_device = parse_device_selector(args.source_output_device)
    headphone_output_device = parse_device_selector(args.headphone_output_device)
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "headphone-route-probe-report.json"
    report_path.unlink(missing_ok=True)
    reference = add_padding(
        apply_playback_gain(
            build_route_probe_signal(int(args.sample_rate_hz), float(args.duration_s)),
            float(args.playback_gain_db),
            float(args.max_peak_dbfs),
        ),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    playback = mono_playback(reference, int(args.output_channels))
    source_reference_path = run_dir / "source-route-probe-reference.wav"
    headphone_reference_path = run_dir / "headphone-route-probe-reference.wav"
    source_recording_path = run_dir / "source-route-probe-recording.wav"
    headphone_recording_path = run_dir / "headphone-route-probe-recording.wav"
    for path in (
        headphone_reference_path,
        headphone_recording_path,
        source_reference_path,
        source_recording_path,
    ):
        path.unlink(missing_ok=True)
    write_mono_wav(source_reference_path, reference, int(args.sample_rate_hz))
    write_mono_wav(headphone_reference_path, reference, int(args.sample_rate_hz))

    device_info = {
        "headphone_output_device": portaudio_device_identity(headphone_output_device, kind="output"),
        "measurement_input_device": portaudio_device_identity(measurement_input_device, kind="input"),
        "source_output_device": portaudio_device_identity(source_output_device, kind="output"),
    }
    device_fingerprint = measurement_device_fingerprint(
        device_info=device_info,
        sample_rate_hz=int(args.sample_rate_hz),
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )
    summary: dict[str, Any] = {
        "adapter_id": args.adapter_id,
        "device_info": device_info,
        "device_path_fingerprint": device_fingerprint,
        "device_path_identity_recorded": True,
        "input_channels": int(args.input_channels),
        "measurement_kind": "headphone_earpiece_route_probe_triage",
        "output_channels": int(args.output_channels),
        "playback_gain_db": float(args.playback_gain_db),
        "release_proof": False,
        "sample_rate_hz": int(args.sample_rate_hz),
        "shared_output_device_allowed": bool(args.allow_shared_output_device),
    }

    source_recording: np.ndarray | None = None
    headphone_recording: np.ndarray | None = None
    try:
        source_recording, elapsed = record_playback(
            playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        summary["source_route_opened"] = True
        summary["source_route_elapsed_s"] = round(elapsed, 6)
        summary["source_route_recording"] = recording_diagnostics(source_recording, int(args.sample_rate_hz))
        write_mono_wav(source_recording_path, source_recording, int(args.sample_rate_hz))
    except Exception as exc:
        summary["source_route_opened"] = False
        summary["source_route_error"] = str(exc)
        summary["source_route_error_type"] = type(exc).__name__

    try:
        headphone_recording, elapsed = record_playback(
            playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=headphone_output_device,
            input_channels=int(args.input_channels),
        )
        summary["headphone_route_opened"] = True
        summary["headphone_route_elapsed_s"] = round(elapsed, 6)
        summary["headphone_route_recording"] = recording_diagnostics(
            headphone_recording,
            int(args.sample_rate_hz),
        )
        write_mono_wav(headphone_recording_path, headphone_recording, int(args.sample_rate_hz))
    except Exception as exc:
        summary["headphone_route_opened"] = False
        summary["headphone_route_error"] = str(exc)
        summary["headphone_route_error_type"] = type(exc).__name__

    if source_recording is not None:
        metrics = reference_metrics(
            source_recording,
            reference,
            int(args.sample_rate_hz),
            float(args.max_alignment_lag_ms),
        )
        summary.update(
            {
                "source_route_gain_db": metrics["gain_db"],
                "source_route_recording_dbfs": metrics["recording_dbfs"],
                "source_route_reference_confidence": round(abs(float(metrics["correlation"])), 6),
                "source_route_reference_correlation": metrics["correlation"],
                "source_route_reference_distortion_db": metrics["distortion_db"],
                "source_route_reference_lag_samples": metrics["lag_samples"],
            }
        )
    if headphone_recording is not None:
        metrics = reference_metrics(
            headphone_recording,
            reference,
            int(args.sample_rate_hz),
            float(args.max_alignment_lag_ms),
        )
        summary.update(
            {
                "headphone_route_gain_db": metrics["gain_db"],
                "headphone_route_recording_dbfs": metrics["recording_dbfs"],
                "headphone_route_reference_confidence": round(abs(float(metrics["correlation"])), 6),
                "headphone_route_reference_correlation": metrics["correlation"],
                "headphone_route_reference_distortion_db": metrics["distortion_db"],
                "headphone_route_reference_lag_samples": metrics["lag_samples"],
            }
        )

    artifact_paths = {
        "headphone_route_probe_reference": str(headphone_reference_path),
        "source_route_probe_reference": str(source_reference_path),
    }
    if source_recording_path.exists():
        artifact_paths["source_route_probe_recording"] = str(source_recording_path)
    if headphone_recording_path.exists():
        artifact_paths["headphone_route_probe_recording"] = str(headphone_recording_path)
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    expected_artifact_keys = {
        "headphone_route_probe_recording",
        "headphone_route_probe_reference",
        "source_route_probe_recording",
        "source_route_probe_reference",
    }
    missing_artifact_hashes = sorted(expected_artifact_keys.difference(artifact_hashes))
    summary["missing_artifact_hashes"] = missing_artifact_hashes
    summary["all_artifact_hashes_present"] = (
        not missing_artifact_hashes
        and all(len(artifact_hashes[key]) == 64 for key in expected_artifact_keys)
    )
    summary["source_route_recording_matches_reference"] = (
        artifact_hashes.get("source_route_probe_recording") == artifact_hashes.get("source_route_probe_reference")
    )
    summary["headphone_route_recording_matches_reference"] = (
        artifact_hashes.get("headphone_route_probe_recording")
        == artifact_hashes.get("headphone_route_probe_reference")
    )
    gates = route_probe_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "headphone_earpiece_route_probe",
        "measurement_kind": "headphone_earpiece_route_probe_triage",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": False,
        },
        "benchmarks": {
            "headphone_earpiece_route_probe": {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_hashes": artifact_hashes,
        "artifact_paths": artifact_paths,
        "detractor_loop": {
            "strongest_objection": (
                "This is only a route-opening and reference-fidelity triage check. It does not prove "
                "headphone source isolation or translated playback quality."
            ),
            "verdict": "Use a passing route probe only to choose devices for the full guided capture.",
        },
    }
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"headphone/earpiece route probe {status}: "
        f"source_opened={summary.get('source_route_opened')}, "
        f"headphone_opened={summary.get('headphone_route_opened')}"
    )
    print(f"wrote headphone route probe report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


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
    x -= float(np.mean(x))
    y -= float(np.mean(y))
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
    frame_count = min(int(measured.size), int(reference.size))
    max_lag_samples = max(0, int(round(float(sample_rate_hz) * float(max_lag_ms) / 1000.0)))
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


def reference_metrics(
    recording: np.ndarray,
    reference: np.ndarray,
    sample_rate_hz: int,
    max_lag_ms: float,
) -> dict[str, float | int]:
    lag_samples = best_alignment_lag_samples(recording, reference, sample_rate_hz, max_lag_ms)
    aligned_recording, aligned_reference = align_pair(recording, reference, lag_samples)
    gain = abs(projection_gain(aligned_recording, aligned_reference))
    return {
        "correlation": round(correlation(aligned_recording, aligned_reference), 6),
        "distortion_db": round(distortion_db(aligned_recording, aligned_reference), 3),
        "gain_db": round(linear_to_db(gain), 3) if gain > 0.0 else float("-inf"),
        "lag_samples": lag_samples,
        "recording_dbfs": round(dbfs(recording), 3),
    }


def quality_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    finite_metric_names = [
        "source_isolated_gain_db",
        "source_isolated_recording_dbfs",
        "source_isolation_db",
        "source_open_gain_db",
        "source_open_recording_dbfs",
        "source_open_reference_correlation",
        "source_open_reference_distortion_db",
        "translated_headphone_gain_db",
        "translated_headphone_recording_dbfs",
        "translated_headphone_reference_correlation",
        "translated_headphone_reference_distortion_db",
    ]
    finite_metrics = {
        name: math.isfinite(float(summary.get(name, float("nan"))))
        for name in finite_metric_names
    }
    source_open_level = float(summary["source_open_recording_dbfs"])
    translated_level = float(summary["translated_headphone_recording_dbfs"])
    source_open_corr = float(summary["source_open_reference_correlation"])
    translated_corr = float(summary["translated_headphone_reference_correlation"])
    translated_distortion = float(summary["translated_headphone_reference_distortion_db"])
    source_isolation = float(summary["source_isolation_db"])
    min_duration = float(summary["min_artifact_duration_s"])
    hashes = bool(summary["all_artifact_hashes_present"])
    source_open_clone = bool(summary.get("source_open_recording_matches_reference"))
    source_isolated_clone = bool(summary.get("source_isolated_recording_matches_reference"))
    translated_clone = bool(summary.get("translated_headphone_recording_matches_reference"))
    mode = summary["source_suppression_mode"]
    claim = summary["suppression_claim"]
    capture_backend = str(summary.get("capture_backend", ""))
    capture_source_kind = str(summary.get("capture_source_kind", ""))
    device_identity = bool(summary.get("device_path_identity_recorded"))
    device_fingerprint = str(summary.get("device_path_fingerprint", ""))
    identity_fingerprint = str(summary.get("measurement_identity_fingerprint", ""))
    release_proof = bool(summary["release_proof"])
    return [
        {
            "name": "headphone_measurement_release_proof",
            "passed": release_proof,
            "threshold": "measured listener-ear headphone isolation evidence",
            "value": release_proof,
        },
        {
            "name": "headphone_core_metrics_finite",
            "passed": all(finite_metrics.values()),
            "threshold": "all release-critical headphone metrics are finite numbers",
            "value": finite_metrics,
        },
        {
            "name": "headphone_mode_claim_declared",
            "passed": mode == SUPPRESSION_MODE,
            "threshold": f"source_suppression_mode == {SUPPRESSION_MODE}",
            "value": mode,
        },
        {
            "name": "headphone_claim_not_true_cancellation",
            "passed": claim == SUPPRESSION_CLAIM,
            "threshold": f"suppression_claim == {SUPPRESSION_CLAIM}",
            "value": claim,
        },
        {
            "name": "headphone_device_identity_recorded",
            "passed": specific_label(summary.get("headphone_device_label"))
            and specific_label(summary.get("measurement_microphone_label"))
            and len(identity_fingerprint) == 64,
            "threshold": "specific headphone device, listener-ear microphone, and SHA-256 identity fingerprint recorded",
            "value": {
                "headphone_device_label": summary.get("headphone_device_label"),
                "measurement_identity_fingerprint": identity_fingerprint,
                "measurement_microphone_label": summary.get("measurement_microphone_label"),
            },
        },
        {
            "name": "headphone_capture_source_declared",
            "passed": (
                capture_backend in CAPTURE_BACKENDS
                and capture_source_kind in CAPTURE_SOURCE_KINDS
                and (
                    capture_backend != CAPTURE_BACKEND_PORTAUDIO
                    or (device_identity and len(device_fingerprint) == 64)
                )
            ),
            "threshold": "capture backend/source declared; guided PortAudio capture includes device fingerprint",
            "value": {
                "capture_backend": capture_backend,
                "capture_source_kind": capture_source_kind,
                "device_path_fingerprint": device_fingerprint,
                "device_path_identity_recorded": device_identity,
            },
        },
        {
            "name": "isolation_fixture_identity_recorded",
            "passed": specific_label(summary.get("isolation_fixture_label")),
            "threshold": "specific physical isolation fixture label recorded",
            "value": summary.get("isolation_fixture_label"),
        },
        {
            "name": "headphone_recordings_duration_floor",
            "passed": min_duration >= float(args.min_measurement_duration_s),
            "threshold": f"all headphone isolation artifacts >= {float(args.min_measurement_duration_s):.3f}s",
            "value": min_duration,
        },
        {
            "name": "open_ear_source_control_audible",
            "passed": source_open_level >= float(args.min_source_open_dbfs),
            "threshold": f"open-ear source recording >= {float(args.min_source_open_dbfs):.3f} dBFS",
            "value": source_open_level,
        },
        {
            "name": "headphone_source_open_reference_fidelity",
            "passed": source_open_corr >= float(args.min_source_open_correlation),
            "threshold": (
                "open-ear source recording/reference correlation >= "
                f"{float(args.min_source_open_correlation):.3f}"
            ),
            "value": source_open_corr,
        },
        {
            "name": "source_isolation_measured",
            "passed": source_isolation >= float(args.min_source_isolation_db),
            "threshold": f"source attenuation >= {float(args.min_source_isolation_db):.3f} dB",
            "value": source_isolation,
        },
        {
            "name": "translated_headphone_output_audible",
            "passed": translated_level >= float(args.min_translated_dbfs),
            "threshold": f"translated headphone recording >= {float(args.min_translated_dbfs):.3f} dBFS",
            "value": translated_level,
        },
        {
            "name": "translated_headphone_output_not_distorted",
            "passed": (
                translated_corr >= float(args.min_translated_correlation)
                and translated_distortion <= float(args.max_translated_distortion_db)
            ),
            "threshold": (
                f"translated correlation >= {float(args.min_translated_correlation):.3f} "
                f"and distortion <= {float(args.max_translated_distortion_db):.3f} dB"
            ),
            "value": {
                "translated_headphone_reference_correlation": translated_corr,
                "translated_headphone_reference_distortion_db": translated_distortion,
            },
        },
        {
            "name": "headphone_artifacts_hashed",
            "passed": hashes,
            "threshold": "all headphone isolation WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "headphone_metrics_are_wav_derived",
            "passed": True,
            "threshold": "metrics were derived from the submitted WAV artifacts",
            "value": True,
        },
        {
            "name": "headphone_recordings_not_reference_clones",
            "passed": not (source_open_clone or source_isolated_clone or translated_clone),
            "threshold": "recording artifacts must not be byte-identical to generated references",
            "value": {
                "source_isolated_recording_matches_reference": source_isolated_clone,
                "source_open_recording_matches_reference": source_open_clone,
                "translated_headphone_recording_matches_reference": translated_clone,
            },
        },
    ]


def score(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    artifact_paths = {
        "source_reference": str(Path(args.source_reference)),
        "source_open_ear_recording": str(Path(args.source_open_ear_recording)),
        "source_isolated_ear_recording": str(Path(args.source_isolated_ear_recording)),
        "translated_playback_reference": str(Path(args.translated_playback_reference)),
        "translated_headphone_recording": str(Path(args.translated_headphone_recording)),
    }
    audio: dict[str, np.ndarray] = {}
    sample_rates: dict[str, int] = {}
    for key, value in artifact_paths.items():
        samples, sample_rate_hz = read_mono_wav(Path(value))
        audio[key] = samples
        sample_rates[key] = sample_rate_hz
    if len(set(sample_rates.values())) != 1:
        raise ValueError(f"all WAV artifacts must share a sample rate: {sample_rates}")
    sample_rate_hz = next(iter(sample_rates.values()))
    frame_counts = {key: int(value.size) for key, value in audio.items()}
    min_artifact_duration_s = min(
        float(frame_count) / float(sample_rate_hz)
        for frame_count in frame_counts.values()
    )

    source_open = reference_metrics(
        audio["source_open_ear_recording"],
        audio["source_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    source_isolated = reference_metrics(
        audio["source_isolated_ear_recording"],
        audio["source_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    translated = reference_metrics(
        audio["translated_headphone_recording"],
        audio["translated_playback_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    source_open_gain_db = float(source_open["gain_db"])
    source_isolated_gain_db = float(source_isolated["gain_db"])
    source_isolation_db = source_open_gain_db - source_isolated_gain_db
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    headphone_device_label = str(args.headphone_device_label)
    isolation_fixture_label = str(args.isolation_fixture_label)
    measurement_microphone_label = str(args.measurement_microphone_label)
    identity_fingerprint = measurement_identity_fingerprint(
        artifact_hashes=artifact_hashes,
        headphone_device_label=headphone_device_label,
        isolation_fixture_label=isolation_fixture_label,
        measurement_microphone_label=measurement_microphone_label,
        sample_rate_hz=sample_rate_hz,
    )
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "capture_backend": str(getattr(args, "capture_backend", CAPTURE_BACKEND_EXTERNAL)),
        "capture_source_kind": str(getattr(args, "capture_source_kind", CAPTURE_SOURCE_KIND_EXTERNAL)),
        "device_path_fingerprint": str(getattr(args, "device_path_fingerprint", "")),
        "device_path_identity_recorded": bool(getattr(args, "device_path_identity_recorded", False)),
        "device_info": getattr(args, "device_info", {}),
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "measurement_kind": MEASUREMENT_KIND,
        "measurement_identity_fingerprint": identity_fingerprint,
        "measurement_microphone_label": measurement_microphone_label,
        "artifact_frame_counts": frame_counts,
        "min_artifact_duration_s": round(min_artifact_duration_s, 6),
        "procedure_note": str(args.procedure_note),
        "reference_source_kind": str(getattr(args, "reference_source_kind", "external_wav_pair")),
        "release_proof": True,
        "sample_rate_hz": sample_rate_hz,
        "source_isolated_recording_matches_reference": (
            artifact_hashes["source_isolated_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_isolated_gain_db": source_isolated["gain_db"],
        "source_isolated_recording_dbfs": source_isolated["recording_dbfs"],
        "source_isolated_reference_correlation": source_isolated["correlation"],
        "source_isolated_reference_distortion_db": source_isolated["distortion_db"],
        "source_isolated_reference_lag_samples": source_isolated["lag_samples"],
        "source_isolation_db": round(source_isolation_db, 3),
        "source_open_recording_matches_reference": (
            artifact_hashes["source_open_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_open_gain_db": source_open["gain_db"],
        "source_open_recording_dbfs": source_open["recording_dbfs"],
        "source_open_reference_correlation": source_open["correlation"],
        "source_open_reference_distortion_db": source_open["distortion_db"],
        "source_open_reference_lag_samples": source_open["lag_samples"],
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
        "translated_audio_is_surrogate": False,
        "translated_headphone_gain_db": translated["gain_db"],
        "translated_headphone_recording_matches_reference": (
            artifact_hashes["translated_headphone_recording"]
            == artifact_hashes["translated_playback_reference"]
        ),
        "translated_headphone_recording_dbfs": translated["recording_dbfs"],
        "translated_headphone_reference_correlation": translated["correlation"],
        "translated_headphone_reference_distortion_db": translated["distortion_db"],
        "translated_headphone_reference_lag_samples": translated["lag_samples"],
    }
    gates = quality_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": FIXTURE_KIND,
        "measurement_kind": MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": True,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": True,
        },
        "benchmarks": {
            BENCHMARK_NAME: {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "capture": getattr(args, "capture_context", {}),
        "detractor_loop": {
            "strongest_objection": (
                "Headphone isolation is listener-local attenuation, not room-wide cancellation."
            ),
            "verdict": (
                "This evidence may satisfy a headphone/earpiece release mode only when WAV "
                "artifacts prove source attenuation and translated playback fidelity."
            ),
        },
    }
    report_path = run_dir / "headphone-isolation-report.json"
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    printed_summary = report["benchmarks"][BENCHMARK_NAME]["summary"]
    print(
        f"headphone/earpiece isolation {status}: "
        f"isolation_db={printed_summary['source_isolation_db']}, "
        f"translated_corr={printed_summary['translated_headphone_reference_correlation']}"
    )
    print(f"wrote headphone isolation report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def _capture_reference_tracks(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, str, list[dict[str, Any]]]:
    if bool(args.source_reference) != bool(args.translated_playback_reference):
        raise ValueError("--source-reference and --translated-playback-reference must be provided together")
    if args.source_reference and args.translated_playback_reference:
        source, source_rate = read_mono_wav(Path(args.source_reference))
        translated, translated_rate = read_mono_wav(Path(args.translated_playback_reference))
        source = resample_to_rate(source, source_rate, int(args.sample_rate_hz))
        translated = resample_to_rate(translated, translated_rate, int(args.sample_rate_hz))
        return source, translated, "external_wav_pair", []
    source, translated, segments = build_tts_reference_tracks(
        Path(args.tts_report),
        int(args.sample_rate_hz),
        float(args.gap_s),
    )
    return source, translated, "same_voice_or_fallback_tts_report", segments


def capture(args: argparse.Namespace) -> int:
    for field in ("headphone_device_label", "isolation_fixture_label", "measurement_microphone_label"):
        if not specific_label(getattr(args, field)):
            raise ValueError(f"{field.replace('_', '-')} must be specific, not a placeholder")

    measurement_input_device = parse_device_selector(args.measurement_input_device)
    source_output_device = parse_device_selector(args.source_output_device)
    headphone_output_device = parse_device_selector(args.headphone_output_device)
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_raw, translated_raw, reference_source_kind, reference_segments = _capture_reference_tracks(args)
    source_raw, translated_raw = limit_track_pair(
        source_raw,
        translated_raw,
        sample_rate_hz=int(args.sample_rate_hz),
        max_duration_s=float(args.max_reference_duration_s),
    )
    source_reference = add_padding(
        apply_playback_gain(source_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    translated_reference = add_padding(
        apply_playback_gain(translated_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    if min(source_reference.size, translated_reference.size) / float(args.sample_rate_hz) < float(
        args.min_measurement_duration_s
    ):
        raise ValueError("capture reference artifacts are shorter than the minimum measurement duration")

    source_reference_path = run_dir / "source-reference.wav"
    translated_reference_path = run_dir / "translated-playback-reference.wav"
    source_open_path = run_dir / "source-open-ear-recording.wav"
    source_isolated_path = run_dir / "source-isolated-ear-recording.wav"
    translated_recording_path = run_dir / "translated-headphone-recording.wav"
    write_mono_wav(source_reference_path, source_reference, int(args.sample_rate_hz))
    write_mono_wav(translated_reference_path, translated_reference, int(args.sample_rate_hz))

    device_info = {
        "headphone_output_device": portaudio_device_identity(headphone_output_device, kind="output"),
        "measurement_input_device": portaudio_device_identity(measurement_input_device, kind="input"),
        "source_output_device": portaudio_device_identity(source_output_device, kind="output"),
    }
    device_fingerprint = measurement_device_fingerprint(
        device_info=device_info,
        sample_rate_hz=int(args.sample_rate_hz),
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )
    print(f"measurement device fingerprint: {device_fingerprint}")
    capture_context: dict[str, Any] = {
        "backend": CAPTURE_BACKEND_PORTAUDIO,
        "device_path_fingerprint": device_fingerprint,
        "device_info": device_info,
        "reference_segments": reference_segments,
        "sample_rate_hz": int(args.sample_rate_hz),
        "input_channels": int(args.input_channels),
        "output_channels": int(args.output_channels),
        "playback_gain_db": float(args.playback_gain_db),
        "lead_s": float(args.lead_s),
        "tail_s": float(args.tail_s),
        "reference_source_kind": reference_source_kind,
        "source_route_control": (
            "source_open_ear_recording and source_isolated_ear_recording use the same "
            "source output device, source reference WAV, playback gain, sample rate, and channels"
        ),
    }

    source_playback = mono_playback(source_reference, int(args.output_channels))
    translated_playback = mono_playback(translated_reference, int(args.output_channels))
    artifact_paths = {
        "source_reference": str(source_reference_path),
        "source_open_ear_recording": str(source_open_path),
        "source_isolated_ear_recording": str(source_isolated_path),
        "translated_playback_reference": str(translated_reference_path),
        "translated_headphone_recording": str(translated_recording_path),
    }

    try:
        wait_for_operator(
            "Step 1/3: OPEN-EAR CONTROL. Put the listener-ear microphone in the measurement position, "
            "leave the headphone/earpiece isolation path off or removed, and route the source output to the original-source speaker.",
            non_interactive=bool(args.non_interactive),
        )
        source_open, elapsed = record_playback(
            source_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["source_open_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["source_open_recording"] = recording_diagnostics(source_open, int(args.sample_rate_hz))
        write_mono_wav(source_open_path, source_open, int(args.sample_rate_hz))

        wait_for_operator(
            "Step 2/3: ISOLATED SOURCE. Keep the source speaker route unchanged, place/enable the "
            "headphone or earpiece isolation fixture on the same listener-ear microphone, then record the source again.",
            non_interactive=bool(args.non_interactive),
        )
        source_isolated, elapsed = record_playback(
            source_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["source_isolated_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["source_isolated_recording"] = recording_diagnostics(source_isolated, int(args.sample_rate_hz))
        write_mono_wav(source_isolated_path, source_isolated, int(args.sample_rate_hz))

        wait_for_operator(
            "Step 3/3: TRANSLATED HEADPHONE PLAYBACK. Keep the listener-ear measurement fixture in place, "
            "route output to the headphone/earpiece device, and record the translated playback.",
            non_interactive=bool(args.non_interactive),
        )
        translated_recording, elapsed = record_playback(
            translated_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=headphone_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["translated_headphone_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["translated_headphone_recording"] = recording_diagnostics(
            translated_recording,
            int(args.sample_rate_hz),
        )
        write_mono_wav(translated_recording_path, translated_recording, int(args.sample_rate_hz))
    except Exception as exc:
        report_path = write_capture_failure_report(
            args=args,
            run_dir=run_dir,
            capture_context=capture_context,
            artifact_paths=artifact_paths,
            error=exc,
        )
        print(f"headphone/earpiece guided capture FAIL: {type(exc).__name__}: {exc}")
        print(f"wrote headphone isolation failure report to {report_path}")
        return 0 if args.score_warning_only else 1

    score_args = argparse.Namespace(**vars(args))
    score_args.adapter_id = args.adapter_id
    score_args.capture_backend = CAPTURE_BACKEND_PORTAUDIO
    score_args.capture_context = capture_context
    score_args.capture_source_kind = CAPTURE_SOURCE_KIND_PORTAUDIO
    score_args.device_info = device_info
    score_args.device_path_fingerprint = device_fingerprint
    score_args.device_path_identity_recorded = True
    score_args.reference_source_kind = reference_source_kind
    score_args.source_reference = source_reference_path
    score_args.source_open_ear_recording = source_open_path
    score_args.source_isolated_ear_recording = source_isolated_path
    score_args.translated_playback_reference = translated_reference_path
    score_args.translated_headphone_recording = translated_recording_path
    return score(score_args)


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
        t = np.arange(sample_rate_hz, dtype=np.float64) / float(sample_rate_hz)
        source = (np.sin(2.0 * math.pi * 220.0 * t) * 0.25).astype(np.float32)
        translated = (np.sin(2.0 * math.pi * 330.0 * t) * 0.20).astype(np.float32)
        source_open = source * db_to_linear(-2.0)
        source_isolated = source * db_to_linear(-18.0)
        translated_recording = translated * db_to_linear(-3.0)
        source_path = root / "source.wav"
        source_open_path = root / "source-open.wav"
        source_isolated_path = root / "source-isolated.wav"
        translated_path = root / "translated.wav"
        translated_recording_path = root / "translated-recording.wav"
        silent_source_isolated_path = root / "source-isolated-silent.wav"
        write_mono_wav(source_path, source, sample_rate_hz)
        write_mono_wav(source_open_path, source_open, sample_rate_hz)
        write_mono_wav(source_isolated_path, source_isolated, sample_rate_hz)
        write_mono_wav(silent_source_isolated_path, np.zeros_like(source), sample_rate_hz)
        write_mono_wav(translated_path, translated, sample_rate_hz)
        write_mono_wav(translated_recording_path, translated_recording, sample_rate_hz)
        args = argparse.Namespace(
            adapter_id=DEFAULT_ADAPTER_ID,
            headphone_device_label="unit headphones",
            isolation_fixture_label="unit sealed-ear fixture",
            max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
            max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
            measurement_microphone_label="unit ear microphone",
            min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
            min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
            min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
            min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
            min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
            min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
            output_dir=root / "out",
            procedure_note="unit synthetic measurement",
            run_id=DEFAULT_RUN_ID,
            score_warning_only=False,
            source_isolated_ear_recording=source_isolated_path,
            source_open_ear_recording=source_open_path,
            source_reference=source_path,
            translated_headphone_recording=translated_recording_path,
            translated_playback_reference=translated_path,
        )
        result = score(args)
        if result != 0:
            raise RuntimeError("expected headphone isolation self-test fixture to pass")
        args.run_id = "failing-headphone-earpiece-isolation"
        args.source_isolated_ear_recording = source_open_path
        args.score_warning_only = True
        result = score(args)
        if result != 0:
            raise RuntimeError("warning-only failing self-test should return 0")
        report_path = (
            Path(args.output_dir)
            / "runs"
            / args.run_id
            / "headphone-isolation-report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if bool(report.get("summary", {}).get("passed")):
            raise RuntimeError("expected no-isolation self-test fixture to fail")
        args.run_id = "silent-isolated-headphone-earpiece-isolation"
        args.source_isolated_ear_recording = silent_source_isolated_path
        args.score_warning_only = True
        result = score(args)
        if result != 0:
            raise RuntimeError("warning-only silent-isolated self-test should return 0")
        report_path = (
            Path(args.output_dir)
            / "runs"
            / args.run_id
            / "headphone-isolation-report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if bool(report.get("summary", {}).get("passed")):
            raise RuntimeError("expected silent-isolated self-test fixture to fail")
        gates = {gate["name"]: gate for gate in report.get("summary", {}).get("quality_gates", [])}
        if bool(gates["headphone_core_metrics_finite"]["passed"]):
            raise RuntimeError("expected silent-isolated finite-metrics gate to fail")
        json.dumps(report, allow_nan=False)
        route_args = argparse.Namespace(
            allow_shared_output_device=False,
            max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
            max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
            min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
            min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
        )
        route_summary = {
            "all_artifact_hashes_present": True,
            "device_info": {
                "headphone_output_device": {
                    "hostapi": 1,
                    "hostapi_name": "unit",
                    "index": 3,
                    "name": "unit headphone",
                    "requested_device": 3,
                },
                "source_output_device": {
                    "hostapi": 1,
                    "hostapi_name": "unit",
                    "index": 2,
                    "name": "unit source",
                    "requested_device": 2,
                },
            },
            "headphone_route_opened": True,
            "headphone_route_recording": {
                "clipped_sample_count": 0,
                "peak_dbfs": -18.0,
            },
            "headphone_route_recording_dbfs": -24.0,
            "headphone_route_recording_matches_reference": False,
            "headphone_route_reference_confidence": 0.95,
            "headphone_route_reference_correlation": 0.95,
            "headphone_route_reference_distortion_db": 3.0,
            "release_proof": False,
            "source_route_opened": True,
            "source_route_recording": {
                "clipped_sample_count": 0,
                "peak_dbfs": -18.0,
            },
            "source_route_recording_dbfs": -24.0,
            "source_route_recording_matches_reference": False,
            "source_route_reference_confidence": 0.95,
            "source_route_reference_correlation": 0.95,
            "source_route_reference_distortion_db": 3.0,
        }
        if not all(bool(gate["passed"]) for gate in route_probe_gates(route_summary, route_args)):
            raise RuntimeError("expected route probe gate self-test fixture to pass")
        route_summary["all_artifact_hashes_present"] = False
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_route_probe_artifacts_hashed"]["passed"]):
            raise RuntimeError("expected route probe missing-artifact self-test fixture to fail")
        route_summary["all_artifact_hashes_present"] = True
        route_summary["source_route_recording"]["clipped_sample_count"] = 1
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_source_route_not_clipped"]["passed"]):
            raise RuntimeError("expected route probe clipped-source self-test fixture to fail")
        route_summary["source_route_recording"]["clipped_sample_count"] = 0
        route_summary["device_info"]["headphone_output_device"] = dict(
            route_summary["device_info"]["source_output_device"]
        )
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_route_outputs_distinct"]["passed"]):
            raise RuntimeError("expected route probe same-output self-test fixture to fail")
        json.dumps(
            {"quality_gates": route_probe_gates({"release_proof": False}, route_args)},
            allow_nan=False,
        )
        original_portaudio_device_identity = globals()["portaudio_device_identity"]
        original_record_playback = globals()["record_playback"]

        def fake_portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
            index = int(device) if device is not None and str(device).isdigit() else 99
            return {
                "default": device is None,
                "default_samplerate": float(sample_rate_hz),
                "hostapi": 1,
                "hostapi_name": "unit",
                "index": index,
                "max_input_channels": 1 if kind == "input" else 0,
                "max_output_channels": 0 if kind == "input" else 2,
                "name": f"unit {kind} {index}",
                "requested_device": device,
            }

        def fake_silent_record_playback(
            playback: np.ndarray,
            *,
            sample_rate_hz: int,
            input_device: int | str | None,
            output_device: int | str | None,
            input_channels: int,
        ) -> tuple[np.ndarray, float]:
            return np.zeros(int(playback.shape[0]), dtype=np.float32), 0.001

        silent_report_path = (
            root
            / "route-out"
            / "runs"
            / "silent-route"
            / "headphone-route-probe-report.json"
        )
        silent_report_path.parent.mkdir(parents=True, exist_ok=True)
        silent_report_path.write_text('{"stale": true}\n', encoding="utf-8")
        globals()["portaudio_device_identity"] = fake_portaudio_device_identity
        globals()["record_playback"] = fake_silent_record_playback
        try:
            silent_result = route_probe(
                argparse.Namespace(
                    adapter_id=DEFAULT_ROUTE_PROBE_ADAPTER_ID,
                    allow_shared_output_device=False,
                    duration_s=0.05,
                    headphone_output_device="3",
                    input_channels=1,
                    lead_s=0.0,
                    max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                    max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                    max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                    max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                    measurement_input_device="1",
                    min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                    min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                    output_channels=2,
                    output_dir=root / "route-out",
                    playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                    run_id="silent-route",
                    sample_rate_hz=sample_rate_hz,
                    score_warning_only=True,
                    source_output_device="2",
                    tail_s=0.0,
                )
            )
        finally:
            globals()["portaudio_device_identity"] = original_portaudio_device_identity
            globals()["record_playback"] = original_record_playback
        if silent_result != 0:
            raise RuntimeError("warning-only silent route probe self-test should return 0")
        silent_report = json.loads(silent_report_path.read_text(encoding="utf-8"))
        if silent_report.get("stale"):
            raise RuntimeError("silent route probe should replace stale reports")
        if bool(silent_report.get("summary", {}).get("passed")):
            raise RuntimeError("expected silent route probe self-test fixture to fail")
        json.dumps(silent_report, allow_nan=False)
        preflight_report_path = (
            root
            / "route-out"
            / "runs"
            / "preflight-failure"
            / "headphone-route-probe-report.json"
        )
        preflight_report_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_report_path.write_text('{"stale": true}\n', encoding="utf-8")

        def fake_failing_portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
            raise ValueError("unit preflight failure")

        globals()["portaudio_device_identity"] = fake_failing_portaudio_device_identity
        try:
            try:
                route_probe(
                    argparse.Namespace(
                        adapter_id=DEFAULT_ROUTE_PROBE_ADAPTER_ID,
                        allow_shared_output_device=False,
                        duration_s=0.05,
                        headphone_output_device="3",
                        input_channels=1,
                        lead_s=0.0,
                        max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                        max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                        max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                        max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                        measurement_input_device="1",
                        min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                        min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                        output_channels=2,
                        output_dir=root / "route-out",
                        playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                        run_id="preflight-failure",
                        sample_rate_hz=sample_rate_hz,
                        score_warning_only=True,
                        source_output_device="2",
                        tail_s=0.0,
                    )
                )
            except ValueError:
                pass
            else:
                raise RuntimeError("expected route probe preflight self-test fixture to raise")
        finally:
            globals()["portaudio_device_identity"] = original_portaudio_device_identity
        if preflight_report_path.exists():
            raise RuntimeError("route probe preflight failure should remove stale reports")
    print("headphone/earpiece isolation contract self-test PASS")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score measured headphone/earpiece source isolation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-devices", help="list PortAudio devices for guided host capture")
    subparsers.add_parser("self-test", help="validate scoring gates without external artifacts")
    score_parser = subparsers.add_parser(
        "score",
        help="score listener-ear source isolation and translated headphone playback WAVs",
    )
    score_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    score_parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    score_parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    score_parser.add_argument("--source-reference", type=Path, required=True)
    score_parser.add_argument("--source-open-ear-recording", type=Path, required=True)
    score_parser.add_argument("--source-isolated-ear-recording", type=Path, required=True)
    score_parser.add_argument("--translated-playback-reference", type=Path, required=True)
    score_parser.add_argument("--translated-headphone-recording", type=Path, required=True)
    score_parser.add_argument("--headphone-device-label", required=True)
    score_parser.add_argument("--isolation-fixture-label", required=True)
    score_parser.add_argument("--measurement-microphone-label", required=True)
    score_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    score_parser.add_argument("--procedure-note", default="listener-ear measurement")
    score_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    score_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    score_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    score_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    score_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    score_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    score_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    score_parser.add_argument("--score-warning-only", action="store_true")
    capture_parser = subparsers.add_parser(
        "capture",
        help="guide a host PortAudio measurement and then score the captured WAV artifacts",
    )
    capture_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    capture_parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    capture_parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    capture_parser.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    capture_parser.add_argument("--source-reference", type=Path)
    capture_parser.add_argument("--translated-playback-reference", type=Path)
    capture_parser.add_argument("--measurement-input-device", required=True)
    capture_parser.add_argument("--source-output-device", required=True)
    capture_parser.add_argument("--headphone-output-device", required=True)
    capture_parser.add_argument("--input-channels", type=int, default=DEFAULT_CAPTURE_INPUT_CHANNELS)
    capture_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    capture_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    capture_parser.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    capture_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    capture_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    capture_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    capture_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    capture_parser.add_argument("--max-reference-duration-s", type=float, default=8.0)
    capture_parser.add_argument("--headphone-device-label", required=True)
    capture_parser.add_argument("--isolation-fixture-label", required=True)
    capture_parser.add_argument("--measurement-microphone-label", required=True)
    capture_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    capture_parser.add_argument("--procedure-note", default="guided host listener-ear measurement")
    capture_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    capture_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    capture_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    capture_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    capture_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    capture_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    capture_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    capture_parser.add_argument("--score-warning-only", action="store_true")
    capture_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="print measurement steps without waiting for Enter before each capture",
    )
    probe_parser = subparsers.add_parser(
        "probe-route",
        help="triage whether source/headphone output routes can open and be heard by the measurement input",
    )
    probe_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    probe_parser.add_argument("--run-id", default=DEFAULT_ROUTE_PROBE_RUN_ID)
    probe_parser.add_argument("--adapter-id", default=DEFAULT_ROUTE_PROBE_ADAPTER_ID)
    probe_parser.add_argument("--measurement-input-device", required=True)
    probe_parser.add_argument("--source-output-device", required=True)
    probe_parser.add_argument("--headphone-output-device", required=True)
    probe_parser.add_argument("--input-channels", type=int, default=DEFAULT_CAPTURE_INPUT_CHANNELS)
    probe_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    probe_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    probe_parser.add_argument("--duration-s", type=float, default=DEFAULT_ROUTE_PROBE_DURATION_S)
    probe_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    probe_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    probe_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    probe_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    probe_parser.add_argument("--min-route-probe-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    probe_parser.add_argument(
        "--min-route-probe-correlation",
        type=float,
        default=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
    )
    probe_parser.add_argument(
        "--max-route-probe-distortion-db",
        type=float,
        default=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
    )
    probe_parser.add_argument(
        "--max-route-probe-clipped-samples",
        type=int,
        default=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
    )
    probe_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    probe_parser.add_argument(
        "--allow-shared-output-device",
        action="store_true",
        help="allow source and headphone outputs to resolve to the same PortAudio device for explicit multi-channel hardware tests",
    )
    probe_parser.add_argument("--score-warning-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "list-devices":
        return list_devices()
    if args.command == "self-test":
        return self_test()
    if args.command == "score":
        return score(args)
    if args.command == "capture":
        return capture(args)
    if args.command == "probe-route":
        return route_probe(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
