#!/usr/bin/env python3
"""Score measured headphone/earpiece source isolation.

This is an alternate release-evidence path for listener-local source reduction.
It does not claim room-wide source cancellation. It requires measured listener-ear
recordings with and without the headphone/earpiece isolation path, plus a separate
translated-playback fidelity recording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "headphone-earpiece-isolation"
DEFAULT_ADAPTER_ID = "listener_headphone_earpiece_isolation_measurement_v1"
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_MIN_SOURCE_OPEN_DBFS = -60.0
DEFAULT_MIN_TRANSLATED_DBFS = -60.0
DEFAULT_MIN_SOURCE_OPEN_CORRELATION = 0.30
DEFAULT_MIN_TRANSLATED_CORRELATION = 0.30
DEFAULT_MIN_SOURCE_ISOLATION_DB = 12.0
DEFAULT_MIN_MEASUREMENT_DURATION_S = 1.0
DEFAULT_MAX_TRANSLATED_DISTORTION_DB = 12.0
DEFAULT_MAX_ALIGNMENT_LAG_MS = 500.0
FIXTURE_KIND = "headphone_earpiece_isolation"
BENCHMARK_NAME = "headphone_earpiece_isolation"
MEASUREMENT_KIND = "headphone_earpiece_isolation"
SUPPRESSION_MODE = "HEADPHONE_ISOLATED"
SUPPRESSION_CLAIM = "headphone_isolated_not_true_cancellation"
PLACEHOLDER_LABEL_PREFIXES = ("unspecified", "unknown", "todo", "placeholder")


def linear_to_db(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return float(20.0 * math.log10(value))


def db_to_linear(value: float) -> float:
    return float(10.0 ** (value / 20.0))


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))


def dbfs(samples: np.ndarray) -> float:
    return linear_to_db(rms(samples))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def specific_label(value: Any) -> bool:
    text = str(value).strip()
    return bool(text) and not text.lower().startswith(PLACEHOLDER_LABEL_PREFIXES)


def measurement_identity_fingerprint(
    *,
    artifact_hashes: dict[str, str],
    headphone_device_label: str,
    isolation_fixture_label: str,
    measurement_microphone_label: str,
    sample_rate_hz: int,
) -> str:
    payload = {
        "artifact_hashes": artifact_hashes,
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "measurement_kind": MEASUREMENT_KIND,
        "measurement_microphone_label": measurement_microphone_label,
        "sample_rate_hz": int(sample_rate_hz),
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def read_mono_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate_hz = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"{path} must be PCM_16 WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1).astype(np.float32)
    if samples.size <= 0:
        raise ValueError(f"{path} must contain frames")
    return samples.astype(np.float32), int(sample_rate_hz)


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm.tobytes())


def projection_gain(target: np.ndarray, reference: np.ndarray) -> float:
    frame_count = min(int(target.size), int(reference.size))
    if frame_count <= 0:
        return 0.0
    target = target[:frame_count].astype(np.float64)
    reference = reference[:frame_count].astype(np.float64)
    denominator = float(np.dot(reference, reference))
    if denominator <= 1.0e-12:
        return 0.0
    return float(np.dot(target, reference) / denominator)


def correlation(a: np.ndarray, b: np.ndarray) -> float:
    frame_count = min(int(a.size), int(b.size))
    if frame_count <= 1:
        return 0.0
    x = a[:frame_count].astype(np.float64)
    y = b[:frame_count].astype(np.float64)
    x -= float(np.mean(x))
    y -= float(np.mean(y))
    denominator = float(np.sqrt(np.dot(x, x) * np.dot(y, y)))
    if denominator <= 1.0e-12:
        return 0.0
    return float(np.dot(x, y) / denominator)


def distortion_db(measured: np.ndarray, reference: np.ndarray) -> float:
    frame_count = min(int(measured.size), int(reference.size))
    if frame_count <= 0:
        return float("inf")
    measured = measured[:frame_count]
    reference = reference[:frame_count]
    gain = projection_gain(measured, reference)
    aligned = reference * gain
    error = measured - aligned
    return linear_to_db((rms(error) + 1.0e-12) / (rms(aligned) + 1.0e-12))


def align_pair(a: np.ndarray, b: np.ndarray, lag_samples: int) -> tuple[np.ndarray, np.ndarray]:
    frame_count = min(int(a.size), int(b.size))
    if frame_count <= 0:
        return a[:0], b[:0]
    if lag_samples > 0:
        lag = min(lag_samples, frame_count)
        count = min(int(a.size) - lag, int(b.size))
        return a[lag : lag + count], b[:count]
    if lag_samples < 0:
        lag = min(-lag_samples, frame_count)
        count = min(int(a.size), int(b.size) - lag)
        return a[:count], b[lag : lag + count]
    count = frame_count
    return a[:count], b[:count]


def best_alignment_lag_samples(
    measured: np.ndarray,
    reference: np.ndarray,
    sample_rate_hz: int,
    max_lag_ms: float,
    *,
    stride: int = 64,
) -> int:
    frame_count = min(int(measured.size), int(reference.size))
    max_lag_samples = max(0, int(round(float(sample_rate_hz) * float(max_lag_ms) / 1000.0)))
    if frame_count <= stride * 2 or max_lag_samples <= 0:
        return 0
    x = measured[:frame_count:stride].astype(np.float64)
    y = reference[:frame_count:stride].astype(np.float64)
    x -= float(np.mean(x))
    y -= float(np.mean(y))
    max_lag_steps = min(max_lag_samples // stride, max(0, min(x.size, y.size) - 2))
    best_lag_steps = 0
    best_score = float("-inf")
    for lag_steps in range(-max_lag_steps, max_lag_steps + 1):
        if lag_steps > 0:
            a = x[lag_steps:]
            b = y[: a.size]
        elif lag_steps < 0:
            a = x[: x.size + lag_steps]
            b = y[-lag_steps : -lag_steps + a.size]
        else:
            a = x
            b = y[: a.size]
        if a.size <= 1:
            continue
        denominator = float(np.sqrt(np.dot(a, a) * np.dot(b, b)))
        if denominator <= 1.0e-12:
            continue
        score = abs(float(np.dot(a, b) / denominator))
        if score > best_score:
            best_score = score
            best_lag_steps = lag_steps
    return int(best_lag_steps * stride)


def reference_metrics(
    recording: np.ndarray,
    reference: np.ndarray,
    sample_rate_hz: int,
    max_lag_ms: float,
) -> dict[str, float | int]:
    lag_samples = best_alignment_lag_samples(recording, reference, sample_rate_hz, max_lag_ms)
    aligned_recording, aligned_reference = align_pair(recording, reference, lag_samples)
    gain = abs(projection_gain(aligned_recording, aligned_reference))
    return {
        "correlation": round(correlation(aligned_recording, aligned_reference), 6),
        "distortion_db": round(distortion_db(aligned_recording, aligned_reference), 3),
        "gain_db": round(linear_to_db(gain), 3) if gain > 0.0 else float("-inf"),
        "lag_samples": lag_samples,
        "recording_dbfs": round(dbfs(recording), 3),
    }


def quality_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    source_open_level = float(summary["source_open_recording_dbfs"])
    translated_level = float(summary["translated_headphone_recording_dbfs"])
    source_open_corr = float(summary["source_open_reference_correlation"])
    translated_corr = float(summary["translated_headphone_reference_correlation"])
    translated_distortion = float(summary["translated_headphone_reference_distortion_db"])
    source_isolation = float(summary["source_isolation_db"])
    min_duration = float(summary["min_artifact_duration_s"])
    hashes = bool(summary["all_artifact_hashes_present"])
    source_open_clone = bool(summary.get("source_open_recording_matches_reference"))
    source_isolated_clone = bool(summary.get("source_isolated_recording_matches_reference"))
    translated_clone = bool(summary.get("translated_headphone_recording_matches_reference"))
    mode = summary["source_suppression_mode"]
    claim = summary["suppression_claim"]
    identity_fingerprint = str(summary.get("measurement_identity_fingerprint", ""))
    release_proof = bool(summary["release_proof"])
    return [
        {
            "name": "headphone_measurement_release_proof",
            "passed": release_proof,
            "threshold": "measured listener-ear headphone isolation evidence",
            "value": release_proof,
        },
        {
            "name": "headphone_mode_claim_declared",
            "passed": mode == SUPPRESSION_MODE,
            "threshold": f"source_suppression_mode == {SUPPRESSION_MODE}",
            "value": mode,
        },
        {
            "name": "headphone_claim_not_true_cancellation",
            "passed": claim == SUPPRESSION_CLAIM,
            "threshold": f"suppression_claim == {SUPPRESSION_CLAIM}",
            "value": claim,
        },
        {
            "name": "headphone_device_identity_recorded",
            "passed": specific_label(summary.get("headphone_device_label"))
            and specific_label(summary.get("measurement_microphone_label"))
            and len(identity_fingerprint) == 64,
            "threshold": "specific headphone device, listener-ear microphone, and SHA-256 identity fingerprint recorded",
            "value": {
                "headphone_device_label": summary.get("headphone_device_label"),
                "measurement_identity_fingerprint": identity_fingerprint,
                "measurement_microphone_label": summary.get("measurement_microphone_label"),
            },
        },
        {
            "name": "isolation_fixture_identity_recorded",
            "passed": specific_label(summary.get("isolation_fixture_label")),
            "threshold": "specific physical isolation fixture label recorded",
            "value": summary.get("isolation_fixture_label"),
        },
        {
            "name": "headphone_recordings_duration_floor",
            "passed": min_duration >= float(args.min_measurement_duration_s),
            "threshold": f"all headphone isolation artifacts >= {float(args.min_measurement_duration_s):.3f}s",
            "value": min_duration,
        },
        {
            "name": "open_ear_source_control_audible",
            "passed": source_open_level >= float(args.min_source_open_dbfs),
            "threshold": f"open-ear source recording >= {float(args.min_source_open_dbfs):.3f} dBFS",
            "value": source_open_level,
        },
        {
            "name": "headphone_source_open_reference_fidelity",
            "passed": source_open_corr >= float(args.min_source_open_correlation),
            "threshold": (
                "open-ear source recording/reference correlation >= "
                f"{float(args.min_source_open_correlation):.3f}"
            ),
            "value": source_open_corr,
        },
        {
            "name": "source_isolation_measured",
            "passed": source_isolation >= float(args.min_source_isolation_db),
            "threshold": f"source attenuation >= {float(args.min_source_isolation_db):.3f} dB",
            "value": source_isolation,
        },
        {
            "name": "translated_headphone_output_audible",
            "passed": translated_level >= float(args.min_translated_dbfs),
            "threshold": f"translated headphone recording >= {float(args.min_translated_dbfs):.3f} dBFS",
            "value": translated_level,
        },
        {
            "name": "translated_headphone_output_not_distorted",
            "passed": (
                translated_corr >= float(args.min_translated_correlation)
                and translated_distortion <= float(args.max_translated_distortion_db)
            ),
            "threshold": (
                f"translated correlation >= {float(args.min_translated_correlation):.3f} "
                f"and distortion <= {float(args.max_translated_distortion_db):.3f} dB"
            ),
            "value": {
                "translated_headphone_reference_correlation": translated_corr,
                "translated_headphone_reference_distortion_db": translated_distortion,
            },
        },
        {
            "name": "headphone_artifacts_hashed",
            "passed": hashes,
            "threshold": "all headphone isolation WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "headphone_metrics_are_wav_derived",
            "passed": True,
            "threshold": "metrics were derived from the submitted WAV artifacts",
            "value": True,
        },
        {
            "name": "headphone_recordings_not_reference_clones",
            "passed": not (source_open_clone or source_isolated_clone or translated_clone),
            "threshold": "recording artifacts must not be byte-identical to generated references",
            "value": {
                "source_isolated_recording_matches_reference": source_isolated_clone,
                "source_open_recording_matches_reference": source_open_clone,
                "translated_headphone_recording_matches_reference": translated_clone,
            },
        },
    ]


def score(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    artifact_paths = {
        "source_reference": str(Path(args.source_reference)),
        "source_open_ear_recording": str(Path(args.source_open_ear_recording)),
        "source_isolated_ear_recording": str(Path(args.source_isolated_ear_recording)),
        "translated_playback_reference": str(Path(args.translated_playback_reference)),
        "translated_headphone_recording": str(Path(args.translated_headphone_recording)),
    }
    audio: dict[str, np.ndarray] = {}
    sample_rates: dict[str, int] = {}
    for key, value in artifact_paths.items():
        samples, sample_rate_hz = read_mono_wav(Path(value))
        audio[key] = samples
        sample_rates[key] = sample_rate_hz
    if len(set(sample_rates.values())) != 1:
        raise ValueError(f"all WAV artifacts must share a sample rate: {sample_rates}")
    sample_rate_hz = next(iter(sample_rates.values()))
    frame_counts = {key: int(value.size) for key, value in audio.items()}
    min_artifact_duration_s = min(
        float(frame_count) / float(sample_rate_hz)
        for frame_count in frame_counts.values()
    )

    source_open = reference_metrics(
        audio["source_open_ear_recording"],
        audio["source_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    source_isolated = reference_metrics(
        audio["source_isolated_ear_recording"],
        audio["source_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    translated = reference_metrics(
        audio["translated_headphone_recording"],
        audio["translated_playback_reference"],
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    source_open_gain_db = float(source_open["gain_db"])
    source_isolated_gain_db = float(source_isolated["gain_db"])
    source_isolation_db = source_open_gain_db - source_isolated_gain_db
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    headphone_device_label = str(args.headphone_device_label)
    isolation_fixture_label = str(args.isolation_fixture_label)
    measurement_microphone_label = str(args.measurement_microphone_label)
    identity_fingerprint = measurement_identity_fingerprint(
        artifact_hashes=artifact_hashes,
        headphone_device_label=headphone_device_label,
        isolation_fixture_label=isolation_fixture_label,
        measurement_microphone_label=measurement_microphone_label,
        sample_rate_hz=sample_rate_hz,
    )
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "measurement_kind": MEASUREMENT_KIND,
        "measurement_identity_fingerprint": identity_fingerprint,
        "measurement_microphone_label": measurement_microphone_label,
        "artifact_frame_counts": frame_counts,
        "min_artifact_duration_s": round(min_artifact_duration_s, 6),
        "procedure_note": str(args.procedure_note),
        "release_proof": True,
        "sample_rate_hz": sample_rate_hz,
        "source_isolated_recording_matches_reference": (
            artifact_hashes["source_isolated_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_isolated_gain_db": source_isolated["gain_db"],
        "source_isolated_recording_dbfs": source_isolated["recording_dbfs"],
        "source_isolated_reference_correlation": source_isolated["correlation"],
        "source_isolated_reference_distortion_db": source_isolated["distortion_db"],
        "source_isolated_reference_lag_samples": source_isolated["lag_samples"],
        "source_isolation_db": round(source_isolation_db, 3),
        "source_open_recording_matches_reference": (
            artifact_hashes["source_open_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_open_gain_db": source_open["gain_db"],
        "source_open_recording_dbfs": source_open["recording_dbfs"],
        "source_open_reference_correlation": source_open["correlation"],
        "source_open_reference_distortion_db": source_open["distortion_db"],
        "source_open_reference_lag_samples": source_open["lag_samples"],
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
        "translated_audio_is_surrogate": False,
        "translated_headphone_gain_db": translated["gain_db"],
        "translated_headphone_recording_matches_reference": (
            artifact_hashes["translated_headphone_recording"]
            == artifact_hashes["translated_playback_reference"]
        ),
        "translated_headphone_recording_dbfs": translated["recording_dbfs"],
        "translated_headphone_reference_correlation": translated["correlation"],
        "translated_headphone_reference_distortion_db": translated["distortion_db"],
        "translated_headphone_reference_lag_samples": translated["lag_samples"],
    }
    gates = quality_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": FIXTURE_KIND,
        "measurement_kind": MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": True,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": True,
        },
        "benchmarks": {
            BENCHMARK_NAME: {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "detractor_loop": {
            "strongest_objection": (
                "Headphone isolation is listener-local attenuation, not room-wide cancellation."
            ),
            "verdict": (
                "This evidence may satisfy a headphone/earpiece release mode only when WAV "
                "artifacts prove source attenuation and translated playback fidelity."
            ),
        },
    }
    report_path = run_dir / "headphone-isolation-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"headphone/earpiece isolation {status}: "
        f"isolation_db={summary['source_isolation_db']}, "
        f"translated_corr={summary['translated_headphone_reference_correlation']}"
    )
    print(f"wrote headphone isolation report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
        t = np.arange(sample_rate_hz, dtype=np.float64) / float(sample_rate_hz)
        source = (np.sin(2.0 * math.pi * 220.0 * t) * 0.25).astype(np.float32)
        translated = (np.sin(2.0 * math.pi * 330.0 * t) * 0.20).astype(np.float32)
        source_open = source * db_to_linear(-2.0)
        source_isolated = source * db_to_linear(-18.0)
        translated_recording = translated * db_to_linear(-3.0)
        source_path = root / "source.wav"
        source_open_path = root / "source-open.wav"
        source_isolated_path = root / "source-isolated.wav"
        translated_path = root / "translated.wav"
        translated_recording_path = root / "translated-recording.wav"
        write_mono_wav(source_path, source, sample_rate_hz)
        write_mono_wav(source_open_path, source_open, sample_rate_hz)
        write_mono_wav(source_isolated_path, source_isolated, sample_rate_hz)
        write_mono_wav(translated_path, translated, sample_rate_hz)
        write_mono_wav(translated_recording_path, translated_recording, sample_rate_hz)
        args = argparse.Namespace(
            adapter_id=DEFAULT_ADAPTER_ID,
            headphone_device_label="unit headphones",
            isolation_fixture_label="unit sealed-ear fixture",
            max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
            max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
            measurement_microphone_label="unit ear microphone",
            min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
            min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
            min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
            min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
            min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
            min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
            output_dir=root / "out",
            procedure_note="unit synthetic measurement",
            run_id=DEFAULT_RUN_ID,
            score_warning_only=False,
            source_isolated_ear_recording=source_isolated_path,
            source_open_ear_recording=source_open_path,
            source_reference=source_path,
            translated_headphone_recording=translated_recording_path,
            translated_playback_reference=translated_path,
        )
        result = score(args)
        if result != 0:
            raise RuntimeError("expected headphone isolation self-test fixture to pass")
        args.run_id = "failing-headphone-earpiece-isolation"
        args.source_isolated_ear_recording = source_open_path
        args.score_warning_only = True
        result = score(args)
        if result != 0:
            raise RuntimeError("warning-only failing self-test should return 0")
        report_path = (
            Path(args.output_dir)
            / "runs"
            / args.run_id
            / "headphone-isolation-report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if bool(report.get("summary", {}).get("passed")):
            raise RuntimeError("expected no-isolation self-test fixture to fail")
    print("headphone/earpiece isolation contract self-test PASS")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score measured headphone/earpiece source isolation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test", help="validate scoring gates without external artifacts")
    score_parser = subparsers.add_parser(
        "score",
        help="score listener-ear source isolation and translated headphone playback WAVs",
    )
    score_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    score_parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    score_parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    score_parser.add_argument("--source-reference", type=Path, required=True)
    score_parser.add_argument("--source-open-ear-recording", type=Path, required=True)
    score_parser.add_argument("--source-isolated-ear-recording", type=Path, required=True)
    score_parser.add_argument("--translated-playback-reference", type=Path, required=True)
    score_parser.add_argument("--translated-headphone-recording", type=Path, required=True)
    score_parser.add_argument("--headphone-device-label", required=True)
    score_parser.add_argument("--isolation-fixture-label", required=True)
    score_parser.add_argument("--measurement-microphone-label", required=True)
    score_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    score_parser.add_argument("--procedure-note", default="listener-ear measurement")
    score_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    score_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    score_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    score_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    score_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    score_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    score_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    score_parser.add_argument("--score-warning-only", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "self-test":
        return self_test()
    if args.command == "score":
        return score(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
