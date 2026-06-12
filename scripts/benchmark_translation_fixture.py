#!/usr/bin/env python3
"""Prepare and score a tiny multilingual FLEURS translation fixture.

The fixture uses public FLEURS read-speech clips, keeps clip acquisition under
ignored artifacts, and records source-language plus English-reference truth for
future language-ID, ASR, and into-English translation adapters.
"""

from __future__ import annotations

import argparse
from collections import Counter
import csv
from difflib import SequenceMatcher
import io
import json
import math
import sys
import tarfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from audio_eval_harness import (
    DEFAULT_OUTPUT_DIR,
    PCM_SUBTYPE,
    analyze_fixture,
    apply_fade,
    build_oracle_diarization_records,
    dbfs,
    scale_to_level,
    score_diarization_predictions,
    sha256_file,
    write_jsonl,
    write_report,
)
from prepare_real_speech_fixture import fixture_dir, trim_silence


DEFAULT_FIXTURE_SET_ID = "audio-eval-fleurs-translation-v1"
DEFAULT_FIXTURE_ID = "fleurs_four_language_overlap"
DEFAULT_RUN_ID = "fleurs-language-translation-oracle"
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_SPLIT = "test"
DEFAULT_TARGET_LANGUAGE_CODE = "en"
FLEURS_BASE_URL = "https://huggingface.co/datasets/google/fleurs/resolve/main/data"
FLEURS_DATASET_URL = "https://huggingface.co/datasets/google/fleurs"
USER_AGENT = "LanguageAudioEval/0.1 (+https://github.com/Donovoi/Language)"


@dataclass(frozen=True)
class FleursSourceSpec:
    config: str
    language_code: str
    row_id: str
    audio_file: str
    start_s: float
    level_dbfs: float
    max_duration_s: float = 8.0


DEFAULT_SOURCES = (
    FleursSourceSpec(
        config="es_419",
        language_code="es-419",
        row_id="1747",
        audio_file="10149016836336603986.wav",
        start_s=0.2,
        level_dbfs=-23.0,
    ),
    FleursSourceSpec(
        config="fr_fr",
        language_code="fr-FR",
        row_id="1853",
        audio_file="10174413140250646001.wav",
        start_s=1.6,
        level_dbfs=-29.0,
    ),
    FleursSourceSpec(
        config="de_de",
        language_code="de-DE",
        row_id="1797",
        audio_file="10229344228128634115.wav",
        start_s=3.5,
        level_dbfs=-26.0,
    ),
    FleursSourceSpec(
        config="en_us",
        language_code="en-US",
        row_id="1972",
        audio_file="10233995782544396174.wav",
        start_s=6.0,
        level_dbfs=-33.0,
    ),
)


class CountingReader:
    def __init__(self, stream: Any, max_bytes: int) -> None:
        self._stream = stream
        self.max_bytes = max_bytes
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._stream.read(size)
        self.bytes_read += len(chunk)
        if self.bytes_read > self.max_bytes:
            raise RuntimeError(
                f"FLEURS tar stream exceeded {self.max_bytes} bytes before target audio was found"
            )
        return chunk

    def readable(self) -> bool:
        return True


