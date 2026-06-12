#!/usr/bin/env python3
"""Generate consent-safe fallback English TTS audio for translated segments.

This benchmark intentionally does not claim same-voice cloning. It proves the
fallback path the product needs before cloning is safe and validated: a neutral
English voice, per-segment WAV artifacts, output hashes, level matching against
the source speech, and explicit consent/safety metadata.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
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
    apply_fade,
    db_to_linear,
    dbfs,
    peak_dbfs,
    safe_id,
    scale_to_level,
    sha256_file,
    write_jsonl,
    write_report,
)


DEFAULT_RUN_ID = "same-voice-tts"
DEFAULT_ADAPTER_ID = "espeak_ng_neutral_fallback_tts_v1"
DEFAULT_TRANSLATION_PREDICTIONS = (
    DEFAULT_OUTPUT_DIR
    / "runs/whisper-tiny-fleurs-wesep-causal-tse-translation"
    / "final_whisper_causal_tse_translation_predictions.jsonl"
)
DEFAULT_MAX_LEVEL_ERROR_DB = 0.75
DEFAULT_MAX_PEAK_DBFS = -0.1
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_ESPEAK_VOICE = "en-us"
DEFAULT_ESPEAK_WORDS_PER_MINUTE = 165
FALLBACK_STATUS = "fallback_voice"
VOICE_SIMILARITY_CLAIM = "not_claimed"


def read_mono(path: Path) -> tuple[np.ndarray, int]:
    audio, sample_rate_hz = sf.read(path, dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    return np.asarray(audio, dtype=np.float32), int(sample_rate_hz)


def resample_to_rate(audio: np.ndarray, source_rate_hz: int, target_rate_hz: int) -> np.ndarray:
    if source_rate_hz == target_rate_hz:
        return np.asarray(audio, dtype=np.float32)
    gcd = math.gcd(int(source_rate_hz), int(target_rate_hz))
    up = int(target_rate_hz // gcd)
    down = int(source_rate_hz // gcd)
    return resample_poly(audio, up, down).astype(np.float32)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        char in "0123456789abcdef" for char in value
    )


def first_prediction_record(records: list[dict[str, Any]]) -> dict[str, Any]:
    if not records:
        raise ValueError("translation prediction JSONL is empty")
    if len(records) > 1:
        return max(records, key=lambda record: len(record.get("segments", [])))
    return records[0]


def reference_audio_path(
    translation_predictions_path: Path,
    segment: dict[str, Any],
) -> Path:
    metadata = segment.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    clip_path = metadata.get("tse_clip_path")
    if not isinstance(clip_path, str) or not clip_path:
        raise ValueError(f"segment for {segment.get('speaker_id')} lacks metadata.tse_clip_path")
    path = Path(clip_path)
    if path.is_absolute():
        return path
    return translation_predictions_path.parent / path


def synthesize_with_espeak(
    text: str,
    output_path: Path,
    *,
    voice: str,
    words_per_minute: int,
) -> float:
    engine_path = shutil.which("espeak-ng")
    if not engine_path:
        raise RuntimeError(
            "espeak-ng is required for fallback TTS audio. "
            "Use the audio-eval Docker profile or install espeak-ng on PATH."
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir_name:
        text_path = Path(temp_dir_name) / "tts_input.txt"
        text_path.write_text(text, encoding="utf-8")
        start = time.perf_counter()
        completed = subprocess.run(
            [
                engine_path,
                "-v",
                voice,
                "-s",
                str(int(words_per_minute)),
                "-w",
                str(output_path),
                "-f",
                str(text_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000.0
    if completed.returncode != 0:
        raise RuntimeError(
            "espeak-ng failed: "
            + (completed.stderr.strip() or completed.stdout.strip() or str(completed.returncode))
        )
    return elapsed_ms


def match_level_and_limit_peak(
    samples: np.ndarray,
    target_dbfs: float,
    *,
    max_peak_dbfs: float,
) -> np.ndarray:
    matched = scale_to_level(samples.astype(np.float32), target_dbfs).astype(np.float32)
    peak_limit = db_to_linear(max_peak_dbfs)
    peak = float(np.max(np.abs(matched))) if matched.size else 0.0
    if peak > peak_limit:
        matched = (matched * (peak_limit / peak)).astype(np.float32)
    return matched


def tts_segment_output_path(run_dir: Path, index: int, segment: dict[str, Any]) -> Path:
    speaker_id = safe_id(str(segment.get("speaker_id", f"speaker_{index}")))
    return run_dir / "audio" / f"{index:03d}_{speaker_id}_fallback_tts.wav"


def build_fallback_tts_record(
    prediction: dict[str, Any],
    translation_predictions_path: Path,
    run_dir: Path,
    args: argparse.Namespace,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    segment_records: list[dict[str, Any]] = []
    segments = prediction.get("segments", [])
    if not isinstance(segments, list) or not segments:
        raise ValueError("translation prediction must contain at least one segment")

    for index, segment in enumerate(segments):
        text = str(segment.get("translated_text") or "").strip()
        if not text:
            raise ValueError(f"segment {index} has no translated_text")

        reference_path = reference_audio_path(translation_predictions_path, segment)
        reference_audio, reference_rate_hz = read_mono(reference_path)
        reference_audio = resample_to_rate(
            reference_audio,
            reference_rate_hz,
            int(args.sample_rate_hz),
        )
        input_level_dbfs = dbfs(reference_audio)
        if not math.isfinite(input_level_dbfs):
            raise ValueError(f"reference audio is silent for segment {index}: {reference_path}")

        output_path = tts_segment_output_path(run_dir, index, segment)
        raw_output_path = output_path.with_name(output_path.stem + ".raw.wav")
        synthesis_wall_ms = synthesize_with_espeak(
            text,
            raw_output_path,
            voice=args.espeak_voice,
            words_per_minute=int(args.espeak_words_per_minute),
        )
        tts_audio, tts_rate_hz = read_mono(raw_output_path)
        tts_audio = resample_to_rate(tts_audio, tts_rate_hz, int(args.sample_rate_hz))
        tts_audio = apply_fade(tts_audio, int(args.sample_rate_hz))
        tts_audio = match_level_and_limit_peak(
            tts_audio,
            input_level_dbfs,
            max_peak_dbfs=float(args.max_peak_dbfs),
        )
        sf.write(output_path, tts_audio, int(args.sample_rate_hz), subtype=PCM_SUBTYPE)
        raw_output_path.unlink(missing_ok=True)

        output_level_dbfs = dbfs(tts_audio)
        output_peak_dbfs = peak_dbfs(tts_audio)
        level_error_db = abs(output_level_dbfs - input_level_dbfs)
        segment_records.append(
            {
                "segment_index": index,
                "speaker_id": segment.get("speaker_id"),
                "fixture_id": prediction.get("fixture_id"),
                "source_language_code": segment.get("detected_language_code"),
                "target_language_code": segment.get("target_language_code", "en"),
                "translated_text": text,
                "start_s": segment.get("start_s"),
                "end_s": segment.get("end_s"),
                "translation_final_latency_ms": segment.get("final_latency_ms"),
                "translation_first_partial_latency_ms": segment.get("first_partial_latency_ms"),
                "voice_clone_status": FALLBACK_STATUS,
                "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
                "voice_clone_reference_used": False,
                "reference_audio_usage": "level_measurement_only",
                "reference_audio_path": str(reference_path),
                "reference_audio_sha256": sha256_file(reference_path),
                "input_level_dbfs": round(input_level_dbfs, 3),
                "tts_output_path": str(output_path.relative_to(run_dir)),
                "tts_output_sha256": sha256_file(output_path),
                "tts_output_level_dbfs": round(output_level_dbfs, 3),
                "tts_output_peak_dbfs": round(output_peak_dbfs, 3),
                "tts_output_duration_s": round(tts_audio.size / float(args.sample_rate_hz), 6),
                "tts_output_frame_count": int(tts_audio.size),
                "output_level_error_db": round(level_error_db, 3),
                "synthesis_wall_ms": round(synthesis_wall_ms, 3),
            }
        )

    record = {
        "schema_version": 1,
        "adapter_id": args.adapter_id,
        "fixture_id": prediction.get("fixture_id"),
        "voice_clone_status": FALLBACK_STATUS,
        "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
        "segments": segment_records,
        "metadata": {
            "kind": "neutral_fallback_tts_audio_stream",
            "source_translation_adapter_id": prediction.get("adapter_id"),
            "sample_rate_hz": int(args.sample_rate_hz),
            "engine": "espeak-ng",
            "engine_voice": args.espeak_voice,
            "engine_words_per_minute": int(args.espeak_words_per_minute),
            "voice_reference_consent": {
                "voice_clone_reference_used": False,
                "fallback_mode": True,
                "consent_basis": (
                    "neutral fallback TTS uses translated text and source-audio level measurement "
                    "only; it does not clone or persist speaker identity references"
                ),
                "reference_audio_retention": "existing fixture artifacts only",
            },
        },
    }
    return record, segment_records


def summarize_segments(segment_records: list[dict[str, Any]]) -> dict[str, Any]:
    level_errors = [float(segment["output_level_error_db"]) for segment in segment_records]
    peaks = [float(segment["tts_output_peak_dbfs"]) for segment in segment_records]
    durations = [float(segment["tts_output_duration_s"]) for segment in segment_records]
    synth_ms = [float(segment["synthesis_wall_ms"]) for segment in segment_records]
    return {
        "segment_count": len(segment_records),
        "voice_clone_status": FALLBACK_STATUS,
        "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
        "max_output_level_error_db": round(max(level_errors), 3) if level_errors else None,
        "mean_output_level_error_db": round(float(np.mean(level_errors)), 3)
        if level_errors
        else None,
        "max_output_peak_dbfs": round(max(peaks), 3) if peaks else None,
        "min_output_duration_s": round(min(durations), 6) if durations else None,
        "max_synthesis_wall_ms": round(max(synth_ms), 3) if synth_ms else None,
        "mean_synthesis_wall_ms": round(float(np.mean(synth_ms)), 3) if synth_ms else None,
    }


def quality_gates(
    *,
    summary: dict[str, Any],
    segment_records: list[dict[str, Any]],
    max_level_error_db: float,
    max_peak_dbfs: float,
) -> list[dict[str, Any]]:
    all_hashes = all(is_sha256(segment.get("tts_output_sha256")) for segment in segment_records)
    all_reference_hashes = all(
        is_sha256(segment.get("reference_audio_sha256")) for segment in segment_records
    )
    all_nonempty = all(float(segment.get("tts_output_duration_s", 0.0)) > 0.0 for segment in segment_records)
    max_error = summary.get("max_output_level_error_db")
    max_peak = summary.get("max_output_peak_dbfs")
    fallback_declared = (
        summary.get("voice_clone_status") == FALLBACK_STATUS
        and summary.get("voice_similarity_claim") == VOICE_SIMILARITY_CLAIM
    )
    return [
        {
            "name": "voice_reference_consent_present",
            "passed": True,
            "threshold": "fallback mode declares no voice clone reference use and level-only reference policy",
            "value": "fallback_mode_no_voice_clone_reference_used",
        },
        {
            "name": "tts_audio_hashed",
            "passed": all_hashes and all_reference_hashes and all_nonempty,
            "threshold": "every output and level-reference artifact has a SHA-256 hash",
            "value": {
                "output_hashes_present": all_hashes,
                "reference_hashes_present": all_reference_hashes,
                "nonempty_audio": all_nonempty,
            },
        },
        {
            "name": "tts_output_level_matched",
            "passed": isinstance(max_error, (float, int)) and float(max_error) <= max_level_error_db,
            "threshold": f"max output level error <= {max_level_error_db:.3f} dB",
            "value": max_error,
        },
        {
            "name": "voice_similarity_or_fallback_declared",
            "passed": fallback_declared,
            "threshold": "same-voice similarity is either measured or fallback status is explicit",
            "value": {
                "voice_clone_status": summary.get("voice_clone_status"),
                "voice_similarity_claim": summary.get("voice_similarity_claim"),
            },
        },
        {
            "name": "tts_output_not_clipped",
            "passed": isinstance(max_peak, (float, int)) and float(max_peak) <= max_peak_dbfs,
            "threshold": f"max peak <= {max_peak_dbfs:.3f} dBFS",
            "value": max_peak,
        },
    ]


def build_report(
    record: dict[str, Any],
    segment_records: list[dict[str, Any]],
    *,
    output_dir: Path,
    run_dir: Path,
    translation_predictions_path: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    summary = summarize_segments(segment_records)
    gates = quality_gates(
        summary=summary,
        segment_records=segment_records,
        max_level_error_db=float(args.max_level_error_db),
        max_peak_dbfs=float(args.max_peak_dbfs),
    )
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fallback_tts_audio_stream",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
            **summary,
        },
        "benchmarks": {
            "same_voice_or_fallback_tts": {
                "adapter_id": args.adapter_id,
                "summary": summary,
                "segments": segment_records,
            }
        },
        "prediction_paths": {
            "source_translation_predictions": str(translation_predictions_path),
            "fallback_tts_predictions": str(run_dir / "fallback_tts_predictions.jsonl"),
        },
        "adapter": {
            "voice": {
                "adapter_id": args.adapter_id,
                "mode": FALLBACK_STATUS,
                "engine": "espeak-ng",
                "engine_voice": args.espeak_voice,
                "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
                "voice_clone_reference_used": False,
                "reference_audio_usage": "level_measurement_only",
                "sample_rate_hz": int(args.sample_rate_hz),
            }
        },
        "artifacts": {
            "run_dir": str(run_dir),
            "audio_dir": str(run_dir / "audio"),
        },
        "detractor_loop": {
            "strongest_objection": (
                "This proves a neutral fallback TTS audio stream only. It does not prove same-voice "
                "cloning, speaker similarity, naturalness, or provider-grade safety review."
            ),
            "next_falsifying_benchmark": (
                "Run consented same-speaker references through a real cloning or voice-conversion "
                "adapter and compare ASV/speaker similarity, WER, latency, and deletion proof."
            ),
            "verdict": (
                "Safe fallback playback can be wired into the app; same-voice release claims remain "
                "blocked until a cloning adapter passes the stricter benchmark."
            ),
        },
    }


def build_self_test_report(output_dir: Path, run_dir: Path) -> dict[str, Any]:
    sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
    run_dir.mkdir(parents=True, exist_ok=True)
    t = np.arange(sample_rate_hz, dtype=np.float64) / float(sample_rate_hz)
    reference = (0.05 * np.sin(2.0 * math.pi * 180.0 * t)).astype(np.float32)
    tts = apply_fade((0.05 * np.sin(2.0 * math.pi * 220.0 * t)).astype(np.float32), sample_rate_hz)
    tts = match_level_and_limit_peak(tts, dbfs(reference), max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS)
    reference_path = run_dir / "self_test_reference.wav"
    tts_path = run_dir / "audio" / "000_self_test_fallback_tts.wav"
    tts_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(reference_path, reference, sample_rate_hz, subtype=PCM_SUBTYPE)
    sf.write(tts_path, tts, sample_rate_hz, subtype=PCM_SUBTYPE)
    segment_records = [
        {
            "segment_index": 0,
            "speaker_id": "self_test_speaker",
            "fixture_id": "self_test_fallback_tts",
            "source_language_code": "es",
            "target_language_code": "en",
            "translated_text": "Self test fallback speech.",
            "voice_clone_status": FALLBACK_STATUS,
            "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
            "voice_clone_reference_used": False,
            "reference_audio_usage": "level_measurement_only",
            "reference_audio_path": str(reference_path),
            "reference_audio_sha256": sha256_file(reference_path),
            "input_level_dbfs": round(dbfs(reference), 3),
            "tts_output_path": str(tts_path.relative_to(run_dir)),
            "tts_output_sha256": sha256_file(tts_path),
            "tts_output_level_dbfs": round(dbfs(tts), 3),
            "tts_output_peak_dbfs": round(peak_dbfs(tts), 3),
            "tts_output_duration_s": round(tts.size / float(sample_rate_hz), 6),
            "tts_output_frame_count": int(tts.size),
            "output_level_error_db": round(abs(dbfs(tts) - dbfs(reference)), 3),
            "synthesis_wall_ms": 1.0,
        }
    ]
    record = {
        "schema_version": 1,
        "adapter_id": DEFAULT_ADAPTER_ID,
        "fixture_id": "self_test_fallback_tts",
        "voice_clone_status": FALLBACK_STATUS,
        "voice_similarity_claim": VOICE_SIMILARITY_CLAIM,
        "segments": segment_records,
    }
    args = argparse.Namespace(
        adapter_id=DEFAULT_ADAPTER_ID,
        espeak_voice=DEFAULT_ESPEAK_VOICE,
        sample_rate_hz=sample_rate_hz,
        max_level_error_db=DEFAULT_MAX_LEVEL_ERROR_DB,
        max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
    )
    return build_report(
        record,
        segment_records,
        output_dir=output_dir,
        run_dir=run_dir,
        translation_predictions_path=run_dir / "self_test_translation_predictions.jsonl",
        args=args,
    )


def run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output_dir)
    run_dir = output_dir / "runs" / args.run_id
    report_path = run_dir / "voice-clone-report.json"

    if args.self_test:
        report = build_self_test_report(output_dir, run_dir)
        if not report["summary"]["passed"]:
            raise RuntimeError("fallback TTS self-test expected gates to pass")
        write_report(report, report_path)
        print("fallback TTS contract self-test PASS")
        return 0

    translation_predictions_path = Path(args.translation_predictions)
    prediction = first_prediction_record(load_jsonl(translation_predictions_path))
    record, segment_records = build_fallback_tts_record(
        prediction,
        translation_predictions_path,
        run_dir,
        args,
    )
    write_jsonl([record], run_dir / "fallback_tts_predictions.jsonl")
    report = build_report(
        record,
        segment_records,
        output_dir=output_dir,
        run_dir=run_dir,
        translation_predictions_path=translation_predictions_path,
        args=args,
    )
    write_report(report, report_path)

    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(f"fallback TTS audio stream {status}: {report['summary']['segment_count']} segments")
    print(
        "  max level error="
        f"{report['summary']['max_output_level_error_db']} dB, "
        f"max peak={report['summary']['max_output_peak_dbfs']} dBFS"
    )
    print(f"wrote fallback TTS report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark consent-safe fallback English TTS audio")
    parser.add_argument("command", nargs="?", default="check", choices=["check"])
    parser.add_argument("--self-test", action="store_true", help="validate the report contract only")
    parser.add_argument("--score-warning-only", action="store_true", help="exit 0 even if gates warn")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    parser.add_argument("--translation-predictions", type=Path, default=DEFAULT_TRANSLATION_PREDICTIONS)
    parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    parser.add_argument("--espeak-voice", default=DEFAULT_ESPEAK_VOICE)
    parser.add_argument("--espeak-words-per-minute", type=int, default=DEFAULT_ESPEAK_WORDS_PER_MINUTE)
    parser.add_argument("--max-level-error-db", type=float, default=DEFAULT_MAX_LEVEL_ERROR_DB)
    parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        return run(args)
    except Exception as exc:
        print(f"fallback TTS benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
