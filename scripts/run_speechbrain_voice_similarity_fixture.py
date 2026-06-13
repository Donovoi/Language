#!/usr/bin/env python3
"""Score same-voice candidate artifacts with SpeechBrain ECAPA speaker verification.

This runner is intentionally separate from the hard release gate. It gives
future same-voice generators a stronger ASV benchmark than the lightweight
artifact proxy, while keeping the release gate conservative until the evidence
is calibrated against human similarity and real generated speech.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

import benchmark_same_voice_candidate_fixture as same_voice


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_CANDIDATE_REPORT = (
    DEFAULT_OUTPUT_DIR / "runs/same-voice-candidate/voice-clone-report.json"
)
DEFAULT_RUN_ID = "speechbrain-ecapa-same-voice-similarity"
DEFAULT_ADAPTER_ID = "speechbrain_ecapa_voxceleb_voice_similarity_v1"
DEFAULT_MODEL_ID = "speechbrain/spkrec-ecapa-voxceleb"
DEFAULT_MIN_SCORE = 0.25
CANDIDATE_REQUIRED_GATES = {
    "voice_reference_consent_present",
    "tts_audio_hashed",
    "tts_output_level_matched",
    "voice_similarity_or_fallback_declared",
    "tts_output_not_clipped",
}
CANDIDATE_STATUS = "same_voice_candidate"
CANDIDATE_CLAIM = "measured_proxy"
CANDIDATE_MAX_LEVEL_ERROR_DB = 0.75
CANDIDATE_MAX_PEAK_DBFS = -0.1
CANDIDATE_MIN_PROXY_SCORE = 0.65
CANDIDATE_PROXY_SCORE_TOLERANCE = 0.01
CANDIDATE_ALLOWED_RETENTION_POLICIES = {
    "ephemeral_reference_deleted",
    "ephemeral_reference_not_persisted",
    "consented_retention_with_expiry",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate_hz))
        wav.writeframes(pcm.tobytes())


def read_candidate_report(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("candidate report must be a JSON object")
    return loaded


def candidate_segments(report: dict[str, Any]) -> list[dict[str, Any]]:
    benchmark = report.get("benchmarks", {}).get("same_voice_or_fallback_tts", {})
    if not isinstance(benchmark, dict):
        raise ValueError("candidate report missing same_voice_or_fallback_tts benchmark")
    segments = benchmark.get("segments")
    if not isinstance(segments, list) or not segments:
        raise ValueError("candidate report must contain non-empty segments")
    typed_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict):
            raise ValueError(f"candidate report segment {index} must be a JSON object")
        typed_segments.append(segment)
    return typed_segments


def candidate_report_gate_issues(report: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if report.get("fixture_kind") != "same_voice_candidate_tts_audio_stream":
        issues.append("candidate report fixture_kind must be same_voice_candidate_tts_audio_stream")
    summary = report.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    if summary.get("passed") is not True:
        issues.append("candidate report summary.passed must be true")
    if summary.get("voice_clone_status") != CANDIDATE_STATUS:
        issues.append("candidate report summary.voice_clone_status must be same_voice_candidate")
    if summary.get("voice_similarity_claim") != CANDIDATE_CLAIM:
        issues.append("candidate report summary.voice_similarity_claim must be measured_proxy")
    gate_records = summary.get("quality_gates")
    if not isinstance(gate_records, list):
        issues.append("candidate report summary.quality_gates must be a list")
        return issues
    passed_gate_names = {
        str(gate.get("name"))
        for gate in gate_records
        if isinstance(gate, dict) and gate.get("passed") is True
    }
    missing_gates = sorted(CANDIDATE_REQUIRED_GATES - passed_gate_names)
    if missing_gates:
        issues.append(f"candidate report missing passed quality gates: {', '.join(missing_gates)}")
    return issues


def validate_candidate_consent(
    *,
    candidate_report_path: Path,
    report: dict[str, Any],
    expected_speaker_ids: set[str],
    expected_reference_hashes: set[str],
) -> list[str]:
    issues: list[str] = []
    consent = report.get("consent", {})
    consent = consent if isinstance(consent, dict) else {}
    if consent.get("speaker_consent") is not True:
        issues.append("candidate consent.speaker_consent must be true")
    if consent.get("voice_clone_reference_used") is not True:
        issues.append("candidate consent.voice_clone_reference_used must be true")
    retention_policy = consent.get("reference_retention_policy")
    if retention_policy not in CANDIDATE_ALLOWED_RETENTION_POLICIES:
        issues.append("candidate consent reference_retention_policy is not accepted")
    if retention_policy == "consented_retention_with_expiry":
        try:
            expiry = float(consent.get("reference_retention_expires_unix"))
        except (TypeError, ValueError):
            expiry = 0.0
        if expiry <= time.time():
            issues.append("candidate consent reference_retention_expires_unix must be in the future")
    consent_path = None
    try:
        consent_path = resolve_path(candidate_report_path, consent.get("consent_evidence_path"))
    except ValueError:
        issues.append("candidate consent_evidence_path is required")
    consent_hash = consent.get("consent_evidence_sha256")
    if not is_sha256(consent_hash):
        issues.append("candidate consent_evidence_sha256 is invalid")
    elif consent_path is None or not consent_path.exists():
        issues.append("candidate consent evidence artifact is missing")
    elif sha256_file(consent_path) != consent_hash:
        issues.append("candidate consent evidence hash does not match artifact")

    consent_speaker_ids = consent.get("speaker_ids")
    if not isinstance(consent_speaker_ids, list) or {
        str(item) for item in consent_speaker_ids
    } != expected_speaker_ids:
        issues.append("candidate consent.speaker_ids must match segment speaker ids")
    consent_reference_hashes = consent.get("reference_audio_sha256s")
    if not isinstance(consent_reference_hashes, list) or {
        str(item) for item in consent_reference_hashes
    } != expected_reference_hashes:
        issues.append("candidate consent.reference_audio_sha256s must match reference WAV hashes")
    return issues


def validate_candidate_segment_evidence(
    *,
    candidate_report_path: Path,
    segment: dict[str, Any],
    segment_index: int,
) -> tuple[set[str], set[str], tuple[str, str], tuple[str, str], list[str]]:
    issues: list[str] = []
    speaker_ids: set[str] = set()
    reference_hashes: set[str] = set()
    output_hash_pair = ("", "")
    reference_hash_pair = ("", "")
    speaker_id = str(segment.get("speaker_id") or "").strip()
    if speaker_id:
        speaker_ids.add(speaker_id)
    else:
        issues.append(f"candidate segment {segment_index} speaker_id is required")
    if segment.get("voice_clone_status") != CANDIDATE_STATUS:
        issues.append(f"candidate segment {segment_index} voice_clone_status must be same_voice_candidate")
    if segment.get("voice_similarity_claim") != CANDIDATE_CLAIM:
        issues.append(f"candidate segment {segment_index} voice_similarity_claim must be measured_proxy")
    if segment.get("voice_clone_reference_used") is not True:
        issues.append(f"candidate segment {segment_index} must use a consented voice reference")
    if str(segment.get("target_language_code") or "en") != "en":
        issues.append(f"candidate segment {segment_index} target language must be English")
    if segment.get("voice_similarity_metric") != same_voice.VOICE_SIMILARITY_METRIC:
        issues.append(
            f"candidate segment {segment_index} voice_similarity_metric must be {same_voice.VOICE_SIMILARITY_METRIC}"
        )
    if segment.get("voice_similarity_evaluator_id") != same_voice.VOICE_SIMILARITY_EVALUATOR_ID:
        issues.append(
            f"candidate segment {segment_index} voice_similarity_evaluator_id must be {same_voice.VOICE_SIMILARITY_EVALUATOR_ID}"
        )

    paths: dict[str, Path] = {}
    for label, field_name in (
        ("source", "source_audio_path"),
        ("reference", "reference_audio_path"),
        ("output", "tts_output_path"),
        ("similarity evidence", "voice_similarity_evidence_path"),
    ):
        try:
            path = resolve_path(candidate_report_path, segment.get(field_name))
        except ValueError:
            issues.append(f"candidate segment {segment_index} {field_name} is required")
            continue
        if not path.exists():
            issues.append(f"candidate segment {segment_index} {label} artifact is missing")
        paths[label] = path
    if {"source", "reference", "output"} - paths.keys():
        return speaker_ids, reference_hashes, output_hash_pair, reference_hash_pair, issues

    details: dict[str, dict[str, Any]] = {}
    samples: dict[str, np.ndarray] = {}
    for label, hash_field, pcm_hash_field in (
        ("source", "source_audio_sha256", "source_audio_pcm_sha256"),
        ("reference", "reference_audio_sha256", "reference_audio_pcm_sha256"),
        ("output", "tts_output_sha256", "tts_output_pcm_sha256"),
    ):
        try:
            audio_samples, audio_details = same_voice.read_mono_pcm16(paths[label])
        except (OSError, ValueError, wave.Error) as exc:
            issues.append(f"candidate segment {segment_index} {label} WAV could not be inspected: {exc}")
            continue
        samples[label] = audio_samples
        details[label] = audio_details
        expected_hash = segment.get(hash_field)
        expected_pcm_hash = segment.get(pcm_hash_field)
        if not is_sha256(expected_hash):
            issues.append(f"candidate segment {segment_index} {hash_field} is invalid")
        elif audio_details["sha256"] != expected_hash:
            issues.append(f"candidate segment {segment_index} {hash_field} does not match file")
        if not is_sha256(expected_pcm_hash):
            issues.append(f"candidate segment {segment_index} {pcm_hash_field} is invalid")
        elif audio_details["pcm_sha256"] != expected_pcm_hash:
            issues.append(f"candidate segment {segment_index} {pcm_hash_field} does not match WAV")
    if {"source", "reference", "output"} - details.keys():
        return speaker_ids, reference_hashes, output_hash_pair, reference_hash_pair, issues

    reference_hash_pair = (
        str(details["reference"]["sha256"]),
        str(details["reference"]["pcm_sha256"]),
    )
    output_hash_pair = (
        str(details["output"]["sha256"]),
        str(details["output"]["pcm_sha256"]),
    )
    reference_hashes.add(reference_hash_pair[0])
    if output_hash_pair[0] == reference_hash_pair[0] or output_hash_pair[1] == reference_hash_pair[1]:
        issues.append(f"candidate segment {segment_index} output must not clone reference audio")
    source_level = same_voice.dbfs(samples["source"])
    output_level = same_voice.dbfs(samples["output"])
    level_error = abs(output_level - source_level)
    reported_level_error = segment.get("output_level_error_db")
    if level_error > CANDIDATE_MAX_LEVEL_ERROR_DB:
        issues.append(f"candidate segment {segment_index} source/output level error is too high")
    if not isinstance(reported_level_error, (float, int)) or abs(
        float(reported_level_error) - level_error
    ) > 0.075:
        issues.append(f"candidate segment {segment_index} output_level_error_db does not match WAVs")
    output_peak = same_voice.peak_dbfs(samples["output"])
    if output_peak > CANDIDATE_MAX_PEAK_DBFS:
        issues.append(f"candidate segment {segment_index} output peak is too high")

    proxy_score = same_voice.acoustic_similarity_proxy(
        samples["reference"],
        samples["output"],
        int(details["reference"]["sample_rate_hz"]),
    )
    score = segment.get("voice_similarity_score")
    threshold = segment.get("voice_similarity_threshold")
    if not isinstance(score, (float, int)):
        issues.append(f"candidate segment {segment_index} voice_similarity_score is required")
    elif abs(float(score) - proxy_score) > CANDIDATE_PROXY_SCORE_TOLERANCE:
        issues.append(f"candidate segment {segment_index} voice_similarity_score does not match proxy")
    if not isinstance(threshold, (float, int)):
        issues.append(f"candidate segment {segment_index} voice_similarity_threshold is required")
    elif float(threshold) < CANDIDATE_MIN_PROXY_SCORE:
        issues.append(f"candidate segment {segment_index} voice_similarity_threshold is too low")
    if isinstance(score, (float, int)) and isinstance(threshold, (float, int)) and float(score) < float(threshold):
        issues.append(f"candidate segment {segment_index} voice similarity score is below threshold")

    evidence_path = paths.get("similarity evidence")
    evidence_hash = segment.get("voice_similarity_evidence_sha256")
    if not is_sha256(evidence_hash):
        issues.append(f"candidate segment {segment_index} voice_similarity_evidence_sha256 is invalid")
    elif evidence_path is None or not evidence_path.exists() or sha256_file(evidence_path) != evidence_hash:
        issues.append(f"candidate segment {segment_index} similarity evidence hash does not match file")
    if evidence_path is not None and evidence_path.exists():
        try:
            evidence = read_candidate_report(evidence_path)
        except Exception as exc:
            evidence = {}
            issues.append(f"candidate segment {segment_index} similarity evidence is unreadable: {exc}")
        if evidence.get("speaker_id") != speaker_id:
            issues.append(f"candidate segment {segment_index} similarity evidence speaker_id mismatch")
        if evidence.get("metric_name") != same_voice.VOICE_SIMILARITY_METRIC:
            issues.append(f"candidate segment {segment_index} similarity evidence metric mismatch")
        if evidence.get("evaluator_id") != same_voice.VOICE_SIMILARITY_EVALUATOR_ID:
            issues.append(f"candidate segment {segment_index} similarity evidence evaluator mismatch")
        for evidence_field, segment_field in (
            ("reference_audio_sha256", "reference_audio_sha256"),
            ("reference_audio_pcm_sha256", "reference_audio_pcm_sha256"),
            ("tts_output_sha256", "tts_output_sha256"),
            ("tts_output_pcm_sha256", "tts_output_pcm_sha256"),
        ):
            if evidence.get(evidence_field) != segment.get(segment_field):
                issues.append(
                    f"candidate segment {segment_index} similarity evidence {evidence_field} mismatch"
                )
        evidence_score = evidence.get("score")
        evidence_threshold = evidence.get("threshold")
        if not isinstance(evidence_score, (float, int)) or abs(
            float(evidence_score) - proxy_score
        ) > CANDIDATE_PROXY_SCORE_TOLERANCE:
            issues.append(f"candidate segment {segment_index} similarity evidence score mismatch")
        if not isinstance(evidence_threshold, (float, int)) or not isinstance(
            threshold, (float, int)
        ) or abs(float(evidence_threshold) - float(threshold)) > 1e-6:
            issues.append(f"candidate segment {segment_index} similarity evidence threshold mismatch")
    return speaker_ids, reference_hashes, output_hash_pair, reference_hash_pair, issues


def validate_candidate_report_evidence(
    *,
    candidate_report_path: Path,
    report: dict[str, Any],
    segments: list[dict[str, Any]],
) -> list[str]:
    issues = candidate_report_gate_issues(report)
    speaker_ids: set[str] = set()
    reference_hashes: set[str] = set()
    output_hash_pairs: dict[int, tuple[str, str]] = {}
    reference_hash_pairs: dict[int, tuple[str, str]] = {}
    for index, segment in enumerate(segments):
        segment_speakers, segment_references, output_pair, reference_pair, segment_issues = (
            validate_candidate_segment_evidence(
                candidate_report_path=candidate_report_path,
                segment=segment,
                segment_index=index,
            )
        )
        speaker_ids.update(segment_speakers)
        reference_hashes.update(segment_references)
        output_hash_pairs[index] = output_pair
        reference_hash_pairs[index] = reference_pair
        issues.extend(segment_issues)
    issues.extend(
        validate_candidate_consent(
            candidate_report_path=candidate_report_path,
            report=report,
            expected_speaker_ids=speaker_ids,
            expected_reference_hashes=reference_hashes,
        )
    )
    for output_index, output_pair in output_hash_pairs.items():
        if not all(output_pair):
            continue
        for reference_index, reference_pair in reference_hash_pairs.items():
            if output_index == reference_index or not all(reference_pair):
                continue
            if output_pair[0] == reference_pair[0] or output_pair[1] == reference_pair[1]:
                issues.append(
                    f"candidate segment {output_index} output must not clone segment {reference_index} reference"
                )
    return issues


def scalar_float(value: Any) -> float:
    if hasattr(value, "detach"):
        value = value.detach().cpu().item()
    elif hasattr(value, "item"):
        value = value.item()
    return float(value)


def scalar_bool(value: Any) -> bool:
    if hasattr(value, "detach"):
        value = value.detach().cpu().item()
    elif hasattr(value, "item"):
        value = value.item()
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value)


def default_model_cache_dir(output_dir: Path, model_id: str) -> Path:
    cache_root = os.environ.get("SPEECHBRAIN_CACHE_DIR") or os.environ.get("HF_HOME")
    if cache_root:
        return Path(cache_root) / "speechbrain" / model_id.replace("/", "--")
    return output_dir / "model_cache" / "speechbrain" / model_id.replace("/", "--")


def load_speechbrain_verifier(model_id: str, device: str, savedir: Path) -> Any:
    try:
        from speechbrain.inference.speaker import SpeakerRecognition
    except ImportError:
        try:
            from speechbrain.pretrained import SpeakerRecognition
        except ImportError as exc:
            raise SystemExit(
                "SpeechBrain speaker verification requires the "
                "audio-eval-speechbrain-sepformer Docker profile."
            ) from exc

    kwargs: dict[str, Any] = {"source": model_id, "savedir": str(savedir)}
    if device:
        kwargs["run_opts"] = {"device": device}
    return SpeakerRecognition.from_hparams(**kwargs)


def verify_segment_artifacts(
    *,
    candidate_report_path: Path,
    segment: dict[str, Any],
    segment_index: int,
) -> tuple[Path | None, Path | None, list[str]]:
    issues: list[str] = []
    reference_path: Path | None = None
    output_path: Path | None = None
    try:
        reference_path = resolve_path(candidate_report_path, segment.get("reference_audio_path"))
        output_path = resolve_path(candidate_report_path, segment.get("tts_output_path"))
    except ValueError as exc:
        issues.append(str(exc))
        return None, None, issues
    for label, path, hash_field in (
        ("reference", reference_path, "reference_audio_sha256"),
        ("output", output_path, "tts_output_sha256"),
    ):
        if not path.exists():
            issues.append(f"segment {segment_index} {label} WAV is missing")
            continue
        expected_hash = segment.get(hash_field)
        if not is_sha256(expected_hash):
            issues.append(f"segment {segment_index} {hash_field} is invalid")
        elif sha256_file(path) != expected_hash:
            issues.append(f"segment {segment_index} {label} WAV hash mismatch")
    return reference_path, output_path, issues


def score_segments_with_speechbrain(
    *,
    args: argparse.Namespace,
    candidate_report_path: Path,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    verifier = load_speechbrain_verifier(
        args.model_id,
        args.device,
        Path(args.model_cache_dir)
        if args.model_cache_dir
        else default_model_cache_dir(Path(args.output_dir), args.model_id),
    )
    scored: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        reference_path, output_path, issues = verify_segment_artifacts(
            candidate_report_path=candidate_report_path,
            segment=segment,
            segment_index=index,
        )
        score = None
        prediction = False
        if reference_path is not None and output_path is not None and not issues:
            raw_score, raw_prediction = verifier.verify_files(
                str(reference_path),
                str(output_path),
            )
            score = scalar_float(raw_score)
            prediction = scalar_bool(raw_prediction)
        scored.append(
            {
                "segment_index": index,
                "speaker_id": segment.get("speaker_id"),
                "fixture_id": segment.get("fixture_id"),
                "reference_audio_path": segment.get("reference_audio_path"),
                "reference_audio_sha256": segment.get("reference_audio_sha256"),
                "tts_output_path": segment.get("tts_output_path"),
                "tts_output_sha256": segment.get("tts_output_sha256"),
                "asv_score": round(score, 6) if score is not None and math.isfinite(score) else None,
                "asv_same_speaker_prediction": prediction,
                "issues": issues,
            }
        )
    return scored


def unscored_segment_records(
    *,
    candidate_report_path: Path,
    segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, segment in enumerate(segments):
        _reference_path, _output_path, issues = verify_segment_artifacts(
            candidate_report_path=candidate_report_path,
            segment=segment,
            segment_index=index,
        )
        records.append(
            {
                "segment_index": index,
                "speaker_id": segment.get("speaker_id"),
                "fixture_id": segment.get("fixture_id"),
                "reference_audio_path": segment.get("reference_audio_path"),
                "reference_audio_sha256": segment.get("reference_audio_sha256"),
                "tts_output_path": segment.get("tts_output_path"),
                "tts_output_sha256": segment.get("tts_output_sha256"),
                "asv_score": None,
                "asv_same_speaker_prediction": False,
                "issues": issues,
            }
        )
    return records


def quality_gates(
    *,
    candidate_report: dict[str, Any],
    candidate_validation_issues: list[str],
    score_records: list[dict[str, Any]],
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    candidate_summary = candidate_report.get("summary", {})
    candidate_summary = candidate_summary if isinstance(candidate_summary, dict) else {}
    all_scores = [
        float(item["asv_score"])
        for item in score_records
        if isinstance(item.get("asv_score"), (float, int))
    ]
    all_clean = all(not item.get("issues") for item in score_records)
    predictions_pass = all(bool(item.get("asv_same_speaker_prediction")) for item in score_records)
    min_score = min(all_scores) if all_scores else None
    return [
        {
            "name": "candidate_report_passed",
            "passed": candidate_summary.get("passed") is True
            and candidate_summary.get("voice_clone_status") == "same_voice_candidate",
            "threshold": "same_voice_candidate report already passed candidate artifact checks",
            "value": {
                "passed": candidate_summary.get("passed"),
                "voice_clone_status": candidate_summary.get("voice_clone_status"),
            },
        },
        {
            "name": "candidate_report_evidence_revalidated",
            "passed": not candidate_validation_issues,
            "threshold": "candidate consent, hashes, sidecars, proxy score, levels, and non-clone audio revalidate",
            "value": {
                "issue_count": len(candidate_validation_issues),
                "issues": candidate_validation_issues[:10],
            },
        },
        {
            "name": "candidate_artifacts_hash_verified",
            "passed": all_clean and bool(score_records),
            "threshold": "reference and output WAV hashes match candidate report",
            "value": {
                "segment_count": len(score_records),
                "issue_count": sum(len(item.get("issues", [])) for item in score_records),
            },
        },
        {
            "name": "speechbrain_predictions_same_speaker",
            "passed": predictions_pass and bool(score_records),
            "threshold": "SpeechBrain verifier predicts same speaker for every segment",
            "value": [item.get("asv_same_speaker_prediction") for item in score_records],
        },
        {
            "name": "speechbrain_min_score",
            "passed": isinstance(min_score, (float, int)) and float(min_score) >= float(args.min_score),
            "threshold": f"min ASV score >= {float(args.min_score):.3f}",
            "value": round(float(min_score), 6) if isinstance(min_score, (float, int)) else None,
        },
    ]


def build_report(
    *,
    args: argparse.Namespace,
    candidate_report_path: Path,
    candidate_report: dict[str, Any],
    candidate_validation_issues: list[str],
    score_records: list[dict[str, Any]],
) -> dict[str, Any]:
    gates = quality_gates(
        candidate_report=candidate_report,
        candidate_validation_issues=candidate_validation_issues,
        score_records=score_records,
        args=args,
    )
    scores = [
        float(item["asv_score"])
        for item in score_records
        if isinstance(item.get("asv_score"), (float, int))
    ]
    passed = all(bool(gate["passed"]) for gate in gates)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "speechbrain_ecapa_voice_similarity",
        "summary": {
            "passed": passed,
            "segment_count": len(score_records),
            "min_asv_score": round(min(scores), 6) if scores else None,
            "mean_asv_score": round(sum(scores) / len(scores), 6) if scores else None,
            "same_speaker_prediction_count": sum(
                1 for item in score_records if item.get("asv_same_speaker_prediction")
            ),
            "quality_gates": gates,
            "release_proof": False,
        },
        "benchmarks": {
            "speechbrain_ecapa_voice_similarity": {
                "adapter_id": args.adapter_id,
                "candidate_report_path": str(candidate_report_path),
                "candidate_report_sha256": sha256_file(candidate_report_path),
                "model_id": args.model_id,
                "min_score": float(args.min_score),
                "candidate_report_validation_issues": candidate_validation_issues,
                "segments": score_records,
            }
        },
        "adapter": {
            "speaker_verification": {
                "adapter_id": args.adapter_id,
                "model_id": args.model_id,
                "model_family": "SpeechBrain ECAPA-TDNN",
                "training_data": "VoxCeleb1+VoxCeleb2 per official model card",
                "metric": "SpeechBrain verify_files score plus same-speaker prediction",
            }
        },
        "detractor_loop": {
            "strongest_objection": (
                "ECAPA/VoxCeleb ASV is stronger than the built-in proxy, but generated cross-language "
                "TTS can fool or degrade speaker embeddings and this is not calibrated against human "
                "listener similarity for the app's target rooms."
            ),
            "next_falsifying_benchmark": (
                "Run consented local speakers through the selected same-voice generator, then compare "
                "SpeechBrain ECAPA scores against blinded human same-speaker ratings and WER/MOS."
            ),
            "verdict": (
                "Use this as stronger candidate evidence before runtime integration; do not treat it "
                "as final release proof by itself."
            ),
        },
    }


def run(args: argparse.Namespace) -> int:
    if args.self_test:
        return self_test()
    candidate_report_path = Path(args.candidate_report)
    candidate_report = read_candidate_report(candidate_report_path)
    segments = candidate_segments(candidate_report)
    candidate_validation_issues = validate_candidate_report_evidence(
        candidate_report_path=candidate_report_path,
        report=candidate_report,
        segments=segments,
    )
    if candidate_validation_issues:
        score_records = unscored_segment_records(
            candidate_report_path=candidate_report_path,
            segments=segments,
        )
    else:
        score_records = score_segments_with_speechbrain(
            args=args,
            candidate_report_path=candidate_report_path,
            segments=segments,
        )
    report = build_report(
        args=args,
        candidate_report_path=candidate_report_path,
        candidate_report=candidate_report,
        candidate_validation_issues=candidate_validation_issues,
        score_records=score_records,
    )
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    report_path = run_dir / "speechbrain-voice-similarity-report.json"
    write_json(report_path, report)
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        "speechbrain voice similarity "
        f"{status}: segments={report['summary']['segment_count']}, "
        f"min_asv_score={report['summary']['min_asv_score']}"
    )
    print(f"wrote SpeechBrain voice similarity report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def self_test() -> int:
    with tempfile.TemporaryDirectory() as temp_dir_name:
        root = Path(temp_dir_name)
        same_voice_args = argparse.Namespace(
            adapter_id=same_voice.DEFAULT_ADAPTER_ID,
            max_level_error_db=same_voice.DEFAULT_MAX_LEVEL_ERROR_DB,
            max_peak_dbfs=same_voice.DEFAULT_MAX_PEAK_DBFS,
            min_voice_similarity_score=same_voice.DEFAULT_MIN_VOICE_SIMILARITY_SCORE,
            output_dir=root / "artifacts/audio_eval",
            run_dir=root / "artifacts/audio_eval/runs/same-voice-candidate",
            run_id=same_voice.DEFAULT_RUN_ID,
            score_warning_only=False,
        )
        manifest_path = same_voice.write_self_test_manifest(root)
        candidate_report = same_voice.build_report(manifest_path, same_voice_args)
        candidate_report_path = Path(same_voice_args.run_dir) / "voice-clone-report.json"
        write_json(candidate_report_path, candidate_report)
        loaded_candidate_report = read_candidate_report(candidate_report_path)
        segments = candidate_segments(loaded_candidate_report)
        candidate_validation_issues = validate_candidate_report_evidence(
            candidate_report_path=candidate_report_path,
            report=loaded_candidate_report,
            segments=segments,
        )
        if candidate_validation_issues:
            raise RuntimeError(
                "SpeechBrain voice similarity self-test expected candidate evidence to revalidate"
            )
        artifact_issues = [
            issue
            for index, segment in enumerate(segments)
            for issue in verify_segment_artifacts(
                candidate_report_path=candidate_report_path,
                segment=segment,
                segment_index=index,
            )[2]
        ]
        if artifact_issues:
            raise RuntimeError("SpeechBrain voice similarity self-test expected artifact hashes to verify")
        score_records = [
            {
                "segment_index": 0,
                "speaker_id": segments[0].get("speaker_id"),
                "fixture_id": "self_test",
                "reference_audio_path": segments[0].get("reference_audio_path"),
                "reference_audio_sha256": segments[0].get("reference_audio_sha256"),
                "tts_output_path": segments[0].get("tts_output_path"),
                "tts_output_sha256": segments[0].get("tts_output_sha256"),
                "asv_score": 0.8,
                "asv_same_speaker_prediction": True,
                "issues": [],
            }
        ]
        args = argparse.Namespace(
            adapter_id=DEFAULT_ADAPTER_ID,
            min_score=DEFAULT_MIN_SCORE,
            model_id=DEFAULT_MODEL_ID,
        )
        report = build_report(
            args=args,
            candidate_report_path=candidate_report_path,
            candidate_report=loaded_candidate_report,
            candidate_validation_issues=candidate_validation_issues,
            score_records=score_records,
        )
        if not report["summary"]["passed"]:
            raise RuntimeError("SpeechBrain voice similarity self-test expected pass")
        low_score_records = [{**score_records[0], "asv_score": 0.01}]
        low_score_report = build_report(
            args=args,
            candidate_report_path=candidate_report_path,
            candidate_report=loaded_candidate_report,
            candidate_validation_issues=candidate_validation_issues,
            score_records=low_score_records,
        )
        if low_score_report["summary"]["passed"]:
            raise RuntimeError("SpeechBrain voice similarity self-test expected low-score fail")
        bad_candidate = {
            **loaded_candidate_report,
            "summary": {
                **loaded_candidate_report["summary"],
                "passed": False,
            },
        }
        bad_candidate_validation_issues = validate_candidate_report_evidence(
            candidate_report_path=candidate_report_path,
            report=bad_candidate,
            segments=segments,
        )
        bad_candidate_report = build_report(
            args=args,
            candidate_report_path=candidate_report_path,
            candidate_report=bad_candidate,
            candidate_validation_issues=bad_candidate_validation_issues,
            score_records=score_records,
        )
        if bad_candidate_report["summary"]["passed"]:
            raise RuntimeError("SpeechBrain voice similarity self-test expected candidate fail")
        tampered_candidate = json.loads(json.dumps(loaded_candidate_report))
        tampered_candidate["benchmarks"]["same_voice_or_fallback_tts"]["segments"][0][
            "source_audio_sha256"
        ] = "0" * 64
        tampered_issues = validate_candidate_report_evidence(
            candidate_report_path=candidate_report_path,
            report=tampered_candidate,
            segments=candidate_segments(tampered_candidate),
        )
        if not tampered_issues:
            raise RuntimeError("SpeechBrain voice similarity self-test expected tampered report fail")
        expired_consent_candidate = json.loads(json.dumps(loaded_candidate_report))
        expired_consent_candidate["consent"]["reference_retention_policy"] = "consented_retention_with_expiry"
        expired_consent_candidate["consent"]["reference_retention_expires_unix"] = 1
        expired_consent_issues = validate_candidate_report_evidence(
            candidate_report_path=candidate_report_path,
            report=expired_consent_candidate,
            segments=candidate_segments(expired_consent_candidate),
        )
        if not expired_consent_issues:
            raise RuntimeError("SpeechBrain voice similarity self-test expected expired consent fail")
    print("speechbrain voice similarity contract self-test PASS")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score same-voice candidate audio with SpeechBrain ECAPA")
    parser.add_argument("command", nargs="?", default="score", choices=["score"])
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--score-warning-only", action="store_true")
    parser.add_argument("--candidate-report", type=Path, default=DEFAULT_CANDIDATE_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--model-cache-dir", type=Path)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"speechbrain voice similarity error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