def request_bytes(url: str, retries: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Request failed after {retries} attempts: {url}") from last_error


def request_text(url: str) -> str:
    return request_bytes(url).decode("utf-8")


def split_url(config: str, split: str = DEFAULT_SPLIT) -> str:
    return f"{FLEURS_BASE_URL}/{config}/{split}.tsv"


def audio_archive_url(config: str, split: str = DEFAULT_SPLIT) -> str:
    return f"{FLEURS_BASE_URL}/{config}/audio/{split}.tar.gz"


def parse_fleurs_tsv(config: str, split: str = DEFAULT_SPLIT) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for row in csv.reader(io.StringIO(request_text(split_url(config, split))), delimiter="\t"):
        if len(row) < 7:
            continue
        rows[row[1]] = {
            "row_id": row[0],
            "audio_file": row[1],
            "transcription": row[2],
            "normalized_transcription": row[3],
            "num_samples": int(row[5]),
            "gender": row[6].lower(),
        }
    return rows


def english_reference_by_id(split: str = DEFAULT_SPLIT) -> dict[str, dict[str, Any]]:
    references: dict[str, dict[str, Any]] = {}
    for row in csv.reader(io.StringIO(request_text(split_url("en_us", split))), delimiter="\t"):
        if len(row) < 7:
            continue
        references.setdefault(
            row[0],
            {
                "row_id": row[0],
                "audio_file": row[1],
                "english_text": row[2],
                "normalized_english_text": row[3],
                "num_samples": int(row[5]),
                "gender": row[6].lower(),
            },
        )
    return references


def extract_audio_from_archive(
    config: str,
    audio_file: str,
    *,
    split: str = DEFAULT_SPLIT,
    max_stream_mb: int = 64,
) -> tuple[bytes, dict[str, Any]]:
    url = audio_archive_url(config, split)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    max_bytes = max_stream_mb * 1024 * 1024
    with urllib.request.urlopen(request, timeout=180) as response:
        counter = CountingReader(response, max_bytes=max_bytes)
        with tarfile.open(fileobj=counter, mode="r|gz") as archive:
            for member in archive:
                if not member.isfile():
                    continue
                member_name = Path(member.name).name
                if member_name != audio_file:
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"FLEURS archive member {member.name} could not be read")
                return extracted.read(), {
                    "archive_url": url,
                    "archive_member": member.name,
                    "archive_member_size": int(member.size),
                    "streamed_bytes": counter.bytes_read,
                    "max_stream_mb": max_stream_mb,
                }
    raise RuntimeError(f"FLEURS audio file {audio_file} was not found in {url}")


def load_audio(raw: bytes, sample_rate_hz: int) -> np.ndarray:
    audio, source_rate_hz = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    if int(source_rate_hz) != sample_rate_hz:
        divisor = math.gcd(int(source_rate_hz), sample_rate_hz)
        audio = resample_poly(
            audio,
            sample_rate_hz // divisor,
            int(source_rate_hz) // divisor,
        ).astype(np.float32)
    return np.asarray(audio, dtype=np.float32)


def prepare_source_audio(
    spec: FleursSourceSpec,
    english_references: dict[str, dict[str, Any]],
    output_dir: Path,
    sample_rate_hz: int,
    split: str,
    max_stream_mb: int,
) -> dict[str, Any]:
    rows = parse_fleurs_tsv(spec.config, split)
    row = rows.get(spec.audio_file)
    if not row:
        raise RuntimeError(f"{spec.config}/{split} does not contain {spec.audio_file}")
    if str(row["row_id"]) != spec.row_id:
        raise RuntimeError(
            f"{spec.config}/{spec.audio_file} row id changed: {row['row_id']} != {spec.row_id}"
        )
    english_reference = english_references.get(spec.row_id)
    if not english_reference:
        raise RuntimeError(f"No English FLEURS reference for row id {spec.row_id}")

    raw_audio, acquisition = extract_audio_from_archive(
        spec.config,
        spec.audio_file,
        split=split,
        max_stream_mb=max_stream_mb,
    )
    source_dir = output_dir / "external_corpora" / "google-fleurs" / spec.config
    source_dir.mkdir(parents=True, exist_ok=True)
    downloaded_path = source_dir / spec.audio_file
    downloaded_path.write_bytes(raw_audio)

    samples = trim_silence(load_audio(raw_audio, sample_rate_hz), sample_rate_hz)
    max_frames = int(round(spec.max_duration_s * sample_rate_hz))
    samples = samples[:max_frames]
    if samples.size < int(round(1.5 * sample_rate_hz)):
        raise RuntimeError(f"{spec.config}/{spec.audio_file} is too short after silence trimming")

    samples = apply_fade(samples, sample_rate_hz)
    samples = scale_to_level(samples, spec.level_dbfs).astype(np.float32)

    return {
        "spec": spec,
        "row": row,
        "english_reference": english_reference,
        "audio": samples,
        "duration_s": samples.size / float(sample_rate_hz),
        "measured_dbfs": dbfs(samples),
        "downloaded_audio_path": downloaded_path,
        "downloaded_audio_sha256": sha256_file(downloaded_path),
        "acquisition": acquisition,
    }


