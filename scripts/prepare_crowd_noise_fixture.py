#!/usr/bin/env python3
"""Prepare a tiny real-speech fixture augmented with public crowd ambience.

This keeps the speaker truth from the LibriSpeech overlap fixture, then mixes a
license-reviewed FSD50K/Freesound crowd clip underneath it. Third-party audio is
downloaded only into ignored artifacts.
"""

from __future__ import annotations

import argparse
import csv
import html
import io
import json
import re
import subprocess
import sys
import tempfile
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
    scale_to_level,
    score_diarization_predictions,
    sha256_file,
    stable_seed,
    write_jsonl,
    write_report,
)
from prepare_real_speech_fixture import (
    DEFAULT_SAMPLE_RATE_HZ,
    fixture_dir,
    prepare_real_speech_fixture,
    real_speech_gates,
)


DEFAULT_FIXTURE_SET_ID = "audio-eval-crowd-noise-v1"
DEFAULT_FIXTURE_ID = "librispeech_overlap_fsd50k_crowd_noise"
DEFAULT_RUN_ID = "real-speech-fsd50k-crowd-noise"
DEFAULT_FSD50K_CLIP_ID = "184833"
DEFAULT_NOISE_LEVEL_DBFS = -35.0
FSD50K_GROUND_TRUTH_URL = (
    "https://huggingface.co/datasets/yanei/fsd50k/resolve/main/ground_truth/dev.csv"
)
FSD50K_METADATA_URL = (
    "https://huggingface.co/datasets/yanei/fsd50k/resolve/main/metadata/dev_clips_info_FSD50K.json"
)
FREESOUND_SHORT_URL = "https://freesound.org/s/{clip_id}/"
USER_AGENT = "LanguageAudioEval/0.1 (+https://github.com/Donovoi/Language)"

PREFERRED_LABELS = (
    "Crowd",
    "Chatter",
    "Cheering",
    "Applause",
    "Conversation",
)

ALLOWED_LICENSES = {
    "http://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
    "https://creativecommons.org/publicdomain/zero/1.0/": "CC0-1.0",
    "http://creativecommons.org/licenses/by/3.0/": "CC-BY-3.0",
    "https://creativecommons.org/licenses/by/3.0/": "CC-BY-3.0",
    "http://creativecommons.org/licenses/by/4.0/": "CC-BY-4.0",
    "https://creativecommons.org/licenses/by/4.0/": "CC-BY-4.0",
}


@dataclass(frozen=True)
class NoiseClip:
    clip_id: str
    labels: tuple[str, ...]
    mids: tuple[str, ...]
    fsd50k_dev_split: str
    title: str
    uploader: str
    license_url: str
    license_name: str
    freesound_page_url: str
    preview_url: str


def request_bytes(url: str, retries: int = 4) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(request, timeout=90) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc
            if attempt + 1 == retries:
                break
            time.sleep(0.75 * (attempt + 1))
    raise RuntimeError(f"Request failed after {retries} attempts: {url}") from last_error


def request_text(url: str) -> str:
    return request_bytes(url).decode("utf-8")


def request_json(url: str) -> dict[str, Any]:
    return json.loads(request_text(url))


def load_fsd50k_ground_truth() -> dict[str, dict[str, Any]]:
    rows = csv.DictReader(io.StringIO(request_text(FSD50K_GROUND_TRUTH_URL)))
    return {
        str(row["fname"]): {
            "labels": tuple(label for label in row["labels"].split(",") if label),
            "mids": tuple(mid for mid in row["mids"].split(",") if mid),
            "split": row["split"],
        }
        for row in rows
    }


def choose_preview_url(html_text: str) -> str:
    matches = []
    for match in re.findall(r"https://cdn\.freesound\.org/previews/[^\"'<> ]+", html_text):
        unescaped = html.unescape(match)
        if unescaped not in matches:
            matches.append(unescaped)
    if not matches:
        raise RuntimeError("Freesound page did not expose a public preview URL")

    def priority(url: str) -> tuple[int, str]:
        if "-hq.mp3" in url:
            return (0, url)
        if "-hq.ogg" in url:
            return (1, url)
        if "-lq.ogg" in url:
            return (2, url)
        if "-lq.mp3" in url:
            return (3, url)
        return (4, url)

    return sorted(matches, key=priority)[0]


