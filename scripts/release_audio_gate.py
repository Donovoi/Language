#!/usr/bin/env python3
"""Fail product releases until the realtime audio-loop evidence exists.

Exploratory audio-eval targets are allowed to be warning-only so research can
keep moving. This gate is harsher: it writes a durable release-readiness report
and exits non-zero while any release-blocking product audio capability is still
missing, failing, stubbed, or only proven by a prototype fixture.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import json
import math
import sys
import tempfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_AUDIO_EVAL_DIR = Path("artifacts/audio_eval")
DEFAULT_RELEASE_REPORT = Path("artifacts/release/audio-gate-report.json")
DEFAULT_RELEASE_MARKDOWN_REPORT = Path("artifacts/release/audio-gate-report.md")
DEFAULT_LIVE_CAPTURE_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/live-microphone-capture/live-microphone-capture-report.json"
)
DEFAULT_CAUSAL_DIARIZATION_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR
    / "runs/sortformer-streaming-4spk-v2-1-real-speech-rolling-pcm/rolling-diarization-report.json"
)
DEFAULT_TSE_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/fleurs-wesep-enrolled-target-speaker-extraction/wesep-enrolled-tse-report.json"
)
DEFAULT_STREAMING_TRANSLATION_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR
    / "runs/whisper-tiny-fleurs-wesep-causal-tse-translation/whisper-tse-translation-report.json"
)
DEFAULT_VOICE_REPORT = DEFAULT_AUDIO_EVAL_DIR / "runs/same-voice-tts/voice-clone-report.json"
DEFAULT_ROOM_SUPPRESSION_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/real-room-playback-suppression/room-playback-suppression-report.json"
)
DEFAULT_HEADPHONE_ISOLATION_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/headphone-earpiece-isolation/headphone-isolation-report.json"
)
DEFAULT_PLAYBACK_PROTOTYPE_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/fleurs-playback-ducking-suppression/playback-suppression-report.json"
)
DEFAULT_CAPTURE_PROTOTYPE_REPORT = (
    DEFAULT_AUDIO_EVAL_DIR / "runs/fixture-live-pcm-capture/capture-runtime-report.json"
)
EXPECTED_LIVE_CAPTURE_ADAPTER_ID = "sounddevice_portaudio_microphone_capture_v1"
EXPECTED_LIVE_CAPTURE_BACKEND = "sounddevice_portaudio_callback"
EXPECTED_LIVE_CAPTURE_GENERATOR = "scripts/run_live_microphone_capture.py"
EXPECTED_LIVE_CAPTURE_PROVENANCE_KIND = "host_portaudio_callback_artifact_coherence"
EXPECTED_LIVE_CAPTURE_TRUST_BOUNDARY = "local_artifact_coherence_not_tamper_proof"

PLAYBACK_PROTOTYPE_CLAIM = "ducking_masking_simulation_not_true_cancellation"
PROTOTYPE_FIXTURE_KINDS = {
    "fixture_pcm_capture_replay",
    "fleurs_playback_suppression",
}

LIVE_CAPTURE_REQUIRED_GATES = {
    "capture_source_is_microphone",
    "capture_device_identity_present",
    "capture_provenance_scope_declared",
    "pcm_chunk_schema_valid",
    "chunk_timing_jitter_within_limit",
    "no_chunk_gaps_or_reorders",
    "capture_sample_rate_stable",
    "capture_duration_minimum",
    "capture_chunk_count",
    "capture_callback_status_clean",
    "capture_input_not_silent",
    "capture_artifact_hash_chain_present",
    "capture_timestamps_monotonic",
    "capture_release_proof",
}
CAUSAL_DIARIZATION_REQUIRED_GATES = {
    "chunked_chunk_count",
    "chunked_final_der_like",
    "chunked_first_speech_detection_latency",
    "chunked_overlap_detected",
}
TSE_ORACLE_QUALITY_GATES = {
    "tse_prediction_segment_count",
    "tse_overlap_covered",
    "tse_min_segment_snr_db",
    "tse_min_interferer_reduction_db",
    "tse_output_level_preserved",
    "tse_duration_preserved",
    "tse_extracted_audio_hashed",
}
TSE_REAL_MODEL_REQUIRED_GATES = {
    "tse_prediction_segment_count",
    "tse_overlap_covered",
    "tse_duration_preserved",
    "tse_extracted_audio_hashed",
    "tse_polarity_invariant_scoring_declared",
    "tse_real_model_not_oracle",
    "tse_real_model_enrollment_contract_passed",
    "tse_real_model_postprocess_declared",
    "tse_real_model_beats_passthrough_mean_snr",
    "tse_real_model_beats_passthrough_mean_interferer_reduction",
    "tse_real_model_min_segment_snr_floor",
    "tse_real_model_output_level_preserved",
    "tse_real_model_polarity_invariant_scoring_declared",
}
TSE_PASSTHROUGH_GATES = {
    "beats_mixture_passthrough",
    "target_to_interferer_ratio_beats_passthrough",
    "wesep_beats_passthrough_mean_snr",
}
TRANSLATION_REQUIRED_GATES = {
    "tse_quality_gates_passed",
}
ORACLE_TRANSLATION_STREAMING_PREFIXES = ("oracle_diarization_",)
ORACLE_DIARIZATION_ADAPTER_IDS = {"oracle_diarization_v1"}
VOICE_REQUIRED_GATES = {
    "voice_reference_consent_present",
    "tts_audio_hashed",
    "tts_output_level_matched",
    "voice_similarity_or_fallback_declared",
}
VOICE_CANDIDATE_SIMILARITY_CLAIMS = {"measured_proxy", "asv_similarity_measured"}
VOICE_CANDIDATE_MIN_SIMILARITY_SCORE = 0.65
VOICE_CANDIDATE_SIMILARITY_SCORE_TOLERANCE = 0.01
VOICE_CANDIDATE_METRIC_NAME = "release_gate_acoustic_proxy_v1"
VOICE_CANDIDATE_EVALUATOR_ID = "language_release_gate_builtin_v1"
VOICE_CANDIDATE_ALLOWED_RETENTION_POLICIES = {
    "ephemeral_reference_deleted",
    "ephemeral_reference_not_persisted",
    "consented_retention_with_expiry",
}
ROOM_SUPPRESSION_REQUIRED_GATES = {
    "device_path_identity_recorded",
    "room_loopback_recorded",
    "calibration_recordings_audible",
    "calibration_reference_fidelity",
    "source_residual_measured",
    "translated_output_not_distorted",
    "suppression_claim_matches_measurement",
    "room_suppression_artifacts_hashed",
}
ROOM_REQUIRED_MEASUREMENT_KIND = "real_room_loopback"
ROOM_REQUIRED_SUPPRESSION_CLAIM = "true_source_cancellation"
ROOM_MIN_SOURCE_RESIDUAL_REDUCTION_DB = 6.0
ROOM_MAX_TRANSLATED_OUTPUT_DISTORTION_DB = 12.0
ROOM_MIN_TRANSLATED_OUTPUT_CORRELATION = 0.3
ROOM_MIN_CALIBRATION_DBFS = -60.0
ROOM_MIN_CALIBRATION_CORRELATION = 0.3
ROOM_MAX_CALIBRATION_DISTORTION_DB = 12.0
ROOM_DB_TOLERANCE = 0.075
ROOM_CORRELATION_TOLERANCE = 0.001
ROOM_MAX_ALIGNMENT_LAG_MS = 500.0
HEADPHONE_ISOLATION_REQUIRED_GATES = {
    "headphone_measurement_release_proof",
    "headphone_mode_claim_declared",
    "headphone_claim_not_true_cancellation",
    "headphone_device_identity_recorded",
    "headphone_capture_source_declared",
    "headphone_guided_capture_preflight_bound",
    "isolation_fixture_identity_recorded",
    "headphone_recordings_duration_floor",
    "headphone_release_alignment_window",
    "open_ear_source_control_audible",
    "headphone_source_open_reference_fidelity",
    "source_isolation_measured",
    "translated_headphone_output_audible",
    "translated_headphone_output_not_distorted",
    "headphone_artifacts_hashed",
    "headphone_metrics_are_wav_derived",
    "headphone_recordings_not_reference_clones",
}
HEADPHONE_REQUIRED_FIXTURE_KIND = "headphone_earpiece_isolation"
HEADPHONE_REQUIRED_BENCHMARK_NAME = "headphone_earpiece_isolation"
HEADPHONE_REQUIRED_MEASUREMENT_KIND = "headphone_earpiece_isolation"
HEADPHONE_REQUIRED_SUPPRESSION_MODE = "HEADPHONE_ISOLATED"
HEADPHONE_REQUIRED_SUPPRESSION_CLAIM = "headphone_isolated_not_true_cancellation"
HEADPHONE_CAPTURE_BACKENDS = {"external_wav_measurement", "sounddevice_portaudio_guided_playrec"}
HEADPHONE_CAPTURE_SOURCE_KINDS = {
    "external_listener_ear_wav_measurement",
    "host_guided_listener_ear_playrec_measurement",
}
HEADPHONE_CAPTURE_SOURCE_PAIRS = {
    "external_wav_measurement": "external_listener_ear_wav_measurement",
    "sounddevice_portaudio_guided_playrec": "host_guided_listener_ear_playrec_measurement",
}
HEADPHONE_GUIDED_CAPTURE_BACKEND = "sounddevice_portaudio_guided_playrec"
HEADPHONE_REQUIRED_ARTIFACTS = (
    "source_reference",
    "source_open_ear_recording",
    "source_isolated_ear_recording",
    "translated_playback_reference",
    "translated_headphone_recording",
)
HEADPHONE_MIN_SOURCE_OPEN_DBFS = -60.0
HEADPHONE_MIN_TRANSLATED_DBFS = -60.0
HEADPHONE_MIN_SOURCE_OPEN_CORRELATION = 0.30
HEADPHONE_MIN_TRANSLATED_CORRELATION = 0.30
HEADPHONE_MIN_SOURCE_ISOLATION_DB = 12.0
HEADPHONE_MIN_MEASUREMENT_DURATION_S = 1.0
HEADPHONE_MAX_TRANSLATED_DISTORTION_DB = 12.0
HEADPHONE_DB_TOLERANCE = 0.075
HEADPHONE_CORRELATION_TOLERANCE = 0.001
HEADPHONE_DURATION_TOLERANCE_S = 0.001
PLACEHOLDER_LABEL_PREFIXES = (
    "unspecified",
    "unknown",
    "todo",
    "placeholder",
    "replace_with",
    "replace-with",
    "replace with",
    "virtual",
    "simulated",
    "synthetic",
)


@dataclass(frozen=True)
class EvidenceSpec:
    name: str
    path: Path
    description: str
    next_step: str
    release_blocking: bool = True


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    release_blocking: bool
    message: str
    path: str
    next_step: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "release_blocking": self.release_blocking,
            "message": self.message,
            "path": self.path,
            "next_step": self.next_step,
        }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def _summary(report: dict[str, Any]) -> dict[str, Any]:
    summary = report.get("summary", {})
    return summary if isinstance(summary, dict) else {}


def _summary_passed(report: dict[str, Any]) -> bool:
    return bool(_summary(report).get("passed"))


def _quality_gates(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    gates = _summary(report).get("quality_gates", [])
    named: dict[str, dict[str, Any]] = {}
    if not isinstance(gates, list):
        return named
    for gate in gates:
        if isinstance(gate, dict) and isinstance(gate.get("name"), str):
            named[str(gate["name"])] = gate
    return named


def _gate_passed(report: dict[str, Any], name: str) -> bool:
    gate = _quality_gates(report).get(name)
    return isinstance(gate, dict) and bool(gate.get("passed"))


def _missing_gates(report: dict[str, Any], required: set[str]) -> list[str]:
    return sorted(name for name in required if not _gate_passed(report, name))


def _pass_fail_prefix(spec: EvidenceSpec, report: dict[str, Any] | None) -> GateResult | None:
    if report is None:
        return GateResult(
            spec.name,
            False,
            spec.release_blocking,
            f"missing required report: {spec.description}",
            str(spec.path),
            spec.next_step,
        )
    if not _summary_passed(report):
        return GateResult(
            spec.name,
            False,
            spec.release_blocking,
            f"report is present but did not pass: {spec.description}",
            str(spec.path),
            spec.next_step,
        )
    return None


def _fail(spec: EvidenceSpec, message: str) -> GateResult:
    return GateResult(
        spec.name,
        False,
        spec.release_blocking,
        message,
        str(spec.path),
        spec.next_step,
    )


def _pass(spec: EvidenceSpec, message: str = "passing product-specific evidence present") -> GateResult:
    return GateResult(
        spec.name,
        True,
        spec.release_blocking,
        message,
        str(spec.path),
        spec.next_step,
    )


def _reject_prototype_fixture(spec: EvidenceSpec, report: dict[str, Any]) -> GateResult | None:
    fixture_kind = report.get("fixture_kind")
    if fixture_kind in PROTOTYPE_FIXTURE_KINDS:
        return _fail(spec, f"prototype fixture report cannot satisfy product gate: {fixture_kind}")
    return None


def _capture_summary(report: dict[str, Any]) -> dict[str, Any]:
    capture = report.get("benchmarks", {}).get("capture", {})
    if isinstance(capture, dict):
        summary = capture.get("summary", {})
        if isinstance(summary, dict):
            return summary
    return {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _device_path_fingerprint(
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


def _headphone_measurement_identity_fingerprint(
    summary: dict[str, Any],
    artifact_hashes: dict[str, Any],
) -> str:
    sample_rate_hz = _float_or_none(summary.get("sample_rate_hz"))
    payload = {
        "artifact_hashes": {
            key: str(artifact_hashes.get(key, ""))
            for key in HEADPHONE_REQUIRED_ARTIFACTS
        },
        "headphone_device_label": str(summary.get("headphone_device_label", "")),
        "isolation_fixture_label": str(summary.get("isolation_fixture_label", "")),
        "measurement_kind": HEADPHONE_REQUIRED_MEASUREMENT_KIND,
        "measurement_microphone_label": str(summary.get("measurement_microphone_label", "")),
        "sample_rate_hz": int(sample_rate_hz) if sample_rate_hz is not None else None,
        "source_suppression_mode": HEADPHONE_REQUIRED_SUPPRESSION_MODE,
        "suppression_claim": HEADPHONE_REQUIRED_SUPPRESSION_CLAIM,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _headphone_guided_device_fingerprint(summary: dict[str, Any]) -> str:
    device_info = summary.get("device_info")
    sample_rate_hz = _float_or_none(summary.get("sample_rate_hz"))
    capture = summary.get("capture")
    capture = capture if isinstance(capture, dict) else {}
    payload = {
        "device_info": device_info,
        "input_channels": int(_float_or_none(capture.get("input_channels")) or 1),
        "output_channels": int(_float_or_none(capture.get("output_channels")) or 2),
        "sample_rate_hz": int(sample_rate_hz) if sample_rate_hz is not None else None,
    }
    data = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _resolve_artifact_path(report_path: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path
    beside_report = report_path.parent / path
    if beside_report.exists():
        return beside_report
    return path


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            record = json.loads(text)
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number} did not contain a JSON object")
            records.append(record)
    return records


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value.lower())
    )


def _specific_measurement_label(value: Any) -> bool:
    text = str(value).strip()
    return bool(text) and not text.lower().startswith(PLACEHOLDER_LABEL_PREFIXES)


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _linear_to_db(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return float(20.0 * math.log10(value))


def _dbfs_from_rms_i16(rms_value: float) -> float:
    return _linear_to_db((rms_value + 1.0e-12) / 32768.0)


def _read_mono_pcm16_wav(path: Path) -> tuple[int, array.array]:
    with wave.open(str(path), "rb") as wav:
        if wav.getnchannels() != 1:
            raise ValueError(f"{path} must be mono")
        if wav.getsampwidth() != 2:
            raise ValueError(f"{path} must be 16-bit PCM")
        frame_count = wav.getnframes()
        if frame_count <= 0:
            raise ValueError(f"{path} must contain frames")
        raw = wav.readframes(frame_count)
        sample_rate_hz = wav.getframerate()
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    return sample_rate_hz, samples


def _mono_pcm16_wav_samples_and_details(path: Path) -> tuple[array.array, dict[str, Any]]:
    with wave.open(str(path), "rb") as wav:
        channels = int(wav.getnchannels())
        sample_width = int(wav.getsampwidth())
        sample_rate_hz = int(wav.getframerate())
        frame_count = int(wav.getnframes())
        raw = wav.readframes(frame_count)
    if channels != 1:
        raise ValueError(f"{path} must be mono")
    if sample_width != 2:
        raise ValueError(f"{path} must be 16-bit PCM")
    if sample_rate_hz <= 0 or frame_count <= 0:
        raise ValueError(f"{path} must contain frames")
    samples = array.array("h")
    samples.frombytes(raw)
    if sys.byteorder != "little":
        samples.byteswap()
    rms_value = _rms_i16(samples)
    peak = max(abs(int(sample)) for sample in samples) if samples else 0
    details = {
        "dbfs": _dbfs_from_rms_i16(rms_value),
        "frame_count": frame_count,
        "pcm_sha256": hashlib.sha256(raw).hexdigest(),
        "peak_dbfs": _dbfs_from_rms_i16(float(peak)),
        "sample_rate_hz": sample_rate_hz,
        "sha256": _sha256_file(path),
    }
    return samples, details


def _mono_pcm16_wav_details(path: Path) -> dict[str, Any]:
    _samples, details = _mono_pcm16_wav_samples_and_details(path)
    return details


def _frame_acoustic_features(samples: array.array, sample_rate_hz: int) -> list[float]:
    frame_len = max(1, int(round(sample_rate_hz * 0.04)))
    hop = max(1, int(round(sample_rate_hz * 0.02)))
    frame_starts = [0] if len(samples) < frame_len else list(range(0, len(samples) - frame_len + 1, hop))
    lag = max(1, int(round(sample_rate_hz * 0.005)))
    rows: list[list[float]] = []
    for start in frame_starts:
        frame = [float(sample) / 32768.0 for sample in samples[start : start + frame_len]]
        if not frame:
            continue
        if len(frame) < frame_len:
            frame.extend([0.0] * (frame_len - len(frame)))
        frame_rms = math.sqrt(sum(value * value for value in frame) / float(len(frame)))
        if len(frame) > 1:
            zcr = sum(
                1
                for left, right in zip(frame, frame[1:])
                if (left < 0.0) != (right < 0.0)
            ) / float(len(frame) - 1)
            deltas = [abs(right - left) for left, right in zip(frame, frame[1:])]
            mean_abs_delta = sum(deltas) / float(len(deltas))
        else:
            zcr = 0.0
            mean_abs_delta = 0.0
        if len(frame) > lag and frame_rms > 0.0:
            lhs = frame[:-lag]
            rhs = frame[lag:]
            lhs_energy = sum(value * value for value in lhs)
            rhs_energy = sum(value * value for value in rhs)
            denom = math.sqrt(lhs_energy * rhs_energy)
            autocorr = sum(left * right for left, right in zip(lhs, rhs)) / denom if denom > 0.0 else 0.0
        else:
            autocorr = 0.0
        rows.append([frame_rms, zcr, mean_abs_delta, autocorr])
    if not rows:
        return [0.0] * 8
    means = [sum(row[column] for row in rows) / float(len(rows)) for column in range(4)]
    stds = [
        math.sqrt(sum((row[column] - means[column]) ** 2 for row in rows) / float(len(rows)))
        for column in range(4)
    ]
    return means + stds


def _acoustic_similarity_proxy(
    reference_samples: array.array,
    output_samples: array.array,
    sample_rate_hz: int,
) -> float:
    reference_vector = _frame_acoustic_features(reference_samples, sample_rate_hz)
    output_vector = _frame_acoustic_features(output_samples, sample_rate_hz)
    scale = [0.2, 0.2, 0.05, 1.0, 0.1, 0.1, 0.03, 0.5]
    distance = math.sqrt(
        sum(
            ((reference_value - output_value) / feature_scale) ** 2
            for reference_value, output_value, feature_scale in zip(reference_vector, output_vector, scale)
        )
        / float(len(scale))
    )
    return 1.0 / (1.0 + distance)


def _rms_i16(samples: array.array, frame_count: int | None = None) -> float:
    count = min(len(samples), frame_count) if frame_count is not None else len(samples)
    if count <= 0:
        return 0.0
    total = 0.0
    for index in range(count):
        value = float(samples[index])
        total += value * value
    return math.sqrt(total / float(count))


def _projection_gain_i16(target: array.array, reference: array.array, frame_count: int | None = None) -> float:
    count = min(len(target), len(reference), frame_count) if frame_count is not None else min(len(target), len(reference))
    if count <= 0:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for index in range(count):
        target_value = float(target[index])
        reference_value = float(reference[index])
        numerator += target_value * reference_value
        denominator += reference_value * reference_value
    if denominator <= 1.0e-12:
        return 0.0
    return numerator / denominator


def _best_alignment_lag_samples(
    measured: Any,
    reference: Any,
    sample_rate_hz: int,
    max_lag_ms: float,
    *,
    stride: int = 64,
) -> int:
    frame_count = min(len(measured), len(reference))
    max_lag_samples = max(0, int(round(float(sample_rate_hz) * float(max_lag_ms) / 1000.0)))
    if frame_count <= stride * 2 or max_lag_samples <= 0:
        return 0
    measured_values = [float(measured[index]) for index in range(0, frame_count, stride)]
    reference_values = [float(reference[index]) for index in range(0, frame_count, stride)]
    measured_mean = sum(measured_values) / float(len(measured_values))
    reference_mean = sum(reference_values) / float(len(reference_values))
    measured_values = [value - measured_mean for value in measured_values]
    reference_values = [value - reference_mean for value in reference_values]
    max_lag_steps = min(max_lag_samples // stride, max(0, min(len(measured_values), len(reference_values)) - 2))
    best_lag_steps = 0
    best_score = float("-inf")
    for lag_steps in range(-max_lag_steps, max_lag_steps + 1):
        if lag_steps > 0:
            measured_slice = measured_values[lag_steps:]
            reference_slice = reference_values[: len(measured_slice)]
        elif lag_steps < 0:
            measured_slice = measured_values[: len(measured_values) + lag_steps]
            reference_slice = reference_values[-lag_steps : -lag_steps + len(measured_slice)]
        else:
            measured_slice = measured_values
            reference_slice = reference_values[: len(measured_slice)]
        if len(measured_slice) <= 1:
            continue
        numerator = 0.0
        measured_energy = 0.0
        reference_energy = 0.0
        for measured_value, reference_value in zip(measured_slice, reference_slice):
            numerator += measured_value * reference_value
            measured_energy += measured_value * measured_value
            reference_energy += reference_value * reference_value
        denominator = math.sqrt(measured_energy * reference_energy)
        if denominator <= 1.0e-12:
            continue
        score = abs(numerator / denominator)
        if score > best_score:
            best_score = score
            best_lag_steps = lag_steps
    return int(best_lag_steps * stride)


def _align_numeric_sequences(a: Any, b: Any, lag_samples: int) -> tuple[list[float], list[float]]:
    frame_count = min(len(a), len(b))
    if frame_count <= 0:
        return [], []
    if lag_samples > 0:
        lag = min(lag_samples, frame_count)
        count = min(len(a) - lag, len(b))
        return (
            [float(a[index]) for index in range(lag, lag + count)],
            [float(b[index]) for index in range(count)],
        )
    if lag_samples < 0:
        lag = min(-lag_samples, frame_count)
        count = min(len(a), len(b) - lag)
        return (
            [float(a[index]) for index in range(count)],
            [float(b[index]) for index in range(lag, lag + count)],
        )
    count = frame_count
    return (
        [float(a[index]) for index in range(count)],
        [float(b[index]) for index in range(count)],
    )


def _projection_gain_values(target: list[float], reference: list[float]) -> float:
    count = min(len(target), len(reference))
    if count <= 0:
        return 0.0
    numerator = 0.0
    denominator = 0.0
    for index in range(count):
        numerator += target[index] * reference[index]
        denominator += reference[index] * reference[index]
    if denominator <= 1.0e-12:
        return 0.0
    return numerator / denominator


def _correlation_values(a: list[float], b: list[float]) -> float:
    count = min(len(a), len(b))
    if count <= 1:
        return 0.0
    mean_a = sum(a[:count]) / float(count)
    mean_b = sum(b[:count]) / float(count)
    numerator = 0.0
    a_energy = 0.0
    b_energy = 0.0
    for index in range(count):
        a_value = a[index] - mean_a
        b_value = b[index] - mean_b
        numerator += a_value * b_value
        a_energy += a_value * a_value
        b_energy += b_value * b_value
    denominator = math.sqrt(a_energy * b_energy)
    if denominator <= 1.0e-12:
        return 0.0
    return numerator / denominator


def _distortion_db_values(measured: list[float], reference: list[float]) -> float:
    count = min(len(measured), len(reference))
    if count <= 0:
        return float("inf")
    gain = _projection_gain_values(measured[:count], reference[:count])
    error_energy = 0.0
    aligned_energy = 0.0
    for index in range(count):
        aligned = reference[index] * gain
        error = measured[index] - aligned
        error_energy += error * error
        aligned_energy += aligned * aligned
    error_rms = math.sqrt(error_energy / float(count))
    aligned_rms = math.sqrt(aligned_energy / float(count))
    return _linear_to_db((error_rms + 1.0e-12) / (aligned_rms + 1.0e-12))


def _recompute_room_metrics(artifact_paths: dict[str, Path]) -> dict[str, float]:
    source_rate, source = _read_mono_pcm16_wav(artifact_paths["source_only_room_recording"])
    source_reference_rate, source_reference = _read_mono_pcm16_wav(artifact_paths["source_reference"])
    translated_rate, translated = _read_mono_pcm16_wav(artifact_paths["translated_only_room_recording"])
    translated_reference_rate, translated_reference = _read_mono_pcm16_wav(artifact_paths["translated_playback_reference"])
    loopback_rate, loopback = _read_mono_pcm16_wav(artifact_paths["room_loopback_recording"])
    if len({source_rate, source_reference_rate, translated_rate, translated_reference_rate, loopback_rate}) != 1:
        raise ValueError("room calibration and loopback WAV sample rates must match")
    frame_count = min(len(source), len(translated), len(loopback))
    if frame_count <= 0:
        raise ValueError("room calibration and loopback WAVs must contain overlapping frames")
    source_lag = _best_alignment_lag_samples(loopback, source, source_rate, ROOM_MAX_ALIGNMENT_LAG_MS)
    aligned_loopback, aligned_source = _align_numeric_sequences(loopback, source, source_lag)
    raw_gain = _projection_gain_values(aligned_loopback, aligned_source)
    residual_gain = abs(raw_gain)
    source_reduction_db = -_linear_to_db(residual_gain) if residual_gain > 0.0 else 120.0
    source_rms = _rms_i16(source, frame_count)
    source_reference_lag = _best_alignment_lag_samples(
        source,
        source_reference,
        source_rate,
        ROOM_MAX_ALIGNMENT_LAG_MS,
    )
    aligned_source_recording, aligned_source_reference = _align_numeric_sequences(
        source,
        source_reference,
        source_reference_lag,
    )
    translated_reference_lag = _best_alignment_lag_samples(
        translated,
        translated_reference,
        translated_rate,
        ROOM_MAX_ALIGNMENT_LAG_MS,
    )
    aligned_translated_recording, aligned_translated_reference = _align_numeric_sequences(
        translated,
        translated_reference,
        translated_reference_lag,
    )
    component = [
        loopback_value - (source_value * raw_gain)
        for loopback_value, source_value in zip(aligned_loopback, aligned_source)
    ]
    translated_lag = _best_alignment_lag_samples(
        component,
        translated,
        translated_rate,
        ROOM_MAX_ALIGNMENT_LAG_MS,
    )
    aligned_component, aligned_translated = _align_numeric_sequences(component, translated, translated_lag)
    return {
        "max_alignment_lag_ms": ROOM_MAX_ALIGNMENT_LAG_MS,
        "source_calibration_dbfs": _dbfs_from_rms_i16(source_rms),
        "source_calibration_reference_correlation": _correlation_values(
            aligned_source_recording,
            aligned_source_reference,
        ),
        "source_calibration_reference_distortion_db": _distortion_db_values(
            aligned_source_recording,
            aligned_source_reference,
        ),
        "source_calibration_reference_lag_samples": float(source_reference_lag),
        "source_alignment_lag_samples": float(source_lag),
        "source_residual_dbfs": _dbfs_from_rms_i16(source_rms * residual_gain),
        "source_residual_reduction_db": source_reduction_db,
        "translated_calibration_reference_correlation": _correlation_values(
            aligned_translated_recording,
            aligned_translated_reference,
        ),
        "translated_calibration_reference_distortion_db": _distortion_db_values(
            aligned_translated_recording,
            aligned_translated_reference,
        ),
        "translated_calibration_reference_lag_samples": float(translated_reference_lag),
        "translated_alignment_lag_samples": float(translated_lag),
        "translated_output_correlation": _correlation_values(aligned_component, aligned_translated),
        "translated_output_distortion_db": _distortion_db_values(aligned_component, aligned_translated),
        "translated_reference_dbfs": _dbfs_from_rms_i16(_rms_i16(translated, frame_count)),
    }


def _reference_recording_metrics_i16(
    recording: array.array,
    reference: array.array,
    sample_rate_hz: int,
) -> dict[str, float]:
    lag_samples = _best_alignment_lag_samples(
        recording,
        reference,
        sample_rate_hz,
        ROOM_MAX_ALIGNMENT_LAG_MS,
    )
    aligned_recording, aligned_reference = _align_numeric_sequences(
        recording,
        reference,
        lag_samples,
    )
    gain = abs(_projection_gain_values(aligned_recording, aligned_reference))
    return {
        "correlation": _correlation_values(aligned_recording, aligned_reference),
        "distortion_db": _distortion_db_values(aligned_recording, aligned_reference),
        "gain_db": _linear_to_db(gain) if gain > 0.0 else float("-inf"),
        "lag_samples": float(lag_samples),
        "recording_dbfs": _dbfs_from_rms_i16(_rms_i16(recording)),
    }


def _recompute_headphone_isolation_metrics(artifact_paths: dict[str, Path]) -> dict[str, float]:
    source_rate, source_reference = _read_mono_pcm16_wav(artifact_paths["source_reference"])
    source_open_rate, source_open = _read_mono_pcm16_wav(artifact_paths["source_open_ear_recording"])
    source_isolated_rate, source_isolated = _read_mono_pcm16_wav(
        artifact_paths["source_isolated_ear_recording"]
    )
    translated_rate, translated_reference = _read_mono_pcm16_wav(
        artifact_paths["translated_playback_reference"]
    )
    translated_recording_rate, translated_recording = _read_mono_pcm16_wav(
        artifact_paths["translated_headphone_recording"]
    )
    if len({source_rate, source_open_rate, source_isolated_rate, translated_rate, translated_recording_rate}) != 1:
        raise ValueError("headphone isolation WAV sample rates must match")
    min_artifact_duration_s = min(
        len(source_reference),
        len(source_open),
        len(source_isolated),
        len(translated_reference),
        len(translated_recording),
    ) / float(source_rate)
    source_open_metrics = _reference_recording_metrics_i16(source_open, source_reference, source_rate)
    source_isolated_metrics = _reference_recording_metrics_i16(
        source_isolated,
        source_reference,
        source_rate,
    )
    translated_metrics = _reference_recording_metrics_i16(
        translated_recording,
        translated_reference,
        source_rate,
    )
    return {
        "min_artifact_duration_s": min_artifact_duration_s,
        "sample_rate_hz": float(source_rate),
        "source_isolated_gain_db": source_isolated_metrics["gain_db"],
        "source_isolated_recording_dbfs": source_isolated_metrics["recording_dbfs"],
        "source_isolated_reference_correlation": source_isolated_metrics["correlation"],
        "source_isolated_reference_distortion_db": source_isolated_metrics["distortion_db"],
        "source_isolated_reference_lag_samples": source_isolated_metrics["lag_samples"],
        "source_isolation_db": source_open_metrics["gain_db"] - source_isolated_metrics["gain_db"],
        "source_open_gain_db": source_open_metrics["gain_db"],
        "source_open_recording_dbfs": source_open_metrics["recording_dbfs"],
        "source_open_reference_correlation": source_open_metrics["correlation"],
        "source_open_reference_distortion_db": source_open_metrics["distortion_db"],
        "source_open_reference_lag_samples": source_open_metrics["lag_samples"],
        "translated_headphone_gain_db": translated_metrics["gain_db"],
        "translated_headphone_recording_dbfs": translated_metrics["recording_dbfs"],
        "translated_headphone_reference_correlation": translated_metrics["correlation"],
        "translated_headphone_reference_distortion_db": translated_metrics["distortion_db"],
        "translated_headphone_reference_lag_samples": translated_metrics["lag_samples"],
    }


def _room_metric_tolerance(field: str) -> float:
    return ROOM_CORRELATION_TOLERANCE if field.endswith("_correlation") else ROOM_DB_TOLERANCE


def _headphone_metric_tolerance(field: str) -> float:
    if field.endswith("_duration_s"):
        return HEADPHONE_DURATION_TOLERANCE_S
    return HEADPHONE_CORRELATION_TOLERANCE if field.endswith("_correlation") else HEADPHONE_DB_TOLERANCE


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _strictly_increasing(values: list[float]) -> bool:
    return all(current > previous for previous, current in zip(values, values[1:], strict=False))


def _live_capture_artifact_failures(
    spec: EvidenceSpec,
    report: dict[str, Any],
    capture: dict[str, Any],
) -> list[str]:
    failures: list[str] = []
    benchmark = report.get("benchmarks", {}).get("capture", {})
    benchmark = benchmark if isinstance(benchmark, dict) else {}

    if report.get("fixture_kind") != "live_microphone_capture":
        failures.append(f"fixture_kind must be live_microphone_capture, got {report.get('fixture_kind')!r}")
    if report.get("capture_source_kind") != "microphone":
        failures.append(f"top-level capture_source_kind must be microphone, got {report.get('capture_source_kind')!r}")
    if capture.get("generator") != EXPECTED_LIVE_CAPTURE_GENERATOR:
        failures.append(f"capture generator must be {EXPECTED_LIVE_CAPTURE_GENERATOR}")
    if capture.get("backend") != EXPECTED_LIVE_CAPTURE_BACKEND:
        failures.append(f"capture backend must be {EXPECTED_LIVE_CAPTURE_BACKEND}")
    if capture.get("adapter_id") != EXPECTED_LIVE_CAPTURE_ADAPTER_ID:
        failures.append(f"capture adapter_id must be {EXPECTED_LIVE_CAPTURE_ADAPTER_ID}")
    if capture.get("provenance_kind") != EXPECTED_LIVE_CAPTURE_PROVENANCE_KIND:
        failures.append(f"capture provenance_kind must be {EXPECTED_LIVE_CAPTURE_PROVENANCE_KIND}")
    if capture.get("provenance_trust_boundary") != EXPECTED_LIVE_CAPTURE_TRUST_BOUNDARY:
        failures.append(
            f"capture provenance_trust_boundary must be {EXPECTED_LIVE_CAPTURE_TRUST_BOUNDARY}"
        )
    if benchmark.get("adapter_id") != EXPECTED_LIVE_CAPTURE_ADAPTER_ID:
        failures.append("benchmarks.capture.adapter_id must match the expected live microphone adapter")

    device = capture.get("device", {})
    device = device if isinstance(device, dict) else {}
    if not device.get("name"):
        failures.append("capture device.name must be present")
    if not device.get("hostapi"):
        failures.append("capture device.hostapi must be present")
    max_input_channels = _int_or_none(device.get("max_input_channels"))
    if max_input_channels is None or max_input_channels < 1:
        failures.append("capture device.max_input_channels must be >= 1")
    default_samplerate = _float_or_none(device.get("default_samplerate"))
    if default_samplerate is None or default_samplerate <= 0.0:
        failures.append("capture device.default_samplerate must be > 0")

    artifact_paths = report.get("artifact_paths", {})
    artifact_paths = artifact_paths if isinstance(artifact_paths, dict) else {}
    prediction_paths = report.get("prediction_paths", {})
    prediction_paths = prediction_paths if isinstance(prediction_paths, dict) else {}
    artifact_hashes = report.get("artifact_hashes", {})
    artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}

    audio_path = _resolve_artifact_path(
        spec.path,
        artifact_paths.get("captured_audio") or capture.get("captured_audio_path"),
    )
    chunks_path = _resolve_artifact_path(
        spec.path,
        prediction_paths.get("capture_chunks") or capture.get("capture_chunks_path"),
    )
    if audio_path is None:
        failures.append("artifact_paths.captured_audio is required")
    if chunks_path is None:
        failures.append("prediction_paths.capture_chunks is required")
    if audio_path is None or chunks_path is None:
        return failures
    if not audio_path.exists():
        failures.append(f"captured audio WAV does not exist: {audio_path}")
    if not chunks_path.exists():
        failures.append(f"capture chunks JSONL does not exist: {chunks_path}")
    if failures:
        return failures

    audio_hash = _sha256_file(audio_path)
    chunks_hash = _sha256_file(chunks_path)
    if artifact_hashes.get("captured_audio") != audio_hash:
        failures.append("artifact_hashes.captured_audio does not match the WAV file")
    if capture.get("captured_audio_sha256") != audio_hash:
        failures.append("capture summary captured_audio_sha256 does not match the WAV file")
    if artifact_hashes.get("capture_chunks") != chunks_hash:
        failures.append("artifact_hashes.capture_chunks does not match the chunk JSONL file")
    if capture.get("capture_chunks_sha256") != chunks_hash:
        failures.append("capture summary capture_chunks_sha256 does not match the chunk JSONL file")

    try:
        records = _read_jsonl(chunks_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        failures.append(f"capture chunks JSONL could not be parsed: {exc}")
        return failures

    reported_chunks = benchmark.get("chunks")
    if isinstance(reported_chunks, list) and reported_chunks != records:
        failures.append("benchmarks.capture.chunks must exactly match the chunk JSONL records")

    sample_rates = capture.get("sample_rates_hz")
    if not isinstance(sample_rates, list) or len(sample_rates) != 1:
        failures.append("capture sample_rates_hz must contain exactly one sample rate")
        sample_rate_hz = None
    else:
        sample_rate_hz = _int_or_none(sample_rates[0])
        if sample_rate_hz is None or sample_rate_hz <= 0:
            failures.append("capture sample rate must be a positive integer")

    if _int_or_none(capture.get("channel_count")) != 1:
        failures.append("capture channel_count must be 1")
    if capture.get("pcm_subtype") != "PCM_16":
        failures.append("capture pcm_subtype must be PCM_16")

    try:
        with wave.open(str(audio_path), "rb") as wav:
            wav_channels = wav.getnchannels()
            wav_sampwidth = wav.getsampwidth()
            wav_rate = wav.getframerate()
            wav_frames = wav.getnframes()
    except (OSError, wave.Error) as exc:
        failures.append(f"captured audio WAV could not be inspected: {exc}")
        return failures

    if wav_channels != 1:
        failures.append(f"captured WAV channel count must be 1, got {wav_channels}")
    if wav_sampwidth != 2:
        failures.append(f"captured WAV sample width must be 2 bytes, got {wav_sampwidth}")
    if sample_rate_hz is not None and wav_rate != sample_rate_hz:
        failures.append(f"captured WAV sample rate {wav_rate} did not match report {sample_rate_hz}")

    captured_frame_count = _int_or_none(capture.get("captured_frame_count"))
    if captured_frame_count is None:
        failures.append("capture captured_frame_count must be present")
    elif captured_frame_count != wav_frames:
        failures.append(
            f"capture captured_frame_count {captured_frame_count} did not match WAV frames {wav_frames}"
        )

    chunk_count = _int_or_none(capture.get("chunk_count"))
    if chunk_count is None:
        failures.append("capture chunk_count must be present")
    elif chunk_count != len(records):
        failures.append(f"capture chunk_count {chunk_count} did not match JSONL records {len(records)}")
    if len(records) < 2:
        failures.append("capture chunks JSONL must contain at least two chunks")

    sample_cursor = 0
    frame_counts: list[int] = []
    callback_offsets: list[float] = []
    adc_times: list[float] = []
    chunk_ms = _float_or_none(capture.get("chunk_ms"))
    for expected_index, record in enumerate(records):
        record_index = _int_or_none(record.get("chunk_index"))
        start_sample = _int_or_none(record.get("start_sample"))
        end_sample = _int_or_none(record.get("end_sample"))
        frame_count = _int_or_none(record.get("frame_count"))
        duration_ms = _float_or_none(record.get("duration_ms"))
        callback_offset = _float_or_none(record.get("callback_wall_time_offset_s"))

        if record_index != expected_index:
            failures.append(f"chunk {expected_index} has unexpected chunk_index {record.get('chunk_index')!r}")
        if frame_count is None or frame_count <= 0:
            failures.append(f"chunk {expected_index} frame_count must be positive")
            continue
        if start_sample != sample_cursor:
            failures.append(f"chunk {expected_index} start_sample did not continue from previous chunk")
        if end_sample != sample_cursor + frame_count:
            failures.append(f"chunk {expected_index} end_sample did not match start + frame_count")
        if sample_rate_hz is not None and duration_ms is not None:
            expected_duration_ms = frame_count / float(sample_rate_hz) * 1000.0
            if abs(duration_ms - expected_duration_ms) > 0.01:
                failures.append(f"chunk {expected_index} duration_ms did not match frame_count/sample_rate")
        if record.get("status") not in {"", None}:
            failures.append(f"chunk {expected_index} has callback status {record.get('status')!r}")
        if not _is_sha256(record.get("sha256_float32")):
            failures.append(f"chunk {expected_index} sha256_float32 is not a SHA-256 hex digest")
        if callback_offset is None:
            failures.append(f"chunk {expected_index} callback_wall_time_offset_s is required")
        else:
            callback_offsets.append(callback_offset)
        adc_time = _float_or_none(record.get("input_adc_time_s"))
        if adc_time is not None:
            adc_times.append(adc_time)
        frame_counts.append(frame_count)
        sample_cursor += frame_count

    if sample_cursor != wav_frames:
        failures.append(f"sum of chunk frame_count {sample_cursor} did not match WAV frames {wav_frames}")

    if len(callback_offsets) == len(records) and not _strictly_increasing(callback_offsets):
        failures.append("callback_wall_time_offset_s values must be strictly increasing")

    if chunk_ms is not None and len(callback_offsets) > 1:
        interarrival_ms = [
            (current - previous) * 1000.0
            for previous, current in zip(callback_offsets, callback_offsets[1:], strict=False)
        ]
        max_jitter = max(abs(value - chunk_ms) for value in interarrival_ms)
        reported_max_jitter = _float_or_none(capture.get("max_interarrival_jitter_ms"))
        if reported_max_jitter is None or abs(reported_max_jitter - round(max_jitter, 3)) > 1.0:
            failures.append("capture max_interarrival_jitter_ms did not match recomputed chunk timing")

    timestamp_source = capture.get("timestamp_source")
    if timestamp_source not in {"device_input_adc_time", "callback_wall_clock_fallback"}:
        failures.append(f"unexpected timestamp_source {timestamp_source!r}")
    if capture.get("timestamp_monotonic") is not True:
        failures.append("capture timestamp_monotonic must be true")
    if timestamp_source == "device_input_adc_time":
        if len(adc_times) != len(records) or not _strictly_increasing(adc_times):
            failures.append("device_input_adc_time source requires strictly increasing input_adc_time_s values")
    elif timestamp_source == "callback_wall_clock_fallback":
        if len(callback_offsets) != len(records) or not _strictly_increasing(callback_offsets):
            failures.append("callback fallback source requires strictly increasing callback offsets")

    if sample_rate_hz is not None and frame_counts and callback_offsets:
        duration_from_frames_s = wav_frames / float(sample_rate_hz)
        callback_clock_duration_s = callback_offsets[-1] + frame_counts[-1] / float(sample_rate_hz)
        frame_clock_drift_ppm = (
            abs(callback_clock_duration_s - duration_from_frames_s)
            / duration_from_frames_s
            * 1_000_000.0
            if duration_from_frames_s > 0.0
            else None
        )
        reported_duration = _float_or_none(capture.get("duration_from_frames_s") or capture.get("duration_s"))
        reported_callback_duration = _float_or_none(capture.get("callback_clock_duration_s"))
        reported_drift = _float_or_none(capture.get("frame_clock_drift_ppm"))
        if reported_duration is None or abs(reported_duration - duration_from_frames_s) > 0.001:
            failures.append("capture duration_from_frames_s did not match WAV frame count")
        if reported_callback_duration is None or abs(reported_callback_duration - callback_clock_duration_s) > 0.002:
            failures.append("capture callback_clock_duration_s did not match chunk callback timing")
        if frame_clock_drift_ppm is None or reported_drift is None or abs(reported_drift - frame_clock_drift_ppm) > 25.0:
            failures.append("capture frame_clock_drift_ppm did not match recomputed chunk timing")

    if not capture.get("artifact_hash_chain_present"):
        failures.append("capture artifact_hash_chain_present must be true")
    if not capture.get("release_proof"):
        failures.append("capture release_proof must be true")

    return failures


def _live_capture_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    prototype = _reject_prototype_fixture(spec, report)
    if prototype:
        return prototype

    capture = _capture_summary(report)
    source_kind = capture.get("capture_source_kind") or report.get("capture_source_kind")
    release_proof = bool(capture.get("release_proof") or _summary(report).get("release_proof"))
    missing = _missing_gates(report, LIVE_CAPTURE_REQUIRED_GATES)
    failures: list[str] = []
    if source_kind != "microphone":
        failures.append(f"capture_source_kind must be microphone, got {source_kind!r}")
    if not release_proof:
        failures.append("release_proof must be true for microphone capture evidence")
    if missing:
        failures.append(f"missing/passing required live-capture gates: {', '.join(missing)}")
    failures.extend(_live_capture_artifact_failures(spec, report, capture))
    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec, "coherent host microphone artifact evidence present")


def _causal_diarization_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    missing = _missing_gates(report, CAUSAL_DIARIZATION_REQUIRED_GATES)
    metrics = _summary(report).get("streaming_metrics", {})
    metrics = metrics if isinstance(metrics, dict) else {}
    failures: list[str] = []
    if report.get("streaming_mode") not in {"raw_pcm_rolling_stateful", "live_pcm_rolling_stateful"}:
        failures.append(f"unexpected streaming_mode {report.get('streaming_mode')!r}")
    if missing:
        failures.append(f"missing/passing required causal-diarization gates: {', '.join(missing)}")
    if metrics.get("causality_ok") is not True:
        failures.append("streaming_metrics.causality_ok must be true")
    if int(metrics.get("max_future_samples_used", -1)) != 0:
        failures.append("streaming_metrics.max_future_samples_used must be 0")
    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec)


def _tse_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    if report is None:
        return _fail(spec, f"missing required report: {spec.description}")

    missing_real_model = _missing_gates(report, TSE_REAL_MODEL_REQUIRED_GATES)
    if _summary_passed(report) and not missing_real_model:
        return _pass(spec, "real TSE/separation beats mixture passthrough with release-candidate gates")

    missing_oracle = _missing_gates(report, TSE_ORACLE_QUALITY_GATES)
    failures: list[str] = []
    if not _summary_passed(report):
        failures.append("report summary did not pass real-model release-candidate gates")
    if missing_real_model:
        failures.append(
            "missing/passing required real-model TSE gates: " + ", ".join(missing_real_model)
        )
    if missing_oracle:
        failures.append(
            "oracle-quality diagnostic gates still failing: " + ", ".join(missing_oracle)
        )
    if not any(_gate_passed(report, gate_name) for gate_name in TSE_PASSTHROUGH_GATES) and missing_real_model:
        failures.append("report does not prove the real separator beats mixture passthrough")
    return _fail(spec, "; ".join(failures))


def _translation_after_tse_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    failures: list[str] = []
    missing = _missing_gates(report, TRANSLATION_REQUIRED_GATES)
    if missing:
        failures.append(
            "missing/passing required translation-after-TSE gates: " + ", ".join(missing)
        )

    adapter = report.get("adapter", {})
    adapter = adapter if isinstance(adapter, dict) else {}
    translation = adapter.get("translation", {})
    translation = translation if isinstance(translation, dict) else {}
    streaming_mode = translation.get("streaming_mode") or report.get("streaming_mode")
    if not isinstance(streaming_mode, str) or not streaming_mode:
        failures.append("adapter.translation.streaming_mode must be declared")
    elif any(streaming_mode.startswith(prefix) for prefix in ORACLE_TRANSLATION_STREAMING_PREFIXES):
        failures.append(
            f"translation streaming_mode must use non-oracle diarization, got {streaming_mode!r}"
        )

    segmentation_prior = translation.get("segmentation_prior")
    if not isinstance(segmentation_prior, str) or not segmentation_prior:
        failures.append("adapter.translation.segmentation_prior must be declared")
    elif segmentation_prior == "oracle_diarization":
        failures.append("translation segmentation_prior must not be oracle_diarization")

    translation_diarization_adapter_id = translation.get("diarization_adapter_id")
    if (
        not isinstance(translation_diarization_adapter_id, str)
        or not translation_diarization_adapter_id
    ):
        failures.append("adapter.translation.diarization_adapter_id must be declared")
    elif translation_diarization_adapter_id in ORACLE_DIARIZATION_ADAPTER_IDS:
        failures.append(
            "adapter.translation.diarization_adapter_id must be non-oracle, "
            f"got {translation_diarization_adapter_id!r}"
        )

    if translation.get("uses_oracle_diarization") is not False:
        failures.append("adapter.translation.uses_oracle_diarization must be false")

    diarization = report.get("benchmarks", {}).get("diarization", {})
    diarization = diarization if isinstance(diarization, dict) else {}
    diarization_adapter_id = diarization.get("adapter_id")
    if diarization_adapter_id in ORACLE_DIARIZATION_ADAPTER_IDS:
        failures.append(
            f"benchmarks.diarization.adapter_id must be non-oracle, got {diarization_adapter_id!r}"
        )

    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec, "non-oracle streaming speech translation evidence present after accepted TSE")


def _voice_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    prototype = _reject_prototype_fixture(spec, report)
    if prototype:
        return prototype
    missing = _missing_gates(report, VOICE_REQUIRED_GATES)
    if missing:
        return _fail(spec, f"missing/passing required voice/TTS gates: {', '.join(missing)}")

    failures: list[str] = []
    summary = _summary(report)
    voice_status = summary.get("voice_clone_status")
    voice_claim = summary.get("voice_similarity_claim")
    if voice_status not in {"fallback_voice", "same_voice_candidate"}:
        failures.append(
            "summary.voice_clone_status must be fallback_voice or same_voice_candidate"
        )
    if voice_status == "fallback_voice" and voice_claim != "not_claimed":
        failures.append("fallback voice reports must set voice_similarity_claim='not_claimed'")
    if voice_status == "same_voice_candidate" and voice_claim not in VOICE_CANDIDATE_SIMILARITY_CLAIMS:
        failures.append(
            "same_voice_candidate reports must set a measured voice_similarity_claim"
        )
    consent = report.get("consent", {})
    consent = consent if isinstance(consent, dict) else {}
    if voice_status == "same_voice_candidate":
        if consent.get("speaker_consent") is not True:
            failures.append("same_voice_candidate consent.speaker_consent must be true")
        if consent.get("voice_clone_reference_used") is not True:
            failures.append("same_voice_candidate consent.voice_clone_reference_used must be true")
        if consent.get("reference_retention_policy") not in VOICE_CANDIDATE_ALLOWED_RETENTION_POLICIES:
            failures.append("same_voice_candidate consent reference retention policy is not release-safe")
        consent_hash = consent.get("consent_evidence_sha256")
        consent_path = _resolve_artifact_path(spec.path, consent.get("consent_evidence_path"))
        if not _is_sha256(consent_hash):
            failures.append("same_voice_candidate consent_evidence_sha256 is required")
        elif consent_path is None or not consent_path.exists():
            failures.append("same_voice_candidate consent evidence artifact is missing")
        elif _sha256_file(consent_path) != consent_hash:
            failures.append("same_voice_candidate consent evidence hash does not match artifact")

    benchmark = report.get("benchmarks", {}).get("same_voice_or_fallback_tts", {})
    benchmark = benchmark if isinstance(benchmark, dict) else {}
    segments = benchmark.get("segments")
    if not isinstance(segments, list) or not segments:
        failures.append("benchmarks.same_voice_or_fallback_tts.segments must be non-empty")
    else:
        candidate_speaker_ids: set[str] = set()
        candidate_reference_hashes: set[str] = set()
        candidate_reference_hashes_by_index: dict[int, tuple[str, str]] = {}
        candidate_output_hashes_by_index: dict[int, tuple[str, str]] = {}
        for index, segment in enumerate(segments):
            if not isinstance(segment, dict):
                failures.append(f"voice/TTS segment {index} is not an object")
                continue
            audio_path = _resolve_artifact_path(spec.path, segment.get("tts_output_path"))
            if audio_path is None or not audio_path.exists():
                failures.append(f"voice/TTS segment {index} output audio is missing")
                continue
            audio_details: dict[str, Any] | None = None
            audio_samples: array.array | None = None
            try:
                audio_samples, audio_details = _mono_pcm16_wav_samples_and_details(audio_path)
            except (OSError, ValueError, wave.Error) as exc:
                failures.append(f"voice/TTS segment {index} WAV could not be inspected: {exc}")
                continue
            expected_hash = segment.get("tts_output_sha256")
            if not _is_sha256(expected_hash):
                failures.append(f"voice/TTS segment {index} tts_output_sha256 is invalid")
            elif audio_details["sha256"] != expected_hash:
                failures.append(f"voice/TTS segment {index} tts_output_sha256 does not match file")
            reported_pcm_hash = segment.get("tts_output_pcm_sha256")
            if reported_pcm_hash is not None and reported_pcm_hash != audio_details["pcm_sha256"]:
                failures.append(f"voice/TTS segment {index} tts_output_pcm_sha256 does not match WAV")
            frame_count = _int_or_none(segment.get("tts_output_frame_count"))
            if frame_count is not None and audio_details["frame_count"] != int(frame_count):
                failures.append(f"voice/TTS segment {index} frame count does not match WAV")
            if audio_details["peak_dbfs"] > -0.1:
                failures.append(f"voice/TTS segment {index} output peak must be <= -0.1 dBFS")

            reference_hash = segment.get("reference_audio_sha256")
            reference_path = _resolve_artifact_path(spec.path, segment.get("reference_audio_path"))
            reference_details: dict[str, Any] | None = None
            reference_samples: array.array | None = None
            if reference_hash is not None and not _is_sha256(reference_hash):
                failures.append(f"voice/TTS segment {index} reference_audio_sha256 is invalid")
            if reference_path is not None and reference_path.exists():
                try:
                    reference_samples, reference_details = _mono_pcm16_wav_samples_and_details(reference_path)
                except (OSError, ValueError, wave.Error) as exc:
                    failures.append(f"voice/TTS segment {index} reference WAV could not be inspected: {exc}")
                if reference_details is not None:
                    if reference_hash is not None and reference_details["sha256"] != reference_hash:
                        failures.append(
                            f"voice/TTS segment {index} reference_audio_sha256 does not match file"
                        )
                    reported_reference_pcm_hash = segment.get("reference_audio_pcm_sha256")
                    if (
                        reported_reference_pcm_hash is not None
                        and reported_reference_pcm_hash != reference_details["pcm_sha256"]
                    ):
                        failures.append(
                            f"voice/TTS segment {index} reference_audio_pcm_sha256 does not match WAV"
                        )
                    candidate_reference_hashes_by_index[index] = (
                        str(reference_details["sha256"]),
                        str(reference_details["pcm_sha256"]),
                    )
                    if voice_status != "same_voice_candidate":
                        recomputed_level_error = abs(float(audio_details["dbfs"]) - float(reference_details["dbfs"]))
                        reported_level_error = _float_or_none(segment.get("output_level_error_db"))
                        if recomputed_level_error > 0.75:
                            failures.append(
                                f"voice/TTS segment {index} recomputed output level error must be <= 0.75 dB"
                            )
                        if (
                            reported_level_error is None
                            or abs(recomputed_level_error - reported_level_error) > 0.075
                        ):
                            failures.append(
                                f"voice/TTS segment {index} output_level_error_db does not match recomputed WAV levels"
                            )
            candidate_output_hashes_by_index[index] = (
                str(audio_details["sha256"]),
                str(audio_details["pcm_sha256"]),
            )
            if voice_status == "fallback_voice":
                if segment.get("voice_clone_reference_used") is not False:
                    failures.append(
                        f"voice/TTS segment {index} fallback must not use voice clone references"
                    )
                if segment.get("voice_similarity_claim") != "not_claimed":
                    failures.append(
                        f"voice/TTS segment {index} fallback must not claim voice similarity"
                    )
            if voice_status == "same_voice_candidate":
                speaker_id = str(segment.get("speaker_id") or "").strip()
                if speaker_id:
                    candidate_speaker_ids.add(speaker_id)
                else:
                    failures.append(f"voice/TTS segment {index} candidate speaker_id is required")
                if segment.get("voice_clone_reference_used") is not True:
                    failures.append(
                        f"voice/TTS segment {index} candidate must use a consented voice reference"
                    )
                if segment.get("voice_similarity_claim") not in VOICE_CANDIDATE_SIMILARITY_CLAIMS:
                    failures.append(f"voice/TTS segment {index} candidate must declare measured similarity")
                if segment.get("voice_similarity_metric") != VOICE_CANDIDATE_METRIC_NAME:
                    failures.append(
                        f"voice/TTS segment {index} candidate metric must be {VOICE_CANDIDATE_METRIC_NAME}"
                    )
                if segment.get("voice_similarity_evaluator_id") != VOICE_CANDIDATE_EVALUATOR_ID:
                    failures.append(
                        f"voice/TTS segment {index} candidate evaluator must be {VOICE_CANDIDATE_EVALUATOR_ID}"
                    )
                failures.append(
                    f"voice/TTS segment {index} uses candidate-only acoustic proxy evidence; "
                    "same_voice_candidate cannot replace fallback release evidence until calibrated ASV/human similarity release acceptance is implemented"
                )
                if reference_details is None:
                    failures.append(f"voice/TTS segment {index} candidate reference audio is required")
                else:
                    candidate_reference_hashes.add(str(reference_details["sha256"]))
                    try:
                        same_path = audio_path.resolve() == reference_path.resolve() if reference_path else False
                    except OSError:
                        same_path = False
                    if same_path or audio_details["sha256"] == reference_details["sha256"]:
                        failures.append(f"voice/TTS segment {index} candidate output must not clone reference WAV bytes")
                    if audio_details["pcm_sha256"] == reference_details["pcm_sha256"]:
                        failures.append(f"voice/TTS segment {index} candidate output must not clone reference PCM")
                source_path = _resolve_artifact_path(spec.path, segment.get("source_audio_path"))
                source_details: dict[str, Any] | None = None
                if source_path is None or not source_path.exists():
                    failures.append(f"voice/TTS segment {index} candidate source audio is required")
                else:
                    try:
                        _source_samples, source_details = _mono_pcm16_wav_samples_and_details(source_path)
                    except (OSError, ValueError, wave.Error) as exc:
                        failures.append(f"voice/TTS segment {index} source WAV could not be inspected: {exc}")
                if source_details is not None:
                    source_hash = segment.get("source_audio_sha256")
                    if not _is_sha256(source_hash):
                        failures.append(f"voice/TTS segment {index} source_audio_sha256 is invalid")
                    elif source_details["sha256"] != source_hash:
                        failures.append(f"voice/TTS segment {index} source_audio_sha256 does not match file")
                    reported_source_pcm_hash = segment.get("source_audio_pcm_sha256")
                    if (
                        reported_source_pcm_hash is not None
                        and reported_source_pcm_hash != source_details["pcm_sha256"]
                    ):
                        failures.append(
                            f"voice/TTS segment {index} source_audio_pcm_sha256 does not match WAV"
                        )
                    recomputed_level_error = abs(float(audio_details["dbfs"]) - float(source_details["dbfs"]))
                    reported_level_error = _float_or_none(segment.get("output_level_error_db"))
                    if recomputed_level_error > 0.75:
                        failures.append(
                            f"voice/TTS segment {index} recomputed source/output level error must be <= 0.75 dB"
                        )
                    if (
                        reported_level_error is None
                        or abs(recomputed_level_error - reported_level_error) > 0.075
                    ):
                        failures.append(
                            f"voice/TTS segment {index} output_level_error_db does not match source/output WAV levels"
                        )
                similarity_score = _float_or_none(segment.get("voice_similarity_score"))
                similarity_threshold = _float_or_none(segment.get("voice_similarity_threshold"))
                if similarity_score is None:
                    failures.append(f"voice/TTS segment {index} voice_similarity_score is required")
                if similarity_threshold is None:
                    failures.append(f"voice/TTS segment {index} voice_similarity_threshold is required")
                elif similarity_threshold < VOICE_CANDIDATE_MIN_SIMILARITY_SCORE:
                    failures.append(
                        f"voice/TTS segment {index} voice_similarity_threshold is below release minimum"
                    )
                if (
                    similarity_score is not None
                    and similarity_threshold is not None
                    and similarity_score < similarity_threshold
                ):
                    failures.append(f"voice/TTS segment {index} voice similarity score is below threshold")
                recomputed_similarity_score: float | None = None
                if (
                    reference_samples is not None
                    and audio_samples is not None
                    and reference_details is not None
                ):
                    recomputed_similarity_score = _acoustic_similarity_proxy(
                        reference_samples,
                        audio_samples,
                        int(reference_details["sample_rate_hz"]),
                    )
                    if (
                        similarity_score is not None
                        and abs(recomputed_similarity_score - similarity_score)
                        > VOICE_CANDIDATE_SIMILARITY_SCORE_TOLERANCE
                    ):
                        failures.append(
                            f"voice/TTS segment {index} voice_similarity_score does not match recomputed proxy"
                        )
                evidence_hash = segment.get("voice_similarity_evidence_sha256")
                evidence_path = _resolve_artifact_path(spec.path, segment.get("voice_similarity_evidence_path"))
                if not _is_sha256(evidence_hash):
                    failures.append(f"voice/TTS segment {index} similarity evidence hash is required")
                elif evidence_path is None or not evidence_path.exists():
                    failures.append(f"voice/TTS segment {index} similarity evidence artifact is missing")
                elif _sha256_file(evidence_path) != evidence_hash:
                    failures.append(f"voice/TTS segment {index} similarity evidence hash does not match artifact")
                else:
                    try:
                        evidence = _load_json(evidence_path)
                    except Exception as exc:
                        evidence = None
                        failures.append(f"voice/TTS segment {index} similarity evidence is unreadable: {exc}")
                    if isinstance(evidence, dict):
                        if evidence.get("speaker_id") != segment.get("speaker_id"):
                            failures.append(f"voice/TTS segment {index} similarity evidence speaker_id mismatch")
                        if evidence.get("reference_audio_sha256") != segment.get("reference_audio_sha256"):
                            failures.append(
                                f"voice/TTS segment {index} similarity evidence reference hash mismatch"
                            )
                        if evidence.get("reference_audio_pcm_sha256") != segment.get("reference_audio_pcm_sha256"):
                            failures.append(
                                f"voice/TTS segment {index} similarity evidence reference PCM hash mismatch"
                            )
                        if evidence.get("tts_output_sha256") != segment.get("tts_output_sha256"):
                            failures.append(
                                f"voice/TTS segment {index} similarity evidence output hash mismatch"
                            )
                        if evidence.get("tts_output_pcm_sha256") != segment.get("tts_output_pcm_sha256"):
                            failures.append(
                                f"voice/TTS segment {index} similarity evidence output PCM hash mismatch"
                            )
                        if evidence.get("metric_name") != VOICE_CANDIDATE_METRIC_NAME:
                            failures.append(f"voice/TTS segment {index} similarity evidence metric mismatch")
                        if evidence.get("evaluator_id") != VOICE_CANDIDATE_EVALUATOR_ID:
                            failures.append(f"voice/TTS segment {index} similarity evidence evaluator mismatch")
                        evidence_score = _float_or_none(evidence.get("score"))
                        evidence_threshold = _float_or_none(evidence.get("threshold"))
                        if (
                            evidence_score is None
                            or similarity_score is None
                            or abs(evidence_score - similarity_score) > 1e-6
                        ):
                            failures.append(f"voice/TTS segment {index} similarity evidence score mismatch")
                        if (
                            evidence_score is not None
                            and recomputed_similarity_score is not None
                            and abs(evidence_score - recomputed_similarity_score)
                            > VOICE_CANDIDATE_SIMILARITY_SCORE_TOLERANCE
                        ):
                            failures.append(
                                f"voice/TTS segment {index} similarity evidence score does not match recomputed proxy"
                            )
                        if (
                            evidence_threshold is None
                            or similarity_threshold is None
                            or abs(evidence_threshold - similarity_threshold) > 1e-6
                        ):
                            failures.append(f"voice/TTS segment {index} similarity evidence threshold mismatch")

        if voice_status == "same_voice_candidate":
            consent_speaker_ids = consent.get("speaker_ids")
            if (
                not isinstance(consent_speaker_ids, list)
                or sorted(str(item) for item in consent_speaker_ids) != sorted(candidate_speaker_ids)
            ):
                failures.append("same_voice_candidate consent.speaker_ids must match segment speakers")
            consent_reference_hashes = consent.get("reference_audio_sha256s")
            if (
                not isinstance(consent_reference_hashes, list)
                or sorted(str(item) for item in consent_reference_hashes)
                != sorted(candidate_reference_hashes)
            ):
                failures.append(
                    "same_voice_candidate consent.reference_audio_sha256s must match segment references"
                )
            if consent.get("reference_retention_policy") == "consented_retention_with_expiry":
                expiry = _float_or_none(consent.get("reference_retention_expires_unix"))
                if expiry is None or expiry <= time.time():
                    failures.append(
                        "same_voice_candidate consent.reference_retention_expires_unix must be in the future"
                    )
            for output_index, output_hashes in candidate_output_hashes_by_index.items():
                for reference_index, reference_hashes in candidate_reference_hashes_by_index.items():
                    if output_index == reference_index:
                        continue
                    if output_hashes[0] == reference_hashes[0]:
                        failures.append(
                            f"voice/TTS segment {output_index} output must not clone segment {reference_index} reference WAV bytes"
                        )
                    if output_hashes[1] == reference_hashes[1]:
                        failures.append(
                            f"voice/TTS segment {output_index} output must not clone segment {reference_index} reference PCM"
                        )

    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec)


def _room_suppression_summary(report: dict[str, Any]) -> dict[str, Any]:
    benchmark = report.get("benchmarks", {}).get("room_playback_suppression", {})
    if isinstance(benchmark, dict):
        summary = benchmark.get("summary", {})
        if isinstance(summary, dict):
            return summary
    return {}


def _room_suppression_benchmark(report: dict[str, Any]) -> dict[str, Any]:
    benchmark = report.get("benchmarks", {}).get("room_playback_suppression", {})
    return benchmark if isinstance(benchmark, dict) else {}


def _headphone_isolation_summary(report: dict[str, Any]) -> dict[str, Any]:
    benchmark = report.get("benchmarks", {}).get(HEADPHONE_REQUIRED_BENCHMARK_NAME, {})
    if isinstance(benchmark, dict):
        summary = benchmark.get("summary", {})
        if isinstance(summary, dict):
            return summary
    return {}


def _room_suppression_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    prototype = _reject_prototype_fixture(spec, report)
    if prototype:
        return prototype

    room_benchmark = _room_suppression_benchmark(report)
    room_summary = _room_suppression_summary(report)
    missing = _missing_gates(report, ROOM_SUPPRESSION_REQUIRED_GATES)
    failures: list[str] = []
    if report.get("fixture_kind") != "real_room_playback_suppression":
        failures.append(f"fixture_kind must be real_room_playback_suppression, got {report.get('fixture_kind')!r}")
    if room_summary.get("measurement_kind") != ROOM_REQUIRED_MEASUREMENT_KIND:
        failures.append(
            f"room_playback_suppression.summary.measurement_kind must be {ROOM_REQUIRED_MEASUREMENT_KIND}"
        )
    if room_summary.get("translated_audio_is_surrogate") is True:
        failures.append("surrogate translated audio cannot satisfy real-room suppression")
    if missing:
        failures.append(f"missing/passing required room-suppression gates: {', '.join(missing)}")
    device_info = room_benchmark.get("device", {})
    if not isinstance(device_info, dict):
        failures.append("room_playback_suppression.device must be recorded")
        device_info = {}
    input_device = device_info.get("input_device", {})
    output_device = device_info.get("output_device", {})
    if not isinstance(input_device, dict) or not isinstance(output_device, dict):
        failures.append("room device info must include input_device and output_device")
    else:
        for label, device in (("input_device", input_device), ("output_device", output_device)):
            for field in ("name", "hostapi", "hostapi_name", "max_input_channels", "max_output_channels"):
                if device.get(field) is None:
                    failures.append(f"room device {label}.{field} must be recorded")
    metric_values = {
        "device_path_fingerprint": room_summary.get("device_path_fingerprint"),
        "device_path_identity_recorded": room_summary.get("device_path_identity_recorded"),
        "input_channels": _float_or_none(room_summary.get("input_channels")),
        "output_channels": _float_or_none(room_summary.get("output_channels")),
        "sample_rate_hz": _float_or_none(room_summary.get("sample_rate_hz")),
        "source_calibration_dbfs": _float_or_none(room_summary.get("source_calibration_dbfs")),
        "source_calibration_reference_correlation": _float_or_none(
            room_summary.get("source_calibration_reference_correlation")
        ),
        "source_calibration_reference_distortion_db": _float_or_none(
            room_summary.get("source_calibration_reference_distortion_db")
        ),
        "source_residual_dbfs": _float_or_none(room_summary.get("source_residual_dbfs")),
        "source_residual_reduction_db": _float_or_none(room_summary.get("source_residual_reduction_db")),
        "translated_calibration_reference_correlation": _float_or_none(
            room_summary.get("translated_calibration_reference_correlation")
        ),
        "translated_calibration_reference_distortion_db": _float_or_none(
            room_summary.get("translated_calibration_reference_distortion_db")
        ),
        "translated_output_distortion_db": _float_or_none(room_summary.get("translated_output_distortion_db")),
        "translated_output_correlation": _float_or_none(room_summary.get("translated_output_correlation")),
        "translated_reference_dbfs": _float_or_none(room_summary.get("translated_reference_dbfs")),
    }
    for field, value in metric_values.items():
        if field in {"device_path_fingerprint", "device_path_identity_recorded"}:
            continue
        if value is None:
            failures.append(f"room_playback_suppression.summary.{field} must be finite")
    if room_summary.get("device_path_identity_recorded") is not True:
        failures.append("room_playback_suppression.summary.device_path_identity_recorded must be true")
    fingerprint = room_summary.get("device_path_fingerprint")
    if not _is_sha256(fingerprint):
        failures.append("room_playback_suppression.summary.device_path_fingerprint must be a SHA-256 hex string")
    sample_rate_hz = metric_values["sample_rate_hz"]
    input_channels = metric_values["input_channels"]
    output_channels = metric_values["output_channels"]
    if (
        isinstance(device_info, dict)
        and _is_sha256(fingerprint)
        and sample_rate_hz is not None
        and input_channels is not None
        and output_channels is not None
    ):
        expected_fingerprint = _device_path_fingerprint(
            device_info,
            sample_rate_hz=int(sample_rate_hz),
            input_channels=int(input_channels),
            output_channels=int(output_channels),
        )
        if fingerprint != expected_fingerprint:
            failures.append("room_playback_suppression.summary.device_path_fingerprint does not match device info")
    if isinstance(input_device, dict) and input_channels is not None:
        try:
            if int(input_device.get("max_input_channels", 0)) < int(input_channels):
                failures.append("room input device does not support reported input_channels")
        except (TypeError, ValueError):
            failures.append("room input device max_input_channels must be numeric")
    if isinstance(output_device, dict) and output_channels is not None:
        try:
            if int(output_device.get("max_output_channels", 0)) < int(output_channels):
                failures.append("room output device does not support reported output_channels")
        except (TypeError, ValueError):
            failures.append("room output device max_output_channels must be numeric")
    suppression_claim = room_summary.get("suppression_claim")
    if not isinstance(suppression_claim, str) or not suppression_claim:
        failures.append("room_playback_suppression.summary.suppression_claim must be declared")
    elif suppression_claim != ROOM_REQUIRED_SUPPRESSION_CLAIM:
        failures.append(
            f"room_playback_suppression.summary.suppression_claim must be {ROOM_REQUIRED_SUPPRESSION_CLAIM}"
        )
    reduction = metric_values["source_residual_reduction_db"]
    if reduction is not None and reduction < ROOM_MIN_SOURCE_RESIDUAL_REDUCTION_DB:
        failures.append(
            "room_playback_suppression.summary.source_residual_reduction_db must be "
            f">= {ROOM_MIN_SOURCE_RESIDUAL_REDUCTION_DB:.1f}"
        )
    source_calibration = metric_values["source_calibration_dbfs"]
    if source_calibration is not None and source_calibration < ROOM_MIN_CALIBRATION_DBFS:
        failures.append(
            "room_playback_suppression.summary.source_calibration_dbfs must be "
            f">= {ROOM_MIN_CALIBRATION_DBFS:.1f}"
        )
    translated_calibration = metric_values["translated_reference_dbfs"]
    if translated_calibration is not None and translated_calibration < ROOM_MIN_CALIBRATION_DBFS:
        failures.append(
            "room_playback_suppression.summary.translated_reference_dbfs must be "
            f">= {ROOM_MIN_CALIBRATION_DBFS:.1f}"
        )
    source_calibration_corr = metric_values["source_calibration_reference_correlation"]
    if source_calibration_corr is not None and source_calibration_corr < ROOM_MIN_CALIBRATION_CORRELATION:
        failures.append(
            "room_playback_suppression.summary.source_calibration_reference_correlation must be "
            f">= {ROOM_MIN_CALIBRATION_CORRELATION:.3f}"
        )
    translated_calibration_corr = metric_values["translated_calibration_reference_correlation"]
    if (
        translated_calibration_corr is not None
        and translated_calibration_corr < ROOM_MIN_CALIBRATION_CORRELATION
    ):
        failures.append(
            "room_playback_suppression.summary.translated_calibration_reference_correlation must be "
            f">= {ROOM_MIN_CALIBRATION_CORRELATION:.3f}"
        )
    source_calibration_distortion = metric_values["source_calibration_reference_distortion_db"]
    if (
        source_calibration_distortion is not None
        and source_calibration_distortion > ROOM_MAX_CALIBRATION_DISTORTION_DB
    ):
        failures.append(
            "room_playback_suppression.summary.source_calibration_reference_distortion_db must be "
            f"<= {ROOM_MAX_CALIBRATION_DISTORTION_DB:.1f}"
        )
    translated_calibration_distortion = metric_values["translated_calibration_reference_distortion_db"]
    if (
        translated_calibration_distortion is not None
        and translated_calibration_distortion > ROOM_MAX_CALIBRATION_DISTORTION_DB
    ):
        failures.append(
            "room_playback_suppression.summary.translated_calibration_reference_distortion_db must be "
            f"<= {ROOM_MAX_CALIBRATION_DISTORTION_DB:.1f}"
        )
    distortion = metric_values["translated_output_distortion_db"]
    if distortion is not None and distortion > ROOM_MAX_TRANSLATED_OUTPUT_DISTORTION_DB:
        failures.append(
            "room_playback_suppression.summary.translated_output_distortion_db must be "
            f"<= {ROOM_MAX_TRANSLATED_OUTPUT_DISTORTION_DB:.1f}"
        )
    translated_corr = metric_values["translated_output_correlation"]
    if translated_corr is not None and translated_corr < ROOM_MIN_TRANSLATED_OUTPUT_CORRELATION:
        failures.append(
            "room_playback_suppression.summary.translated_output_correlation must be "
            f">= {ROOM_MIN_TRANSLATED_OUTPUT_CORRELATION:.3f}"
        )
    artifact_paths = report.get("artifact_paths", {})
    artifact_hashes = report.get("artifact_hashes", {})
    resolved_artifacts: dict[str, Path] = {}
    if not isinstance(artifact_paths, dict) or not isinstance(artifact_hashes, dict):
        failures.append("room report must include artifact_paths and artifact_hashes objects")
    else:
        for key in (
            "room_loopback_recording",
            "source_only_room_recording",
            "source_reference",
            "translated_only_room_recording",
            "translated_playback_reference",
        ):
            artifact_path = _resolve_artifact_path(spec.path, artifact_paths.get(key))
            expected_hash = artifact_hashes.get(key)
            if artifact_path is None or not artifact_path.exists():
                failures.append(f"room artifact {key!r} is missing")
                continue
            resolved_artifacts[key] = artifact_path
            if not _is_sha256(expected_hash):
                failures.append(f"room artifact hash {key!r} is invalid")
            elif _sha256_file(artifact_path) != expected_hash:
                failures.append(f"room artifact hash {key!r} does not match file")
            if key in {"room_loopback_recording", "source_only_room_recording", "translated_only_room_recording"}:
                try:
                    with wave.open(str(artifact_path), "rb") as wav:
                        if wav.getnchannels() != 1:
                            failures.append(f"{key} WAV must be mono")
                        if wav.getsampwidth() != 2:
                            failures.append(f"{key} WAV sample width must be 2 bytes")
                        if wav.getnframes() <= 0:
                            failures.append(f"{key} WAV must contain frames")
                except (OSError, wave.Error) as exc:
                    failures.append(f"{key} WAV could not be inspected: {exc}")
    if not failures:
        try:
            recomputed = _recompute_room_metrics(resolved_artifacts)
        except (OSError, ValueError, wave.Error) as exc:
            failures.append(f"room metrics could not be recomputed from WAV artifacts: {exc}")
        else:
            for field, recomputed_value in recomputed.items():
                reported_value = metric_values.get(field)
                if reported_value is None:
                    continue
                tolerance = _room_metric_tolerance(field)
                if abs(reported_value - recomputed_value) > tolerance:
                    failures.append(
                        f"room_playback_suppression.summary.{field}={reported_value:.6g} "
                        f"does not match WAV-derived {recomputed_value:.6g}"
                    )
            if recomputed["source_residual_reduction_db"] < ROOM_MIN_SOURCE_RESIDUAL_REDUCTION_DB:
                failures.append(
                    "WAV-derived room source residual reduction must be "
                    f">= {ROOM_MIN_SOURCE_RESIDUAL_REDUCTION_DB:.1f}"
                )
            if recomputed["source_calibration_dbfs"] < ROOM_MIN_CALIBRATION_DBFS:
                failures.append(
                    "WAV-derived source calibration level must be "
                    f">= {ROOM_MIN_CALIBRATION_DBFS:.1f} dBFS"
                )
            if recomputed["translated_reference_dbfs"] < ROOM_MIN_CALIBRATION_DBFS:
                failures.append(
                    "WAV-derived translated calibration level must be "
                    f">= {ROOM_MIN_CALIBRATION_DBFS:.1f} dBFS"
                )
            if recomputed["source_calibration_reference_correlation"] < ROOM_MIN_CALIBRATION_CORRELATION:
                failures.append(
                    "WAV-derived source calibration/reference correlation must be "
                    f">= {ROOM_MIN_CALIBRATION_CORRELATION:.3f}"
                )
            if recomputed["translated_calibration_reference_correlation"] < ROOM_MIN_CALIBRATION_CORRELATION:
                failures.append(
                    "WAV-derived translated calibration/reference correlation must be "
                    f">= {ROOM_MIN_CALIBRATION_CORRELATION:.3f}"
                )
            if recomputed["source_calibration_reference_distortion_db"] > ROOM_MAX_CALIBRATION_DISTORTION_DB:
                failures.append(
                    "WAV-derived source calibration/reference distortion must be "
                    f"<= {ROOM_MAX_CALIBRATION_DISTORTION_DB:.1f} dB"
                )
            if (
                recomputed["translated_calibration_reference_distortion_db"]
                > ROOM_MAX_CALIBRATION_DISTORTION_DB
            ):
                failures.append(
                    "WAV-derived translated calibration/reference distortion must be "
                    f"<= {ROOM_MAX_CALIBRATION_DISTORTION_DB:.1f} dB"
                )
            if recomputed["translated_output_distortion_db"] > ROOM_MAX_TRANSLATED_OUTPUT_DISTORTION_DB:
                failures.append(
                    "WAV-derived translated output distortion must be "
                    f"<= {ROOM_MAX_TRANSLATED_OUTPUT_DISTORTION_DB:.1f} dB"
                )
            if recomputed["translated_output_correlation"] < ROOM_MIN_TRANSLATED_OUTPUT_CORRELATION:
                failures.append(
                    "WAV-derived translated output correlation must be "
                    f">= {ROOM_MIN_TRANSLATED_OUTPUT_CORRELATION:.3f}"
                )
    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec)


def _headphone_isolation_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    prototype = _reject_prototype_fixture(spec, report)
    if prototype:
        return prototype

    summary = _headphone_isolation_summary(report)
    missing = _missing_gates(report, HEADPHONE_ISOLATION_REQUIRED_GATES)
    failures: list[str] = []
    if report.get("fixture_kind") != HEADPHONE_REQUIRED_FIXTURE_KIND:
        failures.append(f"fixture_kind must be {HEADPHONE_REQUIRED_FIXTURE_KIND}, got {report.get('fixture_kind')!r}")
    if summary.get("measurement_kind") != HEADPHONE_REQUIRED_MEASUREMENT_KIND:
        failures.append(
            "headphone_earpiece_isolation.summary.measurement_kind must be "
            f"{HEADPHONE_REQUIRED_MEASUREMENT_KIND}"
        )
    release_proof = bool(report.get("release_proof") and _summary(report).get("release_proof") and summary.get("release_proof"))
    if not release_proof:
        failures.append("headphone isolation release_proof must be true")
    if summary.get("source_suppression_mode") != HEADPHONE_REQUIRED_SUPPRESSION_MODE:
        failures.append(
            "headphone_earpiece_isolation.summary.source_suppression_mode must be "
            f"{HEADPHONE_REQUIRED_SUPPRESSION_MODE}"
        )
    if summary.get("suppression_claim") != HEADPHONE_REQUIRED_SUPPRESSION_CLAIM:
        failures.append(
            "headphone_earpiece_isolation.summary.suppression_claim must be "
            f"{HEADPHONE_REQUIRED_SUPPRESSION_CLAIM}"
        )
    if summary.get("translated_audio_is_surrogate") is not False:
        failures.append("headphone_earpiece_isolation.summary.translated_audio_is_surrogate must be false")
    if not _specific_measurement_label(summary.get("headphone_device_label")):
        failures.append("headphone_earpiece_isolation.summary.headphone_device_label must be specific, not a placeholder")
    if not _specific_measurement_label(summary.get("measurement_microphone_label")):
        failures.append("headphone_earpiece_isolation.summary.measurement_microphone_label must be specific, not a placeholder")
    if not _specific_measurement_label(summary.get("isolation_fixture_label")):
        failures.append("headphone_earpiece_isolation.summary.isolation_fixture_label must be specific, not a placeholder")
    max_alignment_lag_ms = _float_or_none(summary.get("max_alignment_lag_ms"))
    if max_alignment_lag_ms is None:
        failures.append("headphone_earpiece_isolation.summary.max_alignment_lag_ms must be finite")
    elif max_alignment_lag_ms > ROOM_MAX_ALIGNMENT_LAG_MS:
        failures.append(
            "headphone_earpiece_isolation.summary.max_alignment_lag_ms must be "
            f"<= {ROOM_MAX_ALIGNMENT_LAG_MS:.1f}"
        )
    capture_backend = summary.get("capture_backend")
    capture_source_kind = summary.get("capture_source_kind")
    if capture_backend not in HEADPHONE_CAPTURE_BACKENDS:
        failures.append("headphone_earpiece_isolation.summary.capture_backend must be declared")
    if capture_source_kind not in HEADPHONE_CAPTURE_SOURCE_KINDS:
        failures.append("headphone_earpiece_isolation.summary.capture_source_kind must be declared")
    if (
        capture_backend in HEADPHONE_CAPTURE_SOURCE_PAIRS
        and capture_source_kind != HEADPHONE_CAPTURE_SOURCE_PAIRS[capture_backend]
    ):
        failures.append("headphone_earpiece_isolation.summary.capture_backend and capture_source_kind must be a valid pair")
    if capture_backend == HEADPHONE_GUIDED_CAPTURE_BACKEND:
        if summary.get("device_path_identity_recorded") is not True:
            failures.append("headphone_earpiece_isolation.summary.device_path_identity_recorded must be true for guided capture")
        if not _is_sha256(summary.get("device_path_fingerprint")):
            failures.append("headphone_earpiece_isolation.summary.device_path_fingerprint must be a SHA-256 hex string for guided capture")
        device_info = summary.get("device_info")
        if not isinstance(device_info, dict):
            failures.append("headphone_earpiece_isolation.summary.device_info must be recorded for guided capture")
        else:
            for key in ("measurement_input_device", "source_output_device", "headphone_output_device"):
                device = device_info.get(key)
                if not isinstance(device, dict) or not device.get("name") or device.get("hostapi_name") is None:
                    failures.append(f"headphone_earpiece_isolation.summary.device_info.{key} must include name and hostapi_name")
        if _is_sha256(summary.get("device_path_fingerprint")):
            expected_device_fingerprint = _headphone_guided_device_fingerprint(summary)
            if summary.get("device_path_fingerprint") != expected_device_fingerprint:
                failures.append("headphone_earpiece_isolation.summary.device_path_fingerprint does not match guided device info and capture channels")
        preflight_binding = summary.get("capture_preflight_binding")
        if not isinstance(preflight_binding, dict):
            failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding must be recorded for guided capture")
        else:
            if preflight_binding.get("bound") is not True:
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.bound must be true")
            if preflight_binding.get("planning_passed") is not True:
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.planning_passed must be true")
            if preflight_binding.get("recommended_path") != "guided_capture_possible":
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.recommended_path must be guided_capture_possible")
            if preflight_binding.get("physical_listener_ear_input_confirmed") is not True:
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.physical_listener_ear_input_confirmed must be true")
            if preflight_binding.get("selected_route_capture_ready") is not True:
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.selected_route_capture_ready must be true")
            if not _is_sha256(preflight_binding.get("preflight_report_sha256")):
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.preflight_report_sha256 must be a SHA-256 hex string")
            if preflight_binding.get("capture_device_path_fingerprint") != summary.get("device_path_fingerprint"):
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.capture_device_path_fingerprint must match device_path_fingerprint")
            preflight_device_info = preflight_binding.get("preflight_device_info")
            device_info = summary.get("device_info")
            if not isinstance(preflight_device_info, dict) or not isinstance(device_info, dict):
                failures.append("headphone_earpiece_isolation.summary.capture_preflight_binding.preflight_device_info must be recorded")
            else:
                for key in ("measurement_input_device", "source_output_device", "headphone_output_device"):
                    expected = preflight_device_info.get(key)
                    current = device_info.get(key)
                    if not isinstance(expected, dict) or not isinstance(current, dict):
                        failures.append(f"headphone_earpiece_isolation.summary.capture_preflight_binding.preflight_device_info.{key} must be recorded")
                        continue
                    for field in ("index", "hostapi", "hostapi_name", "name"):
                        if str(expected.get(field)) != str(current.get(field)):
                            failures.append(
                                "headphone_earpiece_isolation.summary.capture_preflight_binding."
                                f"preflight_device_info.{key}.{field} must match guided device_info"
                            )
    if missing:
        failures.append(f"missing/passing required headphone-isolation gates: {', '.join(missing)}")

    metric_values = {
        "sample_rate_hz": _float_or_none(summary.get("sample_rate_hz")),
        "min_artifact_duration_s": _float_or_none(summary.get("min_artifact_duration_s")),
        "source_isolated_gain_db": _float_or_none(summary.get("source_isolated_gain_db")),
        "source_isolated_recording_dbfs": _float_or_none(summary.get("source_isolated_recording_dbfs")),
        "source_isolated_reference_correlation": _float_or_none(
            summary.get("source_isolated_reference_correlation")
        ),
        "source_isolated_reference_distortion_db": _float_or_none(
            summary.get("source_isolated_reference_distortion_db")
        ),
        "source_isolated_reference_lag_samples": _float_or_none(
            summary.get("source_isolated_reference_lag_samples")
        ),
        "source_isolation_db": _float_or_none(summary.get("source_isolation_db")),
        "source_open_gain_db": _float_or_none(summary.get("source_open_gain_db")),
        "source_open_recording_dbfs": _float_or_none(summary.get("source_open_recording_dbfs")),
        "source_open_reference_correlation": _float_or_none(
            summary.get("source_open_reference_correlation")
        ),
        "source_open_reference_distortion_db": _float_or_none(
            summary.get("source_open_reference_distortion_db")
        ),
        "source_open_reference_lag_samples": _float_or_none(
            summary.get("source_open_reference_lag_samples")
        ),
        "translated_headphone_gain_db": _float_or_none(summary.get("translated_headphone_gain_db")),
        "translated_headphone_recording_dbfs": _float_or_none(
            summary.get("translated_headphone_recording_dbfs")
        ),
        "translated_headphone_reference_correlation": _float_or_none(
            summary.get("translated_headphone_reference_correlation")
        ),
        "translated_headphone_reference_distortion_db": _float_or_none(
            summary.get("translated_headphone_reference_distortion_db")
        ),
        "translated_headphone_reference_lag_samples": _float_or_none(
            summary.get("translated_headphone_reference_lag_samples")
        ),
    }
    for field, value in metric_values.items():
        if value is None:
            failures.append(f"headphone_earpiece_isolation.summary.{field} must be finite")
    source_open_level = metric_values["source_open_recording_dbfs"]
    if source_open_level is not None and source_open_level < HEADPHONE_MIN_SOURCE_OPEN_DBFS:
        failures.append(
            "headphone_earpiece_isolation.summary.source_open_recording_dbfs must be "
            f">= {HEADPHONE_MIN_SOURCE_OPEN_DBFS:.1f}"
        )
    source_open_corr = metric_values["source_open_reference_correlation"]
    if source_open_corr is not None and source_open_corr < HEADPHONE_MIN_SOURCE_OPEN_CORRELATION:
        failures.append(
            "headphone_earpiece_isolation.summary.source_open_reference_correlation must be "
            f">= {HEADPHONE_MIN_SOURCE_OPEN_CORRELATION:.3f}"
        )
    isolation = metric_values["source_isolation_db"]
    if isolation is not None and isolation < HEADPHONE_MIN_SOURCE_ISOLATION_DB:
        failures.append(
            "headphone_earpiece_isolation.summary.source_isolation_db must be "
            f">= {HEADPHONE_MIN_SOURCE_ISOLATION_DB:.1f}"
        )
    translated_level = metric_values["translated_headphone_recording_dbfs"]
    if translated_level is not None and translated_level < HEADPHONE_MIN_TRANSLATED_DBFS:
        failures.append(
            "headphone_earpiece_isolation.summary.translated_headphone_recording_dbfs must be "
            f">= {HEADPHONE_MIN_TRANSLATED_DBFS:.1f}"
        )
    translated_corr = metric_values["translated_headphone_reference_correlation"]
    if translated_corr is not None and translated_corr < HEADPHONE_MIN_TRANSLATED_CORRELATION:
        failures.append(
            "headphone_earpiece_isolation.summary.translated_headphone_reference_correlation must be "
            f">= {HEADPHONE_MIN_TRANSLATED_CORRELATION:.3f}"
        )
    translated_distortion = metric_values["translated_headphone_reference_distortion_db"]
    if translated_distortion is not None and translated_distortion > HEADPHONE_MAX_TRANSLATED_DISTORTION_DB:
        failures.append(
            "headphone_earpiece_isolation.summary.translated_headphone_reference_distortion_db must be "
            f"<= {HEADPHONE_MAX_TRANSLATED_DISTORTION_DB:.1f}"
        )
    min_duration = metric_values["min_artifact_duration_s"]
    if min_duration is not None and min_duration < HEADPHONE_MIN_MEASUREMENT_DURATION_S:
        failures.append(
            "headphone_earpiece_isolation.summary.min_artifact_duration_s must be "
            f">= {HEADPHONE_MIN_MEASUREMENT_DURATION_S:.3f}"
        )

    artifact_paths = report.get("artifact_paths", {})
    artifact_hashes = report.get("artifact_hashes", {})
    resolved_artifacts: dict[str, Path] = {}
    if not isinstance(artifact_paths, dict) or not isinstance(artifact_hashes, dict):
        failures.append("headphone report must include artifact_paths and artifact_hashes objects")
    else:
        for key in HEADPHONE_REQUIRED_ARTIFACTS:
            artifact_path = _resolve_artifact_path(spec.path, artifact_paths.get(key))
            expected_hash = artifact_hashes.get(key)
            if artifact_path is None or not artifact_path.exists():
                failures.append(f"headphone artifact {key!r} is missing")
                continue
            resolved_artifacts[key] = artifact_path
            if not _is_sha256(expected_hash):
                failures.append(f"headphone artifact hash {key!r} is invalid")
            elif _sha256_file(artifact_path) != expected_hash:
                failures.append(f"headphone artifact hash {key!r} does not match file")
            try:
                with wave.open(str(artifact_path), "rb") as wav:
                    if wav.getnchannels() != 1:
                        failures.append(f"{key} WAV must be mono")
                    if wav.getsampwidth() != 2:
                        failures.append(f"{key} WAV sample width must be 2 bytes")
                    if wav.getnframes() <= 0:
                        failures.append(f"{key} WAV must contain frames")
                    if wav.getframerate() <= 0:
                        failures.append(f"{key} WAV sample rate must be positive")
                    elif wav.getnframes() / float(wav.getframerate()) < HEADPHONE_MIN_MEASUREMENT_DURATION_S:
                        failures.append(
                            f"{key} WAV duration must be >= {HEADPHONE_MIN_MEASUREMENT_DURATION_S:.3f}s"
                        )
            except (OSError, wave.Error) as exc:
                failures.append(f"{key} WAV could not be inspected: {exc}")
        if not failures:
            if artifact_hashes.get("source_open_ear_recording") == artifact_hashes.get("source_reference"):
                failures.append("headphone source-open recording must not be byte-identical to reference")
            if artifact_hashes.get("source_isolated_ear_recording") == artifact_hashes.get("source_reference"):
                failures.append("headphone source-isolated recording must not be byte-identical to reference")
            if artifact_hashes.get("translated_headphone_recording") == artifact_hashes.get("translated_playback_reference"):
                failures.append("headphone translated recording must not be byte-identical to reference")
        reported_fingerprint = summary.get("measurement_identity_fingerprint")
        if not _is_sha256(reported_fingerprint):
            failures.append("headphone_earpiece_isolation.summary.measurement_identity_fingerprint must be a SHA-256 hex string")
        else:
            expected_fingerprint = _headphone_measurement_identity_fingerprint(summary, artifact_hashes)
            if reported_fingerprint != expected_fingerprint:
                failures.append(
                    "headphone_earpiece_isolation.summary.measurement_identity_fingerprint does not match labels, sample rate, and artifact hashes"
                )

    if not failures:
        try:
            recomputed = _recompute_headphone_isolation_metrics(resolved_artifacts)
        except (OSError, ValueError, wave.Error) as exc:
            failures.append(f"headphone isolation metrics could not be recomputed from WAV artifacts: {exc}")
        else:
            for field, recomputed_value in recomputed.items():
                reported_value = metric_values.get(field)
                if reported_value is None:
                    continue
                tolerance = _headphone_metric_tolerance(field)
                if abs(reported_value - recomputed_value) > tolerance:
                    failures.append(
                        f"headphone_earpiece_isolation.summary.{field}={reported_value:.6g} "
                        f"does not match WAV-derived {recomputed_value:.6g}"
                    )
            if recomputed["source_open_recording_dbfs"] < HEADPHONE_MIN_SOURCE_OPEN_DBFS:
                failures.append(
                    "WAV-derived headphone source-open level must be "
                    f">= {HEADPHONE_MIN_SOURCE_OPEN_DBFS:.1f} dBFS"
                )
            if recomputed["source_open_reference_correlation"] < HEADPHONE_MIN_SOURCE_OPEN_CORRELATION:
                failures.append(
                    "WAV-derived headphone source-open/reference correlation must be "
                    f">= {HEADPHONE_MIN_SOURCE_OPEN_CORRELATION:.3f}"
                )
            if recomputed["source_isolation_db"] < HEADPHONE_MIN_SOURCE_ISOLATION_DB:
                failures.append(
                    "WAV-derived headphone source isolation must be "
                    f">= {HEADPHONE_MIN_SOURCE_ISOLATION_DB:.1f} dB"
                )
            if recomputed["translated_headphone_recording_dbfs"] < HEADPHONE_MIN_TRANSLATED_DBFS:
                failures.append(
                    "WAV-derived translated headphone level must be "
                    f">= {HEADPHONE_MIN_TRANSLATED_DBFS:.1f} dBFS"
                )
            if recomputed["translated_headphone_reference_correlation"] < HEADPHONE_MIN_TRANSLATED_CORRELATION:
                failures.append(
                    "WAV-derived translated headphone/reference correlation must be "
                    f">= {HEADPHONE_MIN_TRANSLATED_CORRELATION:.3f}"
                )
            if recomputed["translated_headphone_reference_distortion_db"] > HEADPHONE_MAX_TRANSLATED_DISTORTION_DB:
                failures.append(
                    "WAV-derived translated headphone/reference distortion must be "
                    f"<= {HEADPHONE_MAX_TRANSLATED_DISTORTION_DB:.1f} dB"
                )
            if recomputed["min_artifact_duration_s"] < HEADPHONE_MIN_MEASUREMENT_DURATION_S:
                failures.append(
                    "WAV-derived headphone isolation artifact duration must be "
                    f">= {HEADPHONE_MIN_MEASUREMENT_DURATION_S:.3f}s"
                )
    if failures:
        return _fail(spec, "; ".join(failures))
    return _pass(spec, "measured headphone/earpiece isolation evidence present; not true room cancellation")


def _playback_source_suppression_gate(
    spec: EvidenceSpec,
    headphone_report_path: Path,
) -> GateResult:
    room_result = _room_suppression_gate(spec)
    if room_result.passed:
        return GateResult(
            spec.name,
            True,
            spec.release_blocking,
            "true room source-cancellation evidence present",
            str(spec.path),
            spec.next_step,
        )
    headphone_spec = EvidenceSpec(
        spec.name,
        headphone_report_path,
        "measured headphone/earpiece source isolation at the listener",
        "Record listener-ear source-open, source-isolated, and translated-playback WAVs, then run scripts/run_headphone_isolation_check.py score.",
        spec.release_blocking,
    )
    headphone_result = _headphone_isolation_gate(headphone_spec)
    if headphone_result.passed:
        return GateResult(
            spec.name,
            True,
            spec.release_blocking,
            (
                "headphone/earpiece isolation evidence present, explicitly not true room cancellation; "
                f"room cancellation path did not pass ({room_result.message})"
            ),
            str(headphone_report_path),
            spec.next_step,
        )
    return GateResult(
        spec.name,
        False,
        spec.release_blocking,
        (
            f"room cancellation path failed: {room_result.message}; "
            f"headphone isolation path failed: {headphone_result.message}"
        ),
        f"{spec.path}; {headphone_report_path}",
        (
            "Either qualify a reference-faithful real-room cancellation path, or provide a "
            "measured headphone-isolation report with listener-ear WAV artifacts."
        ),
    )


def _playback_prototype_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    if report.get("fixture_kind") != "fleurs_playback_suppression":
        return _fail(spec, f"unexpected playback prototype fixture_kind: {report.get('fixture_kind')!r}")
    claim_gate = _quality_gates(report).get("suppression_claim_is_honest")
    if not isinstance(claim_gate, dict) or claim_gate.get("value") != PLAYBACK_PROTOTYPE_CLAIM:
        return _fail(spec, "playback prototype did not preserve the explicit not-true-cancellation claim")
    return _pass(spec, "prototype playback/ducking fixture passed with honest non-cancellation claim")


def _capture_prototype_gate(spec: EvidenceSpec) -> GateResult:
    report = _load_json(spec.path)
    prefix = _pass_fail_prefix(spec, report)
    if prefix:
        return prefix
    assert report is not None

    capture = _capture_summary(report)
    source_kind = capture.get("capture_source_kind") or report.get("capture_source_kind")
    release_proof = bool(capture.get("release_proof") or _summary(report).get("release_proof"))
    if report.get("fixture_kind") != "fixture_pcm_capture_replay" or source_kind != "fixture_replay":
        return _fail(spec, "capture prototype must identify itself as fixture replay")
    if release_proof:
        return _fail(spec, "capture prototype must not set release_proof=true")
    if not _gate_passed(report, "capture_not_release_proof"):
        return _fail(spec, "capture prototype must pass capture_not_release_proof gate")
    return _pass(spec, "fixture PCM capture scaffold passed and remained non-release evidence")


def release_specs(args: argparse.Namespace) -> list[EvidenceSpec]:
    return [
        EvidenceSpec(
            "live_microphone_capture_runtime",
            args.live_capture_report,
            "live microphone capture path with timestamped PCM chunks",
            "Implement a real microphone capture adapter that proves chunk timing, levels, "
            "drop/reorder counts, device identity, and sample-rate stability.",
        ),
        EvidenceSpec(
            "causal_diarization_runtime",
            args.causal_diarization_report,
            "causal diarization over arriving PCM chunks",
            "Promote a rolling diarization adapter from fixture smoke to a passing causal runtime report.",
        ),
        EvidenceSpec(
            "real_tse_or_separation_beats_passthrough",
            args.tse_report,
            "real target-speaker extraction or separation that beats mixture passthrough",
            "Replace warning-only separator spikes with a report that passes the mixture-passthrough comparison.",
        ),
        EvidenceSpec(
            "streaming_speech_translation_from_audio",
            args.streaming_translation_report,
            "speech translation after accepted diarization and TSE/separation",
            "Run streaming ASR/translation from causal/non-oracle diarization and accepted speaker-isolated audio.",
        ),
        EvidenceSpec(
            "same_voice_or_fallback_tts_audio_stream",
            args.voice_report,
            "same-voice or consent-safe fallback TTS audio stream",
            "Add a voice clone/TTS benchmark with consent metadata, output audio hashes, level matching, and fallback state.",
        ),
        EvidenceSpec(
            "playback_source_suppression_evidence",
            args.room_suppression_report,
            "real-room source cancellation or measured headphone/earpiece isolation",
            "Qualify a reference-faithful room path, or provide a measured headphone/earpiece isolation report that proves listener-ear source attenuation and translated playback.",
        ),
    ]


def prototype_specs(args: argparse.Namespace) -> list[EvidenceSpec]:
    return [
        EvidenceSpec(
            "playback_suppression_fixture",
            args.playback_prototype_report,
            "synthetic ducking/masking playback fixture",
            "Keep this as a gain-staging/prototype gate; do not use it as product source-cancellation evidence.",
            release_blocking=False,
        ),
        EvidenceSpec(
            "fixture_live_capture_scaffold",
            args.capture_prototype_report,
            "fixture-backed PCM capture scaffold",
            "Use this to validate chunk plumbing, then replace it with real microphone evidence.",
            release_blocking=False,
        ),
    ]


def evaluate(args: argparse.Namespace) -> tuple[list[GateResult], list[GateResult]]:
    release_results: list[GateResult] = []
    for spec in release_specs(args):
        if spec.name == "live_microphone_capture_runtime":
            release_results.append(_live_capture_gate(spec))
        elif spec.name == "causal_diarization_runtime":
            release_results.append(_causal_diarization_gate(spec))
        elif spec.name == "real_tse_or_separation_beats_passthrough":
            release_results.append(_tse_gate(spec))
        elif spec.name == "streaming_speech_translation_from_audio":
            release_results.append(_translation_after_tse_gate(spec))
        elif spec.name == "same_voice_or_fallback_tts_audio_stream":
            release_results.append(_voice_gate(spec))
        elif spec.name == "playback_source_suppression_evidence":
            release_results.append(_playback_source_suppression_gate(spec, args.headphone_isolation_report))
        else:
            raise AssertionError(f"unhandled release gate: {spec.name}")

    prototype_results: list[GateResult] = []
    for spec in prototype_specs(args):
        if spec.name == "playback_suppression_fixture":
            prototype_results.append(_playback_prototype_gate(spec))
        elif spec.name == "fixture_live_capture_scaffold":
            prototype_results.append(_capture_prototype_gate(spec))
        else:
            raise AssertionError(f"unhandled prototype gate: {spec.name}")
    return release_results, prototype_results


def build_report(release_results: list[GateResult], prototype_results: list[GateResult]) -> dict[str, Any]:
    blocking_failures = [gate for gate in release_results if not gate.passed and gate.release_blocking]
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "summary": {
            "passed": not blocking_failures,
            "release_blocking_gate_count": len(release_results),
            "release_blocking_failure_count": len(blocking_failures),
            "prototype_evidence_gate_count": len(prototype_results),
        },
        "release_blocking_gates": [gate.as_dict() for gate in release_results],
        "prototype_evidence_gates": [gate.as_dict() for gate in prototype_results],
        "detractor_loop": {
            "verdict": (
                "Do not call this a working realtime translated-audio release until every "
                "release-blocking gate passes with product-specific real-audio evidence."
            ),
            "strongest_current_objection": (
                "Passing report files are not enough. The gate rejects stubs and prototype "
                "fixtures unless the report carries product-specific gates and independently "
                "coherent artifacts. Local host capture evidence is artifact-coherent, not "
                "tamper-proof provenance."
            ),
        },
    }


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")


def playback_source_suppression_handoff_lines() -> list[str]:
    return [
        "",
        "### Playback/Source Suppression Evidence Collection",
        "",
        "Hardware setup:",
        "",
        "- Use a USB/lavalier microphone or phone/external recorder physically at the listener-ear point, inside or flush with the headphone/earpiece seal.",
        "- Use the laptop built-in microphone only for `route_probe_triage_only`; it is not final release evidence.",
        "- Keep the source speaker, headphone/earpiece seal, playback gain, and listener-ear microphone position fixed between matching takes.",
        "- Export manual-recorder takes as mono 16-bit PCM WAV at the kit sample rate, or import stereo recorder exports with `--allow-downmix`.",
        "",
        "Guided host path, only when preflight finds a capture-ready external listener-ear input:",
        "",
        "```powershell",
        "$env:LANGUAGE_PYTHON = \"C:\\Path\\To\\python.exe\"",
        "$headphoneLabel = \"REPLACE_WITH_HEADPHONE_MODEL\"",
        "$fixtureLabel = \"REPLACE_WITH_EARCUP_AND_MIC_POSITION\"",
        "$microphoneLabel = \"REPLACE_WITH_MIC_MODEL_AND_POSITION\"",
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action preflight -Python $env:LANGUAGE_PYTHON --sample-rate-hz 48000 --input-channels 1 --output-channels 2",
        "# If the preflight report emits confirm_physical_input_preflight and capture commands, run those generated commands exactly.",
        "python scripts/release_audio_gate.py --json",
        "```",
        "",
        "Manual recorder fallback when host routing is unreliable or no capture-ready input is available:",
        "",
        "```powershell",
        "$env:LANGUAGE_PYTHON = \"C:\\Path\\To\\python.exe\"",
        "$headphoneLabel = \"REPLACE_WITH_HEADPHONE_MODEL\"",
        "$fixtureLabel = \"REPLACE_WITH_EARCUP_AND_MIC_POSITION\"",
        "$microphoneLabel = \"REPLACE_WITH_MIC_MODEL_AND_POSITION\"",
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action prepare-manual -Python $env:LANGUAGE_PYTHON --sample-rate-hz 48000 --playback-gain-db -18",
        "# Record the three listener-ear WAVs named in manual-recording-checklist.md, or import raw recorder exports:",
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action import-manual -Python $env:LANGUAGE_PYTHON --source-open-ear-recording RAW_SOURCE_OPEN.wav --source-isolated-ear-recording RAW_SOURCE_ISOLATED.wav --translated-headphone-recording RAW_TRANSLATED.wav --allow-downmix",
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action check-manual -Python $env:LANGUAGE_PYTHON --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel",
        "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action score-manual -Python $env:LANGUAGE_PYTHON --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel",
        "python scripts/release_audio_gate.py --json",
        "```",
    ]


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    passed = bool(summary.get("passed"))
    status = "PASS" if passed else "FAIL"
    lines = [
        "# Language Release Audio Gate",
        "",
        f"- Status: **{status}**",
        f"- Release-blocking gates: {summary.get('release_blocking_gate_count', 0)}",
        f"- Release-blocking failures: {summary.get('release_blocking_failure_count', 0)}",
        f"- Prototype evidence gates: {summary.get('prototype_evidence_gate_count', 0)}",
        "",
    ]
    detractor = report.get("detractor_loop", {})
    if isinstance(detractor, dict):
        lines.extend(
            [
                "## Detractor Verdict",
                "",
                str(detractor.get("verdict", "")).strip(),
                "",
                f"Strongest current objection: {str(detractor.get('strongest_current_objection', '')).strip()}",
                "",
            ]
        )
    lines.extend(["## Release-Blocking Gates", ""])
    for gate in report.get("release_blocking_gates", []):
        if not isinstance(gate, dict):
            continue
        gate_status = "PASS" if gate.get("passed") else "FAIL"
        lines.extend(
            [
                f"### {gate_status} {gate.get('name', 'unnamed_gate')}",
                "",
                f"- Message: {gate.get('message', '')}",
                f"- Evidence path: `{gate.get('path', '')}`",
            ]
        )
        if gate.get("passed"):
            lines.append("- Evidence status: accepted by this release gate.")
        else:
            lines.append(f"- Next step: {gate.get('next_step', '')}")
        lines.append("")
    lines.extend(["## Prototype Evidence", ""])
    for gate in report.get("prototype_evidence_gates", []):
        if not isinstance(gate, dict):
            continue
        gate_status = "PASS" if gate.get("passed") else "FAIL"
        lines.extend(
            [
                f"### {gate_status} {gate.get('name', 'unnamed_gate')}",
                "",
                f"- Message: {gate.get('message', '')}",
                f"- Evidence path: `{gate.get('path', '')}`",
                f"- Next step: {gate.get('next_step', '')}",
                "",
            ]
        )
    failed_release_gates = [
        gate
        for gate in report.get("release_blocking_gates", [])
        if isinstance(gate, dict) and not bool(gate.get("passed"))
    ]
    lines.extend(
        [
            "## Operator Handoff",
            "",
            "- Treat this Markdown as a readable handoff; the JSON report remains the authoritative artifact.",
        ]
    )
    included_playback_collection = False
    if failed_release_gates:
        lines.append("- Do not ship a realtime audio-loop release while any release-blocking gate is FAIL.")
        failed_names = {str(gate.get("name", "")) for gate in failed_release_gates}
        if "playback_source_suppression_evidence" in failed_names:
            lines.append(
                "- For the current playback/source suppression blocker, provide either a passing real-room "
                "cancellation report or a passing physical headphone/earpiece listener-ear isolation report."
            )
            lines.extend(playback_source_suppression_handoff_lines())
            included_playback_collection = True
        else:
            lines.append("- Address each failed release-blocking gate above, then rerun the gate.")
    else:
        lines.append("- All release-blocking gates passed in this report; preserve the referenced evidence artifacts.")
        lines.append("- Rerun this gate for the exact commit and artifact set before publishing.")
    if not included_playback_collection:
        lines.append(
            "- When collecting headphone/earpiece evidence, laptop built-in microphones are route triage only; "
            "final evidence needs a real listener-ear microphone/recorder path."
        )
    lines.append("")
    return "\n".join(lines)


def write_markdown_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown_report(report), encoding="utf-8")


def print_summary(report: dict[str, Any], report_path: Path, markdown_report_path: Path | None = None) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(f"release audio gate {status}")
    for gate in report["release_blocking_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['message']}")
        if not gate["passed"]:
            print(f"    next: {gate['next_step']}")
    for gate in report["prototype_evidence_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [prototype {gate_status}] {gate['name']}: {gate['message']}")
    print(f"wrote release audio gate report to {report_path}")
    if markdown_report_path is not None:
        print(f"wrote release audio gate handoff to {markdown_report_path}")


def _report(passed: bool, gates: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "summary": {
            "passed": passed,
            "quality_gates": gates or [],
        },
    }
    payload.update(extra)
    return payload


def _passed_gates(names: set[str]) -> list[dict[str, Any]]:
    return [{"name": name, "passed": True, "value": True} for name in sorted(names)]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def _write_unit_pcm16_wav(path: Path, sample_rate_hz: int, frame_count: int) -> None:
    sample = int(1000).to_bytes(2, byteorder="little", signed=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(sample * frame_count)


def _write_pcm16_samples_wav(path: Path, sample_rate_hz: int, samples: list[int]) -> None:
    frames = bytearray()
    for sample in samples:
        clamped = max(-32768, min(32767, int(round(sample))))
        frames.extend(clamped.to_bytes(2, byteorder="little", signed=True))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(bytes(frames))


def _write_live_capture_fixture_report(path: Path) -> None:
    sample_rate_hz = 16_000
    chunk_frames = 8_000
    chunk_duration_ms = 500.0
    audio_path = path.parent / "captured.wav"
    chunks_path = path.parent / "capture_chunks.jsonl"
    _write_unit_pcm16_wav(audio_path, sample_rate_hz, chunk_frames * 2)
    records = [
        {
            "callback_wall_time_offset_s": 0.0,
            "chunk_index": 0,
            "current_time_s": None,
            "duration_error_ms": 0.0,
            "duration_ms": chunk_duration_ms,
            "end_sample": chunk_frames,
            "frame_count": chunk_frames,
            "input_adc_time_s": None,
            "peak_dbfs": -30.0,
            "rms_dbfs": -40.0,
            "sha256_float32": "0" * 64,
            "start_sample": 0,
            "status": "",
            "target_duration_ms": chunk_duration_ms,
        },
        {
            "callback_wall_time_offset_s": 0.5,
            "chunk_index": 1,
            "current_time_s": None,
            "duration_error_ms": 0.0,
            "duration_ms": chunk_duration_ms,
            "end_sample": chunk_frames * 2,
            "frame_count": chunk_frames,
            "input_adc_time_s": None,
            "peak_dbfs": -30.0,
            "rms_dbfs": -40.0,
            "sha256_float32": "1" * 64,
            "start_sample": chunk_frames,
            "status": "",
            "target_duration_ms": chunk_duration_ms,
        },
    ]
    _write_jsonl(chunks_path, records)
    audio_hash = _sha256_file(audio_path)
    chunks_hash = _sha256_file(chunks_path)
    capture_summary = {
        "adapter_id": EXPECTED_LIVE_CAPTURE_ADAPTER_ID,
        "artifact_hash_chain_present": True,
        "backend": EXPECTED_LIVE_CAPTURE_BACKEND,
        "callback_clock_duration_s": 1.0,
        "callback_status_count": 0,
        "callback_statuses": [],
        "capture_chunks_path": str(chunks_path),
        "capture_chunks_sha256": chunks_hash,
        "capture_source_kind": "microphone",
        "captured_audio_path": str(audio_path),
        "captured_audio_sha256": audio_hash,
        "captured_frame_count": chunk_frames * 2,
        "channel_count": 1,
        "chunk_count": 2,
        "chunk_frame_count": chunk_frames,
        "chunk_hashes_present": True,
        "chunk_ms": chunk_duration_ms,
        "device": {
            "default_samplerate": float(sample_rate_hz),
            "hostapi": "unit",
            "max_input_channels": 1,
            "name": "unit microphone",
            "requested_device": None,
        },
        "dropped_or_reordered_chunk_count": 0,
        "duration_from_frames_s": 1.0,
        "duration_s": 1.0,
        "expected_indices_match": True,
        "frame_clock_drift_ppm": 0.0,
        "generator": EXPECTED_LIVE_CAPTURE_GENERATOR,
        "input_level_dbfs": -40.0,
        "input_peak_dbfs": -30.0,
        "max_interarrival_jitter_ms": 0.0,
        "mean_interarrival_ms": chunk_duration_ms,
        "p95_interarrival_jitter_ms": 0.0,
        "pcm_subtype": "PCM_16",
        "provenance_kind": EXPECTED_LIVE_CAPTURE_PROVENANCE_KIND,
        "provenance_trust_boundary": EXPECTED_LIVE_CAPTURE_TRUST_BOUNDARY,
        "release_proof": True,
        "sample_rate_source": "requested_portaudio_stream",
        "sample_rates_hz": [sample_rate_hz],
        "timestamp_monotonic": True,
        "timestamp_source": "callback_wall_clock_fallback",
        "wall_duration_s": 1.0,
    }
    _write_json(
        path,
        _report(
            True,
            _passed_gates(LIVE_CAPTURE_REQUIRED_GATES),
            fixture_kind="live_microphone_capture",
            capture_source_kind="microphone",
            benchmarks={
                "capture": {
                    "adapter_id": EXPECTED_LIVE_CAPTURE_ADAPTER_ID,
                    "summary": capture_summary,
                    "chunks": records,
                }
            },
            prediction_paths={"capture_chunks": str(chunks_path)},
            artifact_paths={"captured_audio": str(audio_path)},
            artifact_hashes={"captured_audio": audio_hash, "capture_chunks": chunks_hash},
        ),
    )


def _write_voice_fixture_report(path: Path, *, forge_hash: bool = False) -> None:
    sample_rate_hz = 16_000
    frame_count = 8_000
    audio_path = path.parent / "fallback-tts.wav"
    reference_path = path.parent / "fallback-reference.wav"
    _write_unit_pcm16_wav(audio_path, sample_rate_hz, frame_count)
    _write_unit_pcm16_wav(reference_path, sample_rate_hz, frame_count)
    audio_hash = _sha256_file(audio_path)
    reference_hash = _sha256_file(reference_path)
    if forge_hash:
        audio_hash = "0" * 64 if audio_hash != "0" * 64 else "1" * 64
    segment = {
        "fixture_id": "unit_voice_fixture",
        "input_level_dbfs": -24.0,
        "output_level_error_db": 0.0,
        "reference_audio_path": str(reference_path),
        "reference_audio_sha256": reference_hash,
        "reference_audio_usage": "level_measurement_only",
        "segment_index": 0,
        "speaker_id": "speaker_unit",
        "target_language_code": "en",
        "translated_text": "Unit fallback voice.",
        "tts_output_frame_count": frame_count,
        "tts_output_level_dbfs": -24.0,
        "tts_output_path": str(audio_path),
        "tts_output_sha256": audio_hash,
        "voice_clone_reference_used": False,
        "voice_clone_status": "fallback_voice",
        "voice_similarity_claim": "not_claimed",
    }
    report = _report(
        True,
        _passed_gates(VOICE_REQUIRED_GATES),
        fixture_kind="fallback_tts_audio_stream",
        benchmarks={
            "same_voice_or_fallback_tts": {
                "adapter_id": "unit_fallback_tts",
                "segments": [segment],
                "summary": {
                    "max_output_level_error_db": 0.0,
                    "segment_count": 1,
                    "voice_clone_status": "fallback_voice",
                    "voice_similarity_claim": "not_claimed",
                },
            }
        },
        adapter={
            "voice": {
                "adapter_id": "unit_fallback_tts",
                "mode": "fallback_voice",
                "voice_clone_reference_used": False,
                "voice_similarity_claim": "not_claimed",
            }
        },
    )
    report["summary"].update(
        {
            "max_output_level_error_db": 0.0,
            "segment_count": 1,
            "voice_clone_status": "fallback_voice",
            "voice_similarity_claim": "not_claimed",
        }
    )
    _write_json(path, report)


def _level_dbfs_from_samples(samples: list[int]) -> float:
    values = array.array("h", samples)
    return _dbfs_from_rms_i16(_rms_i16(values))


def _write_voice_candidate_fixture_report(
    path: Path,
    *,
    clone_reference: bool = False,
    reported_level_error: float | None = None,
    similarity_score: float | None = None,
    output_gain: float = 1.0,
) -> None:
    sample_rate_hz = 16_000
    frame_count = 8_000
    reference_samples: list[int] = []
    output_samples: list[int] = []
    for index in range(frame_count):
        t = float(index) / float(sample_rate_hz)
        reference = int(round(8500.0 * math.sin(2.0 * math.pi * 180.0 * t)))
        if clone_reference:
            output = reference
        else:
            output = int(round(output_gain * 8500.0 * math.sin(2.0 * math.pi * 185.0 * t)))
        reference_samples.append(reference)
        output_samples.append(output)
    reference_path = path.parent / f"{path.stem}-candidate-reference.wav"
    output_path = path.parent / f"{path.stem}-candidate-output.wav"
    consent_path = path.parent / f"{path.stem}-candidate-consent.txt"
    evidence_path = path.parent / f"{path.stem}-candidate-similarity.json"
    _write_pcm16_samples_wav(reference_path, sample_rate_hz, reference_samples)
    _write_pcm16_samples_wav(output_path, sample_rate_hz, output_samples)
    consent_path.write_text("unit test speaker consent\n", encoding="utf-8")
    reference_hash = _sha256_file(reference_path)
    output_hash = _sha256_file(output_path)
    reference_details = _mono_pcm16_wav_details(reference_path)
    output_details = _mono_pcm16_wav_details(output_path)
    proxy_score = _acoustic_similarity_proxy(
        array.array("h", reference_samples),
        array.array("h", output_samples),
        sample_rate_hz,
    )
    reported_similarity_score = proxy_score if similarity_score is None else similarity_score
    evidence = {
        "schema_version": 1,
        "evaluator_id": VOICE_CANDIDATE_EVALUATOR_ID,
        "metric_name": VOICE_CANDIDATE_METRIC_NAME,
        "reference_audio_pcm_sha256": reference_details["pcm_sha256"],
        "reference_audio_sha256": reference_hash,
        "score": reported_similarity_score,
        "speaker_id": "speaker_unit",
        "threshold": 0.65,
        "tts_output_pcm_sha256": output_details["pcm_sha256"],
        "tts_output_sha256": output_hash,
    }
    _write_json(evidence_path, evidence)
    reference_dbfs = _level_dbfs_from_samples(reference_samples)
    output_dbfs = _level_dbfs_from_samples(output_samples)
    level_error = abs(output_dbfs - reference_dbfs)
    if reported_level_error is not None:
        level_error = reported_level_error
    segment = {
        "fixture_id": "unit_voice_candidate",
        "input_level_dbfs": round(reference_dbfs, 3),
        "output_level_error_db": round(level_error, 3),
        "reference_audio_path": str(reference_path),
        "reference_audio_sha256": reference_hash,
        "reference_audio_pcm_sha256": reference_details["pcm_sha256"],
        "reference_audio_usage": "voice_clone_reference_and_similarity_measurement",
        "segment_index": 0,
        "speaker_id": "speaker_unit",
        "source_audio_path": str(reference_path),
        "source_audio_sha256": reference_hash,
        "source_audio_pcm_sha256": reference_details["pcm_sha256"],
        "target_language_code": "en",
        "translated_text": "Unit same voice candidate.",
        "tts_output_frame_count": frame_count,
        "tts_output_level_dbfs": round(output_dbfs, 3),
        "tts_output_path": str(output_path),
        "tts_output_pcm_sha256": output_details["pcm_sha256"],
        "tts_output_sha256": output_hash,
        "voice_clone_reference_used": True,
        "voice_clone_status": "same_voice_candidate",
        "voice_similarity_claim": "measured_proxy",
        "voice_similarity_evaluator_id": VOICE_CANDIDATE_EVALUATOR_ID,
        "voice_similarity_evidence_path": str(evidence_path),
        "voice_similarity_evidence_sha256": _sha256_file(evidence_path),
        "voice_similarity_metric": VOICE_CANDIDATE_METRIC_NAME,
        "voice_similarity_score": reported_similarity_score,
        "voice_similarity_threshold": 0.65,
    }
    report = _report(
        True,
        _passed_gates(VOICE_REQUIRED_GATES),
        fixture_kind="same_voice_candidate_tts_audio_stream",
        benchmarks={
            "same_voice_or_fallback_tts": {
                "adapter_id": "unit_same_voice_candidate",
                "segments": [segment],
                "summary": {
                    "max_output_level_error_db": round(level_error, 3),
                    "min_voice_similarity_score": reported_similarity_score,
                    "segment_count": 1,
                    "voice_clone_status": "same_voice_candidate",
                    "voice_similarity_claim": "measured_proxy",
                },
            }
        },
        adapter={
            "voice": {
                "adapter_id": "unit_same_voice_candidate",
                "mode": "same_voice_candidate",
                "voice_clone_reference_used": True,
                "voice_similarity_claim": "measured_proxy",
            }
        },
    )
    report["summary"].update(
        {
            "max_output_level_error_db": round(level_error, 3),
            "min_voice_similarity_score": reported_similarity_score,
            "segment_count": 1,
            "voice_clone_status": "same_voice_candidate",
            "voice_similarity_claim": "measured_proxy",
        }
    )
    report["consent"] = {
        "consent_basis": "unit test speaker consent",
        "consent_evidence_path": str(consent_path),
        "consent_evidence_sha256": _sha256_file(consent_path),
        "reference_retention_policy": "ephemeral_reference_deleted",
        "reference_audio_sha256s": [reference_hash],
        "speaker_consent": True,
        "speaker_ids": ["speaker_unit"],
        "voice_clone_reference_used": True,
    }
    _write_json(path, report)


def _write_room_suppression_fixture_report(
    path: Path,
    summary_overrides: dict[str, Any] | None = None,
) -> None:
    sample_rate_hz = 16_000
    frame_count = 16_000
    prefix = path.stem
    source_path = path.parent / f"{prefix}-room-source-reference.wav"
    translated_path = path.parent / f"{prefix}-room-translated-reference.wav"
    source_recording_path = path.parent / f"{prefix}-source-only-room-recording.wav"
    translated_recording_path = path.parent / f"{prefix}-translated-only-room-recording.wav"
    recording_path = path.parent / f"{prefix}-room-loopback-recording.wav"
    residual_gain = 10.0 ** (-7.0 / 20.0)
    source_samples: list[int] = []
    translated_samples: list[int] = []
    loopback_samples: list[int] = []
    for index in range(frame_count):
        t = float(index) / float(sample_rate_hz)
        source = int(round(9000.0 * math.sin(2.0 * math.pi * 220.0 * t)))
        translated = int(round(8500.0 * math.sin(2.0 * math.pi * 330.0 * t)))
        source_samples.append(source)
        translated_samples.append(translated)
        loopback_samples.append(int(round(translated + (source * residual_gain))))
    _write_pcm16_samples_wav(source_path, sample_rate_hz, source_samples)
    _write_pcm16_samples_wav(translated_path, sample_rate_hz, translated_samples)
    _write_pcm16_samples_wav(source_recording_path, sample_rate_hz, source_samples)
    _write_pcm16_samples_wav(translated_recording_path, sample_rate_hz, translated_samples)
    _write_pcm16_samples_wav(recording_path, sample_rate_hz, loopback_samples)
    artifact_paths = {
        "room_loopback_recording": str(recording_path),
        "source_only_room_recording": str(source_recording_path),
        "source_reference": str(source_path),
        "translated_only_room_recording": str(translated_recording_path),
        "translated_playback_reference": str(translated_path),
    }
    artifact_hashes = {
        key: _sha256_file(Path(value))
        for key, value in artifact_paths.items()
    }
    device_info = {
        "input_device": {
            "default": False,
            "default_samplerate": sample_rate_hz,
            "hostapi": 0,
            "hostapi_name": "unit-hostapi",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "name": "unit-input",
            "requested_device": 1,
            "resolved_device_index": 1,
        },
        "output_device": {
            "default": False,
            "default_samplerate": sample_rate_hz,
            "hostapi": 0,
            "hostapi_name": "unit-hostapi",
            "max_input_channels": 0,
            "max_output_channels": 2,
            "name": "unit-output",
            "requested_device": 2,
            "resolved_device_index": 2,
        },
    }
    fingerprint = _device_path_fingerprint(
        device_info,
        sample_rate_hz=sample_rate_hz,
        input_channels=1,
        output_channels=2,
    )
    recomputed = _recompute_room_metrics({key: Path(value) for key, value in artifact_paths.items()})
    room_summary = {
        "device_path_fingerprint": fingerprint,
        "device_path_identity_recorded": True,
        "input_channels": 1,
        "measurement_kind": ROOM_REQUIRED_MEASUREMENT_KIND,
        "output_channels": 2,
        "sample_rate_hz": sample_rate_hz,
        "source_calibration_dbfs": round(recomputed["source_calibration_dbfs"], 3),
        "source_calibration_reference_correlation": round(
            recomputed["source_calibration_reference_correlation"],
            6,
        ),
        "source_calibration_reference_distortion_db": round(
            recomputed["source_calibration_reference_distortion_db"],
            3,
        ),
        "source_residual_dbfs": round(recomputed["source_residual_dbfs"], 3),
        "source_residual_reduction_db": round(recomputed["source_residual_reduction_db"], 3),
        "suppression_claim": ROOM_REQUIRED_SUPPRESSION_CLAIM,
        "translated_audio_is_surrogate": False,
        "translated_calibration_reference_correlation": round(
            recomputed["translated_calibration_reference_correlation"],
            6,
        ),
        "translated_calibration_reference_distortion_db": round(
            recomputed["translated_calibration_reference_distortion_db"],
            3,
        ),
        "translated_output_correlation": round(recomputed["translated_output_correlation"], 6),
        "translated_output_distortion_db": round(recomputed["translated_output_distortion_db"], 3),
        "translated_reference_dbfs": round(recomputed["translated_reference_dbfs"], 3),
    }
    if summary_overrides:
        room_summary.update(summary_overrides)
    _write_json(
        path,
        _report(
            True,
            _passed_gates(ROOM_SUPPRESSION_REQUIRED_GATES),
            fixture_kind="real_room_playback_suppression",
            benchmarks={
                "room_playback_suppression": {
                    "adapter_id": "unit_room_loopback",
                    "device": device_info,
                    "summary": room_summary,
                }
            },
            artifact_hashes=artifact_hashes,
            artifact_paths=artifact_paths,
        ),
    )


def _headphone_summary_from_recomputed(
    recomputed: dict[str, float],
    *,
    artifact_hashes: dict[str, str],
    headphone_device_label: str,
    isolation_fixture_label: str,
    measurement_microphone_label: str,
    release_proof: bool = True,
    suppression_claim: str = HEADPHONE_REQUIRED_SUPPRESSION_CLAIM,
    translated_audio_is_surrogate: bool = False,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "capture_backend": "external_wav_measurement",
        "capture_source_kind": "external_listener_ear_wav_measurement",
        "device_path_fingerprint": "",
        "device_path_identity_recorded": False,
        "device_info": {},
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "max_alignment_lag_ms": ROOM_MAX_ALIGNMENT_LAG_MS,
        "measurement_kind": HEADPHONE_REQUIRED_MEASUREMENT_KIND,
        "measurement_microphone_label": measurement_microphone_label,
        "release_proof": release_proof,
        "sample_rate_hz": 16_000,
        "source_isolated_recording_matches_reference": (
            artifact_hashes["source_isolated_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_open_recording_matches_reference": (
            artifact_hashes["source_open_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_suppression_mode": HEADPHONE_REQUIRED_SUPPRESSION_MODE,
        "suppression_claim": suppression_claim,
        "translated_audio_is_surrogate": translated_audio_is_surrogate,
        "translated_headphone_recording_matches_reference": (
            artifact_hashes["translated_headphone_recording"] == artifact_hashes["translated_playback_reference"]
        ),
    }
    for field, value in recomputed.items():
        if field.endswith("_correlation"):
            summary[field] = round(value, 6)
        elif field.endswith("_lag_samples"):
            summary[field] = value
        else:
            summary[field] = round(value, 3)
    summary["measurement_identity_fingerprint"] = _headphone_measurement_identity_fingerprint(
        summary,
        artifact_hashes,
    )
    return summary


def _write_headphone_isolation_fixture_report(
    path: Path,
    *,
    clone_reference: bool = False,
    forge_hash: bool = False,
    guided_capture: bool = False,
    hybrid_capture_source: bool = False,
    mismatch_guided_fingerprint: bool = False,
    no_isolation: bool = False,
    placeholder_labels: bool = False,
    release_proof: bool = True,
    short_duration: bool = False,
    summary_overrides: dict[str, Any] | None = None,
) -> None:
    sample_rate_hz = 16_000
    frame_count = 800 if short_duration else 16_000
    prefix = path.stem
    source_path = path.parent / f"{prefix}-headphone-source-reference.wav"
    source_open_path = path.parent / f"{prefix}-source-open-ear-recording.wav"
    source_isolated_path = path.parent / f"{prefix}-source-isolated-ear-recording.wav"
    translated_path = path.parent / f"{prefix}-headphone-translated-reference.wav"
    translated_recording_path = path.parent / f"{prefix}-translated-headphone-recording.wav"
    source_samples: list[int] = []
    source_open_samples: list[int] = []
    source_isolated_samples: list[int] = []
    translated_samples: list[int] = []
    translated_recording_samples: list[int] = []
    open_gain = 10.0 ** (-2.0 / 20.0)
    isolated_gain = open_gain if no_isolation else 10.0 ** (-18.0 / 20.0)
    translated_gain = 10.0 ** (-3.0 / 20.0)
    for index in range(frame_count):
        t = float(index) / float(sample_rate_hz)
        source = int(round(9000.0 * math.sin(2.0 * math.pi * 220.0 * t)))
        translated = int(round(8500.0 * math.sin(2.0 * math.pi * 330.0 * t)))
        source_samples.append(source)
        source_open_samples.append(source if clone_reference else int(round(source * open_gain)))
        source_isolated_samples.append(source if clone_reference else int(round(source * isolated_gain)))
        translated_samples.append(translated)
        translated_recording_samples.append(
            translated if clone_reference else int(round(translated * translated_gain))
        )
    _write_pcm16_samples_wav(source_path, sample_rate_hz, source_samples)
    _write_pcm16_samples_wav(source_open_path, sample_rate_hz, source_open_samples)
    _write_pcm16_samples_wav(source_isolated_path, sample_rate_hz, source_isolated_samples)
    _write_pcm16_samples_wav(translated_path, sample_rate_hz, translated_samples)
    _write_pcm16_samples_wav(translated_recording_path, sample_rate_hz, translated_recording_samples)
    artifact_paths = {
        "source_reference": str(source_path),
        "source_open_ear_recording": str(source_open_path),
        "source_isolated_ear_recording": str(source_isolated_path),
        "translated_playback_reference": str(translated_path),
        "translated_headphone_recording": str(translated_recording_path),
    }
    artifact_hashes = {
        key: _sha256_file(Path(value))
        for key, value in artifact_paths.items()
    }
    if forge_hash:
        original_hash = artifact_hashes["translated_headphone_recording"]
        artifact_hashes["translated_headphone_recording"] = (
            "0" * 64 if original_hash != "0" * 64 else "1" * 64
        )
    recomputed = _recompute_headphone_isolation_metrics({key: Path(value) for key, value in artifact_paths.items()})
    headphone_device_label = "unspecified headphones" if placeholder_labels else "unit headphones"
    isolation_fixture_label = (
        "unspecified headphone/earpiece fixture" if placeholder_labels else "unit sealed-ear fixture"
    )
    measurement_microphone_label = (
        "unspecified listener-ear microphone" if placeholder_labels else "unit listener-ear microphone"
    )
    headphone_summary = _headphone_summary_from_recomputed(
        recomputed,
        artifact_hashes=artifact_hashes,
        headphone_device_label=headphone_device_label,
        isolation_fixture_label=isolation_fixture_label,
        measurement_microphone_label=measurement_microphone_label,
        release_proof=release_proof,
    )
    if guided_capture:
        device_info = {
            "headphone_output_device": {
                "default": False,
                "default_samplerate": sample_rate_hz,
                "hostapi": 0,
                "hostapi_name": "unit-hostapi",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "name": "unit-headphones",
                "requested_device": 3,
            },
            "measurement_input_device": {
                "default": False,
                "default_samplerate": sample_rate_hz,
                "hostapi": 0,
                "hostapi_name": "unit-hostapi",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "name": "unit-ear-mic",
                "requested_device": 1,
            },
            "source_output_device": {
                "default": False,
                "default_samplerate": sample_rate_hz,
                "hostapi": 0,
                "hostapi_name": "unit-hostapi",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "name": "unit-source-speaker",
                "requested_device": 2,
            },
        }
        capture = {
            "input_channels": 1,
            "output_channels": 2,
            "sample_rate_hz": sample_rate_hz,
        }
        headphone_summary.update(
            {
                "capture_backend": HEADPHONE_GUIDED_CAPTURE_BACKEND,
                "capture_source_kind": "host_guided_listener_ear_playrec_measurement",
                "capture": capture,
                "device_info": device_info,
                "device_path_identity_recorded": True,
            }
        )
        headphone_summary["device_path_fingerprint"] = _headphone_guided_device_fingerprint(
            headphone_summary
        )
        if mismatch_guided_fingerprint:
            headphone_summary["device_path_fingerprint"] = "0" * 64
        headphone_summary["capture_preflight_binding"] = {
            "bound": True,
            "capture_device_path_fingerprint": headphone_summary["device_path_fingerprint"],
            "input_channels": 1,
            "inventory_fingerprint": "a" * 64,
            "output_channels": 2,
            "physical_listener_ear_input_confirmed": True,
            "planning_passed": True,
            "preflight_device_info": device_info,
            "preflight_report_sha256": "b" * 64,
            "recommended_path": "guided_capture_possible",
            "sample_rate_hz": sample_rate_hz,
            "selected_route": "1:2:3",
            "selected_route_capture_ready": True,
        }
    if hybrid_capture_source:
        headphone_summary["capture_backend"] = "external_wav_measurement"
        headphone_summary["capture_source_kind"] = "host_guided_listener_ear_playrec_measurement"
    if summary_overrides:
        headphone_summary.update(summary_overrides)
    payload = _report(
        release_proof,
        _passed_gates(HEADPHONE_ISOLATION_REQUIRED_GATES),
        fixture_kind=HEADPHONE_REQUIRED_FIXTURE_KIND,
        measurement_kind=HEADPHONE_REQUIRED_MEASUREMENT_KIND,
        release_proof=release_proof,
        benchmarks={
            HEADPHONE_REQUIRED_BENCHMARK_NAME: {
                "adapter_id": "unit_headphone_earpiece_isolation",
                "summary": headphone_summary,
            }
        },
        artifact_hashes=artifact_hashes,
        artifact_paths=artifact_paths,
    )
    payload["summary"]["release_proof"] = release_proof
    _write_json(path, payload)


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if _specific_measurement_label("REPLACE_WITH_MIC_MODEL_AND_POSITION"):
            raise AssertionError("REPLACE_WITH labels must be rejected as placeholder measurement labels")
        stub = root / "stub.json"
        failing = root / "failing.json"
        capture = root / "capture.json"
        forged_capture = root / "forged-capture.json"
        fixture_capture = root / "fixture-capture.json"
        diarization = root / "diarization.json"
        tse = root / "tse.json"
        translation = root / "translation.json"
        voice = root / "voice.json"
        forged_voice = root / "forged-voice.json"
        voice_candidate = root / "voice-candidate.json"
        weak_voice_candidate = root / "weak-voice-candidate.json"
        forged_level_voice_candidate = root / "forged-level-voice-candidate.json"
        clone_voice_candidate = root / "clone-voice-candidate.json"
        room = root / "room.json"
        forged_room = root / "forged-room.json"
        mismatched_room = root / "mismatched-room.json"
        headphone = root / "headphone.json"
        forged_headphone = root / "forged-headphone.json"
        no_isolation_headphone = root / "no-isolation-headphone.json"
        clone_headphone = root / "clone-headphone.json"
        surrogate_headphone = root / "surrogate-headphone.json"
        placeholder_headphone = root / "placeholder-headphone.json"
        short_headphone = root / "short-headphone.json"
        wide_alignment_headphone = root / "wide-alignment-headphone.json"
        guided_headphone = root / "guided-headphone.json"
        unbound_guided_headphone = root / "unbound-guided-headphone.json"
        stale_preflight_guided_headphone = root / "stale-preflight-guided-headphone.json"
        mismatched_guided_headphone = root / "mismatched-guided-headphone.json"
        hybrid_capture_headphone = root / "hybrid-capture-headphone.json"
        route_sweep_headphone = root / "route-sweep-headphone.json"
        preflight_headphone = root / "preflight-headphone.json"
        virtual_lab_headphone = root / "virtual-lab-headphone.json"
        qualification_room = root / "qualification-room.json"
        sweep_room = root / "sweep-room.json"
        route_probe_room = root / "route-probe-room.json"
        route_sweep_room = root / "route-sweep-room.json"
        playback = root / "playback.json"

        _write_json(stub, _report(True))
        _write_json(failing, _report(False))
        _write_live_capture_fixture_report(capture)
        _write_json(
            forged_capture,
            _report(
                True,
                _passed_gates(LIVE_CAPTURE_REQUIRED_GATES),
                fixture_kind="live_microphone_capture",
                capture_source_kind="microphone",
                benchmarks={
                    "capture": {
                        "adapter_id": EXPECTED_LIVE_CAPTURE_ADAPTER_ID,
                        "summary": {
                            "adapter_id": EXPECTED_LIVE_CAPTURE_ADAPTER_ID,
                            "backend": EXPECTED_LIVE_CAPTURE_BACKEND,
                            "capture_source_kind": "microphone",
                            "generator": EXPECTED_LIVE_CAPTURE_GENERATOR,
                            "release_proof": True,
                        },
                    }
                },
            ),
        )
        _write_json(
            fixture_capture,
            _report(
                True,
                _passed_gates({"capture_not_release_proof"}),
                fixture_kind="fixture_pcm_capture_replay",
                benchmarks={"capture": {"summary": {"capture_source_kind": "fixture_replay", "release_proof": False}}},
            ),
        )
        _write_json(
            diarization,
            _report(
                True,
                _passed_gates(CAUSAL_DIARIZATION_REQUIRED_GATES),
                streaming_mode="raw_pcm_rolling_stateful",
                summary={
                    "passed": True,
                    "quality_gates": _passed_gates(CAUSAL_DIARIZATION_REQUIRED_GATES),
                    "streaming_metrics": {"causality_ok": True, "max_future_samples_used": 0},
                },
            ),
        )
        _write_json(
            tse,
            _report(
                True,
                _passed_gates(
                    TSE_ORACLE_QUALITY_GATES
                    | TSE_REAL_MODEL_REQUIRED_GATES
                    | {"beats_mixture_passthrough"}
                ),
            ),
        )
        _write_json(
            translation,
            _report(
                True,
                _passed_gates(TRANSLATION_REQUIRED_GATES),
                adapter={
                    "translation": {
                        "streaming_mode": "causal_diarization_rolling_external_tse_segments",
                        "segmentation_prior": "causal_diarization",
                        "diarization_adapter_id": "sortformer_streaming_v1",
                        "uses_oracle_diarization": False,
                    }
                },
                benchmarks={"diarization": {"adapter_id": "sortformer_streaming_v1"}},
            ),
        )
        _write_voice_fixture_report(voice)
        _write_voice_fixture_report(forged_voice, forge_hash=True)
        _write_voice_candidate_fixture_report(voice_candidate)
        _write_voice_candidate_fixture_report(weak_voice_candidate, similarity_score=0.25)
        _write_voice_candidate_fixture_report(
            forged_level_voice_candidate,
            output_gain=0.25,
            reported_level_error=0.0,
        )
        _write_voice_candidate_fixture_report(clone_voice_candidate, clone_reference=True)
        _write_room_suppression_fixture_report(room)
        _write_room_suppression_fixture_report(
            forged_room,
            summary_overrides={
                "source_residual_reduction_db": 1.0,
                "translated_output_correlation": 0.01,
                "translated_output_distortion_db": 99.0,
            },
        )
        _write_room_suppression_fixture_report(mismatched_room)
        _write_headphone_isolation_fixture_report(headphone)
        _write_headphone_isolation_fixture_report(forged_headphone, forge_hash=True)
        _write_headphone_isolation_fixture_report(no_isolation_headphone, no_isolation=True)
        _write_headphone_isolation_fixture_report(clone_headphone, clone_reference=True)
        _write_headphone_isolation_fixture_report(
            surrogate_headphone,
            summary_overrides={"translated_audio_is_surrogate": True},
        )
        _write_headphone_isolation_fixture_report(placeholder_headphone, placeholder_labels=True)
        _write_headphone_isolation_fixture_report(short_headphone, short_duration=True)
        _write_headphone_isolation_fixture_report(
            wide_alignment_headphone,
            summary_overrides={"max_alignment_lag_ms": ROOM_MAX_ALIGNMENT_LAG_MS + 250.0},
        )
        _write_headphone_isolation_fixture_report(guided_headphone, guided_capture=True)
        _write_headphone_isolation_fixture_report(
            unbound_guided_headphone,
            guided_capture=True,
            summary_overrides={"capture_preflight_binding": {}},
        )
        _write_headphone_isolation_fixture_report(stale_preflight_guided_headphone, guided_capture=True)
        stale_preflight_payload = json.loads(stale_preflight_guided_headphone.read_text(encoding="utf-8"))
        stale_preflight_summary = stale_preflight_payload["benchmarks"][HEADPHONE_REQUIRED_BENCHMARK_NAME]["summary"]
        stale_preflight_summary["capture_preflight_binding"]["preflight_device_info"]["source_output_device"][
            "name"
        ] = "stale-source-speaker"
        _write_json(stale_preflight_guided_headphone, stale_preflight_payload)
        _write_headphone_isolation_fixture_report(
            mismatched_guided_headphone,
            guided_capture=True,
            mismatch_guided_fingerprint=True,
        )
        _write_headphone_isolation_fixture_report(hybrid_capture_headphone, hybrid_capture_source=True)
        _write_json(
            route_sweep_headphone,
            _report(
                True,
                [{"name": "headphone_route_probe_sweep_candidate_found", "passed": True}],
                fixture_kind="headphone_earpiece_route_probe_sweep",
                measurement_kind="headphone_earpiece_route_probe_sweep_triage",
                release_proof=False,
                benchmarks={
                    "headphone_earpiece_route_probe_sweep": {
                        "adapter_id": "unit_headphone_route_probe_sweep",
                        "candidate_attempt": {"attempt_id": "unit-pass"},
                        "summary": {
                            "measurement_kind": "headphone_earpiece_route_probe_sweep_triage",
                            "release_proof": False,
                            "triage_candidate_found": True,
                        },
                    }
                },
            ),
        )
        _write_json(
            preflight_headphone,
            _report(
                True,
                [{"name": "headphone_preflight_physical_listener_ear_input_confirmed", "passed": True}],
                fixture_kind="headphone_earpiece_preflight",
                measurement_kind="headphone_earpiece_preflight",
                release_proof=False,
                benchmarks={
                    "headphone_earpiece_preflight": {
                        "adapter_id": "unit_headphone_preflight",
                        "candidate_route_triples": [{"input_device": 0, "source_output_device": 1, "headphone_output_device": 2}],
                        "summary": {
                            "measurement_kind": "headphone_earpiece_preflight",
                            "planning_passed": True,
                            "recommended_path": "guided_capture_possible",
                            "release_proof": False,
                        },
                    }
                },
            ),
        )
        _write_headphone_isolation_fixture_report(virtual_lab_headphone)
        virtual_lab_payload = json.loads(virtual_lab_headphone.read_text(encoding="utf-8"))
        virtual_lab_benchmark = virtual_lab_payload["benchmarks"].pop(HEADPHONE_REQUIRED_BENCHMARK_NAME)
        virtual_lab_summary = virtual_lab_benchmark["summary"]
        virtual_lab_summary.update(
            {
                "capture_backend": "simulated_virtual_listener_ear",
                "capture_source_kind": "synthetic_room_headphone_model",
                "measurement_kind": "headphone_earpiece_virtual_lab",
                "release_proof": False,
                "translated_audio_is_surrogate": True,
            }
        )
        virtual_lab_payload.update(
            {
                "fixture_kind": "headphone_earpiece_virtual_lab",
                "measurement_kind": "headphone_earpiece_virtual_lab",
                "release_proof": False,
            }
        )
        virtual_lab_payload["summary"]["passed"] = True
        virtual_lab_payload["summary"]["release_proof"] = False
        virtual_lab_payload["benchmarks"]["headphone_earpiece_virtual_lab"] = virtual_lab_benchmark
        _write_json(virtual_lab_headphone, virtual_lab_payload)
        mismatched_payload = json.loads(mismatched_room.read_text(encoding="utf-8"))
        mismatched_loopback_path = Path(mismatched_payload["artifact_paths"]["room_loopback_recording"])
        _write_unit_pcm16_wav(mismatched_loopback_path, 16_000, 16_000)
        mismatched_payload["artifact_hashes"]["room_loopback_recording"] = _sha256_file(
            mismatched_loopback_path
        )
        _write_json(mismatched_room, mismatched_payload)
        _write_json(
            qualification_room,
            _report(
                True,
                _passed_gates(ROOM_SUPPRESSION_REQUIRED_GATES),
                fixture_kind="real_room_device_qualification",
                measurement_kind="real_room_device_qualification",
                release_proof=False,
                benchmarks={
                    "room_device_qualification": {
                        "summary": {
                            "measurement_kind": "real_room_device_qualification",
                            "release_proof": False,
                        }
                    }
                },
            ),
        )
        _write_json(
            sweep_room,
            _report(
                True,
                _passed_gates(ROOM_SUPPRESSION_REQUIRED_GATES),
                fixture_kind="real_room_device_sweep",
                measurement_kind="real_room_device_sweep_triage",
                release_proof=False,
                benchmarks={
                    "room_device_sweep": {
                        "candidate_attempt": None,
                        "summary": {
                            "measurement_kind": "real_room_device_sweep_triage",
                            "release_proof": False,
                        },
                    }
                },
            ),
        )
        _write_json(
            route_probe_room,
            _report(
                True,
                _passed_gates(ROOM_SUPPRESSION_REQUIRED_GATES),
                fixture_kind="real_room_route_probe",
                measurement_kind="real_room_route_probe_triage",
                release_proof=False,
                benchmarks={
                    "room_route_probe": {
                        "summary": {
                            "measurement_kind": "real_room_route_probe_triage",
                            "release_proof": False,
                        }
                    }
                },
            ),
        )
        _write_json(
            route_sweep_room,
            _report(
                True,
                _passed_gates(ROOM_SUPPRESSION_REQUIRED_GATES),
                fixture_kind="real_room_route_probe_sweep",
                measurement_kind="real_room_route_probe_sweep_triage",
                release_proof=False,
                benchmarks={
                    "room_route_probe_sweep": {
                        "candidate_attempt": None,
                        "summary": {
                            "measurement_kind": "real_room_route_probe_sweep_triage",
                            "release_proof": False,
                        },
                    }
                },
            ),
        )
        _write_json(
            playback,
            _report(
                True,
                [
                    {
                        "name": "suppression_claim_is_honest",
                        "passed": True,
                        "value": PLAYBACK_PROTOTYPE_CLAIM,
                    }
                ],
                fixture_kind="fleurs_playback_suppression",
            ),
        )

        complete_args = argparse.Namespace(
            live_capture_report=capture,
            causal_diarization_report=diarization,
            tse_report=tse,
            streaming_translation_report=translation,
            voice_report=voice,
            room_suppression_report=room,
            headphone_isolation_report=headphone,
            playback_prototype_report=playback,
            capture_prototype_report=fixture_capture,
        )
        release_results, prototype_results = evaluate(complete_args)
        report = build_report(release_results, prototype_results)
        if not report["summary"]["passed"]:
            raise AssertionError("expected complete evidence set to pass")
        complete_markdown = render_markdown_report(report)
        complete_release_section = complete_markdown.split("## Prototype Evidence", 1)[0]
        if "Next step:" in complete_release_section:
            raise AssertionError("passed release gates should not show next-step text in Markdown handoff")
        complete_handoff = complete_markdown.split("## Operator Handoff", 1)[1]
        if "current playback/source suppression blocker" in complete_handoff:
            raise AssertionError("passed Markdown handoff must not describe a current playback blocker")
        if "All release-blocking gates passed" not in complete_handoff:
            raise AssertionError("passed Markdown handoff should explain that release gates passed")
        if "Playback/Source Suppression Evidence Collection" in complete_handoff:
            raise AssertionError("passed Markdown handoff must not include blocker collection commands")

        stub_args = argparse.Namespace(
            live_capture_report=stub,
            causal_diarization_report=stub,
            tse_report=stub,
            streaming_translation_report=stub,
            voice_report=stub,
            room_suppression_report=stub,
            headphone_isolation_report=stub,
            playback_prototype_report=playback,
            capture_prototype_report=fixture_capture,
        )
        release_results, prototype_results = evaluate(stub_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected bare summary.passed stubs to fail")

        forged_voice_args = argparse.Namespace(**vars(complete_args))
        forged_voice_args.voice_report = forged_voice
        release_results, prototype_results = evaluate(forged_voice_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected forged voice/TTS artifacts to fail")

        candidate_voice_args = argparse.Namespace(**vars(complete_args))
        candidate_voice_args.voice_report = voice_candidate
        release_results, prototype_results = evaluate(candidate_voice_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected proxy-only same-voice candidate evidence to require stronger proof")

        weak_candidate_voice_args = argparse.Namespace(**vars(complete_args))
        weak_candidate_voice_args.voice_report = weak_voice_candidate
        release_results, prototype_results = evaluate(weak_candidate_voice_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected weak same-voice similarity evidence to fail")

        forged_level_voice_args = argparse.Namespace(**vars(complete_args))
        forged_level_voice_args.voice_report = forged_level_voice_candidate
        release_results, prototype_results = evaluate(forged_level_voice_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected forged same-voice level report to fail")

        clone_candidate_voice_args = argparse.Namespace(**vars(complete_args))
        clone_candidate_voice_args.voice_report = clone_voice_candidate
        release_results, prototype_results = evaluate(clone_candidate_voice_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected same-voice reference clone to fail")

        forged_room_args = argparse.Namespace(**vars(complete_args))
        forged_room_args.room_suppression_report = forged_room
        forged_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(forged_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected forged room-suppression metrics to fail")

        headphone_fallback_args = argparse.Namespace(**vars(complete_args))
        headphone_fallback_args.room_suppression_report = forged_room
        headphone_fallback_args.headphone_isolation_report = headphone
        release_results, prototype_results = evaluate(headphone_fallback_args)
        report = build_report(release_results, prototype_results)
        if not report["summary"]["passed"]:
            raise AssertionError("expected measured headphone isolation to satisfy source suppression fallback")

        guided_headphone_args = argparse.Namespace(**vars(complete_args))
        guided_headphone_args.room_suppression_report = forged_room
        guided_headphone_args.headphone_isolation_report = guided_headphone
        release_results, prototype_results = evaluate(guided_headphone_args)
        report = build_report(release_results, prototype_results)
        if not report["summary"]["passed"]:
            raise AssertionError("expected guided headphone isolation with matching device fingerprint to pass")

        unbound_guided_headphone_args = argparse.Namespace(**vars(complete_args))
        unbound_guided_headphone_args.room_suppression_report = forged_room
        unbound_guided_headphone_args.headphone_isolation_report = unbound_guided_headphone
        release_results, prototype_results = evaluate(unbound_guided_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected guided headphone isolation without preflight binding to fail")

        stale_preflight_guided_headphone_args = argparse.Namespace(**vars(complete_args))
        stale_preflight_guided_headphone_args.room_suppression_report = forged_room
        stale_preflight_guided_headphone_args.headphone_isolation_report = stale_preflight_guided_headphone
        release_results, prototype_results = evaluate(stale_preflight_guided_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected guided headphone isolation with stale preflight device info to fail")

        forged_headphone_args = argparse.Namespace(**vars(complete_args))
        forged_headphone_args.room_suppression_report = forged_room
        forged_headphone_args.headphone_isolation_report = forged_headphone
        release_results, prototype_results = evaluate(forged_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected forged headphone artifact hashes to fail")

        clone_headphone_args = argparse.Namespace(**vars(complete_args))
        clone_headphone_args.room_suppression_report = forged_room
        clone_headphone_args.headphone_isolation_report = clone_headphone
        release_results, prototype_results = evaluate(clone_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected byte-identical headphone recordings to fail")

        surrogate_headphone_args = argparse.Namespace(**vars(complete_args))
        surrogate_headphone_args.room_suppression_report = forged_room
        surrogate_headphone_args.headphone_isolation_report = surrogate_headphone
        release_results, prototype_results = evaluate(surrogate_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected surrogate headphone translated audio to fail")

        placeholder_headphone_args = argparse.Namespace(**vars(complete_args))
        placeholder_headphone_args.room_suppression_report = forged_room
        placeholder_headphone_args.headphone_isolation_report = placeholder_headphone
        release_results, prototype_results = evaluate(placeholder_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected placeholder headphone measurement identity to fail")

        short_headphone_args = argparse.Namespace(**vars(complete_args))
        short_headphone_args.room_suppression_report = forged_room
        short_headphone_args.headphone_isolation_report = short_headphone
        release_results, prototype_results = evaluate(short_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected too-short headphone measurement artifacts to fail")

        wide_alignment_headphone_args = argparse.Namespace(**vars(complete_args))
        wide_alignment_headphone_args.room_suppression_report = forged_room
        wide_alignment_headphone_args.headphone_isolation_report = wide_alignment_headphone
        release_results, prototype_results = evaluate(wide_alignment_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected wide headphone alignment window to fail release gate")

        mismatched_guided_headphone_args = argparse.Namespace(**vars(complete_args))
        mismatched_guided_headphone_args.room_suppression_report = forged_room
        mismatched_guided_headphone_args.headphone_isolation_report = mismatched_guided_headphone
        release_results, prototype_results = evaluate(mismatched_guided_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected mismatched guided headphone device fingerprint to fail")

        hybrid_capture_headphone_args = argparse.Namespace(**vars(complete_args))
        hybrid_capture_headphone_args.room_suppression_report = forged_room
        hybrid_capture_headphone_args.headphone_isolation_report = hybrid_capture_headphone
        release_results, prototype_results = evaluate(hybrid_capture_headphone_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected hybrid headphone capture backend/source metadata to fail")

        route_sweep_headphone_args = argparse.Namespace(**vars(complete_args))
        route_sweep_headphone_args.room_suppression_report = forged_room
        route_sweep_headphone_args.headphone_isolation_report = route_sweep_headphone
        release_results, prototype_results = evaluate(route_sweep_headphone_args)
        report = build_report(release_results, prototype_results)
        failed = {gate.name: gate.message for gate in release_results if not gate.passed}
        route_sweep_message = failed.get("playback_source_suppression_evidence", "")
        if report["summary"]["passed"] or not route_sweep_message:
            raise AssertionError("expected headphone route sweep report to fail release gate")
        if "fixture_kind" not in route_sweep_message or "release_proof" not in route_sweep_message:
            raise AssertionError("expected headphone route sweep rejection to cite release metadata")

        preflight_headphone_args = argparse.Namespace(**vars(complete_args))
        preflight_headphone_args.room_suppression_report = forged_room
        preflight_headphone_args.headphone_isolation_report = preflight_headphone
        release_results, prototype_results = evaluate(preflight_headphone_args)
        report = build_report(release_results, prototype_results)
        failed = {gate.name: gate.message for gate in release_results if not gate.passed}
        preflight_message = failed.get("playback_source_suppression_evidence", "")
        if report["summary"]["passed"] or not preflight_message:
            raise AssertionError("expected headphone preflight report to fail release gate")
        if "fixture_kind" not in preflight_message or "release_proof" not in preflight_message:
            raise AssertionError("expected headphone preflight rejection to cite release metadata")

        virtual_lab_headphone_args = argparse.Namespace(**vars(complete_args))
        virtual_lab_headphone_args.room_suppression_report = forged_room
        virtual_lab_headphone_args.headphone_isolation_report = virtual_lab_headphone
        release_results, prototype_results = evaluate(virtual_lab_headphone_args)
        report = build_report(release_results, prototype_results)
        failed = {gate.name: gate.message for gate in release_results if not gate.passed}
        virtual_lab_message = failed.get("playback_source_suppression_evidence", "")
        if report["summary"]["passed"] or not virtual_lab_message:
            raise AssertionError("expected virtual headphone listener-ear lab report to fail release gate")
        if "fixture_kind" not in virtual_lab_message or "release_proof" not in virtual_lab_message:
            raise AssertionError("expected virtual headphone listener-ear lab rejection to cite release metadata")

        mismatched_room_args = argparse.Namespace(**vars(complete_args))
        mismatched_room_args.room_suppression_report = mismatched_room
        mismatched_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(mismatched_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected WAV-mismatched room-suppression report to fail")

        qualification_room_args = argparse.Namespace(**vars(complete_args))
        qualification_room_args.room_suppression_report = qualification_room
        qualification_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(qualification_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected qualification report to fail room suppression gate")

        sweep_room_args = argparse.Namespace(**vars(complete_args))
        sweep_room_args.room_suppression_report = sweep_room
        sweep_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(sweep_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected device sweep report to fail room suppression gate")

        route_probe_room_args = argparse.Namespace(**vars(complete_args))
        route_probe_room_args.room_suppression_report = route_probe_room
        route_probe_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(route_probe_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected route probe report to fail room suppression gate")

        route_sweep_room_args = argparse.Namespace(**vars(complete_args))
        route_sweep_room_args.room_suppression_report = route_sweep_room
        route_sweep_room_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(route_sweep_room_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected route probe sweep report to fail room suppression gate")

        oracle_translation = root / "oracle-translation.json"
        _write_json(
            oracle_translation,
            _report(
                True,
                _passed_gates(TRANSLATION_REQUIRED_GATES),
                adapter={
                    "translation": {
                        "streaming_mode": "oracle_diarization_rolling_external_tse_segments",
                        "segmentation_prior": "oracle_diarization",
                    }
                },
                benchmarks={"diarization": {"adapter_id": "oracle_diarization_v1"}},
            ),
        )
        oracle_translation_args = argparse.Namespace(**vars(complete_args))
        oracle_translation_args.streaming_translation_report = oracle_translation
        release_results, prototype_results = evaluate(oracle_translation_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected oracle-windowed translation report to fail")

        forged_args = argparse.Namespace(**vars(complete_args))
        forged_args.live_capture_report = forged_capture
        release_results, prototype_results = evaluate(forged_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected self-attested live capture report to fail")

        prototype_args = argparse.Namespace(**vars(complete_args))
        prototype_args.live_capture_report = fixture_capture
        prototype_args.room_suppression_report = playback
        prototype_args.headphone_isolation_report = no_isolation_headphone
        release_results, prototype_results = evaluate(prototype_args)
        report = build_report(release_results, prototype_results)
        failed = {gate.name for gate in release_results if not gate.passed}
        if "live_microphone_capture_runtime" not in failed:
            raise AssertionError("expected fixture capture to fail product capture gate")
        if "playback_source_suppression_evidence" not in failed:
            raise AssertionError("expected playback prototype to fail source suppression evidence gate")
        markdown = render_markdown_report(report)
        if "## Operator Handoff" not in markdown:
            raise AssertionError("expected Markdown report to include operator handoff")
        if "playback_source_suppression_evidence" not in markdown:
            raise AssertionError("expected Markdown report to include playback/source suppression blocker")
        if "laptop built-in microphone" not in markdown.lower() or "route_probe_triage_only" not in markdown:
            raise AssertionError("expected Markdown handoff to preserve laptop mic triage warning")
        if "Playback/Source Suppression Evidence Collection" not in markdown:
            raise AssertionError("expected Markdown handoff to include physical evidence collection section")
        if "headphone_isolation_local.ps1 -Action prepare-manual" not in markdown:
            raise AssertionError("expected Markdown handoff to include manual recorder command path")
        if "headphone_isolation_local.ps1 -Action import-manual" not in markdown:
            raise AssertionError("expected Markdown handoff to include manual recording import command")
        if "confirm_physical_input_preflight" not in markdown:
            raise AssertionError("expected Markdown handoff to point at generated guided capture confirmation")
        if "$headphoneLabel" not in markdown or "$fixtureLabel" not in markdown or "$microphoneLabel" not in markdown:
            raise AssertionError("expected Markdown handoff to define generated guided capture label variables")
        markdown_report = root / "audio-gate-report.md"
        write_markdown_report(report, markdown_report)
        if "Release-Blocking Gates" not in markdown_report.read_text(encoding="utf-8"):
            raise AssertionError("expected Markdown report file to be written")

        failing_args = argparse.Namespace(**vars(complete_args))
        failing_args.voice_report = failing
        release_results, prototype_results = evaluate(failing_args)
        report = build_report(release_results, prototype_results)
        if report["summary"]["passed"]:
            raise AssertionError("expected failed release-blocking report to fail")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Gate product audio-loop release evidence")
    parser.add_argument("--self-test", action="store_true", help="validate gate helper behavior")
    parser.add_argument("--json", action="store_true", help="print the full JSON report")
    parser.add_argument("--report", type=Path, default=DEFAULT_RELEASE_REPORT)
    parser.add_argument("--markdown-report", type=Path, default=DEFAULT_RELEASE_MARKDOWN_REPORT)
    parser.add_argument("--live-capture-report", type=Path, default=DEFAULT_LIVE_CAPTURE_REPORT)
    parser.add_argument("--causal-diarization-report", type=Path, default=DEFAULT_CAUSAL_DIARIZATION_REPORT)
    parser.add_argument("--tse-report", type=Path, default=DEFAULT_TSE_REPORT)
    parser.add_argument("--streaming-translation-report", type=Path, default=DEFAULT_STREAMING_TRANSLATION_REPORT)
    parser.add_argument("--voice-report", type=Path, default=DEFAULT_VOICE_REPORT)
    parser.add_argument("--room-suppression-report", type=Path, default=DEFAULT_ROOM_SUPPRESSION_REPORT)
    parser.add_argument("--headphone-isolation-report", type=Path, default=DEFAULT_HEADPHONE_ISOLATION_REPORT)
    parser.add_argument("--playback-prototype-report", type=Path, default=DEFAULT_PLAYBACK_PROTOTYPE_REPORT)
    parser.add_argument("--capture-prototype-report", type=Path, default=DEFAULT_CAPTURE_PROTOTYPE_REPORT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.self_test:
        self_test()
        print("release audio gate self-test PASS")
        return 0

    release_results, prototype_results = evaluate(args)
    report = build_report(release_results, prototype_results)
    write_report(report, args.report)
    write_markdown_report(report, args.markdown_report)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_summary(report, args.report, args.markdown_report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