def prepare_multilingual_fixture(
    output_dir: Path,
    fixture_set_id: str = DEFAULT_FIXTURE_SET_ID,
    fixture_id: str = DEFAULT_FIXTURE_ID,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    split: str = DEFAULT_SPLIT,
    sources: tuple[FleursSourceSpec, ...] = DEFAULT_SOURCES,
    max_stream_mb: int = 64,
) -> dict[str, Any]:
    if len(sources) < 2:
        raise RuntimeError("Multilingual fixture requires at least two source rows")

    target_dir = fixture_dir(output_dir, fixture_set_id, fixture_id)
    stem_dir = target_dir / "stems"
    clip_dir = target_dir / "source_clips"
    stem_dir.mkdir(parents=True, exist_ok=True)
    clip_dir.mkdir(parents=True, exist_ok=True)

    english_references = english_reference_by_id(split)
    prepared = [
        prepare_source_audio(
            spec,
            english_references,
            target_dir,
            sample_rate_hz,
            split,
            max_stream_mb,
        )
        for spec in sources
    ]

    end_s = max(float(item["spec"].start_s) + float(item["duration_s"]) for item in prepared)
    duration_s = round(end_s + 0.35, 3)
    frame_count = int(round(duration_s * sample_rate_hz))
    mix = np.zeros(frame_count, dtype=np.float32)
    segments: list[dict[str, Any]] = []
    stems: list[dict[str, str]] = []

    for index, item in enumerate(prepared):
        spec: FleursSourceSpec = item["spec"]
        row = item["row"]
        english_reference = item["english_reference"]
        audio = item["audio"]
        track_id = f"speaker_{spec.config}_{spec.row_id}"
        start_sample = int(round(spec.start_s * sample_rate_hz))
        end_sample = start_sample + audio.size
        if end_sample > frame_count:
            raise RuntimeError(f"{spec.config}/{spec.audio_file} does not fit inside fixture duration")

        full_stem = np.zeros(frame_count, dtype=np.float32)
        full_stem[start_sample:end_sample] = audio
        mix += full_stem

        stem_path = stem_dir / f"{track_id}.wav"
        sf.write(stem_path, full_stem, sample_rate_hz, subtype=PCM_SUBTYPE)
        stems.append(
            {
                "track_id": track_id,
                "path": f"stems/{track_id}.wav",
                "sha256": sha256_file(stem_path),
            }
        )

        clip_path = clip_dir / f"{spec.config}_{spec.audio_file}"
        sf.write(clip_path, audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        segments.append(
            {
                "index": index,
                "speaker_id": track_id,
                "source_kind": "human",
                "language_code": spec.language_code,
                "voice_profile": f"fleurs_{spec.config}_{row['gender']}_{spec.row_id}",
                "text": row["transcription"],
                "source_text": row["transcription"],
                "normalized_source_text": row["normalized_transcription"],
                "target_language_code": DEFAULT_TARGET_LANGUAGE_CODE,
                "english_reference_text": english_reference["english_text"],
                "normalized_english_reference_text": english_reference["normalized_english_text"],
                "start_s": round(float(spec.start_s), 6),
                "end_s": round(end_sample / float(sample_rate_hz), 6),
                "start_sample": start_sample,
                "end_sample": end_sample,
                "level_dbfs": float(spec.level_dbfs),
                "stem_path": f"stems/{track_id}.wav",
                "source_clip_path": f"source_clips/{spec.config}_{spec.audio_file}",
                "source_dataset": {
                    "dataset": "google/fleurs",
                    "config": spec.config,
                    "split": split,
                    "row_id": spec.row_id,
                    "audio_file": spec.audio_file,
                    "gender": row["gender"],
                    "num_samples": row["num_samples"],
                    "source_url": FLEURS_DATASET_URL,
                    "downloaded_audio_path": str(
                        item["downloaded_audio_path"].relative_to(target_dir)
                    ),
                    "downloaded_audio_sha256": item["downloaded_audio_sha256"],
                    "acquisition": item["acquisition"],
                },
            }
        )

    max_abs = float(np.max(np.abs(mix))) if mix.size else 0.0
    if max_abs > 0.98:
        raise RuntimeError(f"Multilingual fixture mix would clip: max_abs={max_abs:.6f}")

    mix_path = target_dir / "mix.wav"
    sf.write(mix_path, mix, sample_rate_hz, subtype=PCM_SUBTYPE)
    annotation = {
        "schema_version": 1,
        "fixture_set_id": fixture_set_id,
        "fixture_id": fixture_id,
        "description": (
            "Four FLEURS read-speech clips in Spanish, French, German, and English, mixed "
            "with overlap and level variation for language-ID and into-English translation gates."
        ),
        "sample_rate_hz": sample_rate_hz,
        "duration_s": duration_s,
        "mix_path": "mix.wav",
        "mix_sha256": sha256_file(mix_path),
        "stems": stems,
        "background_noise_dbfs": None,
        "segments": segments,
        "source_license": "FLEURS / google/fleurs, CC-BY-4.0",
        "source_url": FLEURS_DATASET_URL,
        "detractor_note": (
            "This is public multilingual read speech with English reference text, not noisy "
            "spontaneous room translation. It validates acquisition, language labels, overlap, "
            "and translation-truth plumbing before model-backed ASR/MT is trusted."
        ),
    }
    (target_dir / "annotations.json").write_text(
        json.dumps(annotation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return annotation


def build_oracle_translation_records(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for annotation in annotations:
        records.append(
            {
                "schema_version": 1,
                "fixture_id": annotation["fixture_id"],
                "adapter_id": "oracle_language_translation_v1",
                "segments": [
                    {
                        "speaker_id": segment["speaker_id"],
                        "start_s": segment["start_s"],
                        "end_s": segment["end_s"],
                        "detected_language_code": segment["language_code"],
                        "language_confidence": 1.0,
                        "source_text": segment["source_text"],
                        "translated_text": segment["english_reference_text"],
                        "target_language_code": segment["target_language_code"],
                        "first_partial_latency_ms": 0.0,
                        "final_latency_ms": 0.0,
                    }
                    for segment in annotation["segments"]
                    if segment["source_kind"] == "human"
                ],
                "metadata": {
                    "kind": "oracle",
                    "note": "Generated from fixture truth to validate language and translation scorer plumbing.",
                },
            }
        )
    return records


def _normalize_text(value: str) -> str:
    return " ".join(value.casefold().strip().split())


def _primary_language(value: str) -> str:
    normalized = value.strip().replace("_", "-").casefold()
    primary, _, _ = normalized.partition("-")
    return primary or normalized


def _token_f1(expected: str, predicted: str) -> float:
    expected_tokens = _normalize_text(expected).split()
    predicted_tokens = _normalize_text(predicted).split()
    if not expected_tokens and not predicted_tokens:
        return 1.0
    if not expected_tokens or not predicted_tokens:
        return 0.0
    expected_counts = Counter(expected_tokens)
    predicted_counts = Counter(predicted_tokens)
    overlap = sum((expected_counts & predicted_counts).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted_tokens)
    recall = overlap / len(expected_tokens)
    return (2.0 * precision * recall) / (precision + recall)


def _char_similarity(expected: str, predicted: str) -> float:
    return SequenceMatcher(None, _normalize_text(expected), _normalize_text(predicted)).ratio()


def score_translation_predictions(
    annotation: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    expected = {
        str(segment["speaker_id"]): segment
        for segment in annotation["segments"]
        if segment["source_kind"] == "human"
    }
    predicted = {str(segment["speaker_id"]): segment for segment in prediction.get("segments", [])}

    segment_scores: list[dict[str, Any]] = []
    for speaker_id, expected_segment in expected.items():
        pred = predicted.get(speaker_id)
        if pred is None:
            segment_scores.append(
                {
                    "speaker_id": speaker_id,
                    "language_code": expected_segment["language_code"],
                    "language_correct": False,
                    "translation_exact": False,
                    "missing_prediction": True,
                    "first_partial_latency_ms": None,
                    "final_latency_ms": None,
                }
            )
            continue

        expected_language = str(expected_segment["language_code"])
        predicted_language = str(pred.get("detected_language_code", ""))
        expected_translation_raw = str(expected_segment["english_reference_text"])
        predicted_translation_raw = str(pred.get("translated_text", ""))
        expected_translation = _normalize_text(expected_translation_raw)
        predicted_translation = _normalize_text(predicted_translation_raw)
        first_partial_latency_ms = float(pred.get("first_partial_latency_ms", 0.0))
        final_latency_ms = float(pred.get("final_latency_ms", 0.0))
        segment_scores.append(
            {
                "speaker_id": speaker_id,
                "language_code": expected_language,
                "predicted_language_code": predicted_language,
                "language_correct": predicted_language == expected_language,
                "language_primary_correct": (
                    _primary_language(predicted_language) == _primary_language(expected_language)
                ),
                "translation_exact": predicted_translation == expected_translation,
                "translation_token_f1": round(
                    _token_f1(expected_translation_raw, predicted_translation_raw),
                    6,
                ),
                "translation_char_similarity": round(
                    _char_similarity(expected_translation_raw, predicted_translation_raw),
                    6,
                ),
                "missing_prediction": False,
                "first_partial_latency_ms": round(first_partial_latency_ms, 3),
                "final_latency_ms": round(final_latency_ms, 3),
            }
        )

    total = len(segment_scores)
    language_correct = sum(1 for score in segment_scores if score["language_correct"])
    language_primary_correct = sum(
        1 for score in segment_scores if score.get("language_primary_correct")
    )
    translation_exact = sum(1 for score in segment_scores if score["translation_exact"])
    translation_token_f1_values = [
        float(score.get("translation_token_f1", 0.0)) for score in segment_scores
    ]
    translation_char_similarity_values = [
        float(score.get("translation_char_similarity", 0.0)) for score in segment_scores
    ]
    max_first_partial_latency_ms = max(
        (
            float(score["first_partial_latency_ms"])
            for score in segment_scores
            if score["first_partial_latency_ms"] is not None
        ),
        default=float("inf"),
    )
    max_final_latency_ms = max(
        (
            float(score["final_latency_ms"])
            for score in segment_scores
            if score["final_latency_ms"] is not None
        ),
        default=float("inf"),
    )
    return {
        "adapter_id": str(prediction.get("adapter_id", "unknown_translation_adapter")),
        "summary": {
            "segment_count": total,
            "language_accuracy": round(language_correct / total, 6) if total else 0.0,
            "language_primary_accuracy": (
                round(language_primary_correct / total, 6) if total else 0.0
            ),
            "translation_exact_match": round(translation_exact / total, 6) if total else 0.0,
            "mean_translation_token_f1": (
                round(sum(translation_token_f1_values) / total, 6) if total else 0.0
            ),
            "mean_translation_char_similarity": (
                round(sum(translation_char_similarity_values) / total, 6) if total else 0.0
            ),
            "max_first_partial_latency_ms": round(max_first_partial_latency_ms, 3),
            "max_final_latency_ms": round(max_final_latency_ms, 3),
        },
        "segments": segment_scores,
    }


def multilingual_gates(
    annotation: dict[str, Any],
    fixture_report: dict[str, Any],
    diarization_report: dict[str, Any],
    translation_report: dict[str, Any],
) -> list[dict[str, Any]]:
    human_segments = [
        segment for segment in fixture_report["segments"] if segment["source_kind"] == "human"
    ]
    target_levels = [float(segment["target_dbfs"]) for segment in human_segments]
    language_codes = fixture_report["truth"]["language_codes"]
    non_english_languages = [
        code for code in language_codes if not str(code).casefold().startswith("en")
    ]
    overlap_s = float(fixture_report["truth"]["human_overlap"]["overlap_s"])
    level_spread = max(target_levels) - min(target_levels) if target_levels else 0.0
    references_present = all(
        bool(str(segment.get("english_reference_text", "")).strip())
        for segment in annotation["segments"]
        if segment["source_kind"] == "human"
    )

    return [
        {
            "name": "multilingual_fixture_count",
            "value": 1,
            "threshold": "one tiny multilingual fixture",
            "passed": True,
        },
        {
            "name": "multilingual_language_count",
            "value": language_codes,
            "threshold": ">= 4 human source languages",
            "passed": len(language_codes) >= 4,
        },
        {
            "name": "multilingual_non_english_count",
            "value": non_english_languages,
            "threshold": ">= 3 non-English source languages",
            "passed": len(non_english_languages) >= 3,
        },
        {
            "name": "multilingual_overlap_present",
            "value": round(overlap_s, 6),
            "threshold": ">= 2.0s human-human overlap",
            "passed": overlap_s >= 2.0,
        },
        {
            "name": "multilingual_volume_spread",
            "value": round(level_spread, 3),
            "threshold": ">= 8 dB target level spread",
            "passed": level_spread >= 8.0,
        },
        {
            "name": "multilingual_translation_references_present",
            "value": references_present,
            "threshold": "English reference text for every segment",
            "passed": references_present,
        },
        {
            "name": "multilingual_mix_not_clipping",
            "value": fixture_report["mix"]["max_abs"],
            "threshold": "max absolute mix sample <= 0.98",
            "passed": float(fixture_report["mix"]["max_abs"]) <= 0.98,
        },
        *diarization_report["summary"]["quality_gates"],
        {
            "name": "oracle_language_accuracy",
            "value": translation_report["summary"]["language_accuracy"],
            "threshold": ">= 1.0 for oracle predictions",
            "passed": float(translation_report["summary"]["language_accuracy"]) >= 1.0,
        },
        {
            "name": "oracle_translation_exact_match",
            "value": translation_report["summary"]["translation_exact_match"],
            "threshold": ">= 1.0 for oracle predictions",
            "passed": float(translation_report["summary"]["translation_exact_match"]) >= 1.0,
        },
    ]


def build_check_report(annotation: dict[str, Any], output_dir: Path, run_id: str) -> dict[str, Any]:
    run_dir = output_dir / "runs" / run_id
    diarization_predictions_path = run_dir / "oracle_diarization_predictions.jsonl"
    translation_predictions_path = run_dir / "oracle_translation_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records([annotation]), diarization_predictions_path)
    write_jsonl(build_oracle_translation_records([annotation]), translation_predictions_path)

    diarization_report = score_diarization_predictions(
        [annotation],
        diarization_predictions_path,
        strict_oracle=True,
    )
    translation_prediction = build_oracle_translation_records([annotation])[0]
    translation_report = score_translation_predictions(annotation, translation_prediction)
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = multilingual_gates(annotation, fixture_report, diarization_report, translation_report)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "fleurs_multilingual_language_translation",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "diarization": diarization_report,
            "language_translation": translation_report,
        },
        "prediction_paths": {
            "diarization": str(diarization_predictions_path),
            "language_translation": str(translation_predictions_path),
        },
        "fixtures": [fixture_report],
        "detractor_loop": {
            "strongest_objection": (
                "FLEURS is read speech with parallel text, so oracle translation gates can pass "
                "without proving noisy spontaneous streaming translation."
            ),
            "cheapest_falsifying_benchmark": (
                "Run a real LID/ASR/MT adapter on this fixture, then repeat with crowd noise and "
                "compare language accuracy, time to first English partial, and exact/semantic match."
            ),
            "fallback_if_falsified": (
                "Keep captions-only or passthrough English behavior while language confidence is low, "
                "and avoid same-voice audio until the text path stabilizes."
            ),
        },
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(f"translation audio-eval {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare and score multilingual FLEURS fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        subparser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
        subparser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
        subparser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
        subparser.add_argument("--split", default=DEFAULT_SPLIT)
        subparser.add_argument("--max-stream-mb", type=int, default=64)

    prepare = subparsers.add_parser("prepare", help="download, mix, and annotate fixture")
    add_common(prepare)

    check = subparsers.add_parser("check", help="prepare fixture and run oracle gates")
    add_common(check)
    check.add_argument("--run-id", default=DEFAULT_RUN_ID)
    check.add_argument(
        "--report",
        type=Path,
        default=None,
        help="defaults to artifacts/audio_eval/runs/<run-id>/translation-fixture-report.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    annotation = prepare_multilingual_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        sample_rate_hz=args.sample_rate_hz,
        split=args.split,
        max_stream_mb=args.max_stream_mb,
    )
    annotation_path = fixture_dir(output_dir, args.fixture_set_id, args.fixture_id) / "annotations.json"
    print(f"wrote multilingual translation fixture annotations to {annotation_path}")

    if args.command == "prepare":
        return 0

    report_path = (
        args.report.resolve()
        if args.report
        else output_dir / "runs" / args.run_id / "translation-fixture-report.json"
    )
    report = build_check_report(annotation, output_dir, args.run_id)
    write_report(report, report_path)
    print(f"wrote multilingual translation fixture report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
