"""Run Whisper on accepted TSE clips using causal diarization windows as the stream driver."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    analyze_fixture,
    write_jsonl,
    write_report,
)
from benchmark_target_speaker_extraction_fixture import (
    base_fixture_dir,
    build_passthrough_tse_records,
    read_prediction_record,
    read_mono,
    score_tse_predictions,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    build_oracle_translation_records,
    prepare_multilingual_fixture,
    score_translation_predictions,
)
from run_whisper_rolling_translation_fixture import (
    final_prediction_from_rolling,
    human_segments,
    rolling_metrics,
)
from run_whisper_translation_fixture import (
    DEFAULT_MODEL_SIZE,
    load_whisper_model,
    run_self_test as run_source_clip_self_test,
    transcribe_segment,
)
from run_whisper_tse_translation_fixture import (
    REAL_MODEL_MAX_LEVEL_ERROR_DB,
    REAL_MODEL_MIN_SEGMENT_SNR_DB,
    write_external_tse_slice,
)


DEFAULT_RUN_ID = "whisper-tiny-fleurs-wesep-causal-tse-translation"
DEFAULT_ADAPTER_ID = "faster_whisper_tiny_wesep_causal_tse_translate_v1"
DEFAULT_TSE_PREDICTIONS = (
    DEFAULT_OUTPUT_DIR
    / "runs/fleurs-wesep-enrolled-target-speaker-extraction/wesep_enrolled_tse_predictions.jsonl"
)
DEFAULT_DIARIZATION_PREDICTIONS = (
    DEFAULT_OUTPUT_DIR
    / "runs/sortformer-streaming-4spk-v2-1-fleurs-rolling-pcm/rolling_predictions.jsonl"
)
DEFAULT_DIARIZATION_REPORT = (
    DEFAULT_OUTPUT_DIR
    / "runs/sortformer-streaming-4spk-v2-1-fleurs-rolling-pcm/rolling-diarization-report.json"
)
DEFAULT_MIN_CLIP_S = 1.0
FINAL_BOUNDARY_TOLERANCE_S = 0.55
MIN_ASSOCIATION_OVERLAP_S = 0.05


def load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} did not contain a JSON object")
    return payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not all(isinstance(record, dict) for record in records):
        raise ValueError(f"{path} must contain JSON objects")
    return records


def interval_overlap_s(
    left_start_s: float,
    left_end_s: float,
    right_start_s: float,
    right_end_s: float,
) -> float:
    return max(0.0, min(left_end_s, right_end_s) - max(left_start_s, right_start_s))


def tse_segment_by_speaker(tse_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_speaker: dict[str, dict[str, Any]] = {}
    for segment in tse_record.get("segments", []):
        speaker_id = str(segment.get("speaker_id", segment.get("target_speaker_id", "")))
        if speaker_id:
            by_speaker[speaker_id] = segment
    return by_speaker


def normalized_abs_correlation(left: np.ndarray, right: np.ndarray) -> float:
    if left.size == 0 or right.size == 0:
        return 0.0
    size = min(int(left.shape[0]), int(right.shape[0]))
    if size <= 0:
        return 0.0
    left = np.asarray(left[:size], dtype=np.float32)
    right = np.asarray(right[:size], dtype=np.float32)
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom <= 1.0e-12:
        return 0.0
    return abs(float(np.dot(left, right)) / denom)


def build_speaker_association(
    annotation: dict[str, Any],
    output_dir: Path,
    tse_run_dir: Path,
    tse_segments: dict[str, dict[str, Any]],
    diarization_records: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, Any]]:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, mix_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    sample_rate_hz = int(annotation["sample_rate_hz"])
    if mix_rate_hz != sample_rate_hz:
        raise ValueError(f"expected {sample_rate_hz} Hz fixture mix, got {mix_rate_hz} Hz")

    extracted_by_speaker: dict[str, np.ndarray] = {}
    for speaker_id, segment in tse_segments.items():
        extracted_audio, extracted_rate_hz = read_mono(tse_run_dir / str(segment["extracted_audio_path"]))
        if extracted_rate_hz != sample_rate_hz:
            raise ValueError(f"{segment['extracted_audio_path']} sample rate mismatch")
        extracted_by_speaker[speaker_id] = extracted_audio

    scores: dict[str, dict[str, float]] = {}
    overlap_totals: dict[str, dict[str, float]] = {}
    for record in diarization_records:
        for prediction in record.get("segments", []):
            diarized_speaker_id = str(prediction.get("speaker_id", ""))
            if not diarized_speaker_id:
                continue
            pred_start_s = float(prediction["start_s"])
            pred_end_s = float(prediction["end_s"])
            for speaker_id, segment in tse_segments.items():
                overlap_start_s = max(pred_start_s, float(segment["start_s"]))
                overlap_end_s = min(pred_end_s, float(segment["end_s"]))
                overlap_s = overlap_end_s - overlap_start_s
                if overlap_s < MIN_ASSOCIATION_OVERLAP_S:
                    continue
                mix_start = int(round(overlap_start_s * sample_rate_hz))
                mix_end = int(round(overlap_end_s * sample_rate_hz))
                extracted_start = int(round((overlap_start_s - float(segment["start_s"])) * sample_rate_hz))
                extracted_end = extracted_start + max(0, mix_end - mix_start)
                mix_part = mix_audio[mix_start:mix_end]
                extracted_part = extracted_by_speaker[speaker_id][extracted_start:extracted_end]
                score = normalized_abs_correlation(extracted_part, mix_part) * overlap_s
                scores.setdefault(diarized_speaker_id, {})
                scores[diarized_speaker_id][speaker_id] = scores[diarized_speaker_id].get(speaker_id, 0.0) + score
                overlap_totals.setdefault(diarized_speaker_id, {})
                overlap_totals[diarized_speaker_id][speaker_id] = (
                    overlap_totals[diarized_speaker_id].get(speaker_id, 0.0) + overlap_s
                )

    candidates: list[tuple[float, str, str]] = []
    for diarized_speaker_id, speaker_scores in scores.items():
        for speaker_id, score in speaker_scores.items():
            candidates.append((score, diarized_speaker_id, speaker_id))
    candidates.sort(reverse=True)
    association: dict[str, str] = {}
    used_tse_speakers: set[str] = set()
    for score, diarized_speaker_id, speaker_id in candidates:
        if score <= 0.0 or diarized_speaker_id in association or speaker_id in used_tse_speakers:
            continue
        association[diarized_speaker_id] = speaker_id
        used_tse_speakers.add(speaker_id)

    diagnostics = {
        "method": "diarization_tse_mixture_correlation",
        "uses_reference_stems": False,
        "min_overlap_s": MIN_ASSOCIATION_OVERLAP_S,
        "scores": {
            diarized: {speaker: round(score, 6) for speaker, score in speaker_scores.items()}
            for diarized, speaker_scores in scores.items()
        },
        "overlap_s": {
            diarized: {speaker: round(overlap, 6) for speaker, overlap in speaker_overlaps.items()}
            for diarized, speaker_overlaps in overlap_totals.items()
        },
        "association": association,
    }
    return association, diagnostics


def best_tse_segment_for_prediction(
    prediction: dict[str, Any],
    tse_segments: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any], float] | None:
    pred_start_s = float(prediction["start_s"])
    pred_end_s = float(prediction["end_s"])
    best: tuple[str, dict[str, Any], float] | None = None
    for speaker_id, segment in tse_segments.items():
        overlap = interval_overlap_s(
            pred_start_s,
            pred_end_s,
            float(segment["start_s"]),
            float(segment["end_s"]),
        )
        if overlap <= 0.0:
            continue
        if best is None or overlap > best[2]:
            best = (speaker_id, segment, overlap)
    return best


def choose_available_tse_partials(
    diarization_record: dict[str, Any],
    tse_segments: dict[str, dict[str, Any]],
    speaker_association: dict[str, str],
) -> list[dict[str, Any]]:
    by_tse_speaker: dict[str, dict[str, Any]] = {}
    for prediction in diarization_record.get("segments", []):
        diarized_speaker_id = str(prediction.get("speaker_id", ""))
        speaker_id = speaker_association.get(diarized_speaker_id, "")
        if speaker_id and speaker_id in tse_segments:
            tse_segment = tse_segments[speaker_id]
            pred_start_s = float(prediction["start_s"])
            pred_end_s = float(prediction["end_s"])
            overlap = interval_overlap_s(
                pred_start_s,
                pred_end_s,
                float(tse_segment["start_s"]),
                float(tse_segment["end_s"]),
            )
            if overlap <= 0.0:
                continue
        else:
            match = best_tse_segment_for_prediction(prediction, tse_segments)
            if match is None:
                continue
            speaker_id, tse_segment, overlap = match
        clip_end_s = min(float(tse_segment["end_s"]), float(prediction["end_s"]))
        clip_start_s = float(tse_segment["start_s"])
        if clip_end_s <= clip_start_s:
            continue
        current = by_tse_speaker.get(speaker_id)
        if current is None or clip_end_s > float(current["clip_end_s"]):
            by_tse_speaker[speaker_id] = {
                "speaker_id": speaker_id,
                "tse_segment": tse_segment,
                "diarized_speaker_id": diarized_speaker_id,
                "diarized_start_s": float(prediction["start_s"]),
                "diarized_end_s": float(prediction["end_s"]),
                "diarization_tse_overlap_s": round(overlap, 6),
                "clip_end_s": round(clip_end_s, 6),
            }
    return sorted(by_tse_speaker.values(), key=lambda item: (float(item["clip_end_s"]), item["speaker_id"]))


def diarization_report_passed(report: dict[str, Any]) -> bool:
    summary = report.get("summary", {})
    return isinstance(summary, dict) and bool(summary.get("passed"))


def tse_acceptance_report(
    annotation: dict[str, Any],
    output_dir: Path,
    tse_record: dict[str, Any],
    tse_run_dir: Path,
    tse_report: dict[str, Any],
) -> dict[str, Any]:
    metadata = tse_record.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    tse_summary = tse_report["summary"]
    passthrough_run_dir = tse_run_dir / "baselines" / "causal_translation_acceptance_passthrough"
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
    passthrough_summary = passthrough_report["summary"]
    postprocess = metadata.get("postprocess", {})
    postprocess = postprocess if isinstance(postprocess, dict) else {}
    enrollment_segments = tse_record.get("segments", [])
    enrollment_present = all(
        bool(segment.get("enrollment_audio_path"))
        and bool(segment.get("enrollment_audio_sha256"))
        for segment in enrollment_segments
    )
    gates = [
        {
            "name": "tse_acceptance_real_model_not_oracle",
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
            "name": "tse_acceptance_enrollment_metadata_present",
            "value": bool(enrollment_present),
            "threshold": "every external TSE segment carries enrollment path and hash",
            "passed": bool(enrollment_present),
        },
        {
            "name": "tse_acceptance_runtime_postprocess_declared",
            "value": postprocess,
            "threshold": "runtime-available postprocess; no reference stems",
            "passed": (
                postprocess.get("polarity_correction") == "mixture-correlation"
                and postprocess.get("level_normalization") == "enrollment-rms"
                and postprocess.get("uses_reference_stems") is False
            ),
        },
        {
            "name": "tse_acceptance_beats_passthrough_mean_snr",
            "value": float(tse_summary["mean_segment_snr_db"]),
            "threshold": f"> {passthrough_summary['mean_segment_snr_db']} dB passthrough mean SNR",
            "passed": float(tse_summary["mean_segment_snr_db"])
            > float(passthrough_summary["mean_segment_snr_db"]),
        },
        {
            "name": "tse_acceptance_beats_passthrough_mean_interferer_reduction",
            "value": float(tse_summary["mean_interferer_reduction_db"]),
            "threshold": (
                f"> {passthrough_summary['mean_interferer_reduction_db']} dB "
                "passthrough mean interferer reduction"
            ),
            "passed": float(tse_summary["mean_interferer_reduction_db"])
            > float(passthrough_summary["mean_interferer_reduction_db"]),
        },
        {
            "name": "tse_acceptance_min_segment_snr_floor",
            "value": float(tse_summary["min_segment_snr_db"]),
            "threshold": f">= {REAL_MODEL_MIN_SEGMENT_SNR_DB} dB minimum segment SNR",
            "passed": float(tse_summary["min_segment_snr_db"]) >= REAL_MODEL_MIN_SEGMENT_SNR_DB,
        },
        {
            "name": "tse_acceptance_output_level_preserved",
            "value": float(tse_summary["max_abs_level_error_db"]),
            "threshold": f"<= {REAL_MODEL_MAX_LEVEL_ERROR_DB} dB max absolute level error",
            "passed": float(tse_summary["max_abs_level_error_db"]) <= REAL_MODEL_MAX_LEVEL_ERROR_DB,
        },
        {
            "name": "tse_acceptance_polarity_invariant_scoring_declared",
            "value": {
                "enabled": bool(tse_summary.get("polarity_invariant_scoring")),
                "inverted_segment_count": int(tse_summary.get("polarity_inverted_segment_count", 0)),
            },
            "threshold": "global waveform polarity handled in scorer",
            "passed": bool(tse_summary.get("polarity_invariant_scoring")),
        },
    ]
    return {
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
        },
        "mixture_passthrough_lower_bound": passthrough_report,
    }


def build_causal_whisper_predictions(
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path, dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    tse_record = read_prediction_record(args.tse_predictions.resolve())
    tse_segments = tse_segment_by_speaker(tse_record)
    if not tse_segments:
        raise ValueError("external TSE record did not contain speaker segments")
    tse_run_dir = args.tse_predictions.resolve().parent
    diarization_records = load_jsonl(args.diarization_predictions.resolve())
    diarization_report = load_json(args.diarization_report.resolve())
    diarization_adapter_id = str(diarization_report.get("adapter_id") or "unknown_diarization_adapter")
    if diarization_adapter_id == "unknown_diarization_adapter" and diarization_records:
        diarization_adapter_id = str(diarization_records[0].get("adapter_id") or diarization_adapter_id)
    speaker_association, speaker_association_diagnostics = build_speaker_association(
        annotation,
        output_dir,
        tse_run_dir,
        tse_segments,
        diarization_records,
    )
    model = load_whisper_model(args.model_size, args.device, args.compute_type)

    run_dir = output_dir / "runs" / args.run_id
    clip_dir = run_dir / "causal_external_tse_rolling_clips"
    completed_speakers: set[str] = set()
    records: list[dict[str, Any]] = []
    record_kind = "whisper_after_causal_diarization_external_tse_rolling_translation"

    for record in diarization_records:
        if record.get("fixture_id") != annotation["fixture_id"]:
            continue
        metadata = record.get("metadata", {})
        metadata = metadata if isinstance(metadata, dict) else {}
        chunk_index = int(metadata.get("chunk_index", len(records)))
        chunk_end_s = float(metadata.get("chunk_end_s", metadata.get("input_end_s", 0.0)))
        target_output_end_s = float(metadata.get("target_output_end_s", chunk_end_s))
        record_segments: list[dict[str, Any]] = []
        for partial in choose_available_tse_partials(record, tse_segments, speaker_association):
            speaker_id = str(partial["speaker_id"])
            if speaker_id in completed_speakers:
                continue
            tse_segment = partial["tse_segment"]
            segment_start_s = float(tse_segment["start_s"])
            segment_end_s = float(tse_segment["end_s"])
            clip_end_s = min(segment_end_s, float(partial["clip_end_s"]), target_output_end_s)
            segment_final = clip_end_s >= segment_end_s - FINAL_BOUNDARY_TOLERANCE_S
            if segment_final and target_output_end_s >= segment_end_s - FINAL_BOUNDARY_TOLERANCE_S:
                clip_end_s = segment_end_s
            clip_duration_s = clip_end_s - segment_start_s
            if clip_duration_s < args.min_clip_s and not segment_final:
                continue
            if clip_duration_s <= 0.0:
                continue

            clip_path = clip_dir / f"chunk_{chunk_index:03d}_{speaker_id}.wav"
            write_external_tse_slice(
                tse_run_dir,
                tse_segment,
                clip_duration_s=clip_duration_s,
                clip_path=clip_path,
            )
            result = transcribe_segment(
                model,
                clip_path,
                beam_size=args.beam_size,
                vad_filter=bool(args.vad_filter),
            )
            speech_elapsed_ms = max(0.0, chunk_end_s - segment_start_s) * 1000.0
            record_segments.append(
                {
                    "speaker_id": speaker_id,
                    "start_s": segment_start_s,
                    "end_s": round(clip_end_s, 6),
                    "detected_language_code": result["detected_language_code"],
                    "language_confidence": result["language_confidence"],
                    "source_text": None,
                    "translated_text": result["translated_text"],
                    "target_language_code": "en",
                    "first_partial_latency_ms": round(
                        speech_elapsed_ms + float(result["first_partial_latency_ms"]),
                        3,
                    ),
                    "final_latency_ms": round(
                        speech_elapsed_ms + float(result["final_latency_ms"]),
                        3,
                    ),
                    "metadata": {
                        "source_audio": "external_tse_clip_selected_by_causal_diarization",
                        "tse_clip_path": str(clip_path.relative_to(run_dir)),
                        "chunk_index": chunk_index,
                        "chunk_end_s": chunk_end_s,
                        "target_output_end_s": target_output_end_s,
                        "clip_start_s": segment_start_s,
                        "clip_end_s": round(clip_end_s, 6),
                        "segment_final": segment_final,
                        "diarized_speaker_id": partial["diarized_speaker_id"],
                        "diarized_start_s": partial["diarized_start_s"],
                        "diarized_end_s": partial["diarized_end_s"],
                        "diarization_tse_overlap_s": partial["diarization_tse_overlap_s"],
                        "speaker_association_prior": "diarization_tse_mixture_correlation",
                        "final_boundary_tolerance_s": FINAL_BOUNDARY_TOLERANCE_S,
                        "whisper_segment_count": result["whisper_segment_count"],
                        "model_first_partial_latency_ms": result["first_partial_latency_ms"],
                        "model_final_latency_ms": result["final_latency_ms"],
                    },
                }
            )
            if segment_final:
                completed_speakers.add(speaker_id)

        if record_segments:
            records.append(
                {
                    "schema_version": 1,
                    "fixture_id": annotation["fixture_id"],
                    "adapter_id": args.adapter_id,
                    "segments": record_segments,
                    "metadata": {
                        "kind": record_kind,
                        "streaming_mode": "causal_diarization_rolling_external_tse_segments",
                        "chunk_index": chunk_index,
                        "chunk_start_s": 0.0,
                        "chunk_end_s": chunk_end_s,
                        "target_output_end_s": target_output_end_s,
                        "min_clip_s": args.min_clip_s,
                        "model_size": args.model_size,
                        "device": args.device,
                        "compute_type": args.compute_type,
                        "beam_size": args.beam_size,
                        "vad_filter": bool(args.vad_filter),
                        "segmentation_prior": "causal_diarization",
                        "diarization_adapter_id": diarization_adapter_id,
                        "diarization_prediction_source": str(args.diarization_predictions.resolve()),
                        "separation_prior": str(
                            tse_record.get("metadata", {}).get(
                                "kind",
                                "external_target_speaker_extraction",
                            )
                        ),
                        "tse_adapter_id": tse_record["adapter_id"],
                        "tse_prediction_source": str(args.tse_predictions.resolve()),
                        "speaker_association_prior": "diarization_tse_mixture_correlation",
                        "speaker_association": speaker_association,
                        "speaker_association_diagnostics": speaker_association_diagnostics,
                        "uses_oracle_diarization": False,
                        "external_tse_artifacts_oracle_windowed_caveat": True,
                        "final_boundary_tolerance_s": FINAL_BOUNDARY_TOLERANCE_S,
                    },
                }
            )

    final_prediction = final_prediction_from_rolling(annotation, records, args.adapter_id)
    final_prediction["metadata"].update(
        {
            "kind": f"{record_kind}_final",
            "streaming_mode": "causal_diarization_rolling_external_tse_segments",
            "segmentation_prior": "causal_diarization",
            "diarization_adapter_id": diarization_adapter_id,
            "diarization_prediction_source": str(args.diarization_predictions.resolve()),
            "separation_prior": str(
                tse_record.get("metadata", {}).get("kind", "external_target_speaker_extraction")
            ),
            "tse_adapter_id": tse_record["adapter_id"],
            "tse_prediction_source": str(args.tse_predictions.resolve()),
            "speaker_association_prior": "diarization_tse_mixture_correlation",
            "speaker_association": speaker_association,
            "speaker_association_diagnostics": speaker_association_diagnostics,
            "uses_oracle_diarization": False,
            "external_tse_artifacts_oracle_windowed_caveat": True,
            "final_boundary_tolerance_s": FINAL_BOUNDARY_TOLERANCE_S,
        }
    )
    return tse_record, tse_run_dir, diarization_report, records, final_prediction


def causal_quality_gates(
    annotation: dict[str, Any],
    diarization_report: dict[str, Any],
    tse_acceptance: dict[str, Any],
    translation_report: dict[str, Any],
    metrics: dict[str, Any],
    final_prediction: dict[str, Any],
) -> list[dict[str, Any]]:
    translation_summary = translation_report["summary"]
    metadata = final_prediction.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    expected_segments = len(human_segments(annotation))
    max_final_latency_ms = float(translation_summary["max_final_latency_ms"])
    max_first_latency_ms = metrics["max_first_partial_latency_ms"]
    tse_gates_passed = all(
        bool(gate["passed"]) for gate in tse_acceptance["summary"]["quality_gates"]
    )
    return [
        {
            "name": "tse_quality_gates_passed",
            "value": tse_gates_passed,
            "threshold": "target-speaker extraction release-acceptance gates pass",
            "passed": tse_gates_passed,
        },
        {
            "name": "causal_diarization_report_passed",
            "value": diarization_report_passed(diarization_report),
            "threshold": "non-oracle rolling diarization report passes",
            "passed": diarization_report_passed(diarization_report),
        },
        {
            "name": "causal_translation_segmentation_not_oracle",
            "value": {
                "streaming_mode": metadata.get("streaming_mode"),
                "segmentation_prior": metadata.get("segmentation_prior"),
                "diarization_adapter_id": metadata.get("diarization_adapter_id"),
                "uses_oracle_diarization": metadata.get("uses_oracle_diarization"),
            },
            "threshold": "translation driven by causal/non-oracle diarization metadata",
            "passed": (
                metadata.get("streaming_mode")
                == "causal_diarization_rolling_external_tse_segments"
                and metadata.get("segmentation_prior") == "causal_diarization"
                and metadata.get("diarization_adapter_id") != "oracle_diarization_v1"
                and metadata.get("uses_oracle_diarization") is False
            ),
        },
        {
            "name": "whisper_causal_tse_prediction_segment_count",
            "value": int(translation_summary["segment_count"]),
            "threshold": f"{expected_segments} translated speaker clips",
            "passed": int(translation_summary["segment_count"]) == expected_segments,
        },
        {
            "name": "whisper_causal_tse_primary_language_accuracy",
            "value": float(translation_summary["language_primary_accuracy"]),
            "threshold": ">= 0.75 after causal diarization plus accepted TSE",
            "passed": float(translation_summary["language_primary_accuracy"]) >= 0.75,
        },
        {
            "name": "whisper_causal_tse_mean_translation_token_f1",
            "value": float(translation_summary["mean_translation_token_f1"]),
            "threshold": ">= 0.10 after causal diarization plus accepted TSE",
            "passed": float(translation_summary["mean_translation_token_f1"]) >= 0.10,
        },
        {
            "name": "whisper_causal_tse_final_latency_recorded",
            "value": max_final_latency_ms,
            "threshold": "finite positive latency",
            "passed": max_final_latency_ms > 0.0 and max_final_latency_ms < float("inf"),
        },
        {
            "name": "whisper_causal_tse_first_partial_latency_recorded",
            "value": max_first_latency_ms,
            "threshold": "finite first partial latency",
            "passed": max_first_latency_ms is not None and float(max_first_latency_ms) > 0.0,
        },
        {
            "name": "whisper_causal_tse_language_flips_recorded",
            "value": int(metrics["speaker_language_flip_count"]),
            "threshold": "diagnostic count, lower is better",
            "passed": True,
        },
    ]


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    tse_record: dict[str, Any],
    tse_run_dir: Path,
    diarization_report: dict[str, Any],
    rolling_translation_records: list[dict[str, Any]],
    final_translation_prediction: dict[str, Any],
    rolling_translation_prediction_path: Path,
    final_translation_prediction_path: Path,
) -> dict[str, Any]:
    run_dir = rolling_translation_prediction_path.parent
    oracle_translation_path = run_dir / "oracle_translation_predictions.jsonl"
    write_jsonl(build_oracle_translation_records([annotation]), oracle_translation_path)

    tse_report = score_tse_predictions(annotation, output_dir, tse_record, tse_run_dir)
    acceptance_report = tse_acceptance_report(
        annotation,
        output_dir,
        tse_record,
        tse_run_dir,
        tse_report,
    )
    translation_report = score_translation_predictions(annotation, final_translation_prediction)
    fixture_report = analyze_fixture(output_dir, annotation)
    metrics = rolling_metrics(annotation, rolling_translation_records)
    embedded_diarization_report = dict(diarization_report)
    embedded_diarization_report.setdefault(
        "adapter_id",
        final_translation_prediction.get("metadata", {}).get("diarization_adapter_id", ""),
    )
    gates = causal_quality_gates(
        annotation,
        embedded_diarization_report,
        acceptance_report,
        translation_report,
        metrics,
        final_translation_prediction,
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_whisper_after_causal_diarization_target_speaker_extraction",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
            "rolling_metrics": metrics,
        },
        "benchmarks": {
            "diarization": embedded_diarization_report,
            "target_speaker_extraction": tse_report,
            "target_speaker_extraction_acceptance": acceptance_report,
            "language_translation": translation_report,
        },
        "prediction_paths": {
            "diarization": str(diarization_report.get("prediction_path", "")),
            "oracle_language_translation": str(oracle_translation_path),
            "target_speaker_extraction": str(tse_run_dir / "wesep_enrolled_tse_predictions.jsonl"),
            "rolling_model_language_translation": str(rolling_translation_prediction_path),
            "final_model_language_translation": str(final_translation_prediction_path),
        },
        "fixtures": [fixture_report],
        "adapter": {
            "translation": final_translation_prediction["metadata"],
            "target_speaker_extraction": tse_record["metadata"],
        },
        "detractor_loop": {
            "strongest_objection": (
                "This no longer uses oracle diarization windows for streaming translation, but it "
                "still selects from the current accepted external TSE artifact set. Those TSE clips "
                "are fixture-windowed and use clean same-utterance enrollment, so this is not yet "
                "full-session live TSE."
            ),
            "cheapest_falsifying_benchmark": (
                "Run WeSep or the next enrolled TSE adapter directly on each causal diarization "
                "window with held-out enrollment, then compare against this artifact-selection bridge."
            ),
            "fallback_if_falsified": (
                "Keep spoken output behind captions until causal diarization, TSE, translation, TTS, "
                "and room loopback all pass without oracle fixture windows."
            ),
        },
    }


def run_self_test() -> dict[str, Any]:
    source_clip_report = run_source_clip_self_test()
    annotation = {
        "fixture_id": "self_test_causal_tse_translation_fixture",
        "segments": [
            {
                "speaker_id": "speaker_es",
                "source_kind": "human",
                "language_code": "es-419",
                "english_reference_text": "Fellow wrestlers also paid tribute to Luna.",
                "start_s": 0.0,
                "end_s": 2.0,
            },
            {
                "speaker_id": "speaker_en",
                "source_kind": "human",
                "language_code": "en-US",
                "english_reference_text": "Many people do not think about them as dinosaurs.",
                "start_s": 1.0,
                "end_s": 3.0,
            },
        ],
    }
    diarization_report = {"summary": {"passed": True}, "adapter_id": "sortformer_self_test"}
    tse_acceptance = {"summary": {"quality_gates": [{"name": "unit_tse_acceptance", "passed": True}]}}
    final_prediction = {
        "metadata": {
            "streaming_mode": "causal_diarization_rolling_external_tse_segments",
            "segmentation_prior": "causal_diarization",
            "diarization_adapter_id": "sortformer_self_test",
            "uses_oracle_diarization": False,
        }
    }
    translation_report = {
        "summary": {
            "segment_count": 2,
            "language_primary_accuracy": 1.0,
            "mean_translation_token_f1": 0.5,
            "max_final_latency_ms": 2000.0,
        }
    }
    metrics = {
        "max_first_partial_latency_ms": 1000.0,
        "speaker_language_flip_count": 0,
    }
    gates = causal_quality_gates(
        annotation,
        diarization_report,
        tse_acceptance,
        translation_report,
        metrics,
        final_prediction,
    )
    if not all(bool(gate["passed"]) for gate in gates):
        raise RuntimeError("self-test expected causal Whisper-after-TSE gates to pass")
    return {
        "source_clip_contract": source_clip_report["summary"],
        "quality_gates": gates,
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    translation_summary = report["benchmarks"]["language_translation"]["summary"]
    metrics = report["summary"]["rolling_metrics"]
    print(f"whisper causal TSE translation {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  causal diagnostics: "
        f"translation_token_f1={translation_summary['mean_translation_token_f1']} "
        f"language_flips={metrics['speaker_language_flip_count']} "
        f"partials={metrics['partial_prediction_count']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run faster-whisper using causal diarization windows and accepted TSE clips"
    )
    parser.add_argument("--self-test", action="store_true", help="validate causal bridge contract only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--tse-predictions", type=Path, default=DEFAULT_TSE_PREDICTIONS)
    parser.add_argument("--diarization-predictions", type=Path, default=DEFAULT_DIARIZATION_PREDICTIONS)
    parser.add_argument("--diarization-report", type=Path, default=DEFAULT_DIARIZATION_REPORT)
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--vad-filter", action="store_true")
    parser.add_argument("--min-clip-s", type=float, default=DEFAULT_MIN_CLIP_S)
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
        report = run_self_test()
        print("whisper causal target-speaker extraction contract self-test PASS")
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
    rolling_prediction_path = run_dir / "rolling_whisper_causal_tse_translation_predictions.jsonl"
    final_prediction_path = run_dir / "final_whisper_causal_tse_translation_predictions.jsonl"
    (
        tse_record,
        tse_run_dir,
        diarization_report,
        records,
        final_prediction,
    ) = build_causal_whisper_predictions(annotation, output_dir, args)
    if not records:
        raise RuntimeError("causal Whisper-after-TSE produced no prediction records")
    write_jsonl(records, rolling_prediction_path)
    write_jsonl([final_prediction], final_prediction_path)
    report = build_report(
        annotation,
        output_dir,
        tse_record,
        tse_run_dir,
        diarization_report,
        records,
        final_prediction,
        rolling_prediction_path,
        final_prediction_path,
    )
    report_path = args.report.resolve() if args.report else run_dir / "whisper-tse-translation-report.json"
    write_report(report, report_path)
    print(f"wrote causal Whisper-after-TSE predictions to {rolling_prediction_path}")
    print(f"wrote causal Whisper-after-TSE final predictions to {final_prediction_path}")
    print(f"wrote causal Whisper-after-TSE report to {report_path}")
    print_summary(report)
    if report["summary"]["passed"]:
        return 0
    if args.score_warning_only:
        print("Whisper causal TSE translation gates warned, but --score-warning-only was set")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
