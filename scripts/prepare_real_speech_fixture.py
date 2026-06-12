#!/usr/bin/env python3
"""Prepare a tiny licensed real-speech overlap fixture for audio-eval.

The fixture is intentionally artifact-only: it downloads two small LibriSpeech
dummy rows through the Hugging Face Dataset Viewer API, mixes them with known
speaker timing and levels, then writes annotations compatible with the existing
diarization scorer.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import math
import sys
import time
import urllib.error
import urllib.parse
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
    db_to_linear,
    safe_id,
    scale_to_level,
    score_diarization_predictions,
    sha256_file,
    write_jsonl,
    write_report,
)


DATASET_VIEWER_ROWS_URL = "https://datasets-server.huggingface.co/rows"
DEFAULT_DATASET = "sanchit-gandhi/librispeech_asr_dummy"
DEFAULT_CONFIG = "default"
DEFAULT_FIXTURE_SET_ID = "audio-eval-real-speech-v1"
DEFAULT_FIXTURE_ID = "librispeech_two_speaker_overlap"
DEFAULT_RUN_ID = "real-speech-librispeech-overlap"
DEFAULT_SAMPLE_RATE_HZ = 16000


@dataclass(frozen=True)
class SourceSpec:
    split: str
    row_idx: int
    start_s: float
    max_duration_s: float
    level_dbfs: float


DEFAULT_SOURCES = (
    SourceSpec(
        split="test.clean",
        row_idx=1,
        start_s=0.2,
        max_duration_s=6.0,
        level_dbfs=-24.0,
    ),
    SourceSpec(
        split="test.other",
        row_idx=7,
        start_s=2.0,
        max_duration_s=5.8,
        level_dbfs=-28.0,
    ),
)


def request_json(url: str, retries: int = 4) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Dataset Viewer request failed after {retries} attempts: {url}") from last_error


def fetch_dataset_row(dataset: str, config: str, split: str, row_idx: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "dataset": dataset,
            "config": config,
            "split": split,
            "offset": row_idx,
            "length": 1,
        }
    )
    payload = request_json(f"{DATASET_VIEWER_ROWS_URL}?{query}")
    rows = payload.get("rows", [])
    if len(rows) != 1 or int(rows[0]["row_idx"]) != row_idx:
        raise RuntimeError(f"Expected exactly row {row_idx} from {dataset}/{split}, got {rows!r}")
    return rows[0]["row"]


def download_url(url: str, retries: int = 4) -> bytes:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=90) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Audio download failed after {retries} attempts") from last_error


def audio_bytes_from_row(row: dict[str, Any]) -> bytes:
    audio = row.get("audio")
    if isinstance(audio, dict):
        encoded = audio.get("bytes")
        if encoded:
            return base64.b64decode(encoded)
        src = audio.get("src")
        if src:
            return download_url(str(src))
    if isinstance(audio, list):
        for item in audio:
            if isinstance(item, dict) and item.get("src"):
                return download_url(str(item["src"]))
    raise RuntimeError(f"Dataset row {row.get('id')} does not contain downloadable audio")


def load_row_audio(row: dict[str, Any], sample_rate_hz: int) -> np.ndarray:
    raw = audio_bytes_from_row(row)
    audio, source_rate_hz = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = np.mean(audio, axis=1)
    if int(source_rate_hz) != sample_rate_hz:
        divisor = math.gcd(int(source_rate_hz), sample_rate_hz)
        audio = resample_poly(
            audio,
            sample_rate_hz // divisor,
            int(source_rate_hz) // divisor,
        ).astype(np.float32)
    return np.asarray(audio, dtype=np.float32)


def trim_silence(
    samples: np.ndarray,
    sample_rate_hz: int,
    threshold_dbfs: float = -46.0,
    pad_s: float = 0.08,
) -> np.ndarray:
    frame_len = max(1, int(round(sample_rate_hz * 0.025)))
    hop_len = max(1, int(round(sample_rate_hz * 0.010)))
    threshold = db_to_linear(threshold_dbfs)

    active_starts: list[int] = []
    for start in range(0, max(1, samples.size - frame_len + 1), hop_len):
        frame = samples[start : start + frame_len]
        if frame.size and float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) >= threshold:
            active_starts.append(start)

    if not active_starts:
        return samples

    pad = int(round(pad_s * sample_rate_hz))
    start = max(0, active_starts[0] - pad)
    end = min(samples.size, active_starts[-1] + frame_len + pad)
    return samples[start:end]


def prepare_source_audio(
    dataset: str,
    config: str,
    spec: SourceSpec,
    sample_rate_hz: int,
) -> dict[str, Any]:
    row = fetch_dataset_row(dataset, config, spec.split, spec.row_idx)
    samples = trim_silence(load_row_audio(row, sample_rate_hz), sample_rate_hz)
    max_frames = int(round(spec.max_duration_s * sample_rate_hz))
    samples = samples[:max_frames]
    if samples.size < int(round(1.5 * sample_rate_hz)):
        raise RuntimeError(f"{row['id']} is too short after silence trimming")

    samples = apply_fade(samples, sample_rate_hz)
    samples = scale_to_level(samples, spec.level_dbfs).astype(np.float32)
    original_speaker_id = str(row["speaker_id"])
    track_id = safe_id(f"speaker_{original_speaker_id}")
    return {
        "row": row,
        "spec": spec,
        "track_id": track_id,
        "audio": samples,
        "duration_s": samples.size / float(sample_rate_hz),
        "measured_dbfs": dbfs(samples),
    }


def fixture_dir(output_dir: Path, fixture_set_id: str, fixture_id: str) -> Path:
    return output_dir / "fixtures" / fixture_set_id / safe_id(fixture_id)


def prepare_real_speech_fixture(
    output_dir: Path,
    dataset: str = DEFAULT_DATASET,
    config: str = DEFAULT_CONFIG,
    fixture_set_id: str = DEFAULT_FIXTURE_SET_ID,
    fixture_id: str = DEFAULT_FIXTURE_ID,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    sources: tuple[SourceSpec, ...] = DEFAULT_SOURCES,
) -> dict[str, Any]:
    if len(sources) < 2:
        raise RuntimeError("Real-speech fixture requires at least two source rows")

    prepared = [prepare_source_audio(dataset, config, source, sample_rate_hz) for source in sources]
    original_speakers = {str(source["row"]["speaker_id"]) for source in prepared}
    if len(original_speakers) < 2:
        raise RuntimeError(f"Real-speech fixture needs distinct source speakers, got {original_speakers}")

    end_s = max(float(source["spec"].start_s) + float(source["duration_s"]) for source in prepared)
    duration_s = round(end_s + 0.35, 3)
    frame_count = int(round(duration_s * sample_rate_hz))
    target_dir = fixture_dir(output_dir, fixture_set_id, fixture_id)
    stem_dir = target_dir / "stems"
    source_dir = target_dir / "source_clips"
    stem_dir.mkdir(parents=True, exist_ok=True)
    source_dir.mkdir(parents=True, exist_ok=True)

    mix = np.zeros(frame_count, dtype=np.float32)
    segments: list[dict[str, Any]] = []
    stems: list[dict[str, str]] = []

    for index, source in enumerate(prepared):
        spec: SourceSpec = source["spec"]
        row = source["row"]
        audio = source["audio"]
        track_id = source["track_id"]
        start_sample = int(round(spec.start_s * sample_rate_hz))
        end_sample = start_sample + audio.size
        if end_sample > frame_count:
            raise RuntimeError(f"{row['id']} does not fit inside fixture duration")

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

        clip_path = source_dir / f"{safe_id(str(row['id']))}.wav"
        sf.write(clip_path, audio, sample_rate_hz, subtype=PCM_SUBTYPE)

        segments.append(
            {
                "index": index,
                "speaker_id": track_id,
                "source_kind": "human",
                "language_code": "en",
                "voice_profile": f"librispeech_speaker_{row['speaker_id']}",
                "text": row["text"],
                "start_s": round(float(spec.start_s), 6),
                "end_s": round(end_sample / float(sample_rate_hz), 6),
                "start_sample": start_sample,
                "end_sample": end_sample,
                "level_dbfs": float(spec.level_dbfs),
                "stem_path": f"stems/{track_id}.wav",
                "source_clip_path": f"source_clips/{safe_id(str(row['id']))}.wav",
                "source_dataset": {
                    "dataset": dataset,
                    "config": config,
                    "split": spec.split,
                    "row_idx": spec.row_idx,
                    "row_id": row["id"],
                    "speaker_id": row["speaker_id"],
                    "chapter_id": row.get("chapter_id"),
                },
            }
        )

    max_abs = float(np.max(np.abs(mix))) if mix.size else 0.0
    if max_abs > 0.98:
        raise RuntimeError(f"Real-speech fixture mix would clip: max_abs={max_abs:.6f}")

    mix_path = target_dir / "mix.wav"
    sf.write(mix_path, mix, sample_rate_hz, subtype=PCM_SUBTYPE)
    annotation = {
        "schema_version": 1,
        "fixture_set_id": fixture_set_id,
        "fixture_id": fixture_id,
        "description": (
            "Two distinct LibriSpeech dummy speakers mixed with known overlap and level truth "
            "for a tiny real-speech diarization smoke test."
        ),
        "sample_rate_hz": sample_rate_hz,
        "duration_s": duration_s,
        "mix_path": "mix.wav",
        "mix_sha256": sha256_file(mix_path),
        "stems": stems,
        "background_noise_dbfs": None,
        "segments": segments,
        "source_license": "LibriSpeech / OpenSLR SLR12, CC BY 4.0",
        "source_url": "https://huggingface.co/datasets/sanchit-gandhi/librispeech_asr_dummy",
        "detractor_note": (
            "This is real read speech, but the overlap is synthetically mixed from clean "
            "audiobook clips. It does not prove live room capture, multilingual speech, "
            "far-field robustness, or realtime behavior."
        ),
    }
    (target_dir / "annotations.json").write_text(
        json.dumps(annotation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return annotation


def real_speech_gates(fixture_report: dict[str, Any], diarization_report: dict[str, Any]) -> list[dict[str, Any]]:
    human_segments = [
        segment for segment in fixture_report["segments"] if segment["source_kind"] == "human"
    ]
    target_levels = [float(segment["target_dbfs"]) for segment in human_segments]
    overlap_s = float(fixture_report["truth"]["human_overlap"]["overlap_s"])
    speaker_count = int(fixture_report["truth"]["human_speaker_count"])
    max_abs = float(fixture_report["mix"]["max_abs"])
    level_spread = max(target_levels) - min(target_levels) if target_levels else 0.0

    return [
        {
            "name": "real_speech_fixture_count",
            "value": 1,
            "threshold": "one tiny real-speech fixture",
            "passed": True,
        },
        {
            "name": "real_speech_distinct_speakers",
            "value": speaker_count,
            "threshold": ">= 2 speakers",
            "passed": speaker_count >= 2,
        },
        {
            "name": "real_speech_overlap_present",
            "value": round(overlap_s, 6),
            "threshold": ">= 2.0s human-human overlap",
            "passed": overlap_s >= 2.0,
        },
        {
            "name": "real_speech_volume_spread",
            "value": round(level_spread, 3),
            "threshold": ">= 3 dB target level spread",
            "passed": level_spread >= 3.0,
        },
        {
            "name": "real_speech_mix_not_clipping",
            "value": round(max_abs, 6),
            "threshold": "max absolute mix sample <= 0.98",
            "passed": max_abs <= 0.98,
        },
        *diarization_report["summary"]["quality_gates"],
    ]


def build_check_report(annotation: dict[str, Any], output_dir: Path, run_id: str) -> dict[str, Any]:
    annotations = [annotation]
    run_dir = output_dir / "runs" / run_id
    predictions_path = run_dir / "oracle_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records(annotations), predictions_path)
    diarization_report = score_diarization_predictions(
        annotations,
        predictions_path,
        strict_oracle=True,
    )
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = real_speech_gates(fixture_report, diarization_report)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_speech_mixed_overlap",
        "output_dir": str(output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "fixture_count": 1,
            "quality_gates": gates,
        },
        "benchmarks": {
            "diarization": diarization_report,
        },
        "fixtures": [fixture_report],
        "detractor_loop": {
            "strongest_objection": (
                "A tiny clean LibriSpeech mix can catch broken plumbing and obvious diarization "
                "failures, but it is not evidence that the product works in a noisy live room."
            ),
            "cheapest_falsifying_benchmark": (
                "Run pyannote and the selected online diarizer on this fixture, then add one "
                "consented local room recording with measured overlap."
            ),
            "fallback_if_falsified": (
                "Keep real model output in benchmark-only mode and continue using the product-shaped "
                "mock path until real fixtures pass."
            ),
        },
    }


def print_real_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(f"real-speech audio-eval {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare tiny real-speech audio-eval fixture")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        subparser.add_argument("--dataset", default=DEFAULT_DATASET)
        subparser.add_argument("--config", default=DEFAULT_CONFIG)
        subparser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
        subparser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
        subparser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)

    prepare = subparsers.add_parser("prepare", help="download, mix, and annotate the fixture")
    add_common(prepare)

    check = subparsers.add_parser("check", help="prepare fixture and run oracle scorer gates")
    add_common(check)
    check.add_argument("--run-id", default=DEFAULT_RUN_ID)
    check.add_argument(
        "--report",
        type=Path,
        default=None,
        help="defaults to artifacts/audio_eval/runs/<run-id>/real-speech-fixture-report.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    annotation = prepare_real_speech_fixture(
        output_dir=output_dir,
        dataset=args.dataset,
        config=args.config,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        sample_rate_hz=args.sample_rate_hz,
    )
    annotation_path = fixture_dir(output_dir, args.fixture_set_id, args.fixture_id) / "annotations.json"
    print(f"wrote real-speech fixture annotations to {annotation_path}")

    if args.command == "prepare":
        return 0

    report_path = (
        args.report.resolve()
        if args.report
        else output_dir / "runs" / args.run_id / "real-speech-fixture-report.json"
    )
    report = build_check_report(annotation, output_dir, args.run_id)
    write_report(report, report_path)
    print(f"wrote real-speech fixture report to {report_path}")
    print_real_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