def select_noise_clip(clip_id: str) -> NoiseClip:
    ground_truth = load_fsd50k_ground_truth()
    metadata = request_json(FSD50K_METADATA_URL)
    selected_id = choose_auto_clip(ground_truth, metadata) if clip_id == "auto" else clip_id
    truth = ground_truth.get(selected_id)
    details = metadata.get(selected_id)
    if not truth or not details:
        raise RuntimeError(f"FSD50K clip {selected_id} was not found in dev metadata")

    labels = tuple(str(label) for label in truth["labels"])
    if not set(labels).intersection(PREFERRED_LABELS):
        raise RuntimeError(
            f"FSD50K clip {selected_id} lacks preferred crowd labels: {', '.join(labels)}"
        )

    license_url = str(details.get("license", ""))
    license_name = ALLOWED_LICENSES.get(license_url)
    if not license_name:
        raise RuntimeError(f"FSD50K clip {selected_id} has unapproved license: {license_url}")

    page_html = request_text(FREESOUND_SHORT_URL.format(clip_id=selected_id))
    canonical_match = re.search(r"https://freesound\.org/people/[^\"'<> ]+/sounds/[0-9]+/", page_html)
    page_url = html.unescape(canonical_match.group(0)) if canonical_match else FREESOUND_SHORT_URL.format(clip_id=selected_id)

    return NoiseClip(
        clip_id=selected_id,
        labels=labels,
        mids=tuple(str(mid) for mid in truth["mids"]),
        fsd50k_dev_split=str(truth["split"]),
        title=str(details.get("title", "")),
        uploader=str(details.get("uploader", "")),
        license_url=license_url,
        license_name=license_name,
        freesound_page_url=page_url,
        preview_url=choose_preview_url(page_html),
    )


def choose_auto_clip(
    ground_truth: dict[str, dict[str, Any]],
    metadata: dict[str, Any],
) -> str:
    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[int, int, int]:
        candidate_id, truth = item
        labels = set(truth["labels"])
        label_rank = min(
            (index for index, label in enumerate(PREFERRED_LABELS) if label in labels),
            default=len(PREFERRED_LABELS),
        )
        details = metadata.get(candidate_id, {})
        license_name = ALLOWED_LICENSES.get(str(details.get("license", "")), "")
        license_rank = 0 if license_name == "CC0-1.0" else 1
        return (label_rank, license_rank, int(candidate_id))

    candidates = [
        (candidate_id, truth)
        for candidate_id, truth in ground_truth.items()
        if set(truth["labels"]).intersection(PREFERRED_LABELS)
        and ALLOWED_LICENSES.get(str(metadata.get(candidate_id, {}).get("license", "")))
    ]
    if not candidates:
        raise RuntimeError("No approved FSD50K crowd/noise candidates were found")
    return sorted(candidates, key=sort_key)[0][0]


def decode_audio_bytes(raw: bytes, source_url: str, sample_rate_hz: int) -> np.ndarray:
    suffix = Path(urllib.parse.urlparse(source_url).path).suffix or ".audio"
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            input_path = Path(tmp_dir) / f"source{suffix}"
            output_path = Path(tmp_dir) / "decoded.wav"
            input_path.write_bytes(raw)
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(input_path),
                    "-ac",
                    "1",
                    "-ar",
                    str(sample_rate_hz),
                    str(output_path),
                ],
                check=True,
            )
            audio, source_rate_hz = sf.read(output_path, dtype="float32", always_2d=False)
    except (FileNotFoundError, subprocess.CalledProcessError):
        audio, source_rate_hz = sf.read(io.BytesIO(raw), dtype="float32", always_2d=False)

    if getattr(audio, "ndim", 1) > 1:
        audio = np.mean(audio, axis=1)
    audio = np.asarray(audio, dtype=np.float32)
    if int(source_rate_hz) != sample_rate_hz:
        divisor = int(np.gcd(int(source_rate_hz), sample_rate_hz))
        audio = resample_poly(
            audio,
            sample_rate_hz // divisor,
            int(source_rate_hz) // divisor,
        ).astype(np.float32)
    if audio.size < sample_rate_hz:
        raise RuntimeError("Downloaded crowd/noise preview is too short for a fixture")
    return audio


def tile_noise(
    noise: np.ndarray,
    frame_count: int,
    sample_rate_hz: int,
    fixture_id: str,
) -> np.ndarray:
    if noise.size >= frame_count:
        max_offset = noise.size - frame_count
        offset = int(stable_seed(fixture_id, "fsd50k_noise_offset") % (max_offset + 1))
        window = noise[offset : offset + frame_count]
    else:
        repeats = int(np.ceil(frame_count / float(noise.size)))
        window = np.tile(noise, repeats)[:frame_count]
    return apply_fade(np.asarray(window, dtype=np.float32), sample_rate_hz, fade_ms=30.0)


