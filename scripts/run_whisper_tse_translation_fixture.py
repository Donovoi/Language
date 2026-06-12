#!/usr/bin/env python3
"""Run Whisper on oracle target-speaker extraction clips from the FLEURS fixture."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import soundfile as sf

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    analyze_fixture,
    build_oracle_diarization_records,
    score_diarization_predictions,
    write_jsonl,
    write_report,
)
from benchmark_target_speaker_extraction_fixture import (
    DEFAULT_ADAPTER_ID as DEFAULT_TSE_ADAPTER_ID,
    DEFAULT_PASSTHROUGH_ADAPTER_ID,
    base_fixture_dir,
    build_oracle_tse_records,
    build_passthrough_tse_records,
    overlap_s,
    read_mono,
    read_prediction_record,
    score_tse_predictions,
    self_test as run_tse_self_test,
)
from benchmark_translation_fixture import (
    DEFAULT_FIXTURE_ID,
    DEFAULT_FIXTURE_SET_ID,
    build_oracle_translation_records,
    prepare_multilingual_fixture,
    score_translation_predictions,
)
from run_whisper_translation_fixture import (
    DEFAULT_MODEL_SIZE,
    load_whisper_model,
    run_self_test as run_source_clip_self_test,
    transcribe_segment,
)
from run_whisper_rolling_translation_fixture import (
    chunk_end_times,
    final_prediction_from_rolling,
    human_segments,
    rolling_metrics,
)


DEFAULT_RUN_ID = "whisper-tiny-fleurs-oracle-tse-translation"
DEFAULT_ADAPTER_ID = "faster_whisper_tiny_oracle_tse_translate_v1"
DEFAULT_PASSTHROUGH_RUN_ID = "whisper-tiny-fleurs-mixture-passthrough-tse-translation"
DEFAULT_PASSTHROUGH_ADAPTER_ID = "faster_whisper_tiny_mixture_passthrough_tse_translate_v1"
DEFAULT_EXTERNAL_RUN_ID = "whisper-tiny-fleurs-external-tse-translation"
DEFAULT_EXTERNAL_ADAPTER_ID = "faster_whisper_tiny_external_tse_translate_v1"
DEFAULT_HOP_S = 2.0
DEFAULT_MIN_CLIP_S = 1.0
REAL_MODEL_MIN_SEGMENT_SNR_DB = 0.0
REAL_MODEL_MAX_LEVEL_ERROR_DB = 1.0


def expected_human_segment_count(annotation: dict[str, Any]) -> int:
    return sum(1 for segment in annotation["segments"] if segment.get("source_kind") == "human")


def write_oracle_tse_slice(
    annotation: dict[str, Any],
    output_dir: Path,
    source_segment: dict[str, Any],
    *,
    clip_end_s: float,
    clip_path: Path,
) -> None:
    fixture_path = base_fixture_dir(output_dir, annotation)
    stem_audio, sample_rate_hz = read_mono(fixture_path / source_segment["stem_path"])
    start_sample = int(source_segment["start_sample"])
    end_sample = min(
        int(source_segment["end_sample"]),
        int(round(clip_end_s * sample_rate_hz)),
    )
    if end_sample <= start_sample:
        raise ValueError("oracle TSE slice end must be after start")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, stem_audio[start_sample:end_sample], sample_rate_hz, subtype=PCM_SUBTYPE)


def write_passthrough_tse_slice(
    annotation: dict[str, Any],
    output_dir: Path,
    source_segment: dict[str, Any],
    *,
    clip_end_s: float,
    clip_path: Path,
) -> None:
    fixture_path = base_fixture_dir(output_dir, annotation)
    mix_audio, sample_rate_hz = read_mono(fixture_path / annotation["mix_path"])
    start_sample = int(source_segment["start_sample"])
    end_sample = min(
        int(source_segment["end_sample"]),
        int(round(clip_end_s * sample_rate_hz)),
    )
    if end_sample <= start_sample:
        raise ValueError("passthrough TSE slice end must be after start")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, mix_audio[start_sample:end_sample], sample_rate_hz, subtype=PCM_SUBTYPE)


def write_tse_slice(
    annotation: dict[str, Any],
    output_dir: Path,
    source_segment: dict[str, Any],
    *,
    clip_end_s: float,
    clip_path: Path,
    tse_mode: str,
) -> None:
    if tse_mode == "oracle":
        write_oracle_tse_slice(
            annotation,
            output_dir,
            source_segment,
            clip_end_s=clip_end_s,
            clip_path=clip_path,
        )
        return
    if tse_mode == "passthrough":
        write_passthrough_tse_slice(
            annotation,
            output_dir,
            source_segment,
            clip_end_s=clip_end_s,
            clip_path=clip_path,
        )
        return
    raise ValueError(f"unsupported TSE mode: {tse_mode}")


def tse_segment_by_speaker(tse_record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_speaker: dict[str, dict[str, Any]] = {}
    for segment in tse_record.get("segments", []):
        speaker_id = str(segment.get("speaker_id", segment.get("target_speaker_id", "")))
        if speaker_id:
            by_speaker[speaker_id] = segment
    return by_speaker


def write_external_tse_slice(
    tse_run_dir: Path,
    prediction_segment: dict[str, Any],
    *,
    clip_duration_s: float,
    clip_path: Path,
) -> None:
    extracted_path = tse_run_dir / str(prediction_segment["extracted_audio_path"])
    extracted_audio, sample_rate_hz = read_mono(extracted_path)
    end_sample = min(
        int(extracted_audio.shape[0]),
        int(round(clip_duration_s * sample_rate_hz)),
    )
    if end_sample <= 0:
        raise ValueError("external TSE slice end must be after start")
    clip_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(clip_path, extracted_audio[:end_sample], sample_rate_hz, subtype=PCM_SUBTYPE)


def build_whisper_tse_predictions(
    annotation: dict[str, Any],
    output_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path, list[dict[str, Any]], dict[str, Any]]:
    run_dir = output_dir / "runs" / args.run_id
    external_segments: dict[str, dict[str, Any]] = {}
    if args.tse_mode == "oracle":
        tse_records = build_oracle_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=args.tse_adapter_id,
        )
        rolling_clip_dir_name = "oracle_tse_rolling_clips"
        source_audio_kind = "oracle_tse_rolling_clip"
        separation_prior = "oracle_target_speaker_extraction"
        record_kind = "whisper_after_oracle_tse_rolling_translation"
    elif args.tse_mode == "passthrough":
        tse_records = build_passthrough_tse_records(
            annotation,
            output_dir,
            run_dir,
            adapter_id=args.tse_adapter_id,
        )
        rolling_clip_dir_name = "passthrough_tse_rolling_clips"
        source_audio_kind = "mixture_passthrough_tse_rolling_clip"
        separation_prior = "mixture_passthrough_target_speaker_extraction"
        record_kind = "whisper_after_mixture_passthrough_tse_rolling_translation"
    elif args.tse_mode == "external":
        if args.tse_predictions is None:
            raise ValueError("--tse-mode external requires --tse-predictions")
        tse_record = read_prediction_record(args.tse_predictions.resolve())
        tse_records = [tse_record]
        external_segments = tse_segment_by_speaker(tse_record)
        rolling_clip_dir_name = "external_tse_rolling_clips"
        source_audio_kind = "external_tse_rolling_clip"
        separation_prior = str(
            tse_record.get("metadata", {}).get("kind", "external_target_speaker_extraction")
        )
        record_kind = "whisper_after_external_tse_rolling_translation"
    else:
        raise ValueError(f"unsupported TSE mode: {args.tse_mode}")
    tse_record = tse_records[0]
    tse_run_dir = args.tse_predictions.resolve().parent if args.tse_mode == "external" else run_dir
    model = load_whisper_model(args.model_size, args.device, args.compute_type)
    records: list[dict[str, Any]] = []
    completed_speakers: set[str] = set()
    clip_dir = run_dir / rolling_clip_dir_name

    for chunk_index, chunk_end_s in enumerate(
        chunk_end_times(float(annotation["duration_s"]), args.hop_s)
    ):
        record_segments: list[dict[str, Any]] = []
        for source_segment in human_segments(annotation):
            speaker_id = str(source_segment["speaker_id"])
            if speaker_id in completed_speakers:
                continue
            segment_start_s = float(source_segment["start_s"])
            segment_end_s = float(source_segment["end_s"])
            if chunk_end_s <= segment_start_s:
                continue
            clip_end_s = min(segment_end_s, chunk_end_s)
            clip_duration_s = clip_end_s - segment_start_s
            segment_final = chunk_end_s >= segment_end_s
            if clip_duration_s < args.min_clip_s and not segment_final:
                continue

            clip_path = clip_dir / f"chunk_{chunk_index:03d}_{speaker_id}.wav"
            if args.tse_mode == "external":
                prediction_segment = external_segments.get(speaker_id)
                if prediction_segment is None:
                    continue
                write_external_tse_slice(
                    tse_run_dir,
                    prediction_segment,
                    clip_duration_s=clip_duration_s,
                    clip_path=clip_path,
                )
            else:
                write_tse_slice(
                    annotation,
                    output_dir,
                    source_segment,
                    clip_end_s=clip_end_s,
                    clip_path=clip_path,
                    tse_mode=args.tse_mode,
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
                    "speaker_id": source_segment["speaker_id"],
                    "start_s": source_segment["start_s"],
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
                        "source_audio": source_audio_kind,
                        "tse_clip_path": str(clip_path.relative_to(run_dir)),
                        "overlap_s": overlap_s(annotation, source_segment),
                        "chunk_index": chunk_index,
                        "chunk_end_s": chunk_end_s,
                        "clip_start_s": source_segment["start_s"],
                        "clip_end_s": round(clip_end_s, 6),
                        "segment_truth_end_s": source_segment["end_s"],
                        "segment_final": segment_final,
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
                        "streaming_mode": f"oracle_diarization_rolling_{args.tse_mode}_tse_segments",
                        "chunk_index": chunk_index,
                        "chunk_start_s": 0.0,
                        "chunk_end_s": chunk_end_s,
                        "hop_s": args.hop_s,
                        "min_clip_s": args.min_clip_s,
                        "model_size": args.model_size,
                        "device": args.device,
                        "compute_type": args.compute_type,
                        "beam_size": args.beam_size,
                        "vad_filter": bool(args.vad_filter),
                        "segmentation_prior": "oracle_diarization",
                        "separation_prior": separation_prior,
                        "tse_adapter_id": tse_record["adapter_id"],
                        "tse_prediction_source": (
                            str(args.tse_predictions.resolve())
                            if args.tse_mode == "external" and args.tse_predictions
                            else None
                        ),
                    },
                }
            )

    final_prediction = final_prediction_from_rolling(annotation, records, args.adapter_id)
    final_prediction["metadata"].update(
        {
            "kind": f"{record_kind}_final",
            "streaming_mode": f"oracle_diarization_rolling_{args.tse_mode}_tse_segments",
            "segmentation_prior": "oracle_diarization",
            "diarization_adapter_id": "oracle_diarization_v1",
            "separation_prior": separation_prior,
            "tse_adapter_id": tse_record["adapter_id"],
            "tse_prediction_source": (
                str(args.tse_predictions.resolve())
                if args.tse_mode == "external" and args.tse_predictions
                else None
            ),
        }
    )
    return tse_record, tse_run_dir, records, final_prediction


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
    oracle_gates_passed = all(bool(gate["passed"]) for gate in tse_summary["quality_gates"])
    if bool(metadata.get("oracle_upper_bound")):
        gates = [
            {
                "name": "tse_acceptance_oracle_quality_passed",
                "value": oracle_gates_passed,
                "threshold": "oracle upper-bound TSE quality gates pass",
                "passed": oracle_gates_passed,
            }
        ]
        return {"summary": {"passed": oracle_gates_passed, "quality_gates": gates}}

    passthrough_run_dir = tse_run_dir / "baselines" / "translation_acceptance_passthrough"
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


def downstream_quality_gates(
    annotation: dict[str, Any],
    tse_report: dict[str, Any],
    tse_acceptance_report: dict[str, Any],
    translation_report: dict[str, Any],
    metrics: dict[str, Any],
    *,
    hop_s: float,
) -> list[dict[str, Any]]:
    expected_segments = expected_human_segment_count(annotation)
    translation_summary = translation_report["summary"]
    max_final_latency_ms = float(translation_summary["max_final_latency_ms"])
    first_latency_threshold_ms = round(max(1.0, hop_s) * 1000.0 + 120000.0, 3)
    max_first_latency_ms = metrics["max_first_partial_latency_ms"]
    tse_gates_passed = all(
        bool(gate["passed"]) for gate in tse_acceptance_report["summary"]["quality_gates"]
    )
    return [
        {
            "name": "tse_quality_gates_passed",
            "value": tse_gates_passed,
            "threshold": "target-speaker extraction release-acceptance gates pass",
            "passed": tse_gates_passed,
        },
        {
            "name": "whisper_tse_prediction_segment_count",
            "value": int(translation_summary["segment_count"]),
            "threshold": f"{expected_segments} translated speaker clips",
            "passed": int(translation_summary["segment_count"]) == expected_segments,
        },
        {
            "name": "whisper_tse_primary_language_accuracy",
            "value": float(translation_summary["language_primary_accuracy"]),
            "threshold": ">= 0.75 after oracle target-speaker extraction",
            "passed": float(translation_summary["language_primary_accuracy"]) >= 0.75,
        },
        {
            "name": "whisper_tse_mean_translation_token_f1",
            "value": float(translation_summary["mean_translation_token_f1"]),
            "threshold": ">= 0.10 after oracle target-speaker extraction",
            "passed": float(translation_summary["mean_translation_token_f1"]) >= 0.10,
        },
        {
            "name": "whisper_tse_final_latency_recorded",
            "value": max_final_latency_ms,
            "threshold": "finite positive latency",
            "passed": max_final_latency_ms > 0.0 and max_final_latency_ms < float("inf"),
        },
        {
            "name": "whisper_tse_first_partial_latency_recorded",
            "value": max_first_latency_ms,
            "threshold": f"finite and <= {first_latency_threshold_ms} ms",
            "passed": (
                max_first_latency_ms is not None
                and float(max_first_latency_ms) <= first_latency_threshold_ms
            ),
        },
        {
            "name": "whisper_tse_final_latency_smoke_budget",
            "value": round(max_final_latency_ms, 3),
            "threshold": "<= 120000 ms per extracted clip on CPU",
            "passed": max_final_latency_ms <= 120000.0,
        },
        {
            "name": "whisper_tse_language_flips_recorded",
            "value": int(metrics["speaker_language_flip_count"]),
            "threshold": "diagnostic count, lower is better",
            "passed": True,
        },
    ]


def passthrough_warning_expected(report: dict[str, Any]) -> bool:
    gate_map = {str(gate["name"]): bool(gate["passed"]) for gate in report["summary"]["quality_gates"]}
    tse_gates_passed = gate_map.get("tse_quality_gates_passed")
    translation_f1_passed = gate_map.get("whisper_tse_mean_translation_token_f1")
    return tse_gates_passed is False and translation_f1_passed is False


def build_report(
    annotation: dict[str, Any],
    output_dir: Path,
    tse_record: dict[str, Any],
    tse_run_dir: Path,
    rolling_translation_records: list[dict[str, Any]],
    final_translation_prediction: dict[str, Any],
    tse_prediction_path: Path,
    rolling_translation_prediction_path: Path,
    final_translation_prediction_path: Path,
) -> dict[str, Any]:
    run_dir = tse_prediction_path.parent
    oracle_diarization_path = run_dir / "oracle_diarization_predictions.jsonl"
    oracle_translation_path = run_dir / "oracle_translation_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records([annotation]), oracle_diarization_path)
    write_jsonl(build_oracle_translation_records([annotation]), oracle_translation_path)

    diarization_report = score_diarization_predictions(
        [annotation],
        oracle_diarization_path,
        strict_oracle=True,
    )
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
    gates = downstream_quality_gates(
        annotation,
        tse_report,
        acceptance_report,
        translation_report,
        metrics,
        hop_s=float(rolling_translation_records[0]["metadata"]["hop_s"]),
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_whisper_after_target_speaker_extraction",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
            "rolling_metrics": metrics,
        },
        "benchmarks": {
            "diarization": diarization_report,
            "target_speaker_extraction": tse_report,
            "target_speaker_extraction_acceptance": acceptance_report,
            "language_translation": translation_report,
        },
        "prediction_paths": {
            "diarization": str(oracle_diarization_path),
            "oracle_language_translation": str(oracle_translation_path),
            "target_speaker_extraction": str(tse_prediction_path),
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
                "This reuses the TSE artifact contract for oracle, passthrough, and external "
                "separator checks. External separators may still use oracle segment boundaries "
                "or oracle stream assignment, so downstream Whisper gains do not prove speaker "
                "enrollment, microphone capture, causal streaming, or source suppression."
            ),
            "cheapest_falsifying_benchmark": (
                "Require a real TSE model or blind separator to beat the mixed-slice baseline on "
                "Whisper token F1 and language stability without unacceptable latency."
            ),
            "fallback_if_falsified": (
                "Keep separation disabled unless overlap is detected or a speaker is locked, and keep "
                "spoken playback behind captions until real TSE improves downstream translation."
            ),
        },
    }


def run_self_test() -> dict[str, Any]:
    tse_self_test = run_tse_self_test()
    source_clip_self_test = run_source_clip_self_test()
    annotation = {
        "fixture_id": "self_test_whisper_tse_translation_fixture",
        "segments": [
            {"speaker_id": "speaker_es", "source_kind": "human"},
            {"speaker_id": "speaker_en", "source_kind": "human"},
        ],
    }
    tse_report = {"summary": tse_self_test["oracle_summary"]}
    tse_acceptance = {"summary": {"quality_gates": [{"name": "unit_tse_acceptance", "passed": True}]}}
    translation_report = {"summary": source_clip_self_test["summary"]}
    metrics = {
        "max_first_partial_latency_ms": 1000.0,
        "speaker_language_flip_count": 0,
    }
    gates = downstream_quality_gates(
        annotation,
        tse_report,
        tse_acceptance,
        translation_report,
        metrics,
        hop_s=1.0,
    )
    if not all(bool(gate["passed"]) for gate in gates):
        raise RuntimeError("self-test expected Whisper-after-TSE gates to pass")
    return {
        "source_clip_contract": source_clip_self_test["summary"],
        "tse_contract": tse_self_test["oracle_summary"],
        "quality_gates": gates,
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "WARN"
    translation_summary = report["benchmarks"]["language_translation"]["summary"]
    tse_summary = report["benchmarks"]["target_speaker_extraction"]["summary"]
    metrics = report["summary"]["rolling_metrics"]
    print(f"whisper after target-speaker extraction {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "WARN"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  downstream diagnostics: "
        f"tse_min_snr_db={tse_summary['min_segment_snr_db']} "
        f"translation_token_f1={translation_summary['mean_translation_token_f1']} "
        f"language_flips={metrics['speaker_language_flip_count']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run faster-whisper on oracle TSE FLEURS clips")
    parser.add_argument("--self-test", action="store_true", help="validate TSE plus translation contract only")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
    parser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--adapter-id", default=None)
    parser.add_argument("--tse-adapter-id", default=None)
    parser.add_argument("--tse-mode", choices=["oracle", "passthrough", "external"], default="oracle")
    parser.add_argument(
        "--tse-predictions",
        type=Path,
        default=None,
        help="external TSE JSONL to use when --tse-mode external",
    )
    parser.add_argument("--model-size", default=DEFAULT_MODEL_SIZE)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute-type", default="int8")
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--vad-filter", action="store_true")
    parser.add_argument("--hop-s", type=float, default=DEFAULT_HOP_S)
    parser.add_argument("--min-clip-s", type=float, default=DEFAULT_MIN_CLIP_S)
    parser.add_argument("--max-stream-mb", type=int, default=64)
    parser.add_argument(
        "--expect-passthrough-warning",
        action="store_true",
        help="exit 0 only when passthrough TSE is caught as a lower-bound warning",
    )
    parser.add_argument(
        "--score-warning-only",
        action="store_true",
        help="write measured report but exit 0 even when model quality gates warn",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.run_id is None:
        args.run_id = (
            DEFAULT_PASSTHROUGH_RUN_ID
            if args.tse_mode == "passthrough"
            else DEFAULT_EXTERNAL_RUN_ID
            if args.tse_mode == "external"
            else DEFAULT_RUN_ID
        )
    if args.adapter_id is None:
        args.adapter_id = (
            DEFAULT_PASSTHROUGH_ADAPTER_ID
            if args.tse_mode == "passthrough"
            else DEFAULT_EXTERNAL_ADAPTER_ID
            if args.tse_mode == "external"
            else DEFAULT_ADAPTER_ID
        )
    if args.tse_adapter_id is None:
        args.tse_adapter_id = (
            DEFAULT_PASSTHROUGH_ADAPTER_ID
            if args.tse_mode == "passthrough"
            else DEFAULT_TSE_ADAPTER_ID
        )
    if args.tse_mode == "external" and args.tse_predictions is None:
        raise SystemExit("--tse-mode external requires --tse-predictions")
    if args.self_test:
        report = run_self_test()
        print("whisper target-speaker extraction contract self-test PASS")
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
    if args.tse_mode == "external":
        tse_prediction_filename = "external_tse_predictions.jsonl"
    elif args.tse_mode == "passthrough":
        tse_prediction_filename = "passthrough_tse_predictions.jsonl"
    else:
        tse_prediction_filename = "oracle_tse_predictions.jsonl"
    tse_prediction_path = run_dir / tse_prediction_filename
    rolling_translation_prediction_path = run_dir / "rolling_whisper_tse_translation_predictions.jsonl"
    final_translation_prediction_path = run_dir / "final_whisper_tse_translation_predictions.jsonl"
    tse_record, tse_run_dir, rolling_translation_records, final_translation_prediction = (
        build_whisper_tse_predictions(annotation, output_dir, args)
    )
    if not rolling_translation_records:
        raise RuntimeError("Whisper after oracle TSE produced no rolling prediction records")
    write_jsonl([tse_record], tse_prediction_path)
    write_jsonl(rolling_translation_records, rolling_translation_prediction_path)
    write_jsonl([final_translation_prediction], final_translation_prediction_path)
    report = build_report(
        annotation,
        output_dir,
        tse_record,
        tse_run_dir,
        rolling_translation_records,
        final_translation_prediction,
        tse_prediction_path,
        rolling_translation_prediction_path,
        final_translation_prediction_path,
    )
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "whisper-tse-translation-report.json"
    )
    write_report(report, report_path)
    print(f"wrote {args.tse_mode} TSE predictions to {tse_prediction_path}")
    print(f"wrote rolling Whisper TSE translation predictions to {rolling_translation_prediction_path}")
    print(f"wrote final Whisper TSE translation predictions to {final_translation_prediction_path}")
    print(f"wrote Whisper TSE translation report to {report_path}")
    print_summary(report)
    if report["summary"]["passed"]:
        if args.expect_passthrough_warning:
            print("passthrough TSE unexpectedly passed all gates")
            return 1
        return 0
    if args.expect_passthrough_warning:
        if passthrough_warning_expected(report):
            print("passthrough TSE translation failed expected quality gates")
            return 0
        print("passthrough TSE translation did not fail the expected gates")
        return 1
    return 0 if args.score_warning_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
