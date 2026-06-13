#!/usr/bin/env python3
"""Validate externally generated same-voice English TTS candidate audio.

This benchmark intentionally does not synthesize audio. It scores the artifact
contract that a local model or provider must satisfy before the app treats
same-voice playback as more than a fallback: consent metadata, hashed output
WAVs, level matching, non-clone output, and a hashed speaker-similarity evidence
artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "same-voice-candidate"
DEFAULT_ADAPTER_ID = "manual_same_voice_candidate_v1"
DEFAULT_MANIFEST = (
    DEFAULT_OUTPUT_DIR
    / "runs"
    / DEFAULT_RUN_ID
    / "same-voice-candidate-manifest.json"
)
DEFAULT_MAX_LEVEL_ERROR_DB = 0.75
DEFAULT_MAX_PEAK_DBFS = -0.1
DEFAULT_MIN_VOICE_SIMILARITY_SCORE = 0.65
SAME_VOICE_STATUS = "same_voice_candidate"
VOICE_SIMILARITY_CLAIM = "measured_proxy"
VOICE_SIMILARITY_METRIC = "release_gate_acoustic_proxy_v1"
VOICE_SIMILARITY_EVALUATOR_ID = "language_release_gate_builtin_v1"
VOICE_SIMILARITY_SCORE_TOLERANCE = 0.01
ALLOWED_RETENTION_POLICIES = {
    "ephemeral_reference_deleted",
    "ephemeral_reference_not_persisted",
    "consented_retention_with_expiry",
}


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


def acoustic_feature_vector(samples: np.ndarray, sample_rate_hz: int) -> np.ndarray:
    frame_len = max(1, int(round(sample_rate_hz * 0.04)))
    hop = max(1, int(round(sample_rate_hz * 0.02)))
    if samples.size < frame_len:
        frame_starts = [0]
    else:
        frame_starts = list(range(0, samples.size - frame_len + 1, hop))
    frame_features: list[list[float]] = []
    lag = max(1, int(round(sample_rate_hz * 0.005)))
    for start in frame_starts:
        frame = samples[start : start + frame_len]
        if frame.size == 0:
            continue
        if frame.size < frame_len:
            frame = np.pad(frame, (0, frame_len - frame.size))
        frame_rms = rms(frame)
        signs = np.signbit(frame)
        zcr = float(np.mean(signs[1:] != signs[:-1])) if frame.size > 1 else 0.0
        deltas = np.diff(frame)
        mean_abs_delta = float(np.mean(np.abs(deltas))) if deltas.size else 0.0
        if frame.size > lag and frame_rms > 0.0:
            lhs = frame[:-lag]
            rhs = frame[lag:]
            denom = math.sqrt(float(np.dot(lhs, lhs)) * float(np.dot(rhs, rhs)))
            autocorr = float(np.dot(lhs, rhs) / denom) if denom > 0.0 else 0.0
        else:
            autocorr = 0.0
        frame_features.append([frame_rms, zcr, mean_abs_delta, autocorr])
    if not frame_features:
        return np.zeros(8, dtype=np.float64)
    matrix = np.asarray(frame_features, dtype=np.float64)
    return np.concatenate([np.mean(matrix, axis=0), np.std(matrix, axis=0)])


def acoustic_similarity_proxy(
    reference_audio: np.ndarray,
    output_audio: np.ndarray,
    sample_rate_hz: int,
) -> float:
    reference_vector = acoustic_feature_vector(reference_audio, sample_rate_hz)
    output_vector = acoustic_feature_vector(output_audio, sample_rate_hz)
    scale = np.asarray([0.2, 0.2, 0.05, 1.0, 0.1, 0.1, 0.03, 0.5], dtype=np.float64)
    distance = float(
        np.linalg.norm((reference_vector - output_vector) / scale) / math.sqrt(scale.size)
    )
    return float(1.0 / (1.0 + distance))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_report(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate_hz))
        wav.writeframes(pcm.tobytes())


def safe_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return "".join(char if char in allowed else "_" for char in value).strip("_") or "artifact"


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def resolve_path(anchor: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected non-empty path")
    path = Path(value)
    if path.is_absolute():
        return path
    return anchor.parent / path


def bundled_path(run_dir: Path, source: Path, *, kind: str, segment_index: int | None = None) -> Path:
    suffix = source.suffix or ".bin"
    prefix = f"{segment_index:03d}_" if segment_index is not None else ""
    target = run_dir / "candidate_artifacts" / kind / f"{prefix}{safe_id(source.stem)}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        same_file = source.resolve() == target.resolve()
    except OSError:
        same_file = False
    if not same_file:
        shutil.copy2(source, target)
    return target


def report_path(run_dir: Path, path: Path) -> str:
    try:
        return str(path.relative_to(run_dir))
    except ValueError:
        return str(path)


def pcm16_sha256(path: Path) -> str:
    with wave.open(str(path), "rb") as wav:
        channels = int(wav.getnchannels())
        sample_width = int(wav.getsampwidth())
        frame_count = int(wav.getnframes())
        frames = wav.readframes(frame_count)
    if channels != 1 or sample_width != 2:
        raise ValueError(f"{path} must be mono PCM_16 WAV")
    return hashlib.sha256(frames).hexdigest()


def read_mono_pcm16(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    if not path.exists():
        raise ValueError(f"missing WAV: {path}")
    try:
        with wave.open(str(path), "rb") as wav:
            channels = int(wav.getnchannels())
            sample_width = int(wav.getsampwidth())
            sample_rate_hz = int(wav.getframerate())
            frame_count = int(wav.getnframes())
            frames = wav.readframes(frame_count)
    except (OSError, wave.Error) as exc:
        raise ValueError(f"{path} is not a readable WAV: {exc}") from exc
    if channels != 1:
        raise ValueError(f"{path} must be mono")
    if sample_width != 2:
        raise ValueError(f"{path} must be 16-bit PCM")
    if sample_rate_hz <= 0 or frame_count <= 0:
        raise ValueError(f"{path} must contain audio frames")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    info = {
        "duration_s": round(frame_count / float(sample_rate_hz), 6),
        "frame_count": frame_count,
        "path": str(path),
        "pcm_sha256": hashlib.sha256(frames).hexdigest(),
        "sample_rate_hz": sample_rate_hz,
        "sha256": sha256_file(path),
    }
    return samples, info


def load_manifest(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("same-voice candidate manifest must be a JSON object")
    if loaded.get("schema_version") != 1:
        raise ValueError("same-voice candidate manifest schema_version must be 1")
    return loaded


def load_similarity_evidence(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def boolish_true(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "yes", "1"}


def validate_consent(manifest: dict[str, Any], *, run_dir: Path) -> tuple[bool, dict[str, Any], list[str]]:
    consent = manifest.get("consent")
    consent = consent if isinstance(consent, dict) else {}
    issues: list[str] = []
    if not boolish_true(consent.get("speaker_consent")):
        issues.append("consent.speaker_consent must be true")
    if not boolish_true(consent.get("voice_clone_reference_used")):
        issues.append("consent.voice_clone_reference_used must be true")
    retention = str(consent.get("reference_retention_policy") or "").strip()
    if retention not in ALLOWED_RETENTION_POLICIES:
        issues.append(
            "consent.reference_retention_policy must be ephemeral or consented retention with expiry"
        )
    if not str(consent.get("consent_basis") or "").strip():
        issues.append("consent.consent_basis must be provided")
    consent_path_value = consent.get("consent_evidence_path")
    if consent_path_value:
        try:
            manifest_path = Path(str(manifest.get("_manifest_path")))
            consent_path = resolve_path(manifest_path, consent_path_value)
            if not consent_path.exists():
                issues.append(f"consent evidence is missing: {consent_path}")
            else:
                bundled = bundled_path(run_dir, consent_path, kind="consent")
                consent["consent_evidence_path"] = report_path(run_dir, bundled)
                consent["consent_evidence_sha256"] = sha256_file(bundled)
        except ValueError as exc:
            issues.append(str(exc))
    else:
        issues.append("consent.consent_evidence_path must be provided")
    return not issues, consent, issues


def build_segment_record(
    *,
    args: argparse.Namespace,
    manifest_path: Path,
    run_dir: Path,
    segment: dict[str, Any],
    segment_index: int,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    reference_path = resolve_path(manifest_path, segment.get("reference_audio_path"))
    if not segment.get("source_audio_path"):
        raise ValueError(f"manifest segment {segment_index} must provide source_audio_path")
    source_path = resolve_path(manifest_path, segment.get("source_audio_path"))
    output_path = resolve_path(manifest_path, segment.get("tts_output_path"))
    evidence_path = resolve_path(manifest_path, segment.get("voice_similarity_evidence_path"))
    reference_path = bundled_path(run_dir, reference_path, kind="reference_audio", segment_index=segment_index)
    source_path = bundled_path(run_dir, source_path, kind="source_audio", segment_index=segment_index)
    output_path = bundled_path(run_dir, output_path, kind="tts_output", segment_index=segment_index)
    evidence_path = bundled_path(run_dir, evidence_path, kind="similarity_evidence", segment_index=segment_index)
    reference_audio, reference_info = read_mono_pcm16(reference_path)
    source_audio, source_info = read_mono_pcm16(source_path)
    output_audio, output_info = read_mono_pcm16(output_path)
    if reference_info["sha256"] == output_info["sha256"] or reference_info["pcm_sha256"] == output_info["pcm_sha256"]:
        issues.append("candidate output must not be an exact reference clone")
    if reference_info["sample_rate_hz"] != output_info["sample_rate_hz"]:
        issues.append("reference and candidate output sample rates must match")
    if source_info["sample_rate_hz"] != output_info["sample_rate_hz"]:
        issues.append("source and candidate output sample rates must match")

    evidence = load_similarity_evidence(evidence_path)
    evidence_sha256 = sha256_file(evidence_path)
    speaker_id = str(segment.get("speaker_id") or "").strip()
    if not speaker_id:
        issues.append("segment speaker_id must be provided")
    if str(evidence.get("speaker_id") or "") != speaker_id:
        issues.append("similarity evidence speaker_id must match segment")
    if evidence.get("reference_audio_sha256") != reference_info["sha256"]:
        issues.append("similarity evidence reference_audio_sha256 does not match reference WAV")
    if evidence.get("reference_audio_pcm_sha256") != reference_info["pcm_sha256"]:
        issues.append("similarity evidence reference_audio_pcm_sha256 does not match reference WAV")
    if evidence.get("tts_output_sha256") != output_info["sha256"]:
        issues.append("similarity evidence tts_output_sha256 does not match output WAV")
    if evidence.get("tts_output_pcm_sha256") != output_info["pcm_sha256"]:
        issues.append("similarity evidence tts_output_pcm_sha256 does not match output WAV")
    metric = str(segment.get("voice_similarity_metric") or evidence.get("metric_name") or "").strip()
    if metric != VOICE_SIMILARITY_METRIC:
        issues.append(f"voice similarity metric must be {VOICE_SIMILARITY_METRIC}")
    if evidence.get("metric_name") != VOICE_SIMILARITY_METRIC:
        issues.append("similarity evidence metric_name must match built-in proxy")
    evaluator_id = str(segment.get("voice_similarity_evaluator_id") or evidence.get("evaluator_id") or "").strip()
    if evaluator_id != VOICE_SIMILARITY_EVALUATOR_ID:
        issues.append(f"voice similarity evaluator_id must be {VOICE_SIMILARITY_EVALUATOR_ID}")
    if evidence.get("evaluator_id") != VOICE_SIMILARITY_EVALUATOR_ID:
        issues.append("similarity evidence evaluator_id must match built-in proxy")
    proxy_score = acoustic_similarity_proxy(
        reference_audio,
        output_audio,
        reference_info["sample_rate_hz"],
    )
    try:
        score = float(segment.get("voice_similarity_score", evidence.get("score")))
    except (TypeError, ValueError):
        score = float("nan")
        issues.append("voice similarity score must be numeric")
    try:
        threshold = float(
            segment.get(
                "voice_similarity_threshold",
                evidence.get("threshold", args.min_voice_similarity_score),
            )
        )
    except (TypeError, ValueError):
        threshold = float("nan")
        issues.append("voice similarity threshold must be numeric")
    if math.isfinite(threshold) and threshold < float(args.min_voice_similarity_score):
        issues.append(
            f"voice similarity threshold must be >= {float(args.min_voice_similarity_score):.3f}"
        )
    if math.isfinite(score) and math.isfinite(threshold) and score < threshold:
        issues.append("voice similarity score is below threshold")
    if math.isfinite(score) and abs(score - proxy_score) > VOICE_SIMILARITY_SCORE_TOLERANCE:
        issues.append("voice similarity score must match recomputed acoustic proxy")
    evidence_score = evidence.get("score")
    if evidence_score is not None:
        try:
            evidence_score_value = float(evidence_score)
        except (TypeError, ValueError):
            issues.append("similarity evidence score must be numeric")
        else:
            if math.isfinite(score) and abs(evidence_score_value - score) > 1e-6:
                issues.append("similarity evidence score must match segment")
            if abs(evidence_score_value - proxy_score) > VOICE_SIMILARITY_SCORE_TOLERANCE:
                issues.append("similarity evidence score must match recomputed acoustic proxy")
    else:
        issues.append("similarity evidence score is required")
    evidence_threshold = evidence.get("threshold")
    if evidence_threshold is not None:
        try:
            evidence_threshold_value = float(evidence_threshold)
        except (TypeError, ValueError):
            issues.append("similarity evidence threshold must be numeric")
        else:
            if math.isfinite(threshold) and abs(evidence_threshold_value - threshold) > 1e-6:
                issues.append("similarity evidence threshold must match segment")
    else:
        issues.append("similarity evidence threshold is required")

    input_level = dbfs(source_audio)
    reference_level = dbfs(reference_audio)
    output_level = dbfs(output_audio)
    if not math.isfinite(input_level) or not math.isfinite(reference_level) or not math.isfinite(output_level):
        issues.append("source, reference, and output audio must be non-silent")
    level_error = abs(output_level - input_level) if math.isfinite(input_level) and math.isfinite(output_level) else None
    output_peak = peak_dbfs(output_audio)
    if level_error is None or level_error > float(args.max_level_error_db):
        issues.append(f"output level error must be <= {float(args.max_level_error_db):.3f} dB")
    if not math.isfinite(output_peak) or output_peak > float(args.max_peak_dbfs):
        issues.append(f"output peak must be <= {float(args.max_peak_dbfs):.3f} dBFS")
    if str(segment.get("target_language_code") or "en") != "en":
        issues.append("same-voice candidate output must target English")

    record = {
        "segment_index": segment_index,
        "speaker_id": speaker_id,
        "fixture_id": segment.get("fixture_id") or manifest_path.stem,
        "source_language_code": segment.get("source_language_code"),
        "target_language_code": segment.get("target_language_code", "en"),
        "translated_text": str(segment.get("translated_text") or ""),
        "voice_clone_status": SAME_VOICE_STATUS,
        "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
        "voice_clone_reference_used": True,
        "reference_audio_usage": "voice_clone_reference_and_similarity_measurement",
        "reference_audio_path": report_path(run_dir, reference_path),
        "reference_audio_sha256": reference_info["sha256"],
        "reference_audio_pcm_sha256": reference_info["pcm_sha256"],
        "source_audio_path": report_path(run_dir, source_path),
        "source_audio_sha256": source_info["sha256"],
        "source_audio_pcm_sha256": source_info["pcm_sha256"],
        "input_level_dbfs": round(input_level, 3) if math.isfinite(input_level) else None,
        "reference_level_dbfs": round(reference_level, 3) if math.isfinite(reference_level) else None,
        "tts_output_path": report_path(run_dir, output_path),
        "tts_output_sha256": output_info["sha256"],
        "tts_output_pcm_sha256": output_info["pcm_sha256"],
        "tts_output_level_dbfs": round(output_level, 3) if math.isfinite(output_level) else None,
        "tts_output_peak_dbfs": round(output_peak, 3) if math.isfinite(output_peak) else None,
        "tts_output_duration_s": output_info["duration_s"],
        "tts_output_frame_count": output_info["frame_count"],
        "output_level_error_db": round(level_error, 3) if level_error is not None else None,
        "synthesis_wall_ms": segment.get("synthesis_wall_ms"),
        "voice_similarity_metric": VOICE_SIMILARITY_METRIC,
        "voice_similarity_evaluator_id": VOICE_SIMILARITY_EVALUATOR_ID,
        "voice_similarity_score": round(proxy_score, 6),
        "reported_voice_similarity_score": round(score, 6) if math.isfinite(score) else None,
        "voice_similarity_threshold": round(threshold, 6) if math.isfinite(threshold) else None,
        "voice_similarity_evidence_path": report_path(run_dir, evidence_path),
        "voice_similarity_evidence_sha256": evidence_sha256,
        "validation_issues": issues,
    }
    return record, issues


def summarize(segment_records: list[dict[str, Any]]) -> dict[str, Any]:
    level_errors = [
        float(item["output_level_error_db"])
        for item in segment_records
        if isinstance(item.get("output_level_error_db"), (int, float))
    ]
    peaks = [
        float(item["tts_output_peak_dbfs"])
        for item in segment_records
        if isinstance(item.get("tts_output_peak_dbfs"), (int, float))
    ]
    similarities = [
        float(item["voice_similarity_score"])
        for item in segment_records
        if isinstance(item.get("voice_similarity_score"), (int, float))
    ]
    issues = [
        issue
        for item in segment_records
        for issue in item.get("validation_issues", [])
    ]
    return {
        "segment_count": len(segment_records),
        "voice_clone_status": SAME_VOICE_STATUS,
        "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
        "max_output_level_error_db": round(max(level_errors), 3) if level_errors else None,
        "max_output_peak_dbfs": round(max(peaks), 3) if peaks else None,
        "min_voice_similarity_score": round(min(similarities), 6) if similarities else None,
        "validation_issue_count": len(issues),
    }


def apply_cross_segment_clone_checks(segment_records: list[dict[str, Any]]) -> None:
    references = [
        (
            int(item["segment_index"]),
            str(item.get("reference_audio_sha256") or ""),
            str(item.get("reference_audio_pcm_sha256") or ""),
        )
        for item in segment_records
    ]
    for item in segment_records:
        output_sha = str(item.get("tts_output_sha256") or "")
        output_pcm = str(item.get("tts_output_pcm_sha256") or "")
        issues = item.setdefault("validation_issues", [])
        for reference_index, reference_sha, reference_pcm in references:
            if reference_index == int(item["segment_index"]):
                continue
            if output_sha and output_sha == reference_sha:
                issues.append(
                    f"candidate output must not clone segment {reference_index} reference WAV bytes"
                )
            if output_pcm and output_pcm == reference_pcm:
                issues.append(
                    f"candidate output must not clone segment {reference_index} reference PCM"
                )


def apply_consent_binding_checks(
    *,
    consent: dict[str, Any],
    consent_issues: list[str],
    segment_records: list[dict[str, Any]],
) -> None:
    segment_speakers = sorted({str(item.get("speaker_id") or "") for item in segment_records})
    consent_speakers = consent.get("speaker_ids")
    if not isinstance(consent_speakers, list) or sorted(str(item) for item in consent_speakers) != segment_speakers:
        consent_issues.append("consent.speaker_ids must exactly match manifest segment speakers")
    reference_hashes = sorted({str(item.get("reference_audio_sha256") or "") for item in segment_records})
    consent_reference_hashes = consent.get("reference_audio_sha256s")
    if (
        not isinstance(consent_reference_hashes, list)
        or sorted(str(item) for item in consent_reference_hashes) != reference_hashes
    ):
        consent_issues.append(
            "consent.reference_audio_sha256s must exactly match manifest reference WAV hashes"
        )
    if consent.get("reference_retention_policy") == "consented_retention_with_expiry":
        try:
            expiry = float(consent.get("reference_retention_expires_unix"))
        except (TypeError, ValueError):
            expiry = 0.0
        if expiry <= time.time():
            consent_issues.append(
                "consent.reference_retention_expires_unix must be a future Unix timestamp"
            )


def quality_gates(
    *,
    consent_ok: bool,
    consent_issues: list[str],
    segment_records: list[dict[str, Any]],
    summary: dict[str, Any],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    all_segment_clean = all(not item.get("validation_issues") for item in segment_records)
    all_hashes = all(
        is_sha256(item.get("tts_output_sha256"))
        and is_sha256(item.get("reference_audio_sha256"))
        and is_sha256(item.get("source_audio_sha256"))
        and is_sha256(item.get("voice_similarity_evidence_sha256"))
        for item in segment_records
    )
    max_level_error = summary.get("max_output_level_error_db")
    max_peak = summary.get("max_output_peak_dbfs")
    min_similarity = summary.get("min_voice_similarity_score")
    return [
        {
            "name": "voice_reference_consent_present",
            "passed": consent_ok,
            "threshold": "explicit speaker consent and safe reference retention policy",
            "value": consent_issues or "consent_ok",
        },
        {
            "name": "tts_audio_hashed",
            "passed": all_hashes and all_segment_clean and bool(segment_records),
            "threshold": "output, reference, and similarity evidence artifacts are hashed and validation-clean",
            "value": {
                "all_hashes_present": all_hashes,
                "segment_validation_issue_count": summary.get("validation_issue_count"),
            },
        },
        {
            "name": "tts_output_level_matched",
            "passed": isinstance(max_level_error, (float, int))
            and float(max_level_error) <= float(args.max_level_error_db),
            "threshold": f"max output level error <= {float(args.max_level_error_db):.3f} dB",
            "value": max_level_error,
        },
        {
            "name": "voice_similarity_or_fallback_declared",
            "passed": isinstance(min_similarity, (float, int))
            and float(min_similarity) >= float(args.min_voice_similarity_score)
            and all_segment_clean,
            "threshold": f"same-voice similarity evidence score >= {float(args.min_voice_similarity_score):.3f}",
            "value": {
                "voice_clone_status": SAME_VOICE_STATUS,
                "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
                "min_voice_similarity_score": min_similarity,
            },
        },
        {
            "name": "tts_output_not_clipped",
            "passed": isinstance(max_peak, (float, int)) and float(max_peak) <= float(args.max_peak_dbfs),
            "threshold": f"max peak <= {float(args.max_peak_dbfs):.3f} dBFS",
            "value": max_peak,
        },
    ]


def build_report(manifest_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    run_dir = Path(getattr(args, "run_dir", Path(args.output_dir) / "runs" / args.run_id))
    run_dir.mkdir(parents=True, exist_ok=True)
    bundled_manifest = bundled_path(run_dir, manifest_path, kind="manifest")
    manifest["_manifest_path"] = str(manifest_path)
    consent_ok, consent, consent_issues = validate_consent(manifest, run_dir=run_dir)
    raw_segments = manifest.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise ValueError("same-voice candidate manifest must contain non-empty segments")
    segment_records: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise ValueError(f"manifest segment {index} must be an object")
        record, _issues = build_segment_record(
            args=args,
            manifest_path=manifest_path,
            run_dir=run_dir,
            segment=segment,
            segment_index=index,
        )
        segment_records.append(record)
    apply_cross_segment_clone_checks(segment_records)
    apply_consent_binding_checks(
        consent=consent,
        consent_issues=consent_issues,
        segment_records=segment_records,
    )
    consent_ok = consent_ok and not consent_issues
    summary = summarize(segment_records)
    gates = quality_gates(
        consent_ok=consent_ok,
        consent_issues=consent_issues,
        segment_records=segment_records,
        summary=summary,
        args=args,
    )
    passed = all(bool(gate["passed"]) for gate in gates)
    adapter_id = str(manifest.get("adapter_id") or args.adapter_id)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "same_voice_candidate_tts_audio_stream",
        "output_dir": str(args.output_dir),
        "summary": {
            "passed": passed,
            "fixture_count": 1,
            "quality_gates": gates,
            **summary,
        },
        "benchmarks": {
            "same_voice_or_fallback_tts": {
                "adapter_id": adapter_id,
                "summary": summary,
                "segments": segment_records,
            }
        },
        "adapter": {
            "voice": {
                "adapter_id": adapter_id,
                "mode": SAME_VOICE_STATUS,
                "provider_or_model": manifest.get("provider_or_model"),
                "voice_clone_reference_used": True,
                "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
                "reference_retention_policy": consent.get("reference_retention_policy"),
            }
        },
        "manifest": {
            "path": report_path(run_dir, bundled_manifest),
            "sha256": sha256_file(bundled_manifest),
        },
        "consent": consent,
        "detractor_loop": {
            "strongest_objection": (
                "This validates externally generated same-voice candidate artifacts and a hashed "
                "similarity-evidence file, but it does not independently prove the provider/model "
                "did not retain references or that human listeners would accept the voice match."
            ),
            "next_falsifying_benchmark": (
                "Run the same manifest with a stronger ASV model plus blinded human similarity ratings "
                "on consented local speakers and cross-language prompts."
            ),
            "verdict": (
                "Treat as same-voice candidate evidence only when gates pass; keep fallback available."
            ),
        },
    }


def write_self_test_manifest(root: Path) -> Path:
    sample_rate_hz = 16_000
    frame_count = sample_rate_hz
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    reference = (0.05 * np.sin(2.0 * math.pi * 180.0 * t)).astype(np.float32)
    candidate = (0.05 * np.sin(2.0 * math.pi * 185.0 * t)).astype(np.float32)
    reference_path = root / "self-test-reference.wav"
    output_path = root / "self-test-same-voice-output.wav"
    write_mono_wav(reference_path, reference, sample_rate_hz)
    write_mono_wav(output_path, candidate, sample_rate_hz)
    reference_audio, reference_info = read_mono_pcm16(reference_path)
    output_audio, output_info = read_mono_pcm16(output_path)
    proxy_score = acoustic_similarity_proxy(reference_audio, output_audio, sample_rate_hz)
    evidence = {
        "schema_version": 1,
        "speaker_id": "self_test_speaker",
        "metric_name": VOICE_SIMILARITY_METRIC,
        "evaluator_id": VOICE_SIMILARITY_EVALUATOR_ID,
        "score": round(proxy_score, 6),
        "threshold": 0.65,
        "reference_audio_sha256": reference_info["sha256"],
        "reference_audio_pcm_sha256": reference_info["pcm_sha256"],
        "tts_output_sha256": output_info["sha256"],
        "tts_output_pcm_sha256": output_info["pcm_sha256"],
    }
    evidence_path = root / "self-test-similarity-evidence.json"
    evidence_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    consent_path = root / "self-test-consent.txt"
    consent_path.write_text("self test speaker consent placeholder\n", encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "adapter_id": "unit_same_voice_candidate",
        "provider_or_model": "unit-test-external-generator",
        "consent": {
            "speaker_consent": True,
            "voice_clone_reference_used": True,
            "reference_retention_policy": "ephemeral_reference_deleted",
            "consent_basis": "unit test speaker consent",
            "consent_evidence_path": str(consent_path),
            "reference_audio_sha256s": [reference_info["sha256"]],
            "speaker_ids": ["self_test_speaker"],
        },
        "segments": [
            {
                "speaker_id": "self_test_speaker",
                "fixture_id": "self_test_same_voice_candidate",
                "source_language_code": "es",
                "target_language_code": "en",
                "translated_text": "Self test same voice candidate.",
                "reference_audio_path": str(reference_path),
                "source_audio_path": str(reference_path),
                "tts_output_path": str(output_path),
                "voice_similarity_metric": VOICE_SIMILARITY_METRIC,
                "voice_similarity_evaluator_id": VOICE_SIMILARITY_EVALUATOR_ID,
                "voice_similarity_score": round(proxy_score, 6),
                "voice_similarity_threshold": 0.65,
                "voice_similarity_evidence_path": str(evidence_path),
                "synthesis_wall_ms": 42.0,
            }
        ],
    }
    manifest_path = root / "same-voice-candidate-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        root = Path(temp_dir_name)
        manifest_path = write_self_test_manifest(root)
        args = argparse.Namespace(
            adapter_id=DEFAULT_ADAPTER_ID,
            max_level_error_db=DEFAULT_MAX_LEVEL_ERROR_DB,
            max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
            min_voice_similarity_score=DEFAULT_MIN_VOICE_SIMILARITY_SCORE,
            output_dir=root,
            run_dir=root / "runs" / "same-voice-candidate-self-test",
            run_id="same-voice-candidate-self-test",
        )
        report = build_report(manifest_path, args)
        if not report["summary"]["passed"]:
            raise RuntimeError("same-voice candidate self-test expected gates to pass")
        clone_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        clone_manifest["segments"][0]["tts_output_path"] = clone_manifest["segments"][0]["reference_audio_path"]
        clone_manifest_path = root / "same-voice-candidate-clone-manifest.json"
        clone_manifest_path.write_text(
            json.dumps(clone_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        clone_report = build_report(clone_manifest_path, args)
        if clone_report["summary"]["passed"]:
            raise RuntimeError("same-voice candidate self-test should reject reference clones")
        weak_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        weak_manifest["segments"][0]["voice_similarity_score"] = 0.25
        weak_manifest_path = root / "same-voice-candidate-weak-manifest.json"
        weak_manifest_path.write_text(
            json.dumps(weak_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        weak_report = build_report(weak_manifest_path, args)
        if weak_report["summary"]["passed"]:
            raise RuntimeError("same-voice candidate self-test should reject weak similarity")
        mismatch_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        original_evidence_path = Path(mismatch_manifest["segments"][0]["voice_similarity_evidence_path"])
        mismatch_evidence = json.loads(original_evidence_path.read_text(encoding="utf-8"))
        mismatch_evidence["score"] = 0.25
        mismatch_evidence_path = root / "self-test-mismatched-similarity-evidence.json"
        mismatch_evidence_path.write_text(
            json.dumps(mismatch_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        mismatch_manifest["segments"][0]["voice_similarity_evidence_path"] = str(mismatch_evidence_path)
        mismatch_manifest_path = root / "same-voice-candidate-mismatched-evidence-manifest.json"
        mismatch_manifest_path.write_text(
            json.dumps(mismatch_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        mismatch_report = build_report(mismatch_manifest_path, args)
        if mismatch_report["summary"]["passed"]:
            raise RuntimeError("same-voice candidate self-test should reject mismatched evidence")
        no_consent_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        no_consent_manifest["consent"]["speaker_consent"] = False
        no_consent_path = root / "same-voice-candidate-no-consent-manifest.json"
        no_consent_path.write_text(
            json.dumps(no_consent_manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        no_consent_report = build_report(no_consent_path, args)
        if no_consent_report["summary"]["passed"]:
            raise RuntimeError("same-voice candidate self-test should reject missing consent")
    print("same-voice candidate contract self-test PASS")
    return 0


def run(args: argparse.Namespace) -> int:
    if args.self_test:
        return self_test()
    output_dir = Path(args.output_dir)
    run_dir = output_dir / "runs" / args.run_id
    args.run_dir = run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "voice-clone-report.json"
    report = build_report(Path(args.manifest), args)
    write_report(report, report_path)
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        "same-voice candidate "
        f"{status}: segments={report['summary']['segment_count']}, "
        f"min_similarity={report['summary']['min_voice_similarity_score']}"
    )
    print(f"wrote same-voice candidate report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate same-voice candidate TTS artifacts")
    parser.add_argument("command", nargs="?", default="check", choices=["check"])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--max-level-error-db", type=float, default=DEFAULT_MAX_LEVEL_ERROR_DB)
    parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    parser.add_argument("--min-voice-similarity-score", type=float, default=DEFAULT_MIN_VOICE_SIMILARITY_SCORE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"same-voice candidate benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