def prepare_crowd_noise_fixture(
    output_dir: Path,
    fixture_set_id: str = DEFAULT_FIXTURE_SET_ID,
    fixture_id: str = DEFAULT_FIXTURE_ID,
    sample_rate_hz: int = DEFAULT_SAMPLE_RATE_HZ,
    clip_id: str = DEFAULT_FSD50K_CLIP_ID,
    noise_level_dbfs: float = DEFAULT_NOISE_LEVEL_DBFS,
) -> dict[str, Any]:
    annotation = prepare_real_speech_fixture(
        output_dir=output_dir,
        fixture_set_id=fixture_set_id,
        fixture_id=fixture_id,
        sample_rate_hz=sample_rate_hz,
    )
    target_dir = fixture_dir(output_dir, fixture_set_id, fixture_id)
    noise_dir = target_dir / "external_corpora" / "fsd50k-crowd-ambience"
    noise_dir.mkdir(parents=True, exist_ok=True)

    clip = select_noise_clip(clip_id)
    preview_bytes = request_bytes(clip.preview_url)
    suffix = Path(urllib.parse.urlparse(clip.preview_url).path).suffix or ".bin"
    preview_path = noise_dir / f"freesound_{clip.clip_id}_preview{suffix}"
    preview_path.write_bytes(preview_bytes)

    mix_path = target_dir / annotation["mix_path"]
    mix_audio, mix_rate_hz = sf.read(mix_path, dtype="float32", always_2d=False)
    if getattr(mix_audio, "ndim", 1) > 1:
        mix_audio = np.mean(mix_audio, axis=1)
    if int(mix_rate_hz) != sample_rate_hz:
        raise RuntimeError(f"Fixture mix sample rate mismatch: {mix_rate_hz} != {sample_rate_hz}")

    decoded = decode_audio_bytes(preview_bytes, clip.preview_url, sample_rate_hz)
    noise = scale_to_level(
        tile_noise(decoded, int(mix_audio.shape[0]), sample_rate_hz, fixture_id),
        noise_level_dbfs,
    ).astype(np.float32)
    noise_path = noise_dir / f"fsd50k_{clip.clip_id}_noise.wav"
    sf.write(noise_path, noise, sample_rate_hz, subtype=PCM_SUBTYPE)

    augmented_mix = np.asarray(mix_audio, dtype=np.float32) + noise
    max_abs = float(np.max(np.abs(augmented_mix))) if augmented_mix.size else 0.0
    if max_abs > 0.98:
        raise RuntimeError(f"Crowd-noise fixture mix would clip: max_abs={max_abs:.6f}")
    sf.write(mix_path, augmented_mix, sample_rate_hz, subtype=PCM_SUBTYPE)

    annotation.update(
        {
            "description": (
                "Two distinct LibriSpeech dummy speakers mixed with known overlap and levels, "
                "augmented with a license-reviewed FSD50K/Freesound crowd ambience preview."
            ),
            "mix_sha256": sha256_file(mix_path),
            "background_noise_dbfs": float(noise_level_dbfs),
            "external_corpora": [
                {
                    "corpus_id": "fsd50k-crowd-ambience",
                    "source": "FSD50K metadata plus Freesound public preview",
                    "clip_id": clip.clip_id,
                    "labels": list(clip.labels),
                    "mids": list(clip.mids),
                    "fsd50k_dev_split": clip.fsd50k_dev_split,
                    "title": clip.title,
                    "uploader": clip.uploader,
                    "license": clip.license_name,
                    "license_url": clip.license_url,
                    "freesound_page_url": clip.freesound_page_url,
                    "preview_url": clip.preview_url,
                    "preview_path": str(preview_path.relative_to(target_dir)),
                    "preview_sha256": sha256_file(preview_path),
                    "noise_stem_path": str(noise_path.relative_to(target_dir)),
                    "noise_stem_sha256": sha256_file(noise_path),
                    "target_dbfs": float(noise_level_dbfs),
                    "measured_dbfs": round(dbfs(noise), 3),
                }
            ],
            "source_url": "https://huggingface.co/datasets/yanei/fsd50k",
            "detractor_note": (
                "This adds real public crowd ambience, but it still uses clean read English speech "
                "for speaker truth. The Freesound preview is low-bandwidth benchmark ambience, not "
                "speaker-labeled meeting speech, and it does not prove live source suppression."
            ),
        }
    )
    (target_dir / "annotations.json").write_text(
        json.dumps(annotation, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return annotation


def crowd_noise_gates(
    annotation: dict[str, Any],
    fixture_report: dict[str, Any],
    diarization_report: dict[str, Any],
) -> list[dict[str, Any]]:
    external = annotation.get("external_corpora", [])
    noise = external[0] if external else {}
    labels = set(noise.get("labels", []))
    measured_dbfs = float(noise.get("measured_dbfs", float("inf")))
    target_dbfs = float(noise.get("target_dbfs", float("inf")))
    gates = real_speech_gates(fixture_report, diarization_report)
    gates.extend(
        [
            {
                "name": "external_crowd_noise_source_present",
                "value": len(external),
                "threshold": ">= 1 reviewed external noise source",
                "passed": len(external) >= 1,
            },
            {
                "name": "external_crowd_noise_license_allowed",
                "value": noise.get("license"),
                "threshold": "CC0 or CC-BY clip-level license",
                "passed": noise.get("license") in {"CC0-1.0", "CC-BY-3.0", "CC-BY-4.0"},
            },
            {
                "name": "external_crowd_noise_has_crowd_label",
                "value": sorted(labels),
                "threshold": f"one of {', '.join(PREFERRED_LABELS)}",
                "passed": bool(labels.intersection(PREFERRED_LABELS)),
            },
            {
                "name": "external_crowd_noise_level",
                "value": round(measured_dbfs, 3),
                "threshold": f"within 0.75 dB of {target_dbfs:.1f} dBFS",
                "passed": abs(measured_dbfs - target_dbfs) <= 0.75,
            },
            {
                "name": "external_crowd_noise_mix_not_clipping",
                "value": fixture_report["mix"]["max_abs"],
                "threshold": "max absolute mix sample <= 0.98",
                "passed": float(fixture_report["mix"]["max_abs"]) <= 0.98,
            },
        ]
    )
    return gates


def build_check_report(annotation: dict[str, Any], output_dir: Path, run_id: str) -> dict[str, Any]:
    run_dir = output_dir / "runs" / run_id
    predictions_path = run_dir / "oracle_predictions.jsonl"
    write_jsonl(build_oracle_diarization_records([annotation]), predictions_path)
    diarization_report = score_diarization_predictions(
        [annotation],
        predictions_path,
        strict_oracle=True,
    )
    fixture_report = analyze_fixture(output_dir, annotation)
    gates = crowd_noise_gates(annotation, fixture_report, diarization_report)
    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "real_speech_with_external_crowd_noise",
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
        "external_corpora": annotation.get("external_corpora", []),
        "detractor_loop": {
            "strongest_objection": (
                "A single Freesound/FSD50K crowd preview only tests noise robustness plumbing. "
                "It is not labeled overlapping meeting speech and should not be used for voice cloning."
            ),
            "cheapest_falsifying_benchmark": (
                "Run the same rolling diarization path on this augmented fixture and compare DER-like, "
                "overlap recall, and first-speaker latency against the clean LibriSpeech mix."
            ),
            "fallback_if_falsified": (
                "Keep the noise source as a benchmark-only augmentation and lower the app's confidence "
                "or request a quieter capture path until real-room fixtures pass."
            ),
        },
    }


def print_summary(report: dict[str, Any]) -> None:
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(f"crowd-noise audio-eval {status}: {report['summary']['fixture_count']} fixture")
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare real-speech fixture with FSD50K crowd noise")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
        subparser.add_argument("--fixture-set-id", default=DEFAULT_FIXTURE_SET_ID)
        subparser.add_argument("--fixture-id", default=DEFAULT_FIXTURE_ID)
        subparser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
        subparser.add_argument(
            "--fsd50k-clip-id",
            default=DEFAULT_FSD50K_CLIP_ID,
            help="FSD50K clip id to use, or 'auto' to pick the first approved crowd candidate",
        )
        subparser.add_argument("--noise-level-dbfs", type=float, default=DEFAULT_NOISE_LEVEL_DBFS)

    prepare = subparsers.add_parser("prepare", help="download, augment, and annotate the fixture")
    add_common(prepare)

    check = subparsers.add_parser("check", help="prepare fixture and run oracle scorer gates")
    add_common(check)
    check.add_argument("--run-id", default=DEFAULT_RUN_ID)
    check.add_argument(
        "--report",
        type=Path,
        default=None,
        help="defaults to artifacts/audio_eval/runs/<run-id>/crowd-noise-fixture-report.json",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    output_dir = args.output_dir.resolve()
    annotation = prepare_crowd_noise_fixture(
        output_dir=output_dir,
        fixture_set_id=args.fixture_set_id,
        fixture_id=args.fixture_id,
        sample_rate_hz=args.sample_rate_hz,
        clip_id=args.fsd50k_clip_id,
        noise_level_dbfs=args.noise_level_dbfs,
    )
    annotation_path = fixture_dir(output_dir, args.fixture_set_id, args.fixture_id) / "annotations.json"
    print(f"wrote crowd-noise fixture annotations to {annotation_path}")

    if args.command == "prepare":
        return 0

    report_path = (
        args.report.resolve()
        if args.report
        else output_dir / "runs" / args.run_id / "crowd-noise-fixture-report.json"
    )
    report = build_check_report(annotation, output_dir, args.run_id)
    write_report(report, report_path)
    print(f"wrote crowd-noise fixture report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
