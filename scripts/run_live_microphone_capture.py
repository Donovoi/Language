#!/usr/bin/env python3
"""Capture a short real microphone PCM stream and write release-gate evidence.

This benchmark intentionally runs on the host rather than inside Docker because
Windows microphone devices are exposed through the host audio stack. It uses a
PortAudio callback via sounddevice, records chunk timing, hashes each chunk, and
writes the product-specific report consumed by scripts/release_audio_gate.py.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import queue
import statistics
import sys
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "live-microphone-capture"
DEFAULT_ADAPTER_ID = "sounddevice_portaudio_microphone_capture_v1"
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_CHANNELS = 1
DEFAULT_CHUNK_MS = 80.0
DEFAULT_DURATION_S = 2.0
DEFAULT_MAX_INTERARRIVAL_JITTER_MS = 250.0
DEFAULT_MAX_FRAME_CLOCK_DRIFT_PPM = 50_000.0
DEFAULT_MIN_PEAK_DBFS = -80.0
PCM_SUBTYPE = "PCM_16"
PROVENANCE_KIND = "host_portaudio_callback_artifact_coherence"
PROVENANCE_TRUST_BOUNDARY = "local_artifact_coherence_not_tamper_proof"


@dataclass(frozen=True)
class CapturedChunk:
    index: int
    frames: int
    callback_wall_time_s: float
    input_adc_time_s: float | None
    current_time_s: float | None
    status: str
    audio: np.ndarray


def dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return float("-inf")
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    if rms <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(rms)


def peak_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return float("-inf")
    peak = float(np.max(np.abs(samples)))
    if peak <= 0.0:
        return float("-inf")
    return 20.0 * math.log10(peak)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )


def write_json(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_pcm16_wav(path: Path, audio: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype("<i2", copy=False)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate_hz)
        handle.writeframes(pcm16.tobytes())


def sounddevice_module() -> Any:
    try:
        import sounddevice as sd  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "sounddevice is required for host microphone capture. "
            "Install with: python -m pip install sounddevice numpy"
        ) from exc
    return sd


def list_devices() -> int:
    sd = sounddevice_module()
    print(sd.query_devices())
    return 0


def device_identity(device: int | str | None) -> dict[str, Any]:
    sd = sounddevice_module()
    info = sd.query_devices(device, kind="input")
    hostapi = sd.query_hostapis(int(info["hostapi"]))
    return {
        "requested_device": device,
        "name": str(info["name"]),
        "hostapi": str(hostapi["name"]),
        "max_input_channels": int(info["max_input_channels"]),
        "default_samplerate": float(info["default_samplerate"]),
    }


def capture_microphone(
    *,
    device: int | str | None,
    sample_rate_hz: int,
    channels: int,
    chunk_ms: float,
    duration_s: float,
) -> tuple[list[CapturedChunk], dict[str, Any]]:
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive")
    if channels <= 0:
        raise ValueError("channels must be positive")
    if chunk_ms <= 0.0:
        raise ValueError("chunk_ms must be positive")
    if duration_s <= 0.0:
        raise ValueError("duration_s must be positive")

    sd = sounddevice_module()
    chunk_frames = max(1, int(round(sample_rate_hz * chunk_ms / 1000.0)))
    target_frames = int(math.ceil(duration_s * sample_rate_hz))
    captured: list[CapturedChunk] = []
    captures: queue.Queue[CapturedChunk] = queue.Queue()
    state = {"chunk_index": 0}

    def callback(indata: np.ndarray, frames: int, time_info: dict[str, float], status: Any) -> None:
        chunk_index = int(state["chunk_index"])
        state["chunk_index"] = chunk_index + 1
        mono = np.asarray(indata[:, 0], dtype=np.float32).copy()
        captures.put(
            CapturedChunk(
                index=chunk_index,
                frames=int(frames),
                callback_wall_time_s=time.perf_counter(),
                input_adc_time_s=(
                    float(getattr(time_info, "inputBufferAdcTime"))
                    if hasattr(time_info, "inputBufferAdcTime")
                    else None
                ),
                current_time_s=(
                    float(getattr(time_info, "currentTime"))
                    if hasattr(time_info, "currentTime")
                    else None
                ),
                status=str(status) if status else "",
                audio=mono,
            )
        )

    started_wall_s = time.perf_counter()
    with sd.InputStream(
        device=device,
        samplerate=sample_rate_hz,
        channels=channels,
        dtype="float32",
        blocksize=chunk_frames,
        callback=callback,
    ):
        captured_frames = 0
        deadline_s = time.perf_counter() + duration_s + 4.0
        while captured_frames < target_frames and time.perf_counter() < deadline_s:
            try:
                chunk = captures.get(timeout=0.5)
            except queue.Empty:
                continue
            captured.append(chunk)
            captured_frames += chunk.frames

    while True:
        try:
            captured.append(captures.get_nowait())
        except queue.Empty:
            break

    captured.sort(key=lambda item: item.index)
    ended_wall_s = time.perf_counter()
    return captured, {
        "chunk_frames": chunk_frames,
        "target_frames": target_frames,
        "started_wall_time_s": started_wall_s,
        "ended_wall_time_s": ended_wall_s,
        "wall_duration_s": ended_wall_s - started_wall_s,
    }


def chunk_records(chunks: list[CapturedChunk], sample_rate_hz: int, chunk_ms: float) -> list[dict[str, Any]]:
    first_wall = chunks[0].callback_wall_time_s if chunks else 0.0
    records: list[dict[str, Any]] = []
    sample_cursor = 0
    for chunk in chunks:
        duration_ms = chunk.frames / float(sample_rate_hz) * 1000.0
        target_duration_ms = chunk_ms
        records.append(
            {
                "chunk_index": chunk.index,
                "start_sample": sample_cursor,
                "end_sample": sample_cursor + chunk.frames,
                "frame_count": chunk.frames,
                "duration_ms": round(duration_ms, 6),
                "target_duration_ms": round(target_duration_ms, 6),
                "duration_error_ms": round(abs(duration_ms - target_duration_ms), 6),
                "callback_wall_time_offset_s": round(chunk.callback_wall_time_s - first_wall, 6),
                "input_adc_time_s": None if chunk.input_adc_time_s is None else round(chunk.input_adc_time_s, 6),
                "current_time_s": None if chunk.current_time_s is None else round(chunk.current_time_s, 6),
                "rms_dbfs": round(dbfs(chunk.audio), 3),
                "peak_dbfs": round(peak_dbfs(chunk.audio), 3),
                "status": chunk.status,
                "sha256_float32": sha256_bytes(np.ascontiguousarray(chunk.audio).tobytes()),
            }
        )
        sample_cursor += chunk.frames
    return records


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percent / 100.0
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)


def strictly_increasing(values: list[float]) -> bool:
    return all(current > previous for previous, current in zip(values, values[1:], strict=False))


def timestamp_evidence(records: list[dict[str, Any]]) -> tuple[str, bool]:
    adc_times = [
        float(record["input_adc_time_s"])
        for record in records
        if record.get("input_adc_time_s") is not None
    ]
    if len(adc_times) == len(records) and len(set(adc_times)) > 1:
        return "device_input_adc_time", strictly_increasing(adc_times)

    callback_offsets = [
        float(record["callback_wall_time_offset_s"])
        for record in records
        if record.get("callback_wall_time_offset_s") is not None
    ]
    return "callback_wall_clock_fallback", (
        len(callback_offsets) == len(records) and strictly_increasing(callback_offsets)
    )


def derive_release_proof(summary: dict[str, Any], args: argparse.Namespace) -> bool:
    device = summary.get("device", {})
    device = device if isinstance(device, dict) else {}
    max_jitter = summary.get("max_interarrival_jitter_ms")
    frame_clock_drift = summary.get("frame_clock_drift_ppm")
    return bool(
        summary.get("capture_source_kind") == "microphone"
        and summary.get("backend") == "sounddevice_portaudio_callback"
        and summary.get("adapter_id") == DEFAULT_ADAPTER_ID
        and summary.get("provenance_kind") == PROVENANCE_KIND
        and summary.get("provenance_trust_boundary") == PROVENANCE_TRUST_BOUNDARY
        and bool(device.get("name"))
        and int(device.get("max_input_channels", 0)) >= 1
        and summary.get("sample_rates_hz") == [args.sample_rate_hz]
        and int(summary.get("channel_count", 0)) == 1
        and summary.get("pcm_subtype") == PCM_SUBTYPE
        and float(summary.get("duration_s", 0.0)) >= args.min_duration_s
        and int(summary.get("chunk_count", 0)) >= 2
        and max_jitter is not None
        and float(max_jitter) <= args.max_interarrival_jitter_ms
        and int(summary.get("dropped_or_reordered_chunk_count", -1)) == 0
        and int(summary.get("callback_status_count", -1)) == 0
        and float(summary.get("input_peak_dbfs", float("-inf"))) > args.min_peak_dbfs
        and bool(summary.get("artifact_hash_chain_present"))
        and summary.get("timestamp_source")
        in {"device_input_adc_time", "callback_wall_clock_fallback"}
        and bool(summary.get("timestamp_monotonic"))
        and frame_clock_drift is not None
        and float(frame_clock_drift) <= args.max_frame_clock_drift_ppm
    )


def build_capture_report(
    *,
    chunks: list[CapturedChunk],
    capture_context: dict[str, Any],
    args: argparse.Namespace,
    run_dir: Path,
    prediction_path: Path,
    audio_path: Path,
) -> dict[str, Any]:
    records = chunk_records(chunks, args.sample_rate_hz, args.chunk_ms)
    audio = (
        np.concatenate([chunk.audio for chunk in chunks]).astype(np.float32)
        if chunks
        else np.zeros((0,), dtype=np.float32)
    )
    write_pcm16_wav(audio_path, audio, args.sample_rate_hz)
    write_jsonl(records, prediction_path)

    expected_indices = list(range(len(chunks)))
    observed_indices = [chunk.index for chunk in chunks]
    interarrival_ms = [
        (current.callback_wall_time_s - previous.callback_wall_time_s) * 1000.0
        for previous, current in zip(chunks, chunks[1:], strict=False)
    ]
    jitter_ms = [abs(value - args.chunk_ms) for value in interarrival_ms]
    status_records = [record for record in records if record["status"]]
    callback_status_clean = not status_records
    chunk_hashes_present = all(bool(record["sha256_float32"]) for record in records)
    wall_duration_s = float(capture_context["wall_duration_s"])
    captured_duration_s = audio.size / float(args.sample_rate_hz) if args.sample_rate_hz else 0.0
    callback_clock_duration_s = (
        float(records[-1]["callback_wall_time_offset_s"]) + float(records[-1]["duration_ms"]) / 1000.0
        if records
        else 0.0
    )
    frame_clock_drift_ppm = (
        abs(callback_clock_duration_s - captured_duration_s) / captured_duration_s * 1_000_000.0
        if captured_duration_s > 0.0 and callback_clock_duration_s > 0.0
        else None
    )
    timestamp_source, timestamp_monotonic = timestamp_evidence(records)
    device = device_identity(args.device)
    captured_audio_sha256 = sha256_file(audio_path)
    capture_chunks_sha256 = sha256_file(prediction_path)

    summary = {
        "generator": "scripts/run_live_microphone_capture.py",
        "capture_source_kind": "microphone",
        "release_proof": False,
        "backend": "sounddevice_portaudio_callback",
        "adapter_id": args.adapter_id,
        "provenance_kind": PROVENANCE_KIND,
        "provenance_trust_boundary": PROVENANCE_TRUST_BOUNDARY,
        "device": device,
        "sample_rate_source": "requested_portaudio_stream",
        "sample_rates_hz": [args.sample_rate_hz],
        "channel_count": args.channels,
        "chunk_ms": args.chunk_ms,
        "chunk_frame_count": int(capture_context["chunk_frames"]),
        "chunk_count": len(chunks),
        "captured_frame_count": int(audio.size),
        "duration_s": round(captured_duration_s, 6),
        "duration_from_frames_s": round(captured_duration_s, 6),
        "callback_clock_duration_s": round(callback_clock_duration_s, 6),
        "frame_clock_drift_ppm": None if frame_clock_drift_ppm is None else round(frame_clock_drift_ppm, 3),
        "timestamp_source": timestamp_source,
        "timestamp_monotonic": timestamp_monotonic,
        "wall_duration_s": round(wall_duration_s, 6),
        "expected_indices_match": observed_indices == expected_indices,
        "dropped_or_reordered_chunk_count": 0 if observed_indices == expected_indices else 1,
        "callback_status_count": len(status_records),
        "callback_statuses": [record["status"] for record in status_records],
        "max_interarrival_jitter_ms": None if not jitter_ms else round(max(jitter_ms), 3),
        "p95_interarrival_jitter_ms": (
            None if not jitter_ms else round(float(percentile(jitter_ms, 95.0)), 3)
        ),
        "mean_interarrival_ms": (
            None if not interarrival_ms else round(statistics.fmean(interarrival_ms), 3)
        ),
        "input_level_dbfs": round(dbfs(audio), 3),
        "input_peak_dbfs": round(peak_dbfs(audio), 3),
        "captured_audio_path": str(audio_path),
        "captured_audio_sha256": captured_audio_sha256,
        "capture_chunks_path": str(prediction_path),
        "capture_chunks_sha256": capture_chunks_sha256,
        "chunk_hashes_present": chunk_hashes_present,
        "artifact_hash_chain_present": bool(
            chunk_hashes_present and audio_path.exists() and prediction_path.exists()
        ),
        "pcm_subtype": PCM_SUBTYPE,
    }
    summary["release_proof"] = derive_release_proof(summary, args)
    summary["quality_gates"] = live_capture_quality_gates(summary, args)

    return {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "live_microphone_capture",
        "capture_source_kind": "microphone",
        "output_dir": str(args.output_dir),
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in summary["quality_gates"]),
            "quality_gates": summary["quality_gates"],
        },
        "benchmarks": {
            "capture": {
                "adapter_id": args.adapter_id,
                "summary": summary,
                "chunks": records,
            }
        },
        "prediction_paths": {
            "capture_chunks": str(prediction_path),
        },
        "artifact_paths": {
            "captured_audio": str(audio_path),
        },
        "artifact_hashes": {
            "captured_audio": summary["captured_audio_sha256"],
            "capture_chunks": summary["capture_chunks_sha256"],
        },
        "detractor_loop": {
            "strongest_objection": (
                "This proves the host can capture microphone PCM chunks through PortAudio. It still "
                "does not prove mobile capture permissions, room separation, speech translation, or "
                "playback suppression."
            ),
            "cheapest_falsifying_benchmark": (
                "Feed this exact microphone stream into the rolling diarizer and then repeat with "
                "known overlapping speakers and translated playback loopback."
            ),
            "fallback_if_falsified": (
                "Keep live listening disabled and remain on fixture/mock ingest until the host or "
                "target-device capture path passes."
            ),
        },
    }


def live_capture_quality_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    max_jitter = summary["max_interarrival_jitter_ms"]
    return [
        {
            "name": "capture_source_is_microphone",
            "value": summary["capture_source_kind"],
            "threshold": "microphone",
            "passed": summary["capture_source_kind"] == "microphone",
        },
        {
            "name": "capture_device_identity_present",
            "value": summary["device"]["name"],
            "threshold": "non-empty microphone device name",
            "passed": bool(summary["device"]["name"]),
        },
        {
            "name": "capture_provenance_scope_declared",
            "value": {
                "provenance_kind": summary["provenance_kind"],
                "provenance_trust_boundary": summary["provenance_trust_boundary"],
            },
            "threshold": "host PortAudio artifact coherence; local evidence is not tamper-proof",
            "passed": (
                summary["provenance_kind"] == PROVENANCE_KIND
                and summary["provenance_trust_boundary"] == PROVENANCE_TRUST_BOUNDARY
            ),
        },
        {
            "name": "pcm_chunk_schema_valid",
            "value": {
                "sample_rates_hz": summary["sample_rates_hz"],
                "channel_count": summary["channel_count"],
                "pcm_subtype": summary["pcm_subtype"],
            },
            "threshold": "single sample rate, mono channel, PCM_16 persisted audio",
            "passed": (
                len(summary["sample_rates_hz"]) == 1
                and int(summary["channel_count"]) == 1
                and summary["pcm_subtype"] == PCM_SUBTYPE
            ),
        },
        {
            "name": "capture_sample_rate_stable",
            "value": {
                "sample_rates_hz": summary["sample_rates_hz"],
                "frame_clock_drift_ppm": summary["frame_clock_drift_ppm"],
            },
            "threshold": (
                f"[{args.sample_rate_hz}] requested stream rate and "
                f"<= {args.max_frame_clock_drift_ppm} ppm frame-clock drift"
            ),
            "passed": (
                summary["sample_rates_hz"] == [args.sample_rate_hz]
                and summary["frame_clock_drift_ppm"] is not None
                and float(summary["frame_clock_drift_ppm"]) <= args.max_frame_clock_drift_ppm
            ),
        },
        {
            "name": "capture_duration_minimum",
            "value": summary["duration_s"],
            "threshold": f">= {args.min_duration_s} s",
            "passed": float(summary["duration_s"]) >= args.min_duration_s,
        },
        {
            "name": "capture_chunk_count",
            "value": summary["chunk_count"],
            "threshold": ">= 2 chunks",
            "passed": int(summary["chunk_count"]) >= 2,
        },
        {
            "name": "chunk_timing_jitter_within_limit",
            "value": max_jitter,
            "threshold": f"<= {args.max_interarrival_jitter_ms} ms max callback interarrival jitter",
            "passed": max_jitter is not None and float(max_jitter) <= args.max_interarrival_jitter_ms,
        },
        {
            "name": "no_chunk_gaps_or_reorders",
            "value": summary["dropped_or_reordered_chunk_count"],
            "threshold": "0 dropped/reordered callback chunks",
            "passed": int(summary["dropped_or_reordered_chunk_count"]) == 0,
        },
        {
            "name": "capture_callback_status_clean",
            "value": summary["callback_status_count"],
            "threshold": "0 PortAudio callback status warnings",
            "passed": int(summary["callback_status_count"]) == 0,
        },
        {
            "name": "capture_input_not_silent",
            "value": summary["input_peak_dbfs"],
            "threshold": f"> {args.min_peak_dbfs} dBFS peak",
            "passed": float(summary["input_peak_dbfs"]) > args.min_peak_dbfs,
        },
        {
            "name": "capture_artifact_hash_chain_present",
            "value": summary["artifact_hash_chain_present"],
            "threshold": "captured WAV, chunk JSONL, and every chunk are hashed",
            "passed": bool(summary["artifact_hash_chain_present"]),
        },
        {
            "name": "capture_timestamps_monotonic",
            "value": {
                "timestamp_source": summary["timestamp_source"],
                "timestamp_monotonic": summary["timestamp_monotonic"],
            },
            "threshold": "monotonic device input ADC time or callback wall-clock fallback",
            "passed": (
                summary["timestamp_source"]
                in {"device_input_adc_time", "callback_wall_clock_fallback"}
                and bool(summary["timestamp_monotonic"])
            ),
        },
        {
            "name": "capture_release_proof",
            "value": summary["release_proof"],
            "threshold": "true only after runtime evidence fields pass",
            "passed": bool(summary["release_proof"]),
        },
    ]


def self_test() -> None:
    args = argparse.Namespace(
        sample_rate_hz=16000,
        channels=1,
        chunk_ms=80.0,
        min_duration_s=1.0,
        max_interarrival_jitter_ms=250.0,
        max_frame_clock_drift_ppm=50_000.0,
        min_peak_dbfs=-80.0,
    )
    passing = {
        "generator": "scripts/run_live_microphone_capture.py",
        "capture_source_kind": "microphone",
        "release_proof": True,
        "backend": "sounddevice_portaudio_callback",
        "adapter_id": DEFAULT_ADAPTER_ID,
        "provenance_kind": PROVENANCE_KIND,
        "provenance_trust_boundary": PROVENANCE_TRUST_BOUNDARY,
        "device": {"name": "unit microphone"},
        "sample_rates_hz": [16000],
        "channel_count": 1,
        "duration_s": 1.2,
        "frame_clock_drift_ppm": 5.0,
        "timestamp_source": "callback_wall_clock_fallback",
        "timestamp_monotonic": True,
        "chunk_count": 15,
        "max_interarrival_jitter_ms": 2.0,
        "dropped_or_reordered_chunk_count": 0,
        "callback_status_count": 0,
        "input_peak_dbfs": -30.0,
        "artifact_hash_chain_present": True,
        "pcm_subtype": PCM_SUBTYPE,
    }
    failing = {
        **passing,
        "capture_source_kind": "fixture_replay",
        "release_proof": False,
        "timestamp_monotonic": False,
        "dropped_or_reordered_chunk_count": 2,
    }
    if not all(gate["passed"] for gate in live_capture_quality_gates(passing, args)):
        raise AssertionError("expected passing live capture summary to pass")
    failed = {
        str(gate["name"])
        for gate in live_capture_quality_gates(failing, args)
        if not bool(gate["passed"])
    }
    expected = {
        "capture_source_is_microphone",
        "no_chunk_gaps_or_reorders",
        "capture_timestamps_monotonic",
        "capture_release_proof",
    }
    if not expected.issubset(failed):
        raise AssertionError(f"expected live capture negative gates to fail, got {failed}")


def print_summary(report: dict[str, Any]) -> None:
    summary = report["benchmarks"]["capture"]["summary"]
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        "live microphone capture "
        f"{status}: {summary['chunk_count']} chunks, {summary['duration_s']}s, "
        f"device={summary['device']['name']!r}"
    )
    for gate in report["summary"]["quality_gates"]:
        gate_status = "PASS" if gate["passed"] else "FAIL"
        print(f"  [{gate_status}] {gate['name']}: {gate['value']} ({gate['threshold']})")
    print(
        "  capture diagnostics: "
        f"peak_dbfs={summary['input_peak_dbfs']} "
        f"max_jitter_ms={summary['max_interarrival_jitter_ms']} "
        f"frame_clock_drift_ppm={summary['frame_clock_drift_ppm']} "
        f"timestamp_source={summary['timestamp_source']} "
        f"backend={summary['backend']}"
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run host live microphone capture benchmark")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-devices", help="list host audio devices visible to sounddevice")
    subparsers.add_parser("self-test", help="validate scorer gates without microphone access")

    check = subparsers.add_parser("check", help="capture a short microphone stream and write report")
    check.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    check.add_argument("--run-id", default=DEFAULT_RUN_ID)
    check.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    check.add_argument("--device", help="sounddevice input device index or name")
    check.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    check.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    check.add_argument("--chunk-ms", type=float, default=DEFAULT_CHUNK_MS)
    check.add_argument("--duration-s", type=float, default=DEFAULT_DURATION_S)
    check.add_argument("--min-duration-s", type=float, default=1.0)
    check.add_argument(
        "--max-interarrival-jitter-ms",
        type=float,
        default=DEFAULT_MAX_INTERARRIVAL_JITTER_MS,
    )
    check.add_argument(
        "--max-frame-clock-drift-ppm",
        type=float,
        default=DEFAULT_MAX_FRAME_CLOCK_DRIFT_PPM,
    )
    check.add_argument("--min-peak-dbfs", type=float, default=DEFAULT_MIN_PEAK_DBFS)
    check.add_argument("--report", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "list-devices":
        return list_devices()
    if args.command == "self-test":
        self_test()
        print("live microphone capture self-test PASS")
        return 0

    args.output_dir = args.output_dir.resolve()
    run_dir = args.output_dir / "runs" / args.run_id
    prediction_path = run_dir / "capture_chunks.jsonl"
    audio_path = run_dir / "captured_microphone.wav"
    report_path = (
        args.report.resolve()
        if args.report
        else run_dir / "live-microphone-capture-report.json"
    )
    device: int | str | None
    if args.device is None:
        device = None
    else:
        try:
            device = int(args.device)
        except ValueError:
            device = args.device
    args.device = device

    chunks, capture_context = capture_microphone(
        device=device,
        sample_rate_hz=args.sample_rate_hz,
        channels=args.channels,
        chunk_ms=args.chunk_ms,
        duration_s=args.duration_s,
    )
    report = build_capture_report(
        chunks=chunks,
        capture_context=capture_context,
        args=args,
        run_dir=run_dir,
        prediction_path=prediction_path,
        audio_path=audio_path,
    )
    write_json(report, report_path)
    print(f"wrote live microphone capture chunks to {prediction_path}")
    print(f"wrote live microphone capture report to {report_path}")
    print_summary(report)
    return 0 if report["summary"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
