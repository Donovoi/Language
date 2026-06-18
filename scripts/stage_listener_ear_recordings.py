#!/usr/bin/env python3
"""Stage external listener-ear WAV exports into the manual recording dropbox."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
import sys
import tempfile
import time
import wave
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    ROOT
    / "artifacts/audio_eval/runs/headphone-earpiece-manual-kit/manual-recording-manifest.json"
)
DEFAULT_LOG_NAME = "listener-ear-staging-log.json"
RAW_DROPBOX_DIR = "raw-listener-ear-recordings"
TAKES = {
    "source_open_ear_recording": {
        "argument": "source_open_ear_recording",
        "filename": "source-open-ear-recording.wav",
        "summary": "source speaker playback with listener ear open",
    },
    "source_isolated_ear_recording": {
        "argument": "source_isolated_ear_recording",
        "filename": "source-isolated-ear-recording.wav",
        "summary": "source speaker playback with headphone/earpiece sealed",
    },
    "translated_headphone_recording": {
        "argument": "translated_headphone_recording",
        "filename": "translated-headphone-recording.wav",
        "summary": "translated headphone playback with headphone/earpiece sealed",
    },
}


def repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except (OSError, ValueError):
        return str(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pcm16_sha256(frames: bytes) -> str:
    return hashlib.sha256(frames).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"manual manifest is missing: {repo_relative(path)}; run release-evidence first")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manual manifest must be a JSON object")
    if payload.get("release_proof") is not False:
        raise ValueError("manual staging only accepts the non-release-proof manual recording manifest")
    return payload


def expected_sample_rate(manifest: dict[str, Any]) -> int:
    requirements = manifest.get("recording_requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    value = requirements.get("sample_rate_hz") or manifest.get("sample_rate_hz") or 48000
    try:
        sample_rate = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("manual manifest sample_rate_hz must be an integer") from exc
    if sample_rate <= 0:
        raise ValueError("manual manifest sample_rate_hz must be positive")
    return sample_rate


def min_duration(manifest: dict[str, Any]) -> float:
    value = manifest.get("min_artifact_duration_s") or 1.85
    try:
        duration = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("manual manifest min_artifact_duration_s must be numeric") from exc
    if duration <= 0.0:
        raise ValueError("manual manifest min_artifact_duration_s must be positive")
    return duration


def output_path_for(manifest_path: Path, key: str) -> Path:
    return manifest_path.parent / RAW_DROPBOX_DIR / str(TAKES[key]["filename"])


def read_wav_for_stage(
    path: Path,
    *,
    allow_downmix: bool,
    expected_sample_rate_hz: int,
    min_duration_s: float,
) -> tuple[dict[str, Any], bytes | None]:
    if not path.exists():
        raise ValueError(f"{path} is missing")
    if path.suffix.lower() != ".wav":
        raise ValueError(f"{path} must be a WAV export; configure the recorder for WAV before staging")

    try:
        with wave.open(str(path), "rb") as wav:
            channels = int(wav.getnchannels())
            sample_width = int(wav.getsampwidth())
            sample_rate_hz = int(wav.getframerate())
            frame_count = int(wav.getnframes())
            frames = wav.readframes(frame_count)
    except (OSError, wave.Error) as exc:
        raise ValueError(f"{path} must be a readable PCM WAV: {exc}") from exc

    if channels <= 0:
        raise ValueError(f"{path} must have at least one channel")
    if sample_width != 2:
        raise ValueError(f"{path} must be 16-bit PCM WAV before staging")
    if sample_rate_hz != int(expected_sample_rate_hz):
        raise ValueError(f"{path} sample rate must be {int(expected_sample_rate_hz)} Hz before staging")
    if frame_count <= 0:
        raise ValueError(f"{path} must contain frames")
    duration_s = float(frame_count) / float(sample_rate_hz)
    if duration_s < float(min_duration_s):
        raise ValueError(f"{path} duration must be >= {float(min_duration_s):.3f}s before staging")

    expected_samples = frame_count * channels
    if len(frames) != expected_samples * 2:
        raise ValueError(f"{path} frame data length does not match its WAV header")

    output_frames: bytes | None = None
    conversion_kind = "copy_mono_pcm16"
    decoded_mono_pcm_sha256 = pcm16_sha256(frames)
    if channels != 1:
        if not allow_downmix:
            raise ValueError(f"{path} has {channels} channels; pass --allow-downmix to stage as mono")
        values = struct.unpack(f"<{expected_samples}h", frames)
        mono = bytearray(frame_count * 2)
        for frame_index in range(frame_count):
            start = frame_index * channels
            averaged = round(sum(values[start : start + channels]) / channels)
            struct.pack_into("<h", mono, frame_index * 2, max(-32768, min(32767, averaged)))
        output_frames = bytes(mono)
        decoded_mono_pcm_sha256 = pcm16_sha256(output_frames)
        conversion_kind = "downmix_to_mono_pcm16"

    return (
        {
            "channels": channels,
            "conversion_kind": conversion_kind,
            "decoded_mono_pcm_sha256": decoded_mono_pcm_sha256,
            "duration_s": round(duration_s, 6),
            "frame_count": frame_count,
            "input_sha256": sha256_file(path),
            "sample_rate_hz": sample_rate_hz,
            "sample_width_bytes": sample_width,
        },
        output_frames,
    )


def write_mono_wav(path: Path, frames: bytes, sample_rate_hz: int) -> None:
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate_hz))
        wav.writeframes(frames)


def build_stage_plan(args: argparse.Namespace) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    sample_rate_hz = expected_sample_rate(manifest)
    min_duration_s = min_duration(manifest)
    plan: list[dict[str, Any]] = []
    seen_paths: dict[str, str] = {}
    seen_hashes: dict[str, str] = {}

    for key, take in TAKES.items():
        source_path = Path(getattr(args, str(take["argument"])))
        target_path = output_path_for(manifest_path, key)
        details, downmixed_frames = read_wav_for_stage(
            source_path,
            allow_downmix=bool(args.allow_downmix),
            expected_sample_rate_hz=sample_rate_hz,
            min_duration_s=min_duration_s,
        )

        source_identity = str(source_path.resolve())
        duplicate_path_key = seen_paths.get(source_identity)
        if duplicate_path_key:
            raise ValueError(f"{key} reuses the same source path as {duplicate_path_key}: {source_path}")
        seen_paths[source_identity] = key

        input_sha256 = str(details["input_sha256"])
        duplicate_hash_key = seen_hashes.get(input_sha256)
        if duplicate_hash_key:
            raise ValueError(f"{key} has the same raw audio hash as {duplicate_hash_key}; record separate takes")
        seen_hashes[input_sha256] = key

        same_file = source_path.resolve() == target_path.resolve()
        action = str(details["conversion_kind"])
        if same_file and action != "copy_mono_pcm16":
            raise ValueError(f"{key} cannot be downmixed in place; stage from a separate source WAV")
        if same_file:
            action = "already_staged"
        elif target_path.exists() and not bool(args.allow_overwrite):
            raise ValueError(f"{key} target already exists: {target_path}; pass --allow-overwrite to replace it")

        event = {
            **details,
            "dry_run": bool(args.dry_run),
            "key": key,
            "output_channels": 1,
            "output_path": str(target_path),
            "output_sample_rate_hz": sample_rate_hz,
            "source_path": str(source_path),
            "summary": str(take["summary"]),
            "write_action": action,
        }
        plan.append(
            {
                "downmixed_frames": downmixed_frames,
                "event": event,
                "source_path": source_path,
                "target_path": target_path,
                "write_action": action,
            }
        )

    return manifest_path, manifest, plan


def stage_recordings(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    log_path = Path(args.log) if args.log else manifest_path.parent / DEFAULT_LOG_NAME
    try:
        manifest_path, manifest, plan = build_stage_plan(args)
    except Exception as exc:
        log = {
            "schema_version": 1,
            "generated_at_unix": int(time.time()),
            "manifest_path": str(manifest_path),
            "release_proof": False,
            "summary": {
                "dry_run": bool(args.dry_run),
                "error": str(exc),
                "error_type": type(exc).__name__,
                "release_proof": False,
                "stage_ready": False,
            },
            "stage_events": [],
        }
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"listener-ear staging NOT-READY: {type(exc).__name__}: {exc}")
        print(f"wrote staging log to {repo_relative(log_path)}")
        return 1

    events: list[dict[str, Any]] = []
    sample_rate_hz = expected_sample_rate(manifest)
    if not args.dry_run:
        for item in plan:
            source_path = Path(item["source_path"])
            target_path = Path(item["target_path"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = str(item["write_action"])
            if action == "already_staged":
                pass
            elif action == "copy_mono_pcm16":
                shutil.copy2(source_path, target_path)
            elif action == "downmix_to_mono_pcm16":
                write_mono_wav(target_path, bytes(item["downmixed_frames"]), sample_rate_hz)
            else:
                raise ValueError(f"unknown staging action: {action}")
            event = dict(item["event"])
            event["target_sha256"] = sha256_file(target_path)
            events.append(event)
    else:
        events = [dict(item["event"]) for item in plan]

    dropbox = manifest_path.parent / RAW_DROPBOX_DIR
    log = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "manifest_sha256": sha256_file(manifest_path),
        "manifest_path": str(manifest_path),
        "raw_recording_dropbox": str(dropbox),
        "release_proof": False,
        "summary": {
            "allow_downmix": bool(args.allow_downmix),
            "allow_overwrite": bool(args.allow_overwrite),
            "dry_run": bool(args.dry_run),
            "release_proof": False,
            "stage_event_count": len(events),
            "stage_ready": True,
        },
        "stage_events": events,
        "detractor_loop": {
            "strongest_objection": (
                "Staging only validates file shape and names. It does not prove microphone placement, "
                "headphone seal, source isolation, or translated fidelity."
            ),
            "verdict": "Run release-evidence and release-evidence-score after staging.",
        },
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    action = "dry-run ready" if args.dry_run else "ready"
    print(f"listener-ear staging {action}: {len(events)} file(s) for {repo_relative(dropbox)}")
    print(f"wrote staging log to {repo_relative(log_path)}")
    print("next: python scripts/run_test_category.py release-evidence")
    return 0


def write_test_wav(path: Path, *, sample_rate_hz: int, seconds: float, channels: int, seed: int) -> None:
    frame_count = int(round(sample_rate_hz * seconds))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        frames = bytearray(frame_count * channels * 2)
        for frame_index in range(frame_count):
            sample = ((frame_index * (seed + 17)) % 32767) - 16384
            for channel in range(channels):
                struct.pack_into("<h", frames, (frame_index * channels + channel) * 2, sample + channel)
        wav.writeframes(bytes(frames))


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="language-listener-ear-stage-") as temp_dir:
        root = Path(temp_dir)
        manifest_path = root / "manual-recording-manifest.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "release_proof": False,
                    "sample_rate_hz": 48000,
                    "min_artifact_duration_s": 1.85,
                    "recording_requirements": {"sample_rate_hz": 48000},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        mono_a = root / "phone-open.wav"
        mono_b = root / "phone-isolated.wav"
        stereo_c = root / "phone-translated.wav"
        write_test_wav(mono_a, sample_rate_hz=48000, seconds=2.0, channels=1, seed=1)
        write_test_wav(mono_b, sample_rate_hz=48000, seconds=2.0, channels=1, seed=2)
        write_test_wav(stereo_c, sample_rate_hz=48000, seconds=2.0, channels=2, seed=3)

        base_args = argparse.Namespace(
            allow_downmix=True,
            allow_overwrite=False,
            dry_run=True,
            log=root / "dry-run-log.json",
            manifest=manifest_path,
            source_open_ear_recording=mono_a,
            source_isolated_ear_recording=mono_b,
            translated_headphone_recording=stereo_c,
        )
        if stage_recordings(base_args) != 0:
            raise RuntimeError("dry-run staging should pass")
        if (manifest_path.parent / RAW_DROPBOX_DIR / "source-open-ear-recording.wav").exists():
            raise RuntimeError("dry-run staging must not write dropbox files")

        base_args.dry_run = False
        base_args.log = root / "stage-log.json"
        if stage_recordings(base_args) != 0:
            raise RuntimeError("staging should pass")
        for take in TAKES.values():
            if not (manifest_path.parent / RAW_DROPBOX_DIR / str(take["filename"])).exists():
                raise RuntimeError(f"staging did not write {take['filename']}")

        duplicate_args = argparse.Namespace(**vars(base_args))
        duplicate_args.allow_overwrite = True
        duplicate_args.source_isolated_ear_recording = mono_a
        duplicate_args.log = root / "duplicate-log.json"
        if stage_recordings(duplicate_args) == 0:
            raise RuntimeError("duplicate source paths must be rejected")

        no_downmix_args = argparse.Namespace(**vars(base_args))
        no_downmix_args.allow_downmix = False
        no_downmix_args.allow_overwrite = True
        no_downmix_args.log = root / "no-downmix-log.json"
        if stage_recordings(no_downmix_args) == 0:
            raise RuntimeError("stereo staging must require --allow-downmix")

    print("listener-ear staging self-test PASS")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-open-ear-recording", type=Path, required=True)
    parser.add_argument("--source-isolated-ear-recording", type=Path, required=True)
    parser.add_argument("--translated-headphone-recording", type=Path, required=True)
    parser.add_argument("--allow-downmix", action="store_true")
    parser.add_argument("--allow-overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    return args


def main(argv: list[str] | None = None) -> int:
    if argv and "--self-test" in argv:
        return self_test()
    if argv is None and "--self-test" in sys.argv[1:]:
        return self_test()
    args = parse_args(argv)
    return stage_recordings(args)


if __name__ == "__main__":
    raise SystemExit(main())
