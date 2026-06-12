#!/usr/bin/env python3
"""Generate and check deterministic audio-eval fixtures.

The first evaluation harness is deliberately model-agnostic. It validates the
fixture truth, level accounting, overlap accounting, and report schema that
future diarization, translation, TTS, and playback-suppression benchmarks will
attach to.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


DEFAULT_MANIFEST = Path("fixtures/audio_eval/v1/manifest.json")
DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_REPORT = DEFAULT_OUTPUT_DIR / "audio-eval-report.json"
DEFAULT_ORACLE_DIARIZATION = DEFAULT_OUTPUT_DIR / "predictions" / "oracle_diarization.jsonl"
PCM_SUBTYPE = "PCM_16"


def db_to_linear(dbfs: float) -> float:
    return float(10 ** (dbfs / 20.0))


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


def stable_seed(*parts: object) -> int:
    material = "|".join(str(part) for part in parts).encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return int.from_bytes(digest[:8], "big") % (2**32)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scale_to_level(samples: np.ndarray, target_dbfs: float) -> np.ndarray:
    current_rms = rms(samples)
    if current_rms == 0.0:
        return samples
    return samples * (db_to_linear(target_dbfs) / current_rms)


def apply_fade(samples: np.ndarray, sample_rate_hz: int, fade_ms: float = 12.0) -> np.ndarray:
    fade_len = min(samples.size // 2, int(sample_rate_hz * fade_ms / 1000.0))
    if fade_len <= 1:
        return samples
    fade = np.linspace(0.0, 1.0, fade_len, dtype=np.float32)
    samples = samples.copy()
    samples[:fade_len] *= fade
    samples[-fade_len:] *= fade[::-1]
    return samples


def synth_segment(
    fixture_id: str,
    segment: dict[str, Any],
    sample_rate_hz: int,
) -> np.ndarray:
    start_s = float(segment["start_s"])
    end_s = float(segment["end_s"])
    frame_count = int(round((end_s - start_s) * sample_rate_hz))
    if frame_count <= 0:
        raise ValueError(f"{fixture_id}: segment must have positive duration: {segment}")

    seed = stable_seed(fixture_id, segment["speaker_id"], start_s, end_s, segment["tone_hz"])
    rng = np.random.default_rng(seed)
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    phase = float(rng.uniform(0.0, 2.0 * math.pi))
    freq = float(segment["tone_hz"])

    carrier = np.sin(2.0 * math.pi * freq * t + phase)
    carrier += 0.18 * np.sin(2.0 * math.pi * freq * 1.91 * t + phase * 0.37)
    carrier += 0.05 * np.sin(2.0 * math.pi * freq * 2.73 * t + phase * 0.11)

    syllables = 0.58 + 0.42 * (0.5 + 0.5 * np.sin(2.0 * math.pi * 4.4 * t + phase))
    phrase = 0.90 + 0.10 * np.sin(2.0 * math.pi * 0.7 * t + phase * 0.5)
    breath = 0.98 + 0.02 * rng.normal(0.0, 1.0, frame_count)

    shaped = carrier * syllables * phrase * breath
    shaped = apply_fade(shaped.astype(np.float32), sample_rate_hz)
    shaped = scale_to_level(shaped, float(segment["level_dbfs"]))
    return shaped.astype(np.float32)


def add_background_noise(
    fixture_id: str,
    frame_count: int,
    sample_rate_hz: int,
    target_dbfs: float,
) -> np.ndarray:
    rng = np.random.default_rng(stable_seed(fixture_id, "background_noise"))
    noise = rng.normal(0.0, 1.0, frame_count).astype(np.float32)
    noise = scale_to_level(noise, target_dbfs)

    # Keep the noise slightly less clinical without making it speech-like.
    time_axis = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    room_mod = 0.94 + 0.06 * np.sin(2.0 * math.pi * 0.33 * time_axis)
    return (noise * room_mod).astype(np.float32)


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1:
        raise ValueError(f"Unsupported audio-eval manifest schema: {manifest.get('schema_version')}")
    if not manifest.get("fixtures"):
        raise ValueError("Audio-eval manifest must contain at least one fixture")
    return manifest


def ensure_segment_order(fixture: dict[str, Any]) -> None:
    duration_s = float(fixture["duration_s"])
    for segment in fixture["segments"]:
        start_s = float(segment["start_s"])
        end_s = float(segment["end_s"])
        if start_s < 0.0 or end_s <= start_s or end_s > duration_s:
            raise ValueError(f"{fixture['id']}: invalid segment bounds: {segment}")


def safe_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return "".join(char if char in allowed else "_" for char in value)


def render_fixture(
    manifest: dict[str, Any],
    fixture: dict[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    ensure_segment_order(fixture)

    sample_rate_hz = int(manifest["sample_rate_hz"])
    duration_s = float(fixture["duration_s"])
    frame_count = int(round(duration_s * sample_rate_hz))
    fixture_dir = output_dir / "fixtures" / str(manifest["fixture_set_id"]) / safe_id(fixture["id"])
    fixture_dir.mkdir(parents=True, exist_ok=True)

    stems: dict[str, np.ndarray] = {}
    rendered_segments: list[dict[str, Any]] = []

    for index, segment in enumerate(fixture["segments"]):
        track_id = safe_id(str(segment["speaker_id"]))
        stems.setdefault(track_id, np.zeros(frame_count, dtype=np.float32))

        start_sample = int(round(float(segment["start_s"]) * sample_rate_hz))
        end_sample = int(round(float(segment["end_s"]) * sample_rate_hz))
        segment_audio = synth_segment(fixture["id"], segment, sample_rate_hz)
        expected_len = end_sample - start_sample
        if segment_audio.size != expected_len:
            segment_audio = np.resize(segment_audio, expected_len).astype(np.float32)

        stems[track_id][start_sample:end_sample] += segment_audio
        rendered_segments.append(
            {
                "index": index,
                "speaker_id": segment["speaker_id"],
                "source_kind": segment.get("source_kind", "human"),
                "language_code": segment["language_code"],
                "voice_profile": segment.get("voice_profile"),
                "text": segment.get("text"),
                "start_s": float(segment["start_s"]),
                "end_s": float(segment["end_s"]),
                "start_sample": start_sample,
                "end_sample": end_sample,
                "level_dbfs": float(segment["level_dbfs"]),
                "tone_hz": float(segment["tone_hz"]),
                "stem_path": f"stems/{track_id}.wav",
            }
        )

    mix = np.zeros(frame_count, dtype=np.float32)
    for stem in stems.values():
        mix += stem

    noise_dbfs = fixture.get("background_noise_dbfs")
    if noise_dbfs is not None:
        mix += add_background_noise(fixture["id"], frame_count, sample_rate_hz, float(noise_dbfs))

    stem_dir = fixture_dir / "stems"
    stem_dir.mkdir(exist_ok=True)
    stem_records: list[dict[str, str]] = []
    for track_id, stem in stems.items():
        stem_path = stem_dir / f"{track_id}.wav"
        sf.write(stem_path, stem, sample_rate_hz, subtype=PCM_SUBTYPE)
        stem_records.append(
            {
                "track_id": track_id,
                "path": f"stems/{track_id}.wav",
                "sha256": sha256_file(stem_path),
            }
        )

    mix_path = fixture_dir / "mix.wav"
    sf.write(mix_path, mix, sample_rate_hz, subtype=PCM_SUBTYPE)

    annotation = {
        "schema_version": 1,
        "fixture_set_id": manifest["fixture_set_id"],
        "fixture_id": fixture["id"],
        "description": fixture["description"],
        "sample_rate_hz": sample_rate_hz,
        "duration_s": duration_s,
        "mix_path": "mix.wav",
        "mix_sha256": sha256_file(mix_path),
        "stems": stem_records,
        "background_noise_dbfs": noise_dbfs,
        "segments": rendered_segments,
        "detractor_note": (
            "Synthetic tones validate harness plumbing, level accounting, and overlap truth. "
            "They do not prove speech recognition, diarization DER, voice similarity, or room "
            "suppression quality."
        ),
    }
    (fixture_dir / "annotations.json").write_text(
        json.dumps(annotation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return annotation


def render_fixtures(manifest_path: Path, output_dir: Path) -> list[dict[str, Any]]:
    manifest = load_manifest(manifest_path)
    return [render_fixture(manifest, fixture, output_dir) for fixture in manifest["fixtures"]]


def overlap_stats(segments: list[dict[str, Any]], human_only: bool) -> dict[str, Any]:
    events: list[tuple[float, int]] = []
    for segment in segments:
        if human_only and segment.get("source_kind") != "human":
            continue
        events.append((float(segment["start_s"]), 1))
        events.append((float(segment["end_s"]), -1))

    events.sort(key=lambda item: (item[0], -item[1]))
    active = 0
    previous_t: float | None = None
    overlap_s = 0.0
    max_concurrent = 0

    for current_t, delta in events:
        if previous_t is not None and current_t > previous_t and active >= 2:
            overlap_s += current_t - previous_t
        active += delta
        max_concurrent = max(max_concurrent, active)
        previous_t = current_t

    return {
        "overlap_s": round(overlap_s, 6),
        "max_concurrent": max_concurrent,
    }


def active_speakers_at(
    segments: list[dict[str, Any]],
    frame_start_s: float,
    frame_end_s: float,
) -> set[str]:
    active: set[str] = set()
    for segment in segments:
        if float(segment["start_s"]) < frame_end_s and float(segment["end_s"]) > frame_start_s:
            active.add(str(segment["speaker_id"]))
    return active


def intersection_duration(a: dict[str, Any], b: dict[str, Any]) -> float:
    start_s = max(float(a["start_s"]), float(b["start_s"]))
    end_s = min(float(a["end_s"]), float(b["end_s"]))
    return max(0.0, end_s - start_s)


def speaker_overlap_seconds(
    ref_segments: list[dict[str, Any]],
    pred_segments: list[dict[str, Any]],
) -> dict[tuple[str, str], float]:
    overlaps: dict[tuple[str, str], float] = {}
    for pred in pred_segments:
        for ref in ref_segments:
            key = (str(pred["speaker_id"]), str(ref["speaker_id"]))
            overlaps[key] = overlaps.get(key, 0.0) + intersection_duration(pred, ref)
    return overlaps


def best_speaker_mapping(
    ref_segments: list[dict[str, Any]],
    pred_segments: list[dict[str, Any]],
) -> dict[str, str]:
    ref_speakers = sorted({str(segment["speaker_id"]) for segment in ref_segments})
    pred_speakers = sorted({str(segment["speaker_id"]) for segment in pred_segments})
    if not ref_speakers or not pred_speakers:
        return {}

    overlaps = speaker_overlap_seconds(ref_segments, pred_segments)
    best_score = -1.0
    best_mapping: dict[str, str] = {}

    if len(pred_speakers) <= len(ref_speakers):
        for ref_assignment in itertools.permutations(ref_speakers, len(pred_speakers)):
            mapping = dict(zip(pred_speakers, ref_assignment, strict=True))
            score = sum(overlaps.get((pred, ref), 0.0) for pred, ref in mapping.items())
            if score > best_score:
                best_score = score
                best_mapping = mapping
    else:
        for pred_subset in itertools.combinations(pred_speakers, len(ref_speakers)):
            for ref_assignment in itertools.permutations(ref_speakers):
                mapping = dict(zip(pred_subset, ref_assignment, strict=True))
                score = sum(overlaps.get((pred, ref), 0.0) for pred, ref in mapping.items())
                if score > best_score:
                    best_score = score
                    best_mapping = mapping

    return best_mapping if best_score > 0.0 else {}


def normalize_prediction_segment(segment: dict[str, Any], fixture_id: str) -> dict[str, Any]:
    speaker_id = str(segment.get("speaker_id", segment.get("speaker_label", ""))).strip()
    if not speaker_id:
        raise ValueError(f"{fixture_id}: diarization prediction segment is missing a speaker label")
    start_s = float(segment["start_s"])
    end_s = float(segment["end_s"])
    confidence = float(segment.get("confidence", 1.0))
    if (
        not math.isfinite(start_s)
        or not math.isfinite(end_s)
        or not math.isfinite(confidence)
        or start_s < 0.0
        or end_s <= start_s
    ):
        raise ValueError(f"{fixture_id}: invalid diarization prediction segment: {segment}")
    return {
        "speaker_id": speaker_id,
        "start_s": start_s,
        "end_s": end_s,
        "confidence": confidence,
    }


def empty_prediction_record(fixture_id: str, adapter_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_id": fixture_id,
        "adapter_id": adapter_id,
        "segments": [],
        "model_layer_latency_ms": {},
        "metadata": {},
    }


def read_diarization_predictions(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.exists():
        raise FileNotFoundError(path)
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        record = json.loads(line)
        fixture_id = str(record["fixture_id"])
        adapter_id = str(record.get("adapter_id", "unknown_diarization_adapter"))
        records.setdefault(fixture_id, empty_prediction_record(fixture_id, adapter_id))
        if records[fixture_id]["adapter_id"] != adapter_id:
            records[fixture_id]["adapter_id"] = "mixed_diarization_adapters"

        if "segments" in record:
            records[fixture_id]["segments"].extend(
                normalize_prediction_segment(segment, fixture_id)
                for segment in record.get("segments", [])
            )
            records[fixture_id]["model_layer_latency_ms"].update(
                record.get("model_layer_latency_ms", {})
            )
            records[fixture_id]["metadata"].update(record.get("metadata", {}))
        else:
            records[fixture_id]["segments"].append(normalize_prediction_segment(record, fixture_id))
    return records


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(record, sort_keys=True) for record in records]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_oracle_diarization_records(annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for annotation in annotations:
        records.append(
            {
                "schema_version": 1,
                "fixture_id": annotation["fixture_id"],
                "adapter_id": "oracle_diarization_v1",
                "segments": [
                    {
                        "speaker_id": segment["speaker_id"],
                        "start_s": segment["start_s"],
                        "end_s": segment["end_s"],
                        "confidence": 1.0,
                    }
                    for segment in annotation["segments"]
                    if segment["source_kind"] == "human"
                ],
                "model_layer_latency_ms": {
                    "diarization": 0.0,
                },
                "metadata": {
                    "kind": "oracle",
                    "note": "Generated from fixture truth to validate the scorer path.",
                },
            }
        )
    return records


def empty_diarization_record(annotation: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fixture_id": annotation["fixture_id"],
        "adapter_id": "missing_prediction",
        "segments": [],
        "model_layer_latency_ms": {},
        "metadata": {
            "kind": "empty",
            "note": "No prediction was provided for this fixture.",
        },
    }


def merge_segments_by_speaker(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for speaker_id, group in itertools.groupby(
        sorted(segments, key=lambda item: (item["speaker_id"], item["start_s"], item["end_s"])),
        key=lambda item: item["speaker_id"],
    ):
        speaker_segments = list(group)
        current = dict(speaker_segments[0])
        for segment in speaker_segments[1:]:
            if float(segment["start_s"]) <= float(current["end_s"]):
                current["end_s"] = max(float(current["end_s"]), float(segment["end_s"]))
            else:
                merged.append(current)
                current = dict(segment)
        merged.append(current)
    return merged


def union_timeline_regions(
    duration_s: float,
    ref_segments: list[dict[str, Any]],
    pred_segments: list[dict[str, Any]],
) -> list[tuple[float, float]]:
    boundaries = {0.0, duration_s}
    for segment in [*ref_segments, *pred_segments]:
        boundaries.add(float(segment["start_s"]))
        boundaries.add(float(segment["end_s"]))
    ordered = sorted(boundary for boundary in boundaries if 0.0 <= boundary <= duration_s)
    return [
        (ordered[index], ordered[index + 1])
        for index in range(len(ordered) - 1)
        if ordered[index + 1] > ordered[index]
    ]


def score_fixture_diarization(
    annotation: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    duration_s = float(annotation["duration_s"])
    ref_segments = [
        {
            "speaker_id": str(segment["speaker_id"]),
            "start_s": float(segment["start_s"]),
            "end_s": float(segment["end_s"]),
        }
        for segment in annotation["segments"]
        if segment["source_kind"] == "human"
    ]
    pred_segments: list[dict[str, Any]] = []
    for segment in prediction.get("segments", []):
        start_s = float(segment["start_s"])
        end_s = float(segment["end_s"])
        if start_s < 0.0 or end_s > duration_s or end_s <= start_s:
            raise ValueError(
                f"{annotation['fixture_id']}: prediction outside fixture duration: {segment}"
            )
        pred_segments.append(
            {
                "speaker_id": str(segment["speaker_id"]),
                "start_s": start_s,
                "end_s": end_s,
            }
        )
    pred_segments = merge_segments_by_speaker(pred_segments)

    mapping = best_speaker_mapping(ref_segments, pred_segments)
    reference_speaker_time_s = 0.0
    miss_s = 0.0
    false_alarm_s = 0.0
    confusion_s = 0.0
    ref_overlap_presence_s = 0.0
    pred_overlap_presence_s = 0.0
    overlap_presence_true_positive_s = 0.0
    ref_overlap_speaker_time_s = 0.0
    overlap_speaker_time_hit_s = 0.0

    for frame_start_s, frame_end_s in union_timeline_regions(duration_s, ref_segments, pred_segments):
        region_duration_s = frame_end_s - frame_start_s
        if region_duration_s <= 0.0:
            continue

        ref_active = active_speakers_at(ref_segments, frame_start_s, frame_end_s)
        pred_active_raw = active_speakers_at(pred_segments, frame_start_s, frame_end_s)
        pred_active = {mapping[pred] for pred in pred_active_raw if pred in mapping}

        ref_count = len(ref_active)
        pred_count = len(pred_active_raw)
        correct_count = len(ref_active & pred_active)

        reference_speaker_time_s += ref_count * region_duration_s
        miss_s += max(ref_count - pred_count, 0) * region_duration_s
        false_alarm_s += max(pred_count - ref_count, 0) * region_duration_s
        confusion_s += max(min(ref_count, pred_count) - correct_count, 0) * region_duration_s

        ref_overlap = ref_count >= 2
        pred_overlap = pred_count >= 2
        if ref_overlap:
            ref_overlap_presence_s += region_duration_s
            ref_overlap_speaker_time_s += ref_count * region_duration_s
            overlap_speaker_time_hit_s += correct_count * region_duration_s
        if pred_overlap:
            pred_overlap_presence_s += region_duration_s
        if ref_overlap and pred_overlap:
            overlap_presence_true_positive_s += region_duration_s

    total_error_s = miss_s + false_alarm_s + confusion_s
    der_like = total_error_s / reference_speaker_time_s if reference_speaker_time_s else 0.0
    overlap_presence_recall = (
        overlap_presence_true_positive_s / ref_overlap_presence_s
        if ref_overlap_presence_s
        else None
    )
    overlap_presence_precision = (
        overlap_presence_true_positive_s / pred_overlap_presence_s
        if pred_overlap_presence_s
        else None
    )
    overlap_speaker_time_recall = (
        overlap_speaker_time_hit_s / ref_overlap_speaker_time_s
        if ref_overlap_speaker_time_s
        else None
    )

    return {
        "fixture_id": annotation["fixture_id"],
        "adapter_id": prediction.get("adapter_id", "unknown_diarization_adapter"),
        "scoring_method": "boundary_union_der_like",
        "collar_ms": 0,
        "speaker_mapping": mapping,
        "reference_speaker_time_s": round(reference_speaker_time_s, 6),
        "miss_s": round(miss_s, 6),
        "false_alarm_s": round(false_alarm_s, 6),
        "confusion_s": round(confusion_s, 6),
        "total_error_s": round(total_error_s, 6),
        "der_like": round(der_like, 6),
        "overlap": {
            "reference_presence_s": round(ref_overlap_presence_s, 6),
            "predicted_presence_s": round(pred_overlap_presence_s, 6),
            "true_positive_presence_s": round(overlap_presence_true_positive_s, 6),
            "presence_recall": (
                None if overlap_presence_recall is None else round(overlap_presence_recall, 6)
            ),
            "presence_precision": (
                None if overlap_presence_precision is None else round(overlap_presence_precision, 6)
            ),
            "reference_speaker_time_s": round(ref_overlap_speaker_time_s, 6),
            "matched_speaker_time_s": round(overlap_speaker_time_hit_s, 6),
            "speaker_time_recall": (
                None if overlap_speaker_time_recall is None else round(overlap_speaker_time_recall, 6)
            ),
        },
        "model_layer_latency_ms": prediction.get("model_layer_latency_ms", {}),
    }


def summarize_diarization_scores(
    fixture_scores: list[dict[str, Any]],
    adapter_id: str,
    prediction_path: Path,
    strict_oracle: bool,
) -> dict[str, Any]:
    total_ref = sum(float(score["reference_speaker_time_s"]) for score in fixture_scores)
    total_error = sum(float(score["total_error_s"]) for score in fixture_scores)
    aggregate_der_like = total_error / total_ref if total_ref else 0.0

    overlap_refs = [
        score["overlap"]
        for score in fixture_scores
        if float(score["overlap"]["reference_presence_s"]) > 0.0
    ]
    total_ref_overlap_presence = sum(float(overlap["reference_presence_s"]) for overlap in overlap_refs)
    total_pred_overlap_presence = sum(float(overlap["predicted_presence_s"]) for overlap in overlap_refs)
    total_tp_overlap_presence = sum(float(overlap["true_positive_presence_s"]) for overlap in overlap_refs)
    total_ref_overlap_speaker_time = sum(
        float(overlap["reference_speaker_time_s"]) for overlap in overlap_refs
    )
    total_matched_overlap_speaker_time = sum(
        float(overlap["matched_speaker_time_s"]) for overlap in overlap_refs
    )
    aggregate_overlap_presence_recall = (
        total_tp_overlap_presence / total_ref_overlap_presence
        if total_ref_overlap_presence
        else None
    )
    aggregate_overlap_presence_precision = (
        total_tp_overlap_presence / total_pred_overlap_presence
        if total_pred_overlap_presence
        else None
    )
    aggregate_overlap_speaker_time_recall = (
        total_matched_overlap_speaker_time / total_ref_overlap_speaker_time
        if total_ref_overlap_speaker_time
        else None
    )

    der_like_threshold = 0.001 if strict_oracle else 0.15
    overlap_recall_threshold = 0.999 if strict_oracle else 0.70
    overlap_presence_recall_value = (
        1.0 if aggregate_overlap_presence_recall is None else aggregate_overlap_presence_recall
    )
    overlap_speaker_time_recall_value = (
        1.0 if aggregate_overlap_speaker_time_recall is None else aggregate_overlap_speaker_time_recall
    )

    gates = [
        {
            "name": "diarization_der_like",
            "adapter_id": adapter_id,
            "value": round(aggregate_der_like, 6),
            "threshold": f"<= {der_like_threshold}",
            "passed": aggregate_der_like <= der_like_threshold,
        },
        {
            "name": "diarization_overlap_presence_recall",
            "adapter_id": adapter_id,
            "value": (
                None
                if aggregate_overlap_presence_recall is None
                else round(aggregate_overlap_presence_recall, 6)
            ),
            "threshold": f">= {overlap_recall_threshold}",
            "passed": overlap_presence_recall_value >= overlap_recall_threshold,
        },
        {
            "name": "diarization_overlap_speaker_time_recall",
            "adapter_id": adapter_id,
            "value": (
                None
                if aggregate_overlap_speaker_time_recall is None
                else round(aggregate_overlap_speaker_time_recall, 6)
            ),
            "threshold": f">= {overlap_recall_threshold}",
            "passed": overlap_speaker_time_recall_value >= overlap_recall_threshold,
        },
    ]

    return {
        "schema_version": 1,
        "adapter_id": adapter_id,
        "prediction_path": str(prediction_path),
        "strict_oracle_thresholds": strict_oracle,
        "summary": {
            "reference_speaker_time_s": round(total_ref, 6),
            "total_error_s": round(total_error, 6),
            "der_like": round(aggregate_der_like, 6),
            "overlap_presence_recall": (
                None
                if aggregate_overlap_presence_recall is None
                else round(aggregate_overlap_presence_recall, 6)
            ),
            "overlap_presence_precision": (
                None
                if aggregate_overlap_presence_precision is None
                else round(aggregate_overlap_presence_precision, 6)
            ),
            "overlap_speaker_time_recall": (
                None
                if aggregate_overlap_speaker_time_recall is None
                else round(aggregate_overlap_speaker_time_recall, 6)
            ),
            "quality_gates": gates,
        },
        "fixtures": fixture_scores,
        "detractor_loop": {
            "strongest_objection": (
                "Frame-based DER on synthetic tones is only a scorer smoke test. It does not "
                "prove model diarization quality on real rooms, cross-talk, or real speech."
            ),
            "cheapest_falsifying_benchmark": (
                "Score one licensed real overlapped speech fixture with the same JSONL schema "
                "and compare DER, JER, overlap recall, and decision latency."
            ),
            "fallback_if_falsified": (
                "Keep model output behind captions-only or manual-review mode until real "
                "fixtures meet thresholds."
            ),
        },
    }


def score_diarization_predictions(
    annotations: list[dict[str, Any]],
    prediction_path: Path,
    strict_oracle: bool,
) -> dict[str, Any]:
    predictions = read_diarization_predictions(prediction_path)
    known_fixture_ids = {annotation["fixture_id"] for annotation in annotations}
    unknown_fixture_ids = sorted(set(predictions) - known_fixture_ids)
    if unknown_fixture_ids:
        raise ValueError(f"Unknown diarization prediction fixture ids: {unknown_fixture_ids}")

    fixture_scores: list[dict[str, Any]] = []
    adapter_ids: set[str] = set()

    for annotation in annotations:
        prediction = predictions.get(annotation["fixture_id"], empty_diarization_record(annotation))
        adapter_ids.add(str(prediction.get("adapter_id", "unknown_diarization_adapter")))
        fixture_scores.append(score_fixture_diarization(annotation, prediction))

    adapter_id = sorted(adapter_ids)[0] if len(adapter_ids) == 1 else "mixed_diarization_adapters"
    return summarize_diarization_scores(fixture_scores, adapter_id, prediction_path, strict_oracle)


def diarization_scorer_self_test(annotations: list[dict[str, Any]]) -> dict[str, Any]:
    empty_scores = [
        score_fixture_diarization(annotation, empty_diarization_record(annotation))
        for annotation in annotations
    ]
    total_ref = sum(float(score["reference_speaker_time_s"]) for score in empty_scores)
    total_miss = sum(float(score["miss_s"]) for score in empty_scores)
    total_error = sum(float(score["total_error_s"]) for score in empty_scores)
    der_like = total_error / total_ref if total_ref else 0.0

    gates = [
        {
            "name": "diarization_empty_predictions_are_not_oracle",
            "adapter_id": "self_test_empty_prediction",
            "value": round(der_like, 6),
            "threshold": ">= 0.999 DER-like for empty predictions",
            "passed": der_like >= 0.999,
        },
        {
            "name": "diarization_empty_predictions_count_misses",
            "adapter_id": "self_test_empty_prediction",
            "value": round(total_miss, 6),
            "threshold": "> 0 missed speaker seconds",
            "passed": total_miss > 0.0,
        },
    ]

    return {
        "adapter_id": "self_test_empty_prediction",
        "summary": {
            "reference_speaker_time_s": round(total_ref, 6),
            "miss_s": round(total_miss, 6),
            "total_error_s": round(total_error, 6),
            "der_like": round(der_like, 6),
            "quality_gates": gates,
        },
        "fixtures": empty_scores,
    }


def analyze_fixture(output_dir: Path, annotation: dict[str, Any]) -> dict[str, Any]:
    fixture_dir = output_dir / "fixtures" / annotation["fixture_set_id"] / safe_id(annotation["fixture_id"])
    mix_audio, sample_rate_hz = sf.read(fixture_dir / annotation["mix_path"], dtype="float32")
    if mix_audio.ndim > 1:
        mix_audio = np.mean(mix_audio, axis=1)

    segment_reports: list[dict[str, Any]] = []
    for segment in annotation["segments"]:
        stem_path = fixture_dir / segment["stem_path"]
        stem_audio, stem_rate_hz = sf.read(stem_path, dtype="float32")
        if stem_audio.ndim > 1:
            stem_audio = np.mean(stem_audio, axis=1)
        if stem_rate_hz != sample_rate_hz:
            raise ValueError(f"{stem_path} sample rate mismatch")

        start_sample = int(segment["start_sample"])
        end_sample = int(segment["end_sample"])
        window = stem_audio[start_sample:end_sample]
        measured_dbfs = dbfs(window)
        target_dbfs = float(segment["level_dbfs"])
        start_quantization_error_ms = abs(
            (float(segment["start_sample"]) / float(sample_rate_hz) - float(segment["start_s"]))
            * 1000.0
        )
        end_quantization_error_ms = abs(
            (float(segment["end_sample"]) / float(sample_rate_hz) - float(segment["end_s"]))
            * 1000.0
        )
        segment_reports.append(
            {
                "index": int(segment["index"]),
                "speaker_id": segment["speaker_id"],
                "source_kind": segment["source_kind"],
                "language_code": segment["language_code"],
                "start_s": float(segment["start_s"]),
                "end_s": float(segment["end_s"]),
                "target_dbfs": target_dbfs,
                "measured_dbfs": round(measured_dbfs, 3),
                "level_error_db": round(measured_dbfs - target_dbfs, 3),
                "timing_quantization_error_ms": round(
                    max(start_quantization_error_ms, end_quantization_error_ms),
                    3,
                ),
            }
        )

    human_segments = [segment for segment in annotation["segments"] if segment["source_kind"] == "human"]
    languages = sorted({segment["language_code"] for segment in human_segments})
    sources = sorted({segment["source_kind"] for segment in annotation["segments"]})

    return {
        "fixture_id": annotation["fixture_id"],
        "sample_rate_hz": int(sample_rate_hz),
        "duration_s": round(float(mix_audio.shape[0]) / float(sample_rate_hz), 6),
        "mix": {
            "peak_dbfs": round(peak_dbfs(mix_audio), 3),
            "rms_dbfs": round(dbfs(mix_audio), 3),
            "max_abs": round(float(np.max(np.abs(mix_audio))), 6),
        },
        "audio_hashes": {
            "mix_sha256": annotation["mix_sha256"],
            "stems": annotation["stems"],
        },
        "segments": segment_reports,
        "truth": {
            "human_speaker_count": len({segment["speaker_id"] for segment in human_segments}),
            "language_codes": languages,
            "source_kinds": sources,
            "human_overlap": overlap_stats(annotation["segments"], human_only=True),
            "all_source_overlap": overlap_stats(annotation["segments"], human_only=False),
        },
        "detractor_note": annotation["detractor_note"],
    }


def quality_gates(fixture_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_segment_errors = [
        abs(float(segment["level_error_db"]))
        for fixture in fixture_reports
        for segment in fixture["segments"]
    ]
    all_timing_errors = [
        abs(float(segment["timing_quantization_error_ms"]))
        for fixture in fixture_reports
        for segment in fixture["segments"]
    ]
    all_levels = [
        float(segment["target_dbfs"])
        for fixture in fixture_reports
        for segment in fixture["segments"]
        if segment["source_kind"] == "human"
    ]
    all_languages = {
        language
        for fixture in fixture_reports
        for language in fixture["truth"]["language_codes"]
    }
    max_peak = max(float(fixture["mix"]["max_abs"]) for fixture in fixture_reports)
    max_level_error = max(all_segment_errors) if all_segment_errors else float("inf")
    max_timing_error = max(all_timing_errors) if all_timing_errors else float("inf")
    has_human_overlap = any(
        float(fixture["truth"]["human_overlap"]["overlap_s"]) >= 0.5
        for fixture in fixture_reports
    )
    has_playback = any(
        "playback" in fixture["truth"]["source_kinds"]
        for fixture in fixture_reports
    )
    quietest = min(all_levels) if all_levels else float("inf")
    loudest = max(all_levels) if all_levels else float("-inf")

    return [
        {
            "name": "fixture_count",
            "value": len(fixture_reports),
            "threshold": ">= 3 fixtures",
            "passed": len(fixture_reports) >= 3,
        },
        {
            "name": "human_overlap_present",
            "value": has_human_overlap,
            "threshold": "at least one fixture with >= 0.5s human-human overlap",
            "passed": bool(has_human_overlap),
        },
        {
            "name": "multi_language_present",
            "value": sorted(all_languages),
            "threshold": ">= 4 human source languages",
            "passed": len(all_languages) >= 4,
        },
        {
            "name": "volume_extremes_present",
            "value": {
                "quietest_human_dbfs": quietest,
                "loudest_human_dbfs": loudest,
            },
            "threshold": "quiet <= -34 dBFS and loud >= -20 dBFS",
            "passed": quietest <= -34.0 and loudest >= -20.0,
        },
        {
            "name": "playback_loopback_present",
            "value": has_playback,
            "threshold": "at least one playback leakage segment",
            "passed": bool(has_playback),
        },
        {
            "name": "segment_level_error",
            "value": round(max_level_error, 3),
            "threshold": "<= 0.75 dB absolute error on rendered stems",
            "passed": max_level_error <= 0.75,
        },
        {
            "name": "segment_timing_quantization",
            "value": round(max_timing_error, 3),
            "threshold": "<= 20 ms fixture timing quantization error",
            "passed": max_timing_error <= 20.0,
        },
        {
            "name": "mix_not_clipping",
            "value": round(max_peak, 6),
            "threshold": "max absolute mix sample <= 0.98",
            "passed": max_peak <= 0.98,
        },
    ]


def build_report(
    manifest_path: Path,
    output_dir: Path,
    diarization_prediction_path: Path | None = None,
) -> dict[str, Any]:
    annotations = render_fixtures(manifest_path, output_dir)
    fixture_reports = [analyze_fixture(output_dir, annotation) for annotation in annotations]
    fixture_gates = quality_gates(fixture_reports)

    strict_oracle = diarization_prediction_path is None
    if diarization_prediction_path is None:
        diarization_prediction_path = output_dir / "predictions" / "oracle_diarization.jsonl"
        write_jsonl(build_oracle_diarization_records(annotations), diarization_prediction_path)
    diarization_report = score_diarization_predictions(
        annotations,
        diarization_prediction_path,
        strict_oracle=strict_oracle,
    )
    diarization_self_test = diarization_scorer_self_test(annotations)
    gates = [
        *fixture_gates,
        *diarization_report["summary"]["quality_gates"],
        *diarization_self_test["summary"]["quality_gates"],
    ]

    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "manifest_path": str(manifest_path),
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": len(fixture_reports),
            "quality_gates": gates,
        },
        "benchmarks": {
            "diarization": diarization_report,
            "diarization_scorer_self_test": diarization_self_test,
        },
        "latency_accounting": {
            "model_layer_latency_ms": {
                "diarization": None,
                "separation_or_tse": None,
                "language_id": None,
                "asr": None,
                "translation": None,
                "voice_clone_or_tts": None,
                "echo_or_suppression": None,
            },
            "full_loop_latency_ms": {
                "capture_to_translated_playback": None,
            },
            "policy": (
                "Future model benchmarks must fill model-layer latency separately from "
                "capture-to-playback latency."
            ),
        },
        "detractor_loop": {
            "strongest_objection": (
                "Synthetic tones are not speech. Passing this harness only proves the "
                "evaluation plumbing and fixture truth are coherent."
            ),
            "cheapest_falsifying_benchmark": (
                "Add one licensed real-speech overlap fixture and compare DER, WER, "
                "language-ID accuracy, voice-similarity MOS proxy, and loop latency."
            ),
            "fallback_if_falsified": (
                "Keep captions-only or translated-overlay mode until real-speech fixtures "
                "meet thresholds."
            ),
        },
        "fixtures": fixture_reports,
    }


def write_report(report: dict[str, Any], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def print_summary(report: dict[str, Any]) -> None:
    summary = report["summary"]
    status = "PASS" if summary["passed"] else "FAIL"
    print(f"audio-eval {status}: {summary['fixture_count']} fixtures")
    for gate in summary["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audio evaluation fixture harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)

    generate = subparsers.add_parser("generate", help="render fixture WAV files and annotations")
    add_common(generate)

    report = subparsers.add_parser("report", help="render fixtures and write a JSON report")
    add_common(report)
    report.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    report.add_argument("--diarization-predictions", type=Path)

    check = subparsers.add_parser("check", help="render fixtures, write a report, and fail on gates")
    add_common(check)
    check.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    check.add_argument("--diarization-predictions", type=Path)

    oracle = subparsers.add_parser("diarization-oracle", help="write oracle diarization JSONL")
    add_common(oracle)
    oracle.add_argument("--predictions", type=Path, default=DEFAULT_ORACLE_DIARIZATION)

    score_diarization = subparsers.add_parser(
        "score-diarization",
        help="score diarization prediction JSONL against fixture truth",
    )
    add_common(score_diarization)
    score_diarization.add_argument("--predictions", type=Path, required=True)
    score_diarization.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_OUTPUT_DIR / "diarization-report.json",
    )
    score_diarization.add_argument(
        "--strict-oracle",
        action="store_true",
        help="use strict thresholds for known oracle predictions",
    )

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()

    if args.command == "generate":
        annotations = render_fixtures(manifest_path, output_dir)
        print(f"generated {len(annotations)} fixtures under {output_dir}")
        return 0

    if args.command == "diarization-oracle":
        annotations = render_fixtures(manifest_path, output_dir)
        predictions_path = args.predictions.resolve()
        write_jsonl(build_oracle_diarization_records(annotations), predictions_path)
        print(f"wrote oracle diarization predictions to {predictions_path}")
        return 0

    if args.command == "score-diarization":
        annotations = render_fixtures(manifest_path, output_dir)
        report = score_diarization_predictions(
            annotations,
            args.predictions.resolve(),
            strict_oracle=bool(args.strict_oracle),
        )
        write_report(report, args.report.resolve())
        print_summary(
            {
                "summary": {
                    "passed": all(
                        bool(gate["passed"]) for gate in report["summary"]["quality_gates"]
                    ),
                    "fixture_count": len(report["fixtures"]),
                    "quality_gates": report["summary"]["quality_gates"],
                }
            }
        )
        return 0 if all(bool(gate["passed"]) for gate in report["summary"]["quality_gates"]) else 1

    diarization_predictions = (
        args.diarization_predictions.resolve()
        if getattr(args, "diarization_predictions", None)
        else None
    )
    report = build_report(manifest_path, output_dir, diarization_predictions)
    write_report(report, args.report.resolve())
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
