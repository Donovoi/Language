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
import shutil
import tempfile
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np


DEFAULT_OUTPUT_DIR = Path("artifacts/audio_eval")
DEFAULT_RUN_ID = "headphone-earpiece-isolation"
DEFAULT_PREFLIGHT_RUN_ID = "headphone-earpiece-preflight"
DEFAULT_ROUTE_PROBE_RUN_ID = "headphone-earpiece-route-probe"
DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID = "headphone-earpiece-route-probe-sweep"
DEFAULT_VIRTUAL_LAB_RUN_ID = "headphone-earpiece-virtual-lab"
DEFAULT_MANUAL_KIT_RUN_ID = "headphone-earpiece-manual-kit"
DEFAULT_PREFLIGHT_REPORT = "headphone-preflight-report.json"
DEFAULT_PREFLIGHT_MARKDOWN = "headphone-preflight-report.md"
DEFAULT_MANUAL_STATUS_REPORT = "manual-recording-status.json"
DEFAULT_MANUAL_STATUS_MARKDOWN = "manual-recording-status.md"
DEFAULT_MANUAL_CHECKLIST = "manual-recording-checklist.md"
DEFAULT_MANUAL_PLAYBACK_LOG = "manual-playback-log.json"
DEFAULT_MANUAL_IMPORT_LOG = "manual-import-log.json"
DEFAULT_ADAPTER_ID = "listener_headphone_earpiece_isolation_measurement_v1"
DEFAULT_PREFLIGHT_ADAPTER_ID = "listener_headphone_earpiece_preflight_v1"
DEFAULT_ROUTE_PROBE_ADAPTER_ID = "listener_headphone_earpiece_route_probe_v1"
DEFAULT_ROUTE_PROBE_SWEEP_ADAPTER_ID = "listener_headphone_earpiece_route_probe_sweep_v1"
DEFAULT_VIRTUAL_LAB_ADAPTER_ID = "listener_headphone_earpiece_virtual_lab_v1"
DEFAULT_MANUAL_KIT_ADAPTER_ID = "listener_headphone_earpiece_manual_kit_v1"
DEFAULT_TTS_REPORT = DEFAULT_OUTPUT_DIR / "runs/same-voice-tts/voice-clone-report.json"
DEFAULT_SAMPLE_RATE_HZ = 16000
DEFAULT_ROUTE_PROBE_SWEEP_SAMPLE_RATES = (DEFAULT_SAMPLE_RATE_HZ, 48000)
DEFAULT_ROUTE_PROBE_SWEEP_CHANNEL_CONFIGS = ((1, 2), (2, 2))
DEFAULT_ROUTE_PROBE_SWEEP_MAX_ATTEMPTS = 24
DEFAULT_ROUTE_PROBE_SWEEP_MAX_TRIPLES = 24
DEFAULT_CAPTURE_OUTPUT_CHANNELS = 2
DEFAULT_CAPTURE_INPUT_CHANNELS = 1
DEFAULT_GAP_S = 0.35
DEFAULT_LEAD_S = 0.25
DEFAULT_TAIL_S = 0.25
DEFAULT_PLAYBACK_GAIN_DB = -18.0
DEFAULT_MAX_PEAK_DBFS = -0.1
DEFAULT_ROUTE_PROBE_DURATION_S = 1.0
DEFAULT_MIN_ROUTE_PROBE_CORRELATION = 0.30
DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB = 24.0
DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES = 0
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
PREFLIGHT_FIXTURE_KIND = "headphone_earpiece_preflight"
PREFLIGHT_MEASUREMENT_KIND = "headphone_earpiece_preflight"
VIRTUAL_FIXTURE_KIND = "headphone_earpiece_virtual_lab"
VIRTUAL_BENCHMARK_NAME = "headphone_earpiece_virtual_lab"
VIRTUAL_MEASUREMENT_KIND = "headphone_earpiece_virtual_lab"
SUPPRESSION_MODE = "HEADPHONE_ISOLATED"
SUPPRESSION_CLAIM = "headphone_isolated_not_true_cancellation"
CAPTURE_BACKEND_EXTERNAL = "external_wav_measurement"
CAPTURE_BACKEND_PORTAUDIO = "sounddevice_portaudio_guided_playrec"
CAPTURE_BACKEND_VIRTUAL = "simulated_virtual_listener_ear"
CAPTURE_SOURCE_KIND_EXTERNAL = "external_listener_ear_wav_measurement"
CAPTURE_SOURCE_KIND_PORTAUDIO = "host_guided_listener_ear_playrec_measurement"
CAPTURE_SOURCE_KIND_VIRTUAL = "synthetic_room_headphone_model"
CAPTURE_BACKENDS = {CAPTURE_BACKEND_EXTERNAL, CAPTURE_BACKEND_PORTAUDIO}
CAPTURE_SOURCE_KINDS = {CAPTURE_SOURCE_KIND_EXTERNAL, CAPTURE_SOURCE_KIND_PORTAUDIO}
MANUAL_REQUIRED_RECORDINGS = (
    "source_open_ear_recording",
    "source_isolated_ear_recording",
    "translated_headphone_recording",
)
MANUAL_REQUIRED_REFERENCES = ("source_reference", "translated_playback_reference")
MANUAL_IMPORT_TAKES = {
    "source_open_ear_recording": {
        "argument": "source_open_ear_recording",
        "summary": "open-ear source control recording",
    },
    "source_isolated_ear_recording": {
        "argument": "source_isolated_ear_recording",
        "summary": "isolated source recording",
    },
    "translated_headphone_recording": {
        "argument": "translated_headphone_recording",
        "summary": "translated headphone playback recording",
    },
}
MANUAL_PLAYBACK_TAKES = {
    "source-open": {
        "reference_key": "source_reference",
        "recording_key": "source_open_ear_recording",
        "route": "source",
        "summary": "open-ear source control",
    },
    "source-isolated": {
        "reference_key": "source_reference",
        "recording_key": "source_isolated_ear_recording",
        "route": "source",
        "summary": "isolated source take",
    },
    "translated": {
        "reference_key": "translated_playback_reference",
        "recording_key": "translated_headphone_recording",
        "route": "headphone",
        "summary": "translated headphone playback take",
    },
}
PLACEHOLDER_LABEL_PREFIXES = (
    "unspecified",
    "unknown",
    "todo",
    "placeholder",
    "replace_with",
    "replace-with",
    "replace with",
    "virtual",
    "simulated",
    "synthetic",
)


def linear_to_db(value: float) -> float:
    if value <= 0.0:
        return float("-inf")
    return float(20.0 * math.log10(value))


def db_to_linear(value: float) -> float:
    return float(10.0 ** (value / 20.0))


def import_sounddevice():
    try:
        import sounddevice as sd  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised on hosts without PortAudio deps.
        raise RuntimeError(
            "sounddevice is required for guided host capture. "
            "Install with: python -m pip install sounddevice numpy"
        ) from exc
    return sd


def list_devices() -> int:
    sd = import_sounddevice()
    print(sd.query_devices())
    return 0


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


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, np.generic):
        return json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def specific_label(value: Any) -> bool:
    text = str(value).strip()
    return bool(text) and not text.lower().startswith(PLACEHOLDER_LABEL_PREFIXES)


def parse_device_selector(value: Any) -> int | str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return text


def safe_id(value: str) -> str:
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
    return "".join(char if char in allowed else "_" for char in value)


def parse_channel_config(value: str) -> tuple[int, int]:
    for separator in (":", ","):
        if separator in value:
            left, right = value.split(separator, 1)
            try:
                input_channels = int(left.strip())
                output_channels = int(right.strip())
            except ValueError as exc:
                raise argparse.ArgumentTypeError(
                    "channel config must be INPUT_CHANNELS:OUTPUT_CHANNELS"
                ) from exc
            if input_channels <= 0 or output_channels <= 0:
                raise argparse.ArgumentTypeError("channel counts must be positive")
            return input_channels, output_channels
    raise argparse.ArgumentTypeError("channel config must be INPUT_CHANNELS:OUTPUT_CHANNELS")


def parse_route_triple(value: str) -> tuple[str, str, str]:
    parts = [part.strip() for part in value.replace(",", ":").split(":")]
    if len(parts) != 3 or not all(parts):
        raise argparse.ArgumentTypeError(
            "route triple must be INPUT:SOURCE_OUTPUT:HEADPHONE_OUTPUT, for example 17:14:16"
        )
    return parts[0], parts[1], parts[2]


def route_triple_arg(route: tuple[str, str, str] | dict[str, Any]) -> str:
    if isinstance(route, dict):
        parts = (
            route.get("input_device"),
            route.get("source_output_device"),
            route.get("headphone_output_device"),
        )
    else:
        parts = route
    return ":".join(str(part) for part in parts)


def route_triple_key(route: tuple[str, str, str] | dict[str, Any]) -> tuple[str, str, str]:
    parts = route_triple_arg(route).split(":", 2)
    return parts[0], parts[1], parts[2]


def hostapi_name(sd: Any, hostapi_index: Any) -> str | None:
    try:
        return sd.query_hostapis(hostapi_index).get("name")
    except Exception:  # pragma: no cover - host API metadata is best-effort diagnostics.
        return None


def hostapi_matches(info: dict[str, Any], name: str | None, filters: list[str]) -> bool:
    if not filters:
        return True
    hostapi_index = str(info.get("hostapi", "")).lower()
    hostapi_label = (name or "").lower()
    return any(item.lower() in {hostapi_index, hostapi_label} or item.lower() in hostapi_label for item in filters)


def candidate_route_triples(
    sd: Any,
    *,
    allow_shared_output_device: bool,
    hostapis: list[str],
    include_cross_hostapi: bool,
    input_channels: int,
    max_triples: int,
    output_channels: int,
) -> list[dict[str, Any]]:
    devices = list(enumerate(sd.query_devices()))
    inputs: list[tuple[int, dict[str, Any], str | None]] = []
    outputs: list[tuple[int, dict[str, Any], str | None]] = []
    for index, info in devices:
        if not isinstance(info, dict):
            continue
        api_name = hostapi_name(sd, info.get("hostapi"))
        if not hostapi_matches(info, api_name, hostapis):
            continue
        if int(info.get("max_input_channels") or 0) >= int(input_channels):
            inputs.append((index, info, api_name))
        if int(info.get("max_output_channels") or 0) >= int(output_channels):
            outputs.append((index, info, api_name))

    try:
        default_input, default_output = sd.default.device
    except Exception:  # pragma: no cover - defensive host diagnostic.
        default_input, default_output = None, None

    def api_rank(name: str | None) -> int:
        label = (name or "").lower()
        if "wasapi" in label:
            return 0
        if "directsound" in label:
            return 1
        if "mme" in label:
            return 2
        if "wdm" in label:
            return 3
        return 4

    triples: list[dict[str, Any]] = []
    for input_index, input_info, input_api_name in inputs:
        for source_index, source_info, source_api_name in outputs:
            for headphone_index, headphone_info, headphone_api_name in outputs:
                if not allow_shared_output_device and source_index == headphone_index:
                    continue
                if not include_cross_hostapi:
                    hostapis_match = (
                        input_info.get("hostapi")
                        == source_info.get("hostapi")
                        == headphone_info.get("hostapi")
                    )
                    if not hostapis_match:
                        continue
                triples.append(
                    {
                        "headphone_hostapi": headphone_info.get("hostapi"),
                        "headphone_hostapi_name": headphone_api_name,
                        "headphone_name": headphone_info.get("name"),
                        "headphone_output_device": headphone_index,
                        "input_device": input_index,
                        "input_hostapi": input_info.get("hostapi"),
                        "input_hostapi_name": input_api_name,
                        "input_name": input_info.get("name"),
                        "source": "auto",
                        "source_hostapi": source_info.get("hostapi"),
                        "source_hostapi_name": source_api_name,
                        "source_name": source_info.get("name"),
                        "source_output_device": source_index,
                    }
                )

    triples.sort(
        key=lambda item: (
            0 if item["input_device"] == default_input else 1,
            0 if item["headphone_output_device"] == default_output else 1,
            api_rank(item.get("input_hostapi_name")),
            item.get("input_hostapi_name") != item.get("source_hostapi_name"),
            item.get("input_hostapi_name") != item.get("headphone_hostapi_name"),
            str(item.get("input_name") or ""),
            str(item.get("source_name") or ""),
            str(item.get("headphone_name") or ""),
        )
    )
    if max_triples > 0:
        return triples[:max_triples]
    return triples


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


HEADSET_TERMS = (
    "airpods",
    "bluetooth",
    "bthhfenum",
    "earbuds",
    "hands-free",
    "hands free",
    "headset",
    "wh-1000",
)
BUILTIN_INPUT_TERMS = (
    "built-in",
    "built in",
    "integrated",
    "intel smart sound",
    "internal",
    "microphone array",
    "realtek",
    "soundwire",
)
EXTERNAL_LISTENER_MIC_TERMS = (
    "anker",
    "atr",
    "audio-technica",
    "behringer",
    "blue",
    "elgato",
    "focusrite",
    "interface",
    "lav",
    "lavalier",
    "line",
    "measurement",
    "q2u",
    "recorder",
    "rode",
    "samson",
    "scarlett",
    "shure",
    "usb",
    "zoom",
)
HEADPHONE_OUTPUT_TERMS = (
    "airpods",
    "bluetooth",
    "earbud",
    "earpiece",
    "headphone",
    "headset",
    "wh-1000",
)
SOURCE_OUTPUT_TERMS = (
    "amd high definition",
    "benq",
    "display",
    "hdmi",
    "monitor",
    "nvidia",
    "realtek",
    "soundwire",
    "speaker",
)


def preflight_device_roles(device: dict[str, Any]) -> dict[str, bool]:
    name = str(device.get("name") or "")
    max_inputs = int(device.get("max_input_channels") or 0)
    max_outputs = int(device.get("max_output_channels") or 0)
    is_input = max_inputs > 0
    is_output = max_outputs > 0
    is_headset_mic = is_input and _contains_any(name, HEADSET_TERMS)
    is_builtin_input = is_input and _contains_any(name, BUILTIN_INPUT_TERMS)
    is_likely_external_input = (
        is_input
        and _contains_any(name, EXTERNAL_LISTENER_MIC_TERMS)
        and not is_headset_mic
        and not is_builtin_input
    )
    is_likely_headphone_output = is_output and _contains_any(name, HEADPHONE_OUTPUT_TERMS)
    is_likely_source_output = is_output and _contains_any(name, SOURCE_OUTPUT_TERMS)
    return {
        "is_builtin_input": is_builtin_input,
        "is_headset_mic": is_headset_mic,
        "is_input": is_input,
        "is_likely_external_input": is_likely_external_input,
        "is_likely_headphone_output": is_likely_headphone_output,
        "is_likely_source_output": is_likely_source_output,
        "is_output": is_output,
    }


def preflight_role_labels(roles: dict[str, bool]) -> list[str]:
    labels: list[str] = []
    if roles.get("is_likely_external_input"):
        labels.append("external_input_candidate_needs_listener_ear_placement")
    if roles.get("is_headset_mic"):
        labels.append("headset_mic_route_triage_only")
    if roles.get("is_builtin_input"):
        labels.append("builtin_or_array_mic_route_triage_only")
    if roles.get("is_likely_headphone_output"):
        labels.append("headphone_output_candidate")
    if roles.get("is_likely_source_output"):
        labels.append("source_output_candidate")
    if roles.get("is_input") and not labels:
        labels.append("input_candidate_unknown_placement")
    if roles.get("is_output") and not any(label.endswith("output_candidate") for label in labels):
        labels.append("output_candidate_unknown_role")
    return labels


def preflight_hostapis(sd: Any) -> list[dict[str, Any]]:
    try:
        hostapis = sd.query_hostapis()
    except Exception as exc:  # pragma: no cover - host diagnostic only.
        return [{"error": str(exc), "error_type": type(exc).__name__}]
    rows: list[dict[str, Any]] = []
    for index, info in enumerate(hostapis):
        if not isinstance(info, dict):
            try:
                info = dict(info)
            except Exception:
                info = {"repr": repr(info)}
        rows.append(
            {
                "default_input_device": info.get("default_input_device"),
                "default_output_device": info.get("default_output_device"),
                "device_count": info.get("device_count"),
                "index": index,
                "name": str(info.get("name", "")),
            }
        )
    return rows


def preflight_default_devices(sd: Any) -> dict[str, Any]:
    try:
        default_input, default_output = sd.default.device
    except Exception as exc:  # pragma: no cover - host diagnostic only.
        return {
            "error": str(exc),
            "error_type": type(exc).__name__,
            "input_device": None,
            "output_device": None,
        }
    return {
        "input_device": default_input,
        "output_device": default_output,
    }


def preflight_devices(sd: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, info in enumerate(sd.query_devices()):
        if not isinstance(info, dict):
            try:
                info = dict(info)
            except Exception:
                continue
        hostapi_index = info.get("hostapi")
        api_name = hostapi_name(sd, hostapi_index)
        row = {
            "default_samplerate": report_float(info.get("default_samplerate"), 3),
            "hostapi": hostapi_index,
            "hostapi_name": api_name,
            "index": int(info.get("index", index)),
            "max_input_channels": int(info.get("max_input_channels") or 0),
            "max_output_channels": int(info.get("max_output_channels") or 0),
            "name": " ".join(str(info.get("name", "")).split()),
        }
        roles = preflight_device_roles(row)
        row["roles"] = preflight_role_labels(roles)
        row["role_flags"] = roles
        rows.append(row)
    return rows


def preflight_inventory_fingerprint(
    *,
    default_devices: dict[str, Any],
    devices: list[dict[str, Any]],
    hostapis: list[dict[str, Any]],
    input_channels: int,
    output_channels: int,
    sample_rate_hz: int,
) -> str:
    payload = {
        "default_devices": default_devices,
        "devices": devices,
        "hostapis": hostapis,
        "input_channels": int(input_channels),
        "output_channels": int(output_channels),
        "sample_rate_hz": int(sample_rate_hz),
    }
    encoded = json.dumps(json_safe(payload), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def annotate_preflight_route_triples(
    triples: list[dict[str, Any]],
    devices: list[dict[str, Any]],
    *,
    max_triples: int,
) -> list[dict[str, Any]]:
    by_index = {int(device["index"]): device for device in devices}
    annotated: list[dict[str, Any]] = []
    for original_rank, triple in enumerate(triples, start=1):
        item = dict(triple)
        item["original_rank"] = original_rank
        for field, prefix in (
            ("input_device", "input"),
            ("source_output_device", "source"),
            ("headphone_output_device", "headphone"),
        ):
            try:
                device = by_index.get(int(item[field]))
            except (KeyError, TypeError, ValueError):
                device = None
            item[f"{prefix}_roles"] = list(device.get("roles", [])) if isinstance(device, dict) else []
            if isinstance(device, dict):
                item[f"{prefix}_name"] = device.get("name")
                item[f"{prefix}_hostapi_name"] = device.get("hostapi_name")
        item["preflight_route_score"] = preflight_route_score(item)
        item["preflight_route_score_reasons"] = preflight_route_score_reasons(item)
        annotated.append(item)
    annotated.sort(
        key=lambda item: (
            item["preflight_route_score"],
            item.get("original_rank", 0),
            str(item.get("input_name") or ""),
            str(item.get("source_name") or ""),
            str(item.get("headphone_name") or ""),
        )
    )
    for rank, item in enumerate(annotated, start=1):
        item["rank"] = rank
    if max_triples > 0:
        return annotated[:max_triples]
    return annotated


def preflight_route_score(item: dict[str, Any]) -> int:
    input_roles = set(str(role) for role in item.get("input_roles", []))
    source_roles = set(str(role) for role in item.get("source_roles", []))
    headphone_roles = set(str(role) for role in item.get("headphone_roles", []))
    score = 0
    if "headphone_output_candidate" not in headphone_roles:
        score += 1000
    if "source_output_candidate" not in source_roles:
        score += 700
    if "headphone_output_candidate" in source_roles:
        score += 300
    if "source_output_candidate" in headphone_roles:
        score += 300
    if "external_input_candidate_needs_listener_ear_placement" in input_roles:
        score += 0
    elif "builtin_or_array_mic_route_triage_only" in input_roles:
        score += 80
    elif "input_candidate_unknown_placement" in input_roles:
        score += 120
    elif "headset_mic_route_triage_only" in input_roles:
        score += 200
    else:
        score += 160
    if item.get("source_hostapi") != item.get("headphone_hostapi"):
        score += 50
    if item.get("input_hostapi") != item.get("source_hostapi"):
        score += 25
    return score


def preflight_route_score_reasons(item: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    input_roles = set(str(role) for role in item.get("input_roles", []))
    source_roles = set(str(role) for role in item.get("source_roles", []))
    headphone_roles = set(str(role) for role in item.get("headphone_roles", []))
    if "headphone_output_candidate" in headphone_roles:
        reasons.append("headphone_slot_has_headphone_output_candidate")
    else:
        reasons.append("headphone_slot_not_labeled_as_headphone")
    if "source_output_candidate" in source_roles:
        reasons.append("source_slot_has_source_output_candidate")
    else:
        reasons.append("source_slot_not_labeled_as_source")
    if "source_output_candidate" in headphone_roles:
        reasons.append("headphone_slot_labeled_as_source_output")
    if "headphone_output_candidate" in source_roles:
        reasons.append("source_slot_labeled_as_headphone_output")
    if "external_input_candidate_needs_listener_ear_placement" in input_roles:
        reasons.append("input_slot_external_candidate")
    elif "builtin_or_array_mic_route_triage_only" in input_roles:
        reasons.append("input_slot_builtin_or_array_candidate")
    elif "headset_mic_route_triage_only" in input_roles:
        reasons.append("input_slot_headset_triage_only")
    elif "input_candidate_unknown_placement" in input_roles:
        reasons.append("input_slot_unknown_placement")
    if item.get("source_hostapi") == item.get("headphone_hostapi"):
        reasons.append("source_and_headphone_share_hostapi")
    if item.get("input_hostapi") == item.get("source_hostapi"):
        reasons.append("input_and_source_share_hostapi")
    return reasons


def preflight_route_roles_aligned(item: dict[str, Any]) -> bool:
    source_roles = set(str(role) for role in item.get("source_roles", []))
    headphone_roles = set(str(role) for role in item.get("headphone_roles", []))
    return "source_output_candidate" in source_roles and "headphone_output_candidate" in headphone_roles


def preflight_route_capture_ready(item: dict[str, Any]) -> bool:
    input_roles = set(str(role) for role in item.get("input_roles", []))
    source_roles = set(str(role) for role in item.get("source_roles", []))
    headphone_roles = set(str(role) for role in item.get("headphone_roles", []))
    if "builtin_or_array_mic_route_triage_only" in input_roles:
        return False
    if "headset_mic_route_triage_only" in input_roles:
        return False
    if not (
        "external_input_candidate_needs_listener_ear_placement" in input_roles
        or "input_candidate_unknown_placement" in input_roles
    ):
        return False
    if not preflight_route_roles_aligned(item):
        return False
    if "headphone_output_candidate" in source_roles:
        return False
    if "source_output_candidate" in headphone_roles:
        return False
    return True


def select_preflight_route(
    triples: list[dict[str, Any]],
    selected_route: tuple[str, str, str] | None,
) -> dict[str, Any] | None:
    if selected_route is None:
        return None
    selected_key = route_triple_key(selected_route)
    for item in triples:
        if route_triple_key(item) == selected_key:
            return item
    return None


def display_preflight_route_triples(
    triples: list[dict[str, Any]],
    *,
    max_triples: int,
    selected_candidate: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if max_triples > 0:
        displayed = list(triples[:max_triples])
    else:
        displayed = list(triples)
    if selected_candidate is None:
        return displayed
    selected_key = route_triple_key(selected_candidate)
    if any(route_triple_key(item) == selected_key for item in displayed):
        return displayed
    if max_triples > 0:
        return [selected_candidate] + displayed[: max_triples - 1]
    return [selected_candidate] + displayed


def find_preflight_candidate(
    candidates: list[Any],
    selected_route: tuple[str, str, str],
) -> dict[str, Any] | None:
    selected_key = route_triple_key(selected_route)
    for item in candidates:
        if isinstance(item, dict) and route_triple_key(item) == selected_key:
            return item
    return None


def preflight_candidate_device_info(candidate: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        "measurement_input_device": {
            "hostapi": candidate.get("input_hostapi"),
            "hostapi_name": candidate.get("input_hostapi_name"),
            "index": candidate.get("input_device"),
            "name": candidate.get("input_name"),
        },
        "source_output_device": {
            "hostapi": candidate.get("source_hostapi"),
            "hostapi_name": candidate.get("source_hostapi_name"),
            "index": candidate.get("source_output_device"),
            "name": candidate.get("source_name"),
        },
        "headphone_output_device": {
            "hostapi": candidate.get("headphone_hostapi"),
            "hostapi_name": candidate.get("headphone_hostapi_name"),
            "index": candidate.get("headphone_output_device"),
            "name": candidate.get("headphone_name"),
        },
    }


def preflight_binding_device_mismatches(
    binding: dict[str, Any],
    device_info: dict[str, Any],
) -> list[str]:
    mismatches: list[str] = []
    preflight_device_info = binding.get("preflight_device_info", {})
    if not isinstance(preflight_device_info, dict):
        return ["preflight binding does not include preflight_device_info"]
    for key in ("measurement_input_device", "source_output_device", "headphone_output_device"):
        expected = preflight_device_info.get(key)
        current = device_info.get(key)
        if not isinstance(expected, dict) or not isinstance(current, dict):
            mismatches.append(f"{key} identity missing from preflight binding or current capture")
            continue
        for field in ("index", "hostapi", "hostapi_name", "name"):
            if str(expected.get(field)) != str(current.get(field)):
                mismatches.append(
                    f"{key}.{field} changed since preflight: {expected.get(field)!r} != {current.get(field)!r}"
                )
    return mismatches


def capture_preflight_binding(
    *,
    preflight_report: Path,
    measurement_input_device: int | str | None,
    source_output_device: int | str | None,
    headphone_output_device: int | str | None,
    sample_rate_hz: int,
    input_channels: int,
    output_channels: int,
) -> dict[str, Any]:
    report_path = Path(preflight_report)
    if not report_path.exists():
        raise ValueError(f"--preflight-report does not exist: {report_path}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("--preflight-report must contain a JSON object")
    summary = report.get("summary", {})
    benchmark = report.get("benchmarks", {}).get("headphone_earpiece_preflight", {})
    candidates = benchmark.get("candidate_route_triples", []) if isinstance(benchmark, dict) else []
    selected_route = route_triple_key(
        {
            "input_device": measurement_input_device,
            "source_output_device": source_output_device,
            "headphone_output_device": headphone_output_device,
        }
    )
    selected_route_arg = route_triple_arg(selected_route)
    selected_candidate = find_preflight_candidate(candidates if isinstance(candidates, list) else [], selected_route)
    failures: list[str] = []
    if report.get("fixture_kind") != PREFLIGHT_FIXTURE_KIND:
        failures.append("fixture_kind is not headphone preflight")
    if report.get("measurement_kind") != PREFLIGHT_MEASUREMENT_KIND:
        failures.append("measurement_kind is not headphone preflight")
    if report.get("release_proof") is not False or summary.get("release_proof") is not False:
        failures.append("preflight report must keep release_proof=false")
    if not bool(summary.get("planning_passed")):
        failures.append("preflight planning did not pass")
    if summary.get("recommended_path") != "guided_capture_possible":
        failures.append("preflight recommended_path is not guided_capture_possible")
    if not bool(summary.get("physical_listener_ear_input_confirmed")):
        failures.append("preflight does not confirm physical listener-ear input")
    if not bool(summary.get("selected_route_requested")):
        failures.append("preflight was not bound to a selected route")
    if not bool(summary.get("selected_route_found")):
        failures.append("selected route was not found in preflight inventory")
    if not bool(summary.get("selected_route_capture_ready")):
        failures.append("selected route is not capture-ready")
    if str(summary.get("selected_route") or "") != selected_route_arg:
        failures.append(
            f"capture devices {selected_route_arg} do not match preflight selected_route {summary.get('selected_route')}"
        )
    if int(summary.get("sample_rate_hz") or 0) != int(sample_rate_hz):
        failures.append("capture sample rate does not match preflight")
    if int(summary.get("input_channels") or 0) != int(input_channels):
        failures.append("capture input channels do not match preflight")
    if int(summary.get("output_channels") or 0) != int(output_channels):
        failures.append("capture output channels do not match preflight")
    if selected_candidate is None:
        failures.append("selected route candidate is not present in preflight report")
    elif not preflight_route_capture_ready(selected_candidate):
        failures.append("selected route candidate is not capture-ready by role labels")
    if failures:
        raise ValueError("invalid guided capture preflight binding: " + "; ".join(failures))
    return {
        "bound": True,
        "candidate_rank": selected_candidate.get("rank") if isinstance(selected_candidate, dict) else None,
        "candidate_score": selected_candidate.get("preflight_route_score") if isinstance(selected_candidate, dict) else None,
        "input_channels": int(input_channels),
        "inventory_fingerprint": summary.get("inventory_fingerprint"),
        "output_channels": int(output_channels),
        "physical_listener_ear_input_confirmed": True,
        "preflight_device_info": preflight_candidate_device_info(selected_candidate),
        "planning_passed": True,
        "preflight_generated_at_unix": report.get("generated_at_unix"),
        "preflight_report_path": str(report_path),
        "preflight_report_sha256": sha256_file(report_path),
        "recommended_path": summary.get("recommended_path"),
        "sample_rate_hz": int(sample_rate_hz),
        "selected_route": selected_route_arg,
        "selected_route_capture_ready": True,
    }


def preflight_quality_gates(summary: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "name": "headphone_preflight_not_release_proof",
            "passed": summary.get("release_proof") is False,
            "threshold": "preflight report must keep release_proof=false",
            "value": summary.get("release_proof"),
        },
        {
            "name": "headphone_preflight_devices_listed",
            "passed": int(summary.get("device_count") or 0) > 0,
            "threshold": "at least one PortAudio device listed",
            "value": summary.get("device_count"),
        },
        {
            "name": "headphone_preflight_input_candidate_found",
            "passed": int(summary.get("input_candidate_count") or 0) > 0,
            "threshold": "at least one device has enough input channels",
            "value": summary.get("input_candidate_count"),
        },
        {
            "name": "headphone_preflight_output_candidate_found",
            "passed": int(summary.get("output_candidate_count") or 0) > 0,
            "threshold": "at least one device has enough output channels",
            "value": summary.get("output_candidate_count"),
        },
        {
            "name": "headphone_preflight_distinct_output_routes_available",
            "passed": bool(summary.get("distinct_output_routes_available")),
            "threshold": "at least two distinct output devices for source and headphone routes",
            "value": summary.get("distinct_output_routes_available"),
        },
        {
            "name": "headphone_preflight_candidate_triple_found",
            "passed": int(summary.get("candidate_route_triple_count") or 0) > 0,
            "threshold": "at least one input/source/headphone route triple can be formed",
            "value": summary.get("candidate_route_triple_count"),
        },
        {
            "name": "headphone_preflight_role_aligned_route_candidate_found",
            "passed": int(summary.get("role_aligned_route_triple_count") or 0) > 0,
            "threshold": "at least one route candidate has source output in source slot and headphone output in headphone slot",
            "value": summary.get("role_aligned_route_triple_count"),
        },
        {
            "name": "headphone_preflight_capture_ready_route_candidate_found",
            "passed": int(summary.get("capture_ready_route_triple_count") or 0) > 0,
            "threshold": (
                "at least one route has a non-triage listener-ear input and unambiguous "
                "source/headphone output roles"
            ),
            "value": summary.get("capture_ready_route_triple_count"),
        },
        {
            "name": "headphone_preflight_selected_route_found_when_requested",
            "passed": not bool(summary.get("selected_route_requested")) or bool(summary.get("selected_route_found")),
            "threshold": "if a selected route is supplied, it must exist in the current device inventory",
            "value": {
                "selected_route": summary.get("selected_route"),
                "selected_route_found": summary.get("selected_route_found"),
            },
        },
        {
            "name": "headphone_preflight_selected_route_capture_ready_when_confirmed",
            "passed": not bool(summary.get("physical_listener_ear_input_confirmed"))
            or bool(summary.get("selected_route_capture_ready")),
            "threshold": "physical confirmation must be tied to a selected capture-ready route",
            "value": {
                "physical_listener_ear_input_confirmed": summary.get("physical_listener_ear_input_confirmed"),
                "selected_route": summary.get("selected_route"),
                "selected_route_capture_ready": summary.get("selected_route_capture_ready"),
            },
        },
        {
            "name": "headphone_preflight_physical_listener_ear_input_confirmed",
            "passed": bool(summary.get("physical_listener_ear_input_confirmed")),
            "threshold": "operator explicitly confirms the selected input is physically at the listener-ear point",
            "value": {
                "likely_external_input_count": summary.get("likely_external_input_count"),
                "physical_listener_ear_input_confirmed": summary.get("physical_listener_ear_input_confirmed"),
            },
        },
    ]


def preflight_recommended_path(summary: dict[str, Any]) -> str:
    if int(summary.get("input_candidate_count") or 0) <= 0:
        return "manual_external_recorder_required"
    if int(summary.get("output_candidate_count") or 0) <= 0:
        return "manual_external_recorder_required"
    if int(summary.get("candidate_route_triple_count") or 0) <= 0:
        return "manual_external_recorder_preferred"
    if int(summary.get("role_aligned_route_triple_count") or 0) <= 0:
        return "manual_external_recorder_preferred"
    if int(summary.get("capture_ready_route_triple_count") or 0) <= 0:
        return "route_probe_triage_only_manual_listener_ear_capture_required"
    if not bool(summary.get("distinct_output_routes_available")):
        return "manual_external_recorder_preferred"
    if not bool(summary.get("physical_listener_ear_input_confirmed")):
        return "guided_capture_possible_after_physical_input_confirmation"
    if not bool(summary.get("selected_route_requested")):
        return "guided_capture_requires_selected_route_confirmation"
    if not bool(summary.get("selected_route_found")):
        return "selected_route_not_found"
    if not bool(summary.get("selected_route_capture_ready")):
        return "selected_route_not_capture_ready"
    if not bool(summary.get("likely_headphone_output_found")):
        return "manual_external_recorder_preferred"
    if not bool(summary.get("likely_source_output_found")):
        return "manual_external_recorder_preferred"
    return "guided_capture_possible"


def powershell_quote_arg(value: Any) -> str:
    text = str(value)
    safe = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-.\\/:$")
    if text and all(char in safe for char in text):
        return text
    return "'" + text.replace("'", "''") + "'"


def preflight_filter_flags(args: argparse.Namespace) -> str:
    parts: list[str] = []
    for hostapi in args.hostapi or []:
        parts.extend(["--hostapi", powershell_quote_arg(hostapi)])
    if bool(args.include_cross_hostapi):
        parts.append("--include-cross-hostapi")
    if bool(args.allow_shared_output_device):
        parts.append("--allow-shared-output-device")
    parts.extend(["--max-triples", str(int(args.max_triples))])
    return " ".join(parts)


def preflight_command_hints(
    route_probe_candidate: dict[str, Any] | None,
    capture_candidate: dict[str, Any] | None,
    args: argparse.Namespace,
    *,
    recommended_path: str,
) -> dict[str, str]:
    base = "pwsh -NoProfile -File scripts/headphone_isolation_local.ps1"
    python = "-Python $env:LANGUAGE_PYTHON"
    preflight_flags = preflight_filter_flags(args)
    preflight_suffix = f" {preflight_flags}" if preflight_flags else ""
    hints = {
        "manual_prepare": (
            f"{base} -Action prepare-manual {python} --sample-rate-hz {int(args.sample_rate_hz)} "
            f"--playback-gain-db {float(DEFAULT_PLAYBACK_GAIN_DB):g}"
        ),
        "preflight": (
            f"{base} -Action preflight {python} --sample-rate-hz {int(args.sample_rate_hz)} "
            f"--input-channels {int(args.input_channels)} --output-channels {int(args.output_channels)}"
            f"{preflight_suffix}"
        ),
    }
    if recommended_path == "guided_capture_possible_after_physical_input_confirmation" and capture_candidate:
        hints["confirm_physical_input_preflight"] = (
            f"{base} -Action preflight {python} --sample-rate-hz {int(args.sample_rate_hz)} "
            f"--input-channels {int(args.input_channels)} --output-channels {int(args.output_channels)} "
            f"{preflight_suffix} --selected-route {route_triple_arg(capture_candidate)} "
            "--confirm-physical-listener-ear-input"
        )
    if capture_candidate and recommended_path == "guided_capture_possible":
        input_device = capture_candidate.get("input_device")
        source_device = capture_candidate.get("source_output_device")
        headphone_device = capture_candidate.get("headphone_output_device")
        probe_command = (
            f"{base} -Action probe-route {python} --measurement-input-device {input_device} "
            f"--source-output-device {source_device} --headphone-output-device {headphone_device} "
            f"--sample-rate-hz {int(args.sample_rate_hz)} --input-channels {int(args.input_channels)} "
            f"--output-channels {int(args.output_channels)} --playback-gain-db {float(DEFAULT_PLAYBACK_GAIN_DB):g}"
        )
        hints["probe_route"] = probe_command
        hints["capture"] = (
            f"{base} -Action capture {python} --measurement-input-device {input_device} "
            f"--source-output-device {source_device} --headphone-output-device {headphone_device} "
            f"--preflight-report {powershell_quote_arg(Path(args.output_dir) / 'runs' / args.run_id / DEFAULT_PREFLIGHT_REPORT)} "
            f"--sample-rate-hz {int(args.sample_rate_hz)} --input-channels {int(args.input_channels)} "
            f"--output-channels {int(args.output_channels)} --playback-gain-db {float(DEFAULT_PLAYBACK_GAIN_DB):g} "
            "--headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel "
            "--measurement-microphone-label $microphoneLabel"
        )
    elif route_probe_candidate:
        input_device = route_probe_candidate.get("input_device")
        source_device = route_probe_candidate.get("source_output_device")
        headphone_device = route_probe_candidate.get("headphone_output_device")
        hints["route_probe_triage_only"] = (
            f"{base} -Action probe-route {python} --measurement-input-device {input_device} "
            f"--source-output-device {source_device} --headphone-output-device {headphone_device} "
            f"--sample-rate-hz {int(args.sample_rate_hz)} --input-channels {int(args.input_channels)} "
            f"--output-channels {int(args.output_channels)} --playback-gain-db {float(DEFAULT_PLAYBACK_GAIN_DB):g} "
            "--score-warning-only"
        )
    return hints


def build_headphone_preflight_report(sd: Any, args: argparse.Namespace) -> dict[str, Any]:
    if int(args.input_channels) <= 0:
        raise ValueError("--input-channels must be positive")
    if int(args.output_channels) <= 0:
        raise ValueError("--output-channels must be positive")
    if int(args.sample_rate_hz) <= 0:
        raise ValueError("--sample-rate-hz must be positive")
    hostapi_filters = list(args.hostapi or [])
    devices = preflight_devices(sd)
    hostapis = preflight_hostapis(sd)
    default_devices = preflight_default_devices(sd)
    filtered_inputs = [
        device
        for device in devices
        if int(device.get("max_input_channels") or 0) >= int(args.input_channels)
        and hostapi_matches(device, str(device.get("hostapi_name") or ""), hostapi_filters)
    ]
    filtered_outputs = [
        device
        for device in devices
        if int(device.get("max_output_channels") or 0) >= int(args.output_channels)
        and hostapi_matches(device, str(device.get("hostapi_name") or ""), hostapi_filters)
    ]
    triples = candidate_route_triples(
        sd,
        allow_shared_output_device=bool(args.allow_shared_output_device),
        hostapis=hostapi_filters,
        include_cross_hostapi=bool(args.include_cross_hostapi),
        input_channels=int(args.input_channels),
        max_triples=0,
        output_channels=int(args.output_channels),
    )
    annotated_triples = annotate_preflight_route_triples(
        triples,
        devices,
        max_triples=0,
    )
    role_aligned_triples = [
        triple for triple in annotated_triples if preflight_route_roles_aligned(triple)
    ]
    capture_ready_triples = [
        triple for triple in annotated_triples if preflight_route_capture_ready(triple)
    ]
    selected_route = tuple(args.selected_route) if args.selected_route else None
    selected_candidate = select_preflight_route(annotated_triples, selected_route)
    selected_route_capture_ready = (
        preflight_route_capture_ready(selected_candidate) if selected_candidate is not None else False
    )
    displayed_triples = display_preflight_route_triples(
        annotated_triples,
        max_triples=int(args.max_triples),
        selected_candidate=selected_candidate,
    )
    distinct_output_routes_available = len({int(device["index"]) for device in filtered_outputs}) >= 2
    role_flags = [device.get("role_flags", {}) for device in devices]
    summary = {
        "adapter_id": args.adapter_id,
        "allow_shared_output_device": bool(args.allow_shared_output_device),
        "candidate_route_triple_count": len(annotated_triples),
        "capture_ready_route_triple_count": len(capture_ready_triples),
        "default_devices": default_devices,
        "device_count": len(devices),
        "distinct_output_routes_available": distinct_output_routes_available,
        "hostapi_filters": hostapi_filters,
        "include_cross_hostapi": bool(args.include_cross_hostapi),
        "input_candidate_count": len(filtered_inputs),
        "input_channels": int(args.input_channels),
        "inventory_fingerprint": preflight_inventory_fingerprint(
            default_devices=default_devices,
            devices=devices,
            hostapis=hostapis,
            input_channels=int(args.input_channels),
            output_channels=int(args.output_channels),
            sample_rate_hz=int(args.sample_rate_hz),
        ),
        "likely_external_input_count": sum(
            1 for flags in role_flags if bool(flags.get("is_likely_external_input"))
        ),
        "likely_headphone_output_found": any(
            bool(flags.get("is_likely_headphone_output")) for flags in role_flags
        ),
        "likely_source_output_found": any(bool(flags.get("is_likely_source_output")) for flags in role_flags),
        "measurement_kind": PREFLIGHT_MEASUREMENT_KIND,
        "output_candidate_count": len(filtered_outputs),
        "output_channels": int(args.output_channels),
        "physical_listener_ear_input_confirmed": bool(args.confirm_physical_listener_ear_input),
        "release_proof": False,
        "role_aligned_route_triple_count": len(role_aligned_triples),
        "sample_rate_hz": int(args.sample_rate_hz),
        "selected_route": route_triple_arg(selected_route) if selected_route is not None else None,
        "selected_route_capture_ready": selected_route_capture_ready,
        "selected_route_found": selected_candidate is not None,
        "selected_route_requested": selected_route is not None,
        "listed_candidate_route_triple_count": len(displayed_triples),
    }
    summary["recommended_path"] = preflight_recommended_path(summary)
    gates = preflight_quality_gates(summary)
    summary["quality_gates"] = gates
    summary["planning_passed"] = all(bool(gate["passed"]) for gate in gates)
    route_probe_candidate = selected_candidate or (role_aligned_triples[0] if role_aligned_triples else None)
    if selected_route is not None:
        capture_candidate = selected_candidate if selected_route_capture_ready else None
    else:
        capture_candidate = capture_ready_triples[0] if capture_ready_triples else None
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": PREFLIGHT_FIXTURE_KIND,
        "measurement_kind": PREFLIGHT_MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": summary,
        "benchmarks": {
            "headphone_earpiece_preflight": {
                "adapter_id": args.adapter_id,
                "candidate_route_triples": displayed_triples,
                "default_devices": default_devices,
                "device_inventory": devices,
                "hostapis": hostapis,
                "recommended_commands": preflight_command_hints(
                    route_probe_candidate,
                    capture_candidate,
                    args,
                    recommended_path=str(summary["recommended_path"]),
                ),
                "required_follow_up": (
                    "Use this report to choose either route-probe plus capture or the manual external "
                    "recorder kit. Preflight never satisfies release evidence."
                ),
            }
        },
        "detractor_loop": {
            "strongest_objection": (
                "Device enumeration cannot prove acoustic listener-ear placement, Bluetooth mode behavior, "
                "Windows processing state, source leakage, or translated-playback fidelity."
            ),
            "verdict": (
                "Keep release_proof=false. Treat preflight as a hardware plan, then collect physical "
                "listener-ear WAV evidence with score-manual or capture."
            ),
        },
    }
    return json_safe(report)


def render_headphone_preflight_markdown(report: dict[str, Any], json_report_path: Path) -> str:
    summary = report.get("summary", {})
    benchmark = report.get("benchmarks", {}).get("headphone_earpiece_preflight", {})
    candidates = benchmark.get("candidate_route_triples", [])
    devices = benchmark.get("device_inventory", [])
    commands = benchmark.get("recommended_commands", {})
    lines = [
        "# Headphone/Earpiece Preflight",
        "",
        "No audio was played or recorded by this preflight.",
        "",
        f"- JSON report: `{json_report_path}`",
        f"- Release proof: `{summary.get('release_proof')}`",
        f"- Planning passed: `{summary.get('planning_passed')}`",
        f"- Recommended path: `{summary.get('recommended_path')}`",
        f"- Physical listener-ear input confirmed: `{summary.get('physical_listener_ear_input_confirmed')}`",
        f"- Inventory fingerprint: `{summary.get('inventory_fingerprint')}`",
        "",
        "## Detractor Verdict",
        "",
        str(report.get("detractor_loop", {}).get("strongest_objection", "")),
        "",
        str(report.get("detractor_loop", {}).get("verdict", "")),
        "",
        "## Device Summary",
        "",
        "| Index | Host API | Inputs | Outputs | Roles | Name |",
        "| --- | --- | ---: | ---: | --- | --- |",
    ]
    for device in devices:
        roles = ", ".join(device.get("roles", []))
        lines.append(
            "| {index} | {hostapi} | {inputs} | {outputs} | {roles} | {name} |".format(
                hostapi=str(device.get("hostapi_name") or ""),
                index=device.get("index"),
                inputs=device.get("max_input_channels"),
                name=str(device.get("name") or "").replace("|", "/"),
                outputs=device.get("max_output_channels"),
                roles=roles.replace("|", "/"),
            )
        )
    lines.extend(
        [
            "",
            "## Route Candidates",
            "",
        ]
    )
    if candidates:
        lines.extend(
            [
                "| Rank | Score | Input | Source Output | Headphone Output | Notes |",
                "| ---: | ---: | --- | --- | --- | --- |",
            ]
        )
        for candidate in candidates[:10]:
            lines.append(
                "| {rank} | {score} | {input_device} `{input_name}` | {source_device} `{source_name}` | "
                "{headphone_device} `{headphone_name}` | {reasons} |".format(
                    headphone_device=candidate.get("headphone_output_device"),
                    headphone_name=str(candidate.get("headphone_name") or "").replace("|", "/"),
                    input_device=candidate.get("input_device"),
                    input_name=str(candidate.get("input_name") or "").replace("|", "/"),
                    rank=candidate.get("rank"),
                    reasons=", ".join(candidate.get("preflight_route_score_reasons", [])).replace("|", "/"),
                    score=candidate.get("preflight_route_score"),
                    source_device=candidate.get("source_output_device"),
                    source_name=str(candidate.get("source_name") or "").replace("|", "/"),
                )
            )
    else:
        lines.append("No input/source/headphone route triple was formed with the current filters.")
    lines.extend(["", "## Next Commands", ""])
    for name, command in sorted(commands.items()):
        lines.extend([f"### {name}", "", "```powershell", str(command), "```", ""])
    lines.extend(
        [
            "## Hardware Notes",
            "",
            "- Use a USB/lav/recorder microphone physically at the listener-ear point for release evidence.",
            "- Laptop built-in microphones are route triage only; they do not unlock guided capture or release evidence.",
            "- For an improvised laptop sanity test, place one headphone earcup over the laptop mic opening and run `route_probe_triage_only`.",
            "- A Bluetooth headset microphone is route triage only unless it is physically at that point.",
            "- Disable audio enhancements, AGC, echo cancellation, spatial audio, and communications ducking.",
            "- Preflight is complete when it tells you which path to try next; release evidence still needs WAV scoring.",
            "",
        ]
    )
    return "\n".join(lines)


def headphone_preflight(args: argparse.Namespace) -> int:
    sd = import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / DEFAULT_PREFLIGHT_REPORT
    markdown_path = run_dir / DEFAULT_PREFLIGHT_MARKDOWN
    report = build_headphone_preflight_report(sd, args)
    report["artifact_paths"] = {"preflight_markdown": str(markdown_path)}
    markdown_path.write_text(render_headphone_preflight_markdown(report, report_path), encoding="utf-8")
    report["artifact_hashes"] = {"preflight_markdown": sha256_file(markdown_path)}
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    summary = report["summary"]
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    else:
        recommended_path = str(summary.get("recommended_path"))
        if recommended_path == "guided_capture_possible":
            status = "GUIDED-CAPTURE-READY"
        elif recommended_path == "guided_capture_possible_after_physical_input_confirmation":
            status = "NEEDS-PHYSICAL-INPUT-CONFIRMATION"
        elif recommended_path == "route_probe_triage_only_manual_listener_ear_capture_required":
            status = "ROUTE-TRIAGE-ONLY"
        elif recommended_path == "guided_capture_requires_selected_route_confirmation":
            status = "NEEDS-SELECTED-ROUTE-CONFIRMATION"
        elif recommended_path in {"selected_route_not_found", "selected_route_not_capture_ready"}:
            status = "NEEDS-ROUTE-FIX"
        else:
            status = "NEEDS-HARDWARE"
        print(
            "headphone/earpiece preflight {status}: devices={devices}, candidates={candidates}, "
            "recommended_path={path}".format(
                candidates=summary.get("candidate_route_triple_count"),
                devices=summary.get("device_count"),
                path=recommended_path,
                status=status,
            )
        )
        print(f"wrote headphone preflight report to {report_path}")
        print(f"wrote headphone preflight checklist to {markdown_path}")
    return 0


def report_float(value: Any, digits: int = 6) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return round(numeric, digits)


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
    if channels != 1:
        raise ValueError(f"{path} must be mono PCM_16 WAV")
    if sample_width != 2:
        raise ValueError(f"{path} must be mono PCM_16 WAV")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if samples.size <= 0:
        raise ValueError(f"{path} must contain frames")
    return samples.astype(np.float32), int(sample_rate_hz)


def write_mono_wav(path: Path, samples: np.ndarray, sample_rate_hz: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pcm = mono_float_to_pcm16(samples)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate_hz)
        wav.writeframes(pcm.tobytes())


def mono_float_to_pcm16(samples: np.ndarray) -> np.ndarray:
    return np.round(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")


def pcm16_bytes_sha256(pcm: np.ndarray) -> str:
    return hashlib.sha256(pcm.astype("<i2", copy=False).tobytes()).hexdigest()


def mono_wav_pcm_sha256(path: Path) -> str:
    with wave.open(str(path), "rb") as wav:
        if int(wav.getnchannels()) != 1 or int(wav.getsampwidth()) != 2:
            raise ValueError(f"{path} must be mono PCM_16 WAV")
        frames = wav.readframes(int(wav.getnframes()))
    return hashlib.sha256(frames).hexdigest()


def resample_to_rate(audio: np.ndarray, source_rate_hz: int, target_rate_hz: int) -> np.ndarray:
    if source_rate_hz == target_rate_hz:
        return audio.astype(np.float32)
    if audio.size == 0:
        return audio.astype(np.float32)
    source_positions = np.linspace(0.0, 1.0, int(audio.size), endpoint=False)
    target_size = max(1, int(round(float(audio.size) * float(target_rate_hz) / float(source_rate_hz))))
    target_positions = np.linspace(0.0, 1.0, target_size, endpoint=False)
    return np.interp(target_positions, source_positions, audio.astype(np.float64)).astype(np.float32)


def apply_playback_gain(samples: np.ndarray, gain_db: float, max_peak_dbfs: float) -> np.ndarray:
    scaled = np.asarray(samples, dtype=np.float32) * db_to_linear(float(gain_db))
    peak = float(np.max(np.abs(scaled))) if scaled.size else 0.0
    limit = db_to_linear(float(max_peak_dbfs))
    if peak > limit and peak > 0.0:
        scaled = scaled * (limit / peak)
    return scaled.astype(np.float32)


def add_padding(samples: np.ndarray, sample_rate_hz: int, lead_s: float, tail_s: float) -> np.ndarray:
    lead = np.zeros(max(0, int(round(float(lead_s) * float(sample_rate_hz)))), dtype=np.float32)
    tail = np.zeros(max(0, int(round(float(tail_s) * float(sample_rate_hz)))), dtype=np.float32)
    return np.concatenate([lead, np.asarray(samples, dtype=np.float32), tail]).astype(np.float32)


def mono_playback(samples: np.ndarray, channels: int) -> np.ndarray:
    channel_count = max(1, int(channels))
    mono = np.asarray(samples, dtype=np.float32).reshape(-1, 1)
    return np.repeat(mono, channel_count, axis=1).astype(np.float32)


def resolve_report_path(report_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty artifact path")
    path = Path(value)
    if path.is_absolute():
        return path
    beside = report_path.parent / path
    if beside.exists():
        return beside
    return path


def resolve_manual_manifest_path(manifest_path: Path, value: Any) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("expected non-empty manifest path")
    path = Path(value)
    if path.is_absolute():
        return path
    candidates = [
        path,
        manifest_path.parent / path,
        manifest_path.parent / path.name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return path


def inspect_mono_pcm16_wav(
    path: Path,
    *,
    expected_sample_rate_hz: int,
    min_duration_s: float,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exists": path.exists(),
        "issues": [],
        "path": str(path),
        "passed": False,
    }
    if not path.exists():
        result["issues"].append("missing")
        return result
    try:
        with wave.open(str(path), "rb") as wav:
            channels = int(wav.getnchannels())
            sample_width = int(wav.getsampwidth())
            sample_rate_hz = int(wav.getframerate())
            frame_count = int(wav.getnframes())
    except (OSError, wave.Error) as exc:
        result["issues"].append(f"unreadable WAV: {exc}")
        return result
    duration_s = float(frame_count) / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    result.update(
        {
            "channels": channels,
            "duration_s": round(duration_s, 6),
            "frame_count": frame_count,
            "sample_rate_hz": sample_rate_hz,
            "sample_width_bytes": sample_width,
        }
    )
    if channels != 1:
        result["issues"].append("must be mono")
    if sample_width != 2:
        result["issues"].append("must be 16-bit PCM")
    if sample_rate_hz != int(expected_sample_rate_hz):
        result["issues"].append(f"sample rate must be {int(expected_sample_rate_hz)} Hz")
    if frame_count <= 0:
        result["issues"].append("must contain frames")
    if duration_s < float(min_duration_s):
        result["issues"].append(f"duration must be >= {float(min_duration_s):.3f}s")
    result["passed"] = not result["issues"]
    return result


def load_tts_segments(report_path: Path) -> list[dict[str, Any]]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    benchmark = report.get("benchmarks", {}).get("same_voice_or_fallback_tts", {})
    segments = benchmark.get("segments", []) if isinstance(benchmark, dict) else []
    if not isinstance(segments, list) or not segments:
        raise ValueError(f"{report_path} does not contain same_voice_or_fallback_tts segments")
    return [segment for segment in segments if isinstance(segment, dict)]


def build_tts_reference_tracks(
    report_path: Path,
    sample_rate_hz: int,
    gap_s: float,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    source_parts: list[np.ndarray] = []
    translated_parts: list[np.ndarray] = []
    gap = np.zeros(max(0, int(round(float(gap_s) * float(sample_rate_hz)))), dtype=np.float32)
    segment_records: list[dict[str, Any]] = []
    cursor = 0
    for index, segment in enumerate(load_tts_segments(report_path)):
        source_path = resolve_report_path(report_path, segment.get("reference_audio_path"))
        translated_path = resolve_report_path(report_path, segment.get("tts_output_path"))
        source_audio, source_rate_hz = read_mono_wav(source_path)
        translated_audio, translated_rate_hz = read_mono_wav(translated_path)
        source_audio = resample_to_rate(source_audio, source_rate_hz, sample_rate_hz)
        translated_audio = resample_to_rate(translated_audio, translated_rate_hz, sample_rate_hz)
        frame_count = max(int(source_audio.size), int(translated_audio.size))
        source_window = np.zeros(frame_count, dtype=np.float32)
        translated_window = np.zeros(frame_count, dtype=np.float32)
        source_window[: source_audio.size] = source_audio
        translated_window[: translated_audio.size] = translated_audio
        source_parts.append(source_window)
        translated_parts.append(translated_window)
        source_parts.append(gap)
        translated_parts.append(gap)
        segment_records.append(
            {
                "segment_index": index,
                "start_sample": cursor,
                "end_sample": cursor + frame_count,
                "source_reference_path": str(source_path),
                "source_reference_sha256": sha256_file(source_path),
                "translated_reference_path": str(translated_path),
                "translated_reference_sha256": sha256_file(translated_path),
            }
        )
        cursor += frame_count + gap.size
    source_track = np.concatenate(source_parts) if source_parts else np.zeros(0, dtype=np.float32)
    translated_track = np.concatenate(translated_parts) if translated_parts else np.zeros(0, dtype=np.float32)
    return source_track.astype(np.float32), translated_track.astype(np.float32), segment_records


def limit_track_pair(
    source_track: np.ndarray,
    translated_track: np.ndarray,
    *,
    sample_rate_hz: int,
    max_duration_s: float,
) -> tuple[np.ndarray, np.ndarray]:
    if max_duration_s <= 0.0:
        return source_track.astype(np.float32), translated_track.astype(np.float32)
    max_samples = max(1, int(round(float(max_duration_s) * float(sample_rate_hz))))
    return source_track[:max_samples].astype(np.float32), translated_track[:max_samples].astype(np.float32)


def limit_reference_segments(
    segments: list[dict[str, Any]],
    *,
    sample_rate_hz: int,
    max_duration_s: float,
) -> list[dict[str, Any]]:
    if max_duration_s <= 0.0:
        return [dict(segment) for segment in segments]
    max_samples = max(1, int(round(float(max_duration_s) * float(sample_rate_hz))))
    limited: list[dict[str, Any]] = []
    for segment in segments:
        start_sample = int(segment.get("start_sample", 0))
        end_sample = int(segment.get("end_sample", 0))
        if start_sample >= max_samples:
            continue
        item = dict(segment)
        if end_sample > max_samples:
            item["end_sample"] = max_samples
            item["truncated_by_max_reference_duration"] = True
        limited.append(item)
    return limited


def build_route_probe_signal(sample_rate_hz: int, duration_s: float) -> np.ndarray:
    frame_count = max(1, int(round(float(sample_rate_hz) * float(duration_s))))
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    start_hz = 420.0
    end_hz = min(3600.0, float(sample_rate_hz) * 0.40)
    slope = (end_hz - start_hz) / max(float(duration_s), 1.0 / float(sample_rate_hz))
    phase = 2.0 * math.pi * (start_hz * t + 0.5 * slope * t * t)
    signal = np.sin(phase).astype(np.float32) * 0.35
    fade_samples = min(frame_count // 2, max(1, int(round(0.025 * float(sample_rate_hz)))))
    if fade_samples > 1:
        ramp = np.linspace(0.0, 1.0, fade_samples, dtype=np.float32)
        signal[:fade_samples] *= ramp
        signal[-fade_samples:] *= ramp[::-1]
    return signal.astype(np.float32)


def build_virtual_speech_like_track(sample_rate_hz: int, duration_s: float, *, base_hz: float) -> np.ndarray:
    frame_count = max(1, int(round(float(sample_rate_hz) * float(duration_s))))
    t = np.arange(frame_count, dtype=np.float64) / float(sample_rate_hz)
    carrier = (
        np.sin(2.0 * math.pi * base_hz * t)
        + 0.45 * np.sin(2.0 * math.pi * base_hz * 2.07 * t + 0.4)
        + 0.22 * np.sin(2.0 * math.pi * base_hz * 3.91 * t + 1.1)
    )
    syllables = 0.58 + 0.42 * np.sin(2.0 * math.pi * 3.7 * t) ** 2
    phrase = 0.72 + 0.28 * np.sin(2.0 * math.pi * 0.83 * t + 0.6)
    signal = carrier * syllables * phrase
    peak = float(np.max(np.abs(signal))) if signal.size else 1.0
    if peak > 0.0:
        signal = signal / peak
    return (signal * 0.30).astype(np.float32)


def simulate_virtual_listener_recording(
    reference: np.ndarray,
    *,
    sample_rate_hz: int,
    gain_db: float,
    lag_ms: float,
    noise_dbfs: float,
    reflection_db: float,
    seed: int,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    lag_samples = max(0, int(round(float(lag_ms) * float(sample_rate_hz) / 1000.0)))
    reflection_samples = max(1, int(round(0.018 * float(sample_rate_hz))))
    padded = np.concatenate([np.zeros(lag_samples, dtype=np.float32), reference]).astype(np.float32)
    rendered = padded[: reference.size].copy()
    if reflection_samples < rendered.size:
        rendered[reflection_samples:] += rendered[:-reflection_samples] * db_to_linear(float(reflection_db))
    rendered *= db_to_linear(float(gain_db))
    noise = rng.normal(0.0, db_to_linear(float(noise_dbfs)), size=reference.size).astype(np.float32)
    return (rendered + noise).astype(np.float32)


def portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
    sd = import_sounddevice()
    info = sd.query_devices(device, kind=kind)
    hostapi = sd.query_hostapis(int(info["hostapi"]))
    return {
        "default": device is None,
        "default_samplerate": float(info["default_samplerate"]),
        "hostapi": int(info["hostapi"]),
        "hostapi_name": str(hostapi.get("name", "")),
        "index": int(info.get("index", -1)),
        "max_input_channels": int(info["max_input_channels"]),
        "max_output_channels": int(info["max_output_channels"]),
        "name": str(info["name"]),
        "requested_device": device,
    }


def measurement_device_fingerprint(
    *,
    device_info: dict[str, Any],
    sample_rate_hz: int,
    input_channels: int,
    output_channels: int,
) -> str:
    payload = {
        "device_info": device_info,
        "input_channels": int(input_channels),
        "output_channels": int(output_channels),
        "sample_rate_hz": int(sample_rate_hz),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def record_playback(
    playback: np.ndarray,
    *,
    sample_rate_hz: int,
    input_device: int | str | None,
    output_device: int | str | None,
    input_channels: int,
) -> tuple[np.ndarray, float]:
    sd = import_sounddevice()
    start = time.perf_counter()
    recording = sd.playrec(
        playback,
        samplerate=sample_rate_hz,
        channels=max(1, int(input_channels)),
        dtype="float32",
        device=(input_device, output_device),
        blocking=True,
    )
    elapsed_s = time.perf_counter() - start
    if getattr(recording, "ndim", 1) > 1:
        recording = recording.mean(axis=1)
    return np.asarray(recording, dtype=np.float32), elapsed_s


def recording_diagnostics(samples: np.ndarray, sample_rate_hz: int) -> dict[str, Any]:
    clipped = int(np.count_nonzero(np.abs(samples) >= 0.999))
    return {
        "clipped_sample_count": clipped,
        "duration_s": round(float(samples.size) / float(sample_rate_hz), 6),
        "peak_dbfs": round(peak_dbfs(samples), 3),
        "rms_dbfs": round(dbfs(samples), 3),
    }


def portaudio_output_signature(device_info: dict[str, Any]) -> dict[str, Any]:
    return {
        "hostapi": device_info.get("hostapi"),
        "hostapi_name": device_info.get("hostapi_name"),
        "index": device_info.get("index"),
        "name": device_info.get("name"),
    }


def wait_for_operator(message: str, *, non_interactive: bool) -> None:
    print(message)
    if not non_interactive:
        input("Press Enter when ready...")


def write_capture_failure_report(
    *,
    args: argparse.Namespace,
    run_dir: Path,
    capture_context: dict[str, Any],
    artifact_paths: dict[str, str],
    error: Exception,
) -> Path:
    artifact_hashes = {
        key: sha256_file(Path(value))
        for key, value in artifact_paths.items()
        if Path(value).exists()
    }
    summary = {
        "capture_backend": CAPTURE_BACKEND_PORTAUDIO,
        "capture_error": str(error),
        "capture_error_type": type(error).__name__,
        "capture_source_kind": CAPTURE_SOURCE_KIND_PORTAUDIO,
        "measurement_kind": MEASUREMENT_KIND,
        "quality_gates": [
            {
                "name": "headphone_guided_capture_completed",
                "passed": False,
                "threshold": "all three guided host capture steps complete",
                "value": {
                    "capture_error": str(error),
                    "capture_error_type": type(error).__name__,
                },
            }
        ],
        "release_proof": False,
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
    }
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": FIXTURE_KIND,
        "measurement_kind": MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": False,
            "quality_gates": summary["quality_gates"],
            "release_proof": False,
        },
        "benchmarks": {
            BENCHMARK_NAME: {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_paths": artifact_paths,
        "artifact_hashes": artifact_hashes,
        "capture": capture_context,
        "detractor_loop": {
            "strongest_objection": (
                "A failed guided capture cannot satisfy playback source-suppression evidence."
            ),
            "verdict": "Use this as route triage only; fix devices/sample rate before release gating.",
        },
    }
    report_path = run_dir / "headphone-isolation-report.json"
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report_path


def route_probe_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    def finite_float(name: str) -> float | None:
        value = summary.get(name)
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    def finite_nested_float(route_name: str, field_name: str) -> float | None:
        recording = summary.get(f"{route_name}_route_recording")
        if not isinstance(recording, dict):
            return None
        value = recording.get(field_name)
        if value is None:
            return None
        number = float(value)
        return number if math.isfinite(number) else None

    def nested_int(route_name: str, field_name: str) -> int | None:
        recording = summary.get(f"{route_name}_route_recording")
        if not isinstance(recording, dict):
            return None
        value = recording.get(field_name)
        if value is None:
            return None
        return int(value)

    source_opened = bool(summary.get("source_route_opened"))
    headphone_opened = bool(summary.get("headphone_route_opened"))
    source_clone = bool(summary.get("source_route_recording_matches_reference"))
    headphone_clone = bool(summary.get("headphone_route_recording_matches_reference"))
    hashes = bool(summary.get("all_artifact_hashes_present"))
    source_corr = finite_float("source_route_reference_correlation")
    headphone_corr = finite_float("headphone_route_reference_correlation")
    source_confidence = finite_float("source_route_reference_confidence")
    headphone_confidence = finite_float("headphone_route_reference_confidence")
    source_distortion = finite_float("source_route_reference_distortion_db")
    headphone_distortion = finite_float("headphone_route_reference_distortion_db")
    source_level = finite_float("source_route_recording_dbfs")
    headphone_level = finite_float("headphone_route_recording_dbfs")
    source_gain = finite_float("source_route_gain_db")
    headphone_gain = finite_float("headphone_route_gain_db")
    source_lag = summary.get("source_route_reference_lag_samples")
    headphone_lag = summary.get("headphone_route_reference_lag_samples")
    source_peak = finite_nested_float("source", "peak_dbfs")
    headphone_peak = finite_nested_float("headphone", "peak_dbfs")
    source_clipped = nested_int("source", "clipped_sample_count")
    headphone_clipped = nested_int("headphone", "clipped_sample_count")
    source_info = dict(summary.get("device_info", {}).get("source_output_device", {}))
    headphone_info = dict(summary.get("device_info", {}).get("headphone_output_device", {}))
    source_signature = portaudio_output_signature(source_info)
    headphone_signature = portaudio_output_signature(headphone_info)
    shared_output_allowed = bool(getattr(args, "allow_shared_output_device", False))
    outputs_distinct = shared_output_allowed or source_signature != headphone_signature
    min_corr = float(args.min_route_probe_correlation)
    max_distortion = float(args.max_route_probe_distortion_db)
    min_level = float(args.min_route_probe_dbfs)
    max_clipped = int(getattr(args, "max_route_probe_clipped_samples", DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES))
    return [
        {
            "name": "headphone_route_probe_not_release_proof",
            "passed": summary.get("release_proof") is False,
            "threshold": "route probes are triage only",
            "value": summary.get("release_proof"),
        },
        {
            "name": "headphone_route_outputs_distinct",
            "passed": outputs_distinct,
            "threshold": "source output and headphone output resolve to distinct PortAudio devices",
            "value": {
                "allow_shared_output_device": shared_output_allowed,
                "headphone_output_signature": headphone_signature,
                "source_output_signature": source_signature,
            },
        },
        {
            "name": "headphone_source_route_opened",
            "passed": source_opened,
            "threshold": "measurement input and source output can open a duplex stream",
            "value": summary.get("source_route_error") or source_opened,
        },
        {
            "name": "headphone_output_route_opened",
            "passed": headphone_opened,
            "threshold": "measurement input and headphone output can open a duplex stream",
            "value": summary.get("headphone_route_error") or headphone_opened,
        },
        {
            "name": "headphone_source_route_reference_fidelity",
            "passed": (
                source_confidence is not None
                and source_distortion is not None
                and source_level is not None
                and source_confidence >= min_corr
                and source_distortion <= max_distortion
                and source_level >= min_level
            ),
            "threshold": (
                f"source route abs(correlation) >= {min_corr:.3f}, distortion <= {max_distortion:.3f} dB, "
                f"level >= {min_level:.3f} dBFS"
            ),
            "value": {
                "source_route_gain_db": source_gain,
                "source_route_peak_dbfs": source_peak,
                "source_route_reference_confidence": source_confidence,
                "source_route_reference_correlation": source_corr,
                "source_route_reference_distortion_db": source_distortion,
                "source_route_reference_lag_samples": source_lag,
                "source_route_recording_dbfs": source_level,
            },
        },
        {
            "name": "headphone_output_route_reference_fidelity",
            "passed": (
                headphone_confidence is not None
                and headphone_distortion is not None
                and headphone_level is not None
                and headphone_confidence >= min_corr
                and headphone_distortion <= max_distortion
                and headphone_level >= min_level
            ),
            "threshold": (
                f"headphone route abs(correlation) >= {min_corr:.3f}, distortion <= {max_distortion:.3f} dB, "
                f"level >= {min_level:.3f} dBFS"
            ),
            "value": {
                "headphone_route_gain_db": headphone_gain,
                "headphone_route_peak_dbfs": headphone_peak,
                "headphone_route_reference_confidence": headphone_confidence,
                "headphone_route_reference_correlation": headphone_corr,
                "headphone_route_reference_distortion_db": headphone_distortion,
                "headphone_route_reference_lag_samples": headphone_lag,
                "headphone_route_recording_dbfs": headphone_level,
            },
        },
        {
            "name": "headphone_source_route_not_clipped",
            "passed": source_clipped is not None and source_clipped <= max_clipped,
            "threshold": f"source route clipped samples <= {max_clipped}",
            "value": source_clipped,
        },
        {
            "name": "headphone_output_route_not_clipped",
            "passed": headphone_clipped is not None and headphone_clipped <= max_clipped,
            "threshold": f"headphone route clipped samples <= {max_clipped}",
            "value": headphone_clipped,
        },
        {
            "name": "headphone_route_probe_artifacts_hashed",
            "passed": hashes,
            "threshold": "route probe reference and recording artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "headphone_route_recordings_not_reference_clones",
            "passed": not (source_clone or headphone_clone),
            "threshold": "route probe recordings must not be byte-identical to generated references",
            "value": {
                "headphone_route_recording_matches_reference": headphone_clone,
                "source_route_recording_matches_reference": source_clone,
            },
        },
    ]


def route_probe_diagnostics(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    min_corr = float(args.min_route_probe_correlation)
    max_distortion = float(args.max_route_probe_distortion_db)
    min_level = float(args.min_route_probe_dbfs)
    max_lag_samples = max(1, int(round(float(args.sample_rate_hz) * float(args.max_alignment_lag_ms) / 1000.0)))

    def route(prefix: str, label: str) -> dict[str, Any]:
        opened = bool(summary.get(f"{prefix}_route_opened"))
        error = summary.get(f"{prefix}_route_error")
        recording = summary.get(f"{prefix}_route_recording")
        recording = recording if isinstance(recording, dict) else {}
        level = report_float(summary.get(f"{prefix}_route_recording_dbfs"), 3)
        confidence = report_float(summary.get(f"{prefix}_route_reference_confidence"), 6)
        distortion = report_float(summary.get(f"{prefix}_route_reference_distortion_db"), 3)
        lag_samples = summary.get(f"{prefix}_route_reference_lag_samples")
        clipped = recording.get("clipped_sample_count")
        reasons: list[str] = []
        next_actions: list[str] = []
        if not opened:
            reasons.append("route_not_opened")
            next_actions.append("try another host API/device triple or channel config")
            if error:
                next_actions.append("inspect the PortAudio route error in the report")
        else:
            too_quiet = level is None or level < min_level
            if too_quiet:
                reasons.append("recording_too_quiet")
                next_actions.append("move the measurement mic closer or raise playback gain without clipping")
            if not too_quiet and (confidence is None or confidence < min_corr):
                reasons.append("reference_not_detected")
                next_actions.append("disable Windows audio enhancements, noise suppression, AGC, and echo processing")
                next_actions.append("try an alternate host API route for the same physical devices")
            if not too_quiet and (distortion is None or distortion > max_distortion):
                reasons.append("reference_distorted")
                next_actions.append("reduce processing in the capture/playback path or use a USB/wired listener-ear mic")
            if isinstance(clipped, int) and clipped > int(args.max_route_probe_clipped_samples):
                reasons.append("recording_clipped")
                next_actions.append("lower playback gain and rerun the route probe")
            if isinstance(lag_samples, int) and abs(lag_samples) >= int(max_lag_samples * 0.9):
                reasons.append("alignment_near_search_boundary")
                next_actions.append("increase --max-alignment-lag-ms only for diagnosis, then fix the route latency")
        if not reasons:
            reasons.append("route_reference_faithful")
            next_actions.append("rerun this exact sample rate/channel config as probe-route before capture")
        return {
            "label": label,
            "reasons": reasons,
            "next_actions": list(dict.fromkeys(next_actions)),
            "opened": opened,
            "recording_dbfs": level,
            "reference_confidence": confidence,
            "reference_distortion_db": distortion,
            "reference_lag_samples": lag_samples,
        }

    source = route("source", "source speaker route")
    headphone = route("headphone", "headphone playback route")
    blocking_reasons = [
        f"source:{reason}" for reason in source["reasons"] if reason != "route_reference_faithful"
    ] + [
        f"headphone:{reason}" for reason in headphone["reasons"] if reason != "route_reference_faithful"
    ]
    return {
        "blocking_reasons": blocking_reasons,
        "headphone": headphone,
        "next_actions": list(dict.fromkeys(source["next_actions"] + headphone["next_actions"])),
        "source": source,
    }


def route_sweep_failure_summary(attempts: list[dict[str, Any]]) -> dict[str, int]:
    failure_summary: dict[str, int] = {}
    for attempt in attempts:
        diagnosis = attempt.get("diagnosis")
        if isinstance(diagnosis, dict):
            for reason in diagnosis.get("blocking_reasons", []):
                reason = str(reason)
                failure_summary[reason] = failure_summary.get(reason, 0) + 1
        failed_gates = attempt.get("failed_gates", [])
        if not isinstance(failed_gates, list):
            continue
        for failed_gate in failed_gates:
            reason = f"gate:{failed_gate}"
            failure_summary[reason] = failure_summary.get(reason, 0) + 1
    return dict(sorted(failure_summary.items()))


def route_probe(args: argparse.Namespace) -> int:
    measurement_input_device = parse_device_selector(args.measurement_input_device)
    source_output_device = parse_device_selector(args.source_output_device)
    headphone_output_device = parse_device_selector(args.headphone_output_device)
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "headphone-route-probe-report.json"
    report_path.unlink(missing_ok=True)
    reference = add_padding(
        apply_playback_gain(
            build_route_probe_signal(int(args.sample_rate_hz), float(args.duration_s)),
            float(args.playback_gain_db),
            float(args.max_peak_dbfs),
        ),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    playback = mono_playback(reference, int(args.output_channels))
    source_reference_path = run_dir / "source-route-probe-reference.wav"
    headphone_reference_path = run_dir / "headphone-route-probe-reference.wav"
    source_recording_path = run_dir / "source-route-probe-recording.wav"
    headphone_recording_path = run_dir / "headphone-route-probe-recording.wav"
    for path in (
        headphone_reference_path,
        headphone_recording_path,
        source_reference_path,
        source_recording_path,
    ):
        path.unlink(missing_ok=True)
    write_mono_wav(source_reference_path, reference, int(args.sample_rate_hz))
    write_mono_wav(headphone_reference_path, reference, int(args.sample_rate_hz))

    device_info = {
        "headphone_output_device": portaudio_device_identity(headphone_output_device, kind="output"),
        "measurement_input_device": portaudio_device_identity(measurement_input_device, kind="input"),
        "source_output_device": portaudio_device_identity(source_output_device, kind="output"),
    }
    device_fingerprint = measurement_device_fingerprint(
        device_info=device_info,
        sample_rate_hz=int(args.sample_rate_hz),
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )
    summary: dict[str, Any] = {
        "adapter_id": args.adapter_id,
        "device_info": device_info,
        "device_path_fingerprint": device_fingerprint,
        "device_path_identity_recorded": True,
        "input_channels": int(args.input_channels),
        "measurement_kind": "headphone_earpiece_route_probe_triage",
        "output_channels": int(args.output_channels),
        "playback_gain_db": float(args.playback_gain_db),
        "release_proof": False,
        "sample_rate_hz": int(args.sample_rate_hz),
        "shared_output_device_allowed": bool(args.allow_shared_output_device),
    }

    source_recording: np.ndarray | None = None
    headphone_recording: np.ndarray | None = None
    try:
        source_recording, elapsed = record_playback(
            playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        summary["source_route_opened"] = True
        summary["source_route_elapsed_s"] = round(elapsed, 6)
        summary["source_route_recording"] = recording_diagnostics(source_recording, int(args.sample_rate_hz))
        write_mono_wav(source_recording_path, source_recording, int(args.sample_rate_hz))
    except Exception as exc:
        summary["source_route_opened"] = False
        summary["source_route_error"] = str(exc)
        summary["source_route_error_type"] = type(exc).__name__

    try:
        headphone_recording, elapsed = record_playback(
            playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=headphone_output_device,
            input_channels=int(args.input_channels),
        )
        summary["headphone_route_opened"] = True
        summary["headphone_route_elapsed_s"] = round(elapsed, 6)
        summary["headphone_route_recording"] = recording_diagnostics(
            headphone_recording,
            int(args.sample_rate_hz),
        )
        write_mono_wav(headphone_recording_path, headphone_recording, int(args.sample_rate_hz))
    except Exception as exc:
        summary["headphone_route_opened"] = False
        summary["headphone_route_error"] = str(exc)
        summary["headphone_route_error_type"] = type(exc).__name__

    if source_recording is not None:
        metrics = reference_metrics(
            source_recording,
            reference,
            int(args.sample_rate_hz),
            float(args.max_alignment_lag_ms),
        )
        summary.update(
            {
                "source_route_gain_db": metrics["gain_db"],
                "source_route_recording_dbfs": metrics["recording_dbfs"],
                "source_route_reference_confidence": round(abs(float(metrics["correlation"])), 6),
                "source_route_reference_correlation": metrics["correlation"],
                "source_route_reference_distortion_db": metrics["distortion_db"],
                "source_route_reference_lag_samples": metrics["lag_samples"],
            }
        )
    if headphone_recording is not None:
        metrics = reference_metrics(
            headphone_recording,
            reference,
            int(args.sample_rate_hz),
            float(args.max_alignment_lag_ms),
        )
        summary.update(
            {
                "headphone_route_gain_db": metrics["gain_db"],
                "headphone_route_recording_dbfs": metrics["recording_dbfs"],
                "headphone_route_reference_confidence": round(abs(float(metrics["correlation"])), 6),
                "headphone_route_reference_correlation": metrics["correlation"],
                "headphone_route_reference_distortion_db": metrics["distortion_db"],
                "headphone_route_reference_lag_samples": metrics["lag_samples"],
            }
        )

    artifact_paths = {
        "headphone_route_probe_reference": str(headphone_reference_path),
        "source_route_probe_reference": str(source_reference_path),
    }
    if source_recording_path.exists():
        artifact_paths["source_route_probe_recording"] = str(source_recording_path)
    if headphone_recording_path.exists():
        artifact_paths["headphone_route_probe_recording"] = str(headphone_recording_path)
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    expected_artifact_keys = {
        "headphone_route_probe_recording",
        "headphone_route_probe_reference",
        "source_route_probe_recording",
        "source_route_probe_reference",
    }
    missing_artifact_hashes = sorted(expected_artifact_keys.difference(artifact_hashes))
    summary["missing_artifact_hashes"] = missing_artifact_hashes
    summary["all_artifact_hashes_present"] = (
        not missing_artifact_hashes
        and all(len(artifact_hashes[key]) == 64 for key in expected_artifact_keys)
    )
    summary["source_route_recording_matches_reference"] = (
        artifact_hashes.get("source_route_probe_recording") == artifact_hashes.get("source_route_probe_reference")
    )
    summary["headphone_route_recording_matches_reference"] = (
        artifact_hashes.get("headphone_route_probe_recording")
        == artifact_hashes.get("headphone_route_probe_reference")
    )
    summary["route_failure_diagnosis"] = route_probe_diagnostics(summary, args)
    gates = route_probe_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "headphone_earpiece_route_probe",
        "measurement_kind": "headphone_earpiece_route_probe_triage",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": False,
        },
        "benchmarks": {
            "headphone_earpiece_route_probe": {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_hashes": artifact_hashes,
        "artifact_paths": artifact_paths,
        "detractor_loop": {
            "strongest_objection": (
                "This is only a route-opening and reference-fidelity triage check. It does not prove "
                "headphone source isolation or translated playback quality."
            ),
            "verdict": "Use a passing route probe only to choose devices for the full guided capture.",
        },
    }
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"headphone/earpiece route probe {status}: "
        f"source_opened={summary.get('source_route_opened')}, "
        f"headphone_opened={summary.get('headphone_route_opened')}"
    )
    print(f"wrote headphone route probe report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def route_probe_attempt_metrics(summary: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    sample_rate_hz = max(1, int(summary.get("sample_rate_hz") or args.sample_rate_hz))

    def route_metrics(prefix: str) -> dict[str, Any]:
        recording = summary.get(f"{prefix}_route_recording")
        recording = recording if isinstance(recording, dict) else {}
        lag_samples = int(summary.get(f"{prefix}_route_reference_lag_samples") or 0)
        lag_ms = abs(float(lag_samples)) * 1000.0 / float(sample_rate_hz)
        level = float(summary.get(f"{prefix}_route_recording_dbfs", float("-inf")))
        confidence = float(summary.get(f"{prefix}_route_reference_confidence", float("-inf")))
        correlation_value = float(summary.get(f"{prefix}_route_reference_correlation", float("-inf")))
        distortion = float(summary.get(f"{prefix}_route_reference_distortion_db", float("inf")))
        peak = float(recording.get("peak_dbfs", float("-inf")))
        clipped = int(recording.get("clipped_sample_count") or 0)
        return {
            "clipped_sample_count": clipped,
            "confidence": report_float(confidence, 6),
            "correlation": report_float(correlation_value, 6),
            "distortion_db": report_float(distortion, 3),
            "gain_db": report_float(summary.get(f"{prefix}_route_gain_db"), 3),
            "lag_ms": report_float(lag_ms, 3),
            "lag_samples": lag_samples,
            "level_dbfs": report_float(level, 3),
            "margin_to_threshold": {
                "clipped_samples": int(args.max_route_probe_clipped_samples) - clipped,
                "confidence": report_float(confidence - float(args.min_route_probe_correlation), 6),
                "distortion_db": report_float(float(args.max_route_probe_distortion_db) - distortion, 3),
                "recording_level_db": report_float(level - float(args.min_route_probe_dbfs), 3),
            },
            "peak_dbfs": report_float(peak, 3),
            "recording_matches_reference": bool(summary.get(f"{prefix}_route_recording_matches_reference")),
        }

    return {
        "device_path_fingerprint": summary.get("device_path_fingerprint"),
        "headphone": route_metrics("headphone"),
        "headphone_output_device": summary.get("device_info", {}).get("headphone_output_device"),
        "input_channels": int(summary.get("input_channels") or args.input_channels),
        "measurement_input_device": summary.get("device_info", {}).get("measurement_input_device"),
        "output_channels": int(summary.get("output_channels") or args.output_channels),
        "sample_rate_hz": sample_rate_hz,
        "source": route_metrics("source"),
        "source_output_device": summary.get("device_info", {}).get("source_output_device"),
    }


def route_probe_score(metrics: dict[str, Any]) -> float:
    score = 0.0
    for route_name in ("source", "headphone"):
        route = metrics.get(route_name, {})
        confidence = route.get("confidence")
        if isinstance(confidence, (int, float)):
            score += float(confidence) * 20.0
        margins = route.get("margin_to_threshold", {})
        if isinstance(margins, dict):
            for value in margins.values():
                if isinstance(value, (int, float)):
                    score += max(-100.0, min(100.0, float(value)))
    return score


def sweep_routes(args: argparse.Namespace) -> int:
    sd = None if args.triple else import_sounddevice()
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rates = list(dict.fromkeys(int(value) for value in args.sample_rate_hz))
    channel_configs = list(dict.fromkeys(tuple(config) for config in args.channel_config))

    configs: list[dict[str, Any]] = []
    for sample_rate_hz in sample_rates:
        for input_channels, output_channels in channel_configs:
            if args.triple:
                triples = [
                    {
                        "headphone_output_device": headphone_output_device,
                        "input_device": input_device,
                        "source": "explicit",
                        "source_output_device": source_output_device,
                    }
                    for input_device, source_output_device, headphone_output_device in args.triple
                ]
            else:
                assert sd is not None
                triples = candidate_route_triples(
                    sd,
                    allow_shared_output_device=bool(args.allow_shared_output_device),
                    hostapis=list(args.hostapi or []),
                    include_cross_hostapi=bool(args.include_cross_hostapi),
                    input_channels=int(input_channels),
                    max_triples=int(args.max_triples),
                    output_channels=int(output_channels),
                )
            for triple in triples:
                configs.append(
                    {
                        "input_channels": int(input_channels),
                        "output_channels": int(output_channels),
                        "sample_rate_hz": int(sample_rate_hz),
                        "triple": triple,
                    }
                )
                if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
                    break
            if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
                break
        if int(args.max_attempts) > 0 and len(configs) >= int(args.max_attempts):
            break

    attempts: list[dict[str, Any]] = []
    for index, config in enumerate(configs, start=1):
        triple = config["triple"]
        input_device = str(triple["input_device"])
        source_output_device = str(triple["source_output_device"])
        headphone_output_device = str(triple["headphone_output_device"])
        input_channels = int(config["input_channels"])
        output_channels = int(config["output_channels"])
        sample_rate_hz = int(config["sample_rate_hz"])
        attempt_id = (
            f"attempt-{index:02d}-sr-{sample_rate_hz}-in-ch-{input_channels}-"
            f"out-ch-{output_channels}-in-{safe_id(input_device)}-"
            f"src-{safe_id(source_output_device)}-hp-{safe_id(headphone_output_device)}"
        )
        child_run_id = f"{args.run_id}/{attempt_id}"
        child_args = argparse.Namespace(**vars(args))
        child_args.command = "probe-route"
        child_args.adapter_id = DEFAULT_ROUTE_PROBE_ADAPTER_ID
        child_args.run_id = child_run_id
        child_args.measurement_input_device = input_device
        child_args.source_output_device = source_output_device
        child_args.headphone_output_device = headphone_output_device
        child_args.input_channels = input_channels
        child_args.output_channels = output_channels
        child_args.sample_rate_hz = sample_rate_hz
        child_args.score_warning_only = True
        report_path = Path(args.output_dir) / "runs" / child_run_id / "headphone-route-probe-report.json"
        attempt: dict[str, Any] = {
            "attempt_id": attempt_id,
            "duration_s": float(args.duration_s),
            "headphone_hostapi_name": triple.get("headphone_hostapi_name"),
            "headphone_name": triple.get("headphone_name"),
            "headphone_output_device": headphone_output_device,
            "input_channels": input_channels,
            "input_device": input_device,
            "input_hostapi_name": triple.get("input_hostapi_name"),
            "input_name": triple.get("input_name"),
            "output_channels": output_channels,
            "pair_source": triple.get("source"),
            "playback_gain_db": float(args.playback_gain_db),
            "report_path": str(report_path),
            "sample_rate_hz": sample_rate_hz,
            "source_hostapi_name": triple.get("source_hostapi_name"),
            "source_name": triple.get("source_name"),
            "source_output_device": source_output_device,
        }
        try:
            route_probe(child_args)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            benchmark = report.get("benchmarks", {}).get("headphone_earpiece_route_probe", {})
            summary = benchmark.get("summary", {}) if isinstance(benchmark, dict) else {}
            gates = report.get("summary", {}).get("quality_gates", [])
            artifact_paths = report.get("artifact_paths", {})
            artifact_hashes = report.get("artifact_hashes", {})
            failed_gates = [
                str(gate.get("name"))
                for gate in gates
                if isinstance(gate, dict) and not bool(gate.get("passed"))
            ]
            metrics = route_probe_attempt_metrics(summary, child_args)
            passed = bool(report.get("summary", {}).get("passed")) and not failed_gates
            attempt.update(
                {
                    "artifact_hashes": artifact_hashes if isinstance(artifact_hashes, dict) else {},
                    "artifact_paths": artifact_paths if isinstance(artifact_paths, dict) else {},
                    "device": benchmark.get("device") if isinstance(benchmark, dict) else None,
                    "diagnosis": summary.get("route_failure_diagnosis"),
                    "failed_gates": failed_gates,
                    "metrics": metrics,
                    "passed": passed,
                    "quality_gates": gates,
                    "score": report_float(route_probe_score(metrics), 6),
                    "status": "pass" if passed else "fail",
                }
            )
        except Exception as exc:  # pragma: no cover - depends on host device failures.
            attempt.update(
                {
                    "error": str(exc),
                    "failed_gates": ["headphone_route_probe_attempt_error"],
                    "passed": False,
                    "score": None,
                    "status": "error",
                }
            )
        attempts.append(attempt)

    candidates = [attempt for attempt in attempts if bool(attempt.get("passed"))]
    scored_attempts = [attempt for attempt in attempts if isinstance(attempt.get("score"), (int, float))]
    candidate_attempt = max(candidates, key=lambda item: float(item.get("score") or 0.0)) if candidates else None
    best_scored_attempt = (
        max(scored_attempts, key=lambda item: float(item.get("score") or 0.0)) if scored_attempts else None
    )
    failure_summary = route_sweep_failure_summary(attempts)
    gates = [
        {
            "name": "headphone_route_probe_sweep_not_release_proof",
            "passed": True,
            "threshold": "route sweeps are triage only",
            "value": False,
        },
        {
            "name": "headphone_route_probe_sweep_attempts_recorded",
            "passed": bool(attempts),
            "threshold": "at least one route triple attempted",
            "value": len(attempts),
        },
        {
            "name": "headphone_route_probe_sweep_candidate_found",
            "passed": bool(candidates),
            "threshold": "at least one route probe attempt passed all route gates",
            "value": bool(candidates),
        },
    ]
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": "headphone_earpiece_route_probe_sweep",
        "measurement_kind": "headphone_earpiece_route_probe_sweep_triage",
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "attempted_config_count": len(attempts),
            "best_scored_attempt_id": best_scored_attempt.get("attempt_id") if best_scored_attempt else None,
            "candidate_attempt_id": candidate_attempt.get("attempt_id") if candidate_attempt else None,
            "channel_configs": [
                {"input_channels": item[0], "output_channels": item[1]} for item in channel_configs
            ],
            "failure_summary": failure_summary,
            "passed": bool(candidates),
            "quality_gates": gates,
            "release_proof": False,
            "sample_rates_hz": sample_rates,
            "triage_candidate_found": bool(candidates),
        },
        "benchmarks": {
            "headphone_earpiece_route_probe_sweep": {
                "adapter_id": args.adapter_id,
                "attempts": attempts,
                "best_scored_attempt": best_scored_attempt,
                "candidate_attempt": candidate_attempt,
                "required_follow_up": (
                    "Rerun the candidate with headphone-isolation-probe-route, then collect "
                    "headphone-isolation-capture evidence with the listener-ear microphone physically positioned."
                ),
            }
        },
        "detractor_loop": {
            "strongest_objection": (
                "A chirp sweep can find routes that open and preserve a probe while still failing "
                "speech, Bluetooth mode switching, AGC, or the physical listener-ear placement."
            ),
            "verdict": (
                "This is only route triage. It records attempted configurations and keeps release_proof=false."
            ),
        },
    }
    report = json_safe(report)
    report_path = run_dir / "headphone-route-probe-sweep-report.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    status = "CANDIDATE" if candidates else "NO-CANDIDATE"
    print(
        f"headphone/earpiece route probe sweep {status}: attempts={len(attempts)}, "
        f"candidate_found={bool(candidates)}"
    )
    print(f"wrote headphone route probe sweep report to {report_path}")
    return 0 if candidates or args.score_warning_only else 1


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
    finite_metric_names = [
        "source_isolated_gain_db",
        "source_isolated_recording_dbfs",
        "source_isolation_db",
        "source_open_gain_db",
        "source_open_recording_dbfs",
        "source_open_reference_correlation",
        "source_open_reference_distortion_db",
        "translated_headphone_gain_db",
        "translated_headphone_recording_dbfs",
        "translated_headphone_reference_correlation",
        "translated_headphone_reference_distortion_db",
    ]
    finite_metrics = {
        name: math.isfinite(float(summary.get(name, float("nan"))))
        for name in finite_metric_names
    }
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
    capture_backend = str(summary.get("capture_backend", ""))
    capture_source_kind = str(summary.get("capture_source_kind", ""))
    capture_preflight_binding = summary.get("capture_preflight_binding", {})
    capture_preflight_binding = (
        capture_preflight_binding if isinstance(capture_preflight_binding, dict) else {}
    )
    device_identity = bool(summary.get("device_path_identity_recorded"))
    device_fingerprint = str(summary.get("device_path_fingerprint", ""))
    identity_fingerprint = str(summary.get("measurement_identity_fingerprint", ""))
    max_alignment_lag_ms = float(summary.get("max_alignment_lag_ms", float("inf")))
    release_proof = bool(summary["release_proof"])
    return [
        {
            "name": "headphone_measurement_release_proof",
            "passed": release_proof,
            "threshold": "measured listener-ear headphone isolation evidence",
            "value": release_proof,
        },
        {
            "name": "headphone_core_metrics_finite",
            "passed": all(finite_metrics.values()),
            "threshold": "all release-critical headphone metrics are finite numbers",
            "value": finite_metrics,
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
            "name": "headphone_capture_source_declared",
            "passed": (
                capture_backend in CAPTURE_BACKENDS
                and capture_source_kind in CAPTURE_SOURCE_KINDS
                and (
                    capture_backend != CAPTURE_BACKEND_PORTAUDIO
                    or (device_identity and len(device_fingerprint) == 64)
                )
            ),
            "threshold": "capture backend/source declared; guided PortAudio capture includes device fingerprint",
            "value": {
                "capture_backend": capture_backend,
                "capture_source_kind": capture_source_kind,
                "device_path_fingerprint": device_fingerprint,
                "device_path_identity_recorded": device_identity,
            },
        },
        {
            "name": "headphone_guided_capture_preflight_bound",
            "passed": capture_backend != CAPTURE_BACKEND_PORTAUDIO
            or (
                bool(capture_preflight_binding.get("bound"))
                and bool(capture_preflight_binding.get("planning_passed"))
                and capture_preflight_binding.get("recommended_path") == "guided_capture_possible"
                and bool(capture_preflight_binding.get("physical_listener_ear_input_confirmed"))
                and bool(capture_preflight_binding.get("selected_route_capture_ready"))
                and len(str(capture_preflight_binding.get("preflight_report_sha256", ""))) == 64
                and len(str(capture_preflight_binding.get("capture_device_path_fingerprint", ""))) == 64
            ),
            "threshold": (
                "guided PortAudio capture evidence must bind to a passing preflight report and selected route"
            ),
            "value": {
                "capture_backend": capture_backend,
                "preflight_bound": capture_preflight_binding.get("bound"),
                "preflight_report_sha256": capture_preflight_binding.get("preflight_report_sha256"),
                "capture_device_path_fingerprint": capture_preflight_binding.get("capture_device_path_fingerprint"),
                "recommended_path": capture_preflight_binding.get("recommended_path"),
                "selected_route": capture_preflight_binding.get("selected_route"),
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
            "name": "headphone_release_alignment_window",
            "passed": max_alignment_lag_ms <= DEFAULT_MAX_ALIGNMENT_LAG_MS,
            "threshold": (
                "release scoring alignment window must stay within the release gate recompute window "
                f"<= {DEFAULT_MAX_ALIGNMENT_LAG_MS:.1f} ms"
            ),
            "value": max_alignment_lag_ms,
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
    capture_context = getattr(args, "capture_context", {})
    capture_context = capture_context if isinstance(capture_context, dict) else {}
    capture_preflight_binding = capture_context.get(
        "preflight_binding",
        getattr(args, "capture_preflight_binding", {}),
    )
    capture_preflight_binding = (
        capture_preflight_binding if isinstance(capture_preflight_binding, dict) else {}
    )
    identity_fingerprint = measurement_identity_fingerprint(
        artifact_hashes=artifact_hashes,
        headphone_device_label=headphone_device_label,
        isolation_fixture_label=isolation_fixture_label,
        measurement_microphone_label=measurement_microphone_label,
        sample_rate_hz=sample_rate_hz,
    )
    summary = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "capture_backend": str(getattr(args, "capture_backend", CAPTURE_BACKEND_EXTERNAL)),
        "capture_preflight_binding": capture_preflight_binding,
        "capture_source_kind": str(getattr(args, "capture_source_kind", CAPTURE_SOURCE_KIND_EXTERNAL)),
        "device_path_fingerprint": str(getattr(args, "device_path_fingerprint", "")),
        "device_path_identity_recorded": bool(getattr(args, "device_path_identity_recorded", False)),
        "device_info": getattr(args, "device_info", {}),
        "headphone_device_label": headphone_device_label,
        "isolation_fixture_label": isolation_fixture_label,
        "max_alignment_lag_ms": float(args.max_alignment_lag_ms),
        "measurement_kind": MEASUREMENT_KIND,
        "measurement_identity_fingerprint": identity_fingerprint,
        "measurement_microphone_label": measurement_microphone_label,
        "artifact_frame_counts": frame_counts,
        "min_artifact_duration_s": round(min_artifact_duration_s, 6),
        "procedure_note": str(args.procedure_note),
        "reference_source_kind": str(getattr(args, "reference_source_kind", "external_wav_pair")),
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
        "capture": capture_context,
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
    report = json_safe(report)
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    printed_summary = report["benchmarks"][BENCHMARK_NAME]["summary"]
    print(
        f"headphone/earpiece isolation {status}: "
        f"isolation_db={printed_summary['source_isolation_db']}, "
        f"translated_corr={printed_summary['translated_headphone_reference_correlation']}"
    )
    print(f"wrote headphone isolation report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def virtual_lab_gates(summary: dict[str, Any], args: argparse.Namespace) -> list[dict[str, Any]]:
    source_open_corr = float(summary["source_open_reference_correlation"])
    source_isolation = float(summary["source_isolation_db"])
    translated_corr = float(summary["translated_headphone_reference_correlation"])
    translated_distortion = float(summary["translated_headphone_reference_distortion_db"])
    source_open_level = float(summary["source_open_recording_dbfs"])
    translated_level = float(summary["translated_headphone_recording_dbfs"])
    hashes = bool(summary["all_artifact_hashes_present"])
    clones = {
        "source_isolated_recording_matches_reference": bool(summary["source_isolated_recording_matches_reference"]),
        "source_open_recording_matches_reference": bool(summary["source_open_recording_matches_reference"]),
        "translated_headphone_recording_matches_reference": bool(
            summary["translated_headphone_recording_matches_reference"]
        ),
    }
    return [
        {
            "name": "virtual_lab_not_release_proof",
            "passed": summary.get("release_proof") is False,
            "threshold": "virtual listener-ear lab must remain non-release evidence",
            "value": summary.get("release_proof"),
        },
        {
            "name": "virtual_capture_source_declared",
            "passed": (
                summary.get("capture_backend") == CAPTURE_BACKEND_VIRTUAL
                and summary.get("capture_source_kind") == CAPTURE_SOURCE_KIND_VIRTUAL
            ),
            "threshold": "virtual capture backend/source identify synthetic room-headphone model",
            "value": {
                "capture_backend": summary.get("capture_backend"),
                "capture_source_kind": summary.get("capture_source_kind"),
            },
        },
        {
            "name": "virtual_source_open_reference_fidelity",
            "passed": (
                source_open_level >= float(args.min_source_open_dbfs)
                and source_open_corr >= float(args.min_source_open_correlation)
            ),
            "threshold": (
                f"source-open level >= {float(args.min_source_open_dbfs):.3f} dBFS and "
                f"correlation >= {float(args.min_source_open_correlation):.3f}"
            ),
            "value": {
                "source_open_recording_dbfs": source_open_level,
                "source_open_reference_correlation": source_open_corr,
            },
        },
        {
            "name": "virtual_source_isolation_model_applied",
            "passed": source_isolation >= float(args.min_source_isolation_db),
            "threshold": f"simulated source attenuation >= {float(args.min_source_isolation_db):.3f} dB",
            "value": source_isolation,
        },
        {
            "name": "virtual_translated_headphone_reference_fidelity",
            "passed": (
                translated_level >= float(args.min_translated_dbfs)
                and translated_corr >= float(args.min_translated_correlation)
                and translated_distortion <= float(args.max_translated_distortion_db)
            ),
            "threshold": (
                f"translated level >= {float(args.min_translated_dbfs):.3f} dBFS, "
                f"correlation >= {float(args.min_translated_correlation):.3f}, "
                f"distortion <= {float(args.max_translated_distortion_db):.3f} dB"
            ),
            "value": {
                "translated_headphone_recording_dbfs": translated_level,
                "translated_headphone_reference_correlation": translated_corr,
                "translated_headphone_reference_distortion_db": translated_distortion,
            },
        },
        {
            "name": "virtual_artifacts_hashed",
            "passed": hashes,
            "threshold": "all virtual listener-ear WAV artifacts have SHA-256 hashes",
            "value": hashes,
        },
        {
            "name": "virtual_recordings_not_reference_clones",
            "passed": not any(clones.values()),
            "threshold": "virtual recordings include delay/noise/modeling and are not byte-identical references",
            "value": clones,
        },
    ]


def virtual_lab(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    sample_rate_hz = int(args.sample_rate_hz)
    source_reference = add_padding(
        build_virtual_speech_like_track(sample_rate_hz, float(args.duration_s), base_hz=210.0),
        sample_rate_hz,
        float(args.lead_s),
        float(args.tail_s),
    )
    translated_reference = add_padding(
        build_virtual_speech_like_track(sample_rate_hz, float(args.duration_s), base_hz=330.0),
        sample_rate_hz,
        float(args.lead_s),
        float(args.tail_s),
    )
    source_open = simulate_virtual_listener_recording(
        source_reference,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.source_open_gain_db),
        lag_ms=float(args.source_lag_ms),
        noise_dbfs=float(args.noise_dbfs),
        reflection_db=float(args.reflection_db),
        seed=11,
    )
    source_isolated = simulate_virtual_listener_recording(
        source_reference,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.source_open_gain_db) - float(args.source_isolation_db),
        lag_ms=float(args.source_lag_ms),
        noise_dbfs=float(args.noise_dbfs),
        reflection_db=float(args.reflection_db),
        seed=17,
    )
    translated_recording = simulate_virtual_listener_recording(
        translated_reference,
        sample_rate_hz=sample_rate_hz,
        gain_db=float(args.translated_gain_db),
        lag_ms=float(args.translated_lag_ms),
        noise_dbfs=float(args.noise_dbfs),
        reflection_db=float(args.reflection_db),
        seed=23,
    )

    artifact_paths = {
        "source_reference": str(run_dir / "source-reference.wav"),
        "source_open_ear_recording": str(run_dir / "source-open-ear-recording.wav"),
        "source_isolated_ear_recording": str(run_dir / "source-isolated-ear-recording.wav"),
        "translated_playback_reference": str(run_dir / "translated-playback-reference.wav"),
        "translated_headphone_recording": str(run_dir / "translated-headphone-recording.wav"),
    }
    audio = {
        "source_reference": source_reference,
        "source_open_ear_recording": source_open,
        "source_isolated_ear_recording": source_isolated,
        "translated_playback_reference": translated_reference,
        "translated_headphone_recording": translated_recording,
    }
    for key, path in artifact_paths.items():
        write_mono_wav(Path(path), audio[key], sample_rate_hz)

    source_open_metrics = reference_metrics(
        source_open,
        source_reference,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    source_isolated_metrics = reference_metrics(
        source_isolated,
        source_reference,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    translated_metrics = reference_metrics(
        translated_recording,
        translated_reference,
        sample_rate_hz,
        float(args.max_alignment_lag_ms),
    )
    artifact_hashes = {key: sha256_file(Path(value)) for key, value in artifact_paths.items()}
    source_isolation_db = float(source_open_metrics["gain_db"]) - float(source_isolated_metrics["gain_db"])
    min_artifact_duration_s = min(float(samples.size) / float(sample_rate_hz) for samples in audio.values())
    summary: dict[str, Any] = {
        "all_artifact_hashes_present": all(len(value) == 64 for value in artifact_hashes.values()),
        "artifact_frame_counts": {key: int(value.size) for key, value in audio.items()},
        "capture_backend": CAPTURE_BACKEND_VIRTUAL,
        "capture_source_kind": CAPTURE_SOURCE_KIND_VIRTUAL,
        "headphone_device_label": "virtual headphone transfer function",
        "isolation_fixture_label": "virtual sealed listener-ear coupler",
        "measurement_kind": VIRTUAL_MEASUREMENT_KIND,
        "measurement_microphone_label": "virtual listener-ear microphone",
        "min_artifact_duration_s": round(min_artifact_duration_s, 6),
        "model_parameters": {
            "noise_dbfs": float(args.noise_dbfs),
            "reflection_db": float(args.reflection_db),
            "source_isolation_db": float(args.source_isolation_db),
            "source_lag_ms": float(args.source_lag_ms),
            "source_open_gain_db": float(args.source_open_gain_db),
            "translated_gain_db": float(args.translated_gain_db),
            "translated_lag_ms": float(args.translated_lag_ms),
        },
        "procedure_note": "synthetic virtual listener-ear lab; not physical release evidence",
        "release_proof": False,
        "sample_rate_hz": sample_rate_hz,
        "source_isolated_gain_db": source_isolated_metrics["gain_db"],
        "source_isolated_recording_dbfs": source_isolated_metrics["recording_dbfs"],
        "source_isolated_recording_matches_reference": (
            artifact_hashes["source_isolated_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_isolated_reference_correlation": source_isolated_metrics["correlation"],
        "source_isolated_reference_distortion_db": source_isolated_metrics["distortion_db"],
        "source_isolated_reference_lag_samples": source_isolated_metrics["lag_samples"],
        "source_isolation_db": round(source_isolation_db, 3),
        "source_open_gain_db": source_open_metrics["gain_db"],
        "source_open_recording_dbfs": source_open_metrics["recording_dbfs"],
        "source_open_recording_matches_reference": (
            artifact_hashes["source_open_ear_recording"] == artifact_hashes["source_reference"]
        ),
        "source_open_reference_correlation": source_open_metrics["correlation"],
        "source_open_reference_distortion_db": source_open_metrics["distortion_db"],
        "source_open_reference_lag_samples": source_open_metrics["lag_samples"],
        "source_suppression_mode": SUPPRESSION_MODE,
        "suppression_claim": SUPPRESSION_CLAIM,
        "translated_audio_is_surrogate": True,
        "translated_headphone_gain_db": translated_metrics["gain_db"],
        "translated_headphone_recording_dbfs": translated_metrics["recording_dbfs"],
        "translated_headphone_recording_matches_reference": (
            artifact_hashes["translated_headphone_recording"] == artifact_hashes["translated_playback_reference"]
        ),
        "translated_headphone_reference_correlation": translated_metrics["correlation"],
        "translated_headphone_reference_distortion_db": translated_metrics["distortion_db"],
        "translated_headphone_reference_lag_samples": translated_metrics["lag_samples"],
    }
    gates = virtual_lab_gates(summary, args)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "fixture_kind": VIRTUAL_FIXTURE_KIND,
        "measurement_kind": VIRTUAL_MEASUREMENT_KIND,
        "output_dir": str(args.output_dir),
        "release_proof": False,
        "summary": {
            "passed": all(bool(gate["passed"]) for gate in gates),
            "quality_gates": gates,
            "release_proof": False,
        },
        "benchmarks": {
            VIRTUAL_BENCHMARK_NAME: {
                "adapter_id": args.adapter_id,
                "summary": summary,
            }
        },
        "artifact_hashes": artifact_hashes,
        "artifact_paths": artifact_paths,
        "detractor_loop": {
            "strongest_objection": (
                "This virtual lab proves scorer and artifact plumbing only. It does not prove "
                "real listener-ear isolation, microphone placement, Bluetooth behavior, or room acoustics."
            ),
            "verdict": "Keep release_proof=false; run physical listener-ear capture for release.",
        },
    }
    report = json_safe(report)
    report_path = run_dir / "headphone-virtual-lab-report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    status = "PASS" if report["summary"]["passed"] else "FAIL"
    print(
        f"headphone/earpiece virtual lab {status}: "
        f"simulated_isolation_db={summary['source_isolation_db']}, "
        f"translated_corr={summary['translated_headphone_reference_correlation']}"
    )
    print(f"wrote headphone virtual lab report to {report_path}")
    return 0 if report["summary"]["passed"] or args.score_warning_only else 1


def _capture_reference_tracks(args: argparse.Namespace) -> tuple[np.ndarray, np.ndarray, str, list[dict[str, Any]]]:
    if bool(args.source_reference) != bool(args.translated_playback_reference):
        raise ValueError("--source-reference and --translated-playback-reference must be provided together")
    if args.source_reference and args.translated_playback_reference:
        source, source_rate = read_mono_wav(Path(args.source_reference))
        translated, translated_rate = read_mono_wav(Path(args.translated_playback_reference))
        source = resample_to_rate(source, source_rate, int(args.sample_rate_hz))
        translated = resample_to_rate(translated, translated_rate, int(args.sample_rate_hz))
        return source, translated, "external_wav_pair", []
    source, translated, segments = build_tts_reference_tracks(
        Path(args.tts_report),
        int(args.sample_rate_hz),
        float(args.gap_s),
    )
    return source, translated, "same_voice_or_fallback_tts_report", segments


def _powershell_quote(value: Any) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def write_manual_recording_checklist(
    *,
    checklist_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
) -> None:
    expected_recordings = manifest.get("expected_recording_paths")
    expected_recordings = expected_recordings if isinstance(expected_recordings, dict) else {}
    artifact_paths = manifest.get("artifact_paths")
    artifact_paths = artifact_paths if isinstance(artifact_paths, dict) else {}
    quality_bar = manifest.get("quality_bar")
    quality_bar = quality_bar if isinstance(quality_bar, dict) else {}
    sample_rate_hz = manifest.get("sample_rate_hz")
    max_alignment_lag_ms = quality_bar.get("max_alignment_lag_ms", DEFAULT_MAX_ALIGNMENT_LAG_MS)
    min_source_isolation_db = quality_bar.get("min_source_isolation_db", DEFAULT_MIN_SOURCE_ISOLATION_DB)
    min_artifact_duration_s = manifest.get("min_artifact_duration_s")
    score_report_path = manifest.get("score_report_path")
    manifest_arg = _powershell_quote(manifest_path)
    score_report_arg = _powershell_quote(score_report_path)
    lines = [
        "# Headphone/Earpiece Manual Recording Checklist",
        "",
        "This checklist is generated from the manual recording kit. It is operator guidance only.",
        "The kit and this checklist are not release evidence; only the scored listener-ear WAV report can satisfy the release gate.",
        "",
        "## Hardware Setup",
        "",
        "1. Use laptop speakers or another non-headphone speaker as the original source output.",
        "2. Use the headset or earpiece under test as the translated headphone output.",
        "3. Put a separate recorder or microphone at the listener-ear point inside or flush with the headphone earcup.",
        "4. Keep the source speaker, measurement mic, and headphone seal fixed between matching takes.",
        "5. Disable spatial audio, audio enhancements, AGC, noise suppression, echo cancellation, and communications ducking.",
        "",
        "## Kit Settings",
        "",
        f"- Manifest: `{manifest_path}`",
        f"- Sample rate: `{sample_rate_hz}` Hz",
        f"- Minimum take duration: `{min_artifact_duration_s}` seconds",
        f"- Maximum release alignment lag: `{max_alignment_lag_ms}` ms",
        f"- Required source isolation: `{min_source_isolation_db}` dB or better",
        "",
        "## Takes",
        "",
        "| Take | Play This Reference | Record To This WAV | Physical Setup |",
        "| --- | --- | --- | --- |",
    ]
    for step in manifest.get("recording_steps", []):
        if not isinstance(step, dict):
            continue
        lines.append(
            "| "
            f"`{step.get('name')}` | "
            f"`{step.get('play')}` | "
            f"`{step.get('record_to')}` | "
            f"{step.get('instruction')} |"
        )
    lines.extend(
        [
            "",
            "## Recording Rules",
            "",
            f"- Export each take as mono 16-bit PCM WAV at `{sample_rate_hz}` Hz.",
            f"- Trim pre-roll so the played reference begins within `{max_alignment_lag_ms}` ms of the recording start.",
            "- Do not denoise, normalize, compress, or otherwise repair the recordings.",
            "- Repeat clipped or distorted takes instead of editing them.",
            "- The Bluetooth headset microphone is not enough unless it is physically at the listener-ear point.",
            "",
            "## Optional Repo Playback Helper",
            "",
            "Use this only if the repo should play the references while an external recorder is rolling:",
            "",
            "```powershell",
            f"pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-play-manual --manifest {manifest_arg} --source-output-device SOURCE_OUTPUT_DEVICE --headphone-output-device HEADPHONE_OUTPUT_DEVICE",
            "```",
            "",
            "For a dry run without playback:",
            "",
            "```powershell",
            f"pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-play-manual --manifest {manifest_arg} --dry-run --source-output-device SOURCE_OUTPUT_DEVICE --headphone-output-device HEADPHONE_OUTPUT_DEVICE",
            "```",
            "",
            "## Import External Recorder Files",
            "",
            "If the recorder exports different filenames, import them into the manifest paths:",
            "",
            "```powershell",
            f"pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-import-manual --manifest {manifest_arg} --source-open-ear-recording RAW_SOURCE_OPEN.wav --source-isolated-ear-recording RAW_SOURCE_ISOLATED.wav --translated-headphone-recording RAW_TRANSLATED.wav --allow-downmix",
            "```",
            "",
            "Expected manifest recording paths:",
            "",
            f"- Source open-ear: `{expected_recordings.get('source_open_ear_recording')}`",
            f"- Source isolated-ear: `{expected_recordings.get('source_isolated_ear_recording')}`",
            f"- Translated headphone: `{expected_recordings.get('translated_headphone_recording')}`",
            "",
            "Reference files:",
            "",
            f"- Source reference: `{artifact_paths.get('source_reference')}`",
            f"- Translated playback reference: `{artifact_paths.get('translated_playback_reference')}`",
            "",
            "## Check And Score",
            "",
            "Run the doctor with concrete hardware labels:",
            "",
            "```powershell",
            f"pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-check-manual --manifest {manifest_arg} --headphone-device-label \"REPLACE_WITH_HEADPHONE_MODEL\" --isolation-fixture-label \"REPLACE_WITH_EARCUP_AND_MIC_POSITION\" --measurement-microphone-label \"REPLACE_WITH_MIC_MODEL_AND_POSITION\"",
            "```",
            "",
            "Then score the release-gated report with the same labels:",
            "",
            "```powershell",
            f"pwsh -NoProfile -File scripts/dev_container.ps1 headphone-isolation-score-manual --manifest {manifest_arg} --headphone-device-label \"REPLACE_WITH_HEADPHONE_MODEL\" --isolation-fixture-label \"REPLACE_WITH_EARCUP_AND_MIC_POSITION\" --measurement-microphone-label \"REPLACE_WITH_MIC_MODEL_AND_POSITION\"",
            "```",
            "",
            f"Score report path: `{score_report_path}`",
            "",
            "Finally rerun the hard gate:",
            "",
            "```powershell",
            f"python scripts/release_audio_gate.py --json --headphone-isolation-report {score_report_arg}",
            "```",
            "",
        ]
    )
    checklist_path.write_text("\n".join(str(line) for line in lines), encoding="utf-8")


def prepare_manual_kit(args: argparse.Namespace) -> int:
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_raw, translated_raw, reference_source_kind, reference_segments = _capture_reference_tracks(args)
    reference_segments = limit_reference_segments(
        reference_segments,
        sample_rate_hz=int(args.sample_rate_hz),
        max_duration_s=float(args.max_reference_duration_s),
    )
    source_raw, translated_raw = limit_track_pair(
        source_raw,
        translated_raw,
        sample_rate_hz=int(args.sample_rate_hz),
        max_duration_s=float(args.max_reference_duration_s),
    )
    source_reference = add_padding(
        apply_playback_gain(source_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    translated_reference = add_padding(
        apply_playback_gain(translated_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    min_duration_s = min(source_reference.size, translated_reference.size) / float(args.sample_rate_hz)
    if min_duration_s < float(args.min_measurement_duration_s):
        raise ValueError("manual kit reference artifacts are shorter than the minimum measurement duration")

    source_reference_path = run_dir / "source-reference.wav"
    translated_reference_path = run_dir / "translated-playback-reference.wav"
    source_open_path = run_dir / "source-open-ear-recording.wav"
    source_isolated_path = run_dir / "source-isolated-ear-recording.wav"
    translated_recording_path = run_dir / "translated-headphone-recording.wav"
    manifest_path = run_dir / "manual-recording-manifest.json"
    checklist_path = run_dir / DEFAULT_MANUAL_CHECKLIST
    write_mono_wav(source_reference_path, source_reference, int(args.sample_rate_hz))
    write_mono_wav(translated_reference_path, translated_reference, int(args.sample_rate_hz))
    artifact_hashes = {
        "source_reference": sha256_file(source_reference_path),
        "translated_playback_reference": sha256_file(translated_reference_path),
    }
    score_args = [
        "python",
        "scripts/run_headphone_isolation_check.py",
        "score-manual",
        "--output-dir",
        str(args.output_dir),
        "--run-id",
        str(args.score_run_id),
        "--manifest",
        str(manifest_path),
        "--headphone-device-label",
        "placeholder REPLACE_WITH_HEADPHONE_MODEL",
        "--isolation-fixture-label",
        "placeholder REPLACE_WITH_EARCUP_AND_MIC_POSITION",
        "--measurement-microphone-label",
        "placeholder REPLACE_WITH_MIC_MODEL_AND_POSITION",
        "--procedure-note",
        "external listener-ear manual recording",
    ]
    manifest = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "adapter_id": args.adapter_id,
        "fixture_kind": "headphone_earpiece_manual_recording_kit",
        "measurement_kind": "headphone_earpiece_manual_recording_kit",
        "release_proof": False,
        "reference_source_kind": reference_source_kind,
        "sample_rate_hz": int(args.sample_rate_hz),
        "min_artifact_duration_s": round(float(min_duration_s), 6),
        "artifact_paths": {
            "source_reference": str(source_reference_path),
            "translated_playback_reference": str(translated_reference_path),
        },
        "artifact_hashes": artifact_hashes,
        "expected_recording_paths": {
            "source_open_ear_recording": str(source_open_path),
            "source_isolated_ear_recording": str(source_isolated_path),
            "translated_headphone_recording": str(translated_recording_path),
        },
        "recording_requirements": {
            "format": "mono 16-bit PCM WAV",
            "sample_rate_hz": int(args.sample_rate_hz),
            "sync": (
                "Trim recording pre-roll so the played reference begins within 500 ms of the recording start; "
                "the release gate recomputes metrics with a 500 ms alignment window."
            ),
        },
        "recording_steps": [
            {
                "name": "source_open_ear_recording",
                "play": str(source_reference_path),
                "record_to": str(source_open_path),
                "instruction": (
                    "Place the measurement mic at the listener-ear position with the headphone/earpiece "
                    "removed or isolation disabled, then play the source reference through the original-source speaker."
                ),
            },
            {
                "name": "source_isolated_ear_recording",
                "play": str(source_reference_path),
                "record_to": str(source_isolated_path),
                "instruction": (
                    "Keep the same mic position, seal the headphone/earpiece over it, then play the same "
                    "source reference through the original-source speaker."
                ),
            },
            {
                "name": "translated_headphone_recording",
                "play": str(translated_reference_path),
                "record_to": str(translated_recording_path),
                "instruction": (
                    "Keep the headphone/earpiece sealed over the listener-ear mic, then play the translated "
                    "reference through the headphone/earpiece output."
                ),
            },
        ],
        "score_command": score_args,
        "score_report_path": str(Path(args.output_dir) / "runs" / args.score_run_id / "headphone-isolation-report.json"),
        "operator_checklist_path": str(checklist_path),
        "quality_bar": {
            "min_source_open_dbfs": DEFAULT_MIN_SOURCE_OPEN_DBFS,
            "min_translated_dbfs": DEFAULT_MIN_TRANSLATED_DBFS,
            "min_source_open_correlation": DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
            "min_translated_correlation": DEFAULT_MIN_TRANSLATED_CORRELATION,
            "min_source_isolation_db": DEFAULT_MIN_SOURCE_ISOLATION_DB,
            "max_translated_distortion_db": DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
            "max_alignment_lag_ms": DEFAULT_MAX_ALIGNMENT_LAG_MS,
        },
        "reference_segments": reference_segments,
        "detractor_loop": {
            "strongest_objection": (
                "This kit only prepares reference playback files. It does not prove microphone placement, "
                "headphone seal, route fidelity, or source attenuation until real listener-ear recordings are scored."
            ),
            "verdict": "Keep release_proof=false; run score after recording physical listener-ear WAV artifacts.",
        },
    }
    manifest = json_safe(manifest)
    write_manual_recording_checklist(
        checklist_path=checklist_path,
        manifest_path=manifest_path,
        manifest=manifest,
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "headphone/earpiece manual kit READY: "
        f"duration_s={manifest['min_artifact_duration_s']}, sample_rate_hz={int(args.sample_rate_hz)}"
    )
    print(f"wrote source reference to {source_reference_path}")
    print(f"wrote translated reference to {translated_reference_path}")
    print(f"wrote manual recording manifest to {manifest_path}")
    print(f"wrote manual recording checklist to {checklist_path}")
    return 0


def manual_recording_status_name(summary: dict[str, Any]) -> str:
    if bool(summary.get("manual_score_ready")):
        return "SCORE-READY"
    if bool(summary.get("manual_recordings_ready_for_score_input")):
        return "FILES-READY-LABELS-PENDING"
    return "NOT-READY"


def manual_status_check_value(report: dict[str, Any], name: str) -> Any:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        return None
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            return check.get("value")
    return None


def manual_status_label(report: dict[str, Any], key: str, placeholder: str) -> str:
    labels = manual_status_check_value(report, "manual_score_labels_specific")
    if isinstance(labels, dict):
        item = labels.get(key)
        if isinstance(item, dict) and bool(item.get("passed")) and specific_label(item.get("value")):
            return str(item["value"])
    return placeholder


def render_manual_recording_status_markdown(report: dict[str, Any]) -> str:
    summary = report.get("summary", {})
    summary = summary if isinstance(summary, dict) else {}
    status = manual_recording_status_name(summary)
    manifest_path = Path(str(report.get("manifest_path") or "manual-recording-manifest.json"))
    manifest_arg = _powershell_quote(manifest_path)
    score_report_path = Path(
        str(
            report.get("score_report_path")
            or DEFAULT_OUTPUT_DIR / "runs" / DEFAULT_RUN_ID / "headphone-isolation-report.json"
        )
    )
    score_report_arg = _powershell_quote(score_report_path)
    checklist_path = manifest_path.parent / DEFAULT_MANUAL_CHECKLIST
    headphone_label = manual_status_label(report, "headphone_device_label", "REPLACE_WITH_HEADPHONE_MODEL")
    fixture_label = manual_status_label(report, "isolation_fixture_label", "REPLACE_WITH_EARCUP_AND_MIC_POSITION")
    microphone_label = manual_status_label(report, "measurement_microphone_label", "REPLACE_WITH_MIC_MODEL_AND_POSITION")
    lines = [
        "# Manual Headphone/Earpiece Recording Status",
        "",
        f"- Status: **{status}**",
        f"- Manifest: `{manifest_path}`",
        f"- Release proof: `{report.get('release_proof')}`",
        f"- Issues: {summary.get('issue_count', 0)}",
        f"- Warnings: {summary.get('warning_count', 0)}",
        f"- Recording WAVs ready for score input: `{summary.get('manual_recordings_ready_for_score_input')}`",
        f"- Score labels specific: `{summary.get('manual_score_labels_specific')}`",
        "",
        "## Checks",
        "",
    ]
    for check in report.get("checks", []):
        if not isinstance(check, dict):
            continue
        check_status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- [{check_status}] {check.get('name')}: {check.get('message')}")
    issues = [str(issue) for issue in report.get("issues", []) if str(issue).strip()]
    warnings = [str(warning) for warning in report.get("warnings", []) if str(warning).strip()]
    lines.extend(["", "## Issues", ""])
    lines.extend([f"- {issue}" for issue in issues] or ["- None"])
    lines.extend(["", "## Warnings", ""])
    lines.extend([f"- {warning}" for warning in warnings] or ["- None"])
    lines.extend(
        [
            "",
            "## Next Actions",
            "",
            "- This status report is not release evidence; only the scored `headphone-isolation-report.json` can satisfy the release gate.",
        ]
    )
    if status == "SCORE-READY":
        lines.extend(
            [
                "- Run the scorer with the same labels, then rerun the hard release gate.",
                "",
                "```powershell",
                "$env:LANGUAGE_PYTHON = \"C:\\Path\\To\\python.exe\"",
                f"$headphoneLabel = {powershell_quote_arg(headphone_label)}",
                f"$fixtureLabel = {powershell_quote_arg(fixture_label)}",
                f"$microphoneLabel = {powershell_quote_arg(microphone_label)}",
                f"pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action score-manual -Python $env:LANGUAGE_PYTHON --manifest {manifest_arg} --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel",
                f"python scripts/release_audio_gate.py --json --headphone-isolation-report {score_report_arg}",
                "```",
            ]
        )
    elif status == "FILES-READY-LABELS-PENDING":
        lines.extend(
            [
                "- The WAV files are ready, but scoring still needs specific hardware and fixture labels.",
                "",
                "```powershell",
                "$env:LANGUAGE_PYTHON = \"C:\\Path\\To\\python.exe\"",
                "$headphoneLabel = \"REPLACE_WITH_HEADPHONE_MODEL\"",
                "$fixtureLabel = \"REPLACE_WITH_EARCUP_AND_MIC_POSITION\"",
                "$microphoneLabel = \"REPLACE_WITH_MIC_MODEL_AND_POSITION\"",
                f"pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action check-manual -Python $env:LANGUAGE_PYTHON --manifest {manifest_arg} --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel",
                f"pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action score-manual -Python $env:LANGUAGE_PYTHON --manifest {manifest_arg} --headphone-device-label $headphoneLabel --isolation-fixture-label $fixtureLabel --measurement-microphone-label $microphoneLabel",
                "```",
            ]
        )
    else:
        lines.extend(
            [
                f"- Follow `{checklist_path}` to collect the three listener-ear recordings.",
                "- If recorder exports use different filenames, import them into the manifest paths before checking again.",
                "",
                "```powershell",
                "$env:LANGUAGE_PYTHON = \"C:\\Path\\To\\python.exe\"",
                f"pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action import-manual -Python $env:LANGUAGE_PYTHON --manifest {manifest_arg} --source-open-ear-recording RAW_SOURCE_OPEN.wav --source-isolated-ear-recording RAW_SOURCE_ISOLATED.wav --translated-headphone-recording RAW_TRANSLATED.wav --allow-downmix",
                f"pwsh -NoProfile -File scripts/headphone_isolation_local.ps1 -Action check-manual -Python $env:LANGUAGE_PYTHON --manifest {manifest_arg} --score-warning-only",
                "```",
            ]
        )
    lines.extend(
        [
            "",
            "## Detractor Note",
            "",
            str(report.get("detractor_loop", {}).get("strongest_objection", "")),
            "",
            str(report.get("detractor_loop", {}).get("verdict", "")),
            "",
        ]
    )
    return "\n".join(lines)


def write_manual_recording_status_markdown(report: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_manual_recording_status_markdown(report), encoding="utf-8")


def check_manual_recordings(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    report_path = Path(args.report) if args.report else manifest_path.parent / DEFAULT_MANUAL_STATUS_REPORT
    markdown_report = getattr(args, "markdown_report", None)
    markdown_path = Path(markdown_report) if markdown_report else report_path.with_suffix(".md")
    checks: list[dict[str, Any]] = []
    warnings: list[str] = []
    issues: list[str] = []

    def add_check(name: str, passed: bool, message: str, value: Any = None) -> None:
        check = {"message": message, "name": name, "passed": bool(passed)}
        if value is not None:
            check["value"] = value
        checks.append(check)
        if not passed:
            issues.append(message)

    manifest: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                manifest = loaded
            else:
                issues.append("manifest JSON must be an object")
        except (OSError, json.JSONDecodeError) as exc:
            issues.append(f"manifest could not be read: {exc}")
    else:
        issues.append(f"manifest is missing: {manifest_path}")

    if manifest:
        add_check(
            "manual_kit_not_release_proof",
            manifest.get("release_proof") is False,
            "manual kit manifest must remain release_proof=false",
            manifest.get("release_proof"),
        )
        requirements = manifest.get("recording_requirements")
        requirements = requirements if isinstance(requirements, dict) else {}
        raw_sample_rate_hz = (
            requirements.get("sample_rate_hz")
            or manifest.get("sample_rate_hz")
            or DEFAULT_SAMPLE_RATE_HZ
        )
        try:
            expected_sample_rate_hz = int(raw_sample_rate_hz)
            if expected_sample_rate_hz <= 0:
                raise ValueError("must be positive")
        except (TypeError, ValueError):
            expected_sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
            issues.append("recording sample_rate_hz must be a positive integer")
        try:
            min_duration_s = float(manifest.get("min_artifact_duration_s") or DEFAULT_MIN_MEASUREMENT_DURATION_S)
            if min_duration_s <= 0.0:
                raise ValueError("must be positive")
        except (TypeError, ValueError):
            min_duration_s = DEFAULT_MIN_MEASUREMENT_DURATION_S
            issues.append("min_artifact_duration_s must be a positive number")
        artifacts = manifest.get("artifact_paths")
        artifacts = artifacts if isinstance(artifacts, dict) else {}
        artifact_hashes = manifest.get("artifact_hashes")
        artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
        expected_recordings = manifest.get("expected_recording_paths")
        expected_recordings = expected_recordings if isinstance(expected_recordings, dict) else {}

        reference_results: dict[str, Any] = {}
        for key in MANUAL_REQUIRED_REFERENCES:
            try:
                path = resolve_manual_manifest_path(manifest_path, artifacts.get(key))
            except ValueError as exc:
                reference_results[key] = {"issues": [str(exc)], "passed": False}
                issues.append(f"{key}: {exc}")
                continue
            result = inspect_mono_pcm16_wav(
                path,
                expected_sample_rate_hz=expected_sample_rate_hz,
                min_duration_s=min_duration_s,
            )
            expected_hash = artifact_hashes.get(key)
            if not expected_hash:
                result["issues"].append("missing manifest hash")
                result["passed"] = False
            elif result["passed"]:
                actual_hash = sha256_file(path)
                result["sha256"] = actual_hash
                if actual_hash != expected_hash:
                    result["issues"].append("hash does not match manifest")
                    result["passed"] = False
            reference_results[key] = result
            if not result["passed"]:
                issues.append(f"{key}: {', '.join(result['issues'])}")
        add_check(
            "manual_reference_wavs_ready",
            all(bool(item.get("passed")) for item in reference_results.values())
            and len(reference_results) == len(MANUAL_REQUIRED_REFERENCES),
            "manual kit source/translated reference WAVs must exist and match the manifest",
            reference_results,
        )

        recording_results: dict[str, Any] = {}
        for key in MANUAL_REQUIRED_RECORDINGS:
            try:
                path = resolve_manual_manifest_path(manifest_path, expected_recordings.get(key))
            except ValueError as exc:
                recording_results[key] = {"issues": [str(exc)], "passed": False}
                issues.append(f"{key}: {exc}")
                continue
            result = inspect_mono_pcm16_wav(
                path,
                expected_sample_rate_hz=expected_sample_rate_hz,
                min_duration_s=min_duration_s,
            )
            recording_results[key] = result
            if not result["passed"]:
                issues.append(f"{key}: {', '.join(result['issues'])}")
        add_check(
            "manual_recording_wavs_ready",
            all(bool(item.get("passed")) for item in recording_results.values())
            and len(recording_results) == len(MANUAL_REQUIRED_RECORDINGS),
            "three listener-ear recordings must exist as mono 16-bit PCM WAVs at the kit sample rate",
            recording_results,
        )
        files_ready = not issues and bool(manifest)

        score_command = manifest.get("score_command")
        score_command = score_command if isinstance(score_command, list) else []
        label_flags = {
            "headphone_device_label": "--headphone-device-label",
            "isolation_fixture_label": "--isolation-fixture-label",
            "measurement_microphone_label": "--measurement-microphone-label",
        }
        score_command_labels = {
            attr: str(score_command[index + 1])
            for attr, flag in label_flags.items()
            for index, value in enumerate(score_command[:-1])
            if value == flag
        }
        score_label_results: dict[str, Any] = {}
        placeholder_labels = []
        for attr, flag in label_flags.items():
            provided = getattr(args, attr, None)
            manifest_value = score_command_labels.get(attr)
            if isinstance(provided, str) and specific_label(provided):
                score_label_results[attr] = {
                    "passed": True,
                    "source": "check-manual argument",
                    "value": provided,
                }
            elif isinstance(manifest_value, str) and specific_label(manifest_value):
                score_label_results[attr] = {
                    "passed": True,
                    "source": "manifest score_command",
                    "value": manifest_value,
                }
            else:
                value = provided if isinstance(provided, str) and provided.strip() else manifest_value
                placeholder_labels.append(str(value or flag))
                score_label_results[attr] = {
                    "passed": False,
                    "source": "missing or placeholder",
                    "value": value,
                }
        score_labels_specific = all(bool(item.get("passed")) for item in score_label_results.values())
        add_check(
            "manual_score_labels_specific",
            score_labels_specific,
            "specific headphone, listener-ear microphone, and fixture labels must be supplied before scoring",
            score_label_results,
        )
        if placeholder_labels:
            warnings.append(
                "replace placeholder score-command labels with specific headphone, mic, and fixture labels before scoring"
            )
    else:
        expected_sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
        min_duration_s = DEFAULT_MIN_MEASUREMENT_DURATION_S
        reference_results = {}
        recording_results = {}
        files_ready = False
        placeholder_labels = []
        score_labels_specific = False

    ready = not issues and bool(manifest)
    report = {
        "schema_version": 1,
        "generated_at_unix": int(time.time()),
        "manifest_path": str(manifest_path),
        "release_proof": False,
        "score_report_path": str(
            manifest.get("score_report_path")
            or DEFAULT_OUTPUT_DIR / "runs" / DEFAULT_RUN_ID / "headphone-isolation-report.json"
        ),
        "summary": {
            "issue_count": len(issues),
            "manual_recordings_ready_for_score_input": files_ready,
            "manual_score_labels_specific": score_labels_specific,
            "manual_score_ready": ready,
            "placeholder_label_count": len(placeholder_labels),
            "release_proof": False,
            "warning_count": len(warnings),
        },
        "checks": checks,
        "issues": issues,
        "warnings": warnings,
        "recording_requirements": {
            "format": "mono 16-bit PCM WAV",
            "min_duration_s": min_duration_s,
            "sample_rate_hz": expected_sample_rate_hz,
            "sync": "trim recording pre-roll so played reference starts within 500 ms",
        },
        "detractor_loop": {
            "strongest_objection": (
                "This status report checks file shape only. It does not prove source isolation, "
                "translated fidelity, microphone placement, or headphone seal."
            ),
            "verdict": "Use this before score; only the scored headphone-isolation report can satisfy release evidence.",
        },
    }
    report = json_safe(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    write_manual_recording_status_markdown(report, markdown_path)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    status = "SCORE-READY" if ready else ("FILES-READY-LABELS-PENDING" if files_ready else "NOT-READY")
    print(
        f"headphone/earpiece manual recordings {status}: "
        f"issues={len(issues)}, warnings={len(warnings)}"
    )
    print(f"wrote manual recording status to {report_path}")
    print(f"wrote manual recording status handoff to {markdown_path}")
    return 0 if ready or args.score_warning_only else 1


def score_command_option(score_command: list[Any], flag: str) -> str | None:
    for index, value in enumerate(score_command[:-1]):
        if value == flag:
            return str(score_command[index + 1])
    return None


def load_manual_manifest(manifest_path: Path) -> dict[str, Any]:
    loaded = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{manifest_path} must contain a JSON object")
    return loaded


def score_manual_recordings(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    status_result = check_manual_recordings(
        argparse.Namespace(
            headphone_device_label=args.headphone_device_label,
            isolation_fixture_label=args.isolation_fixture_label,
            json=False,
            manifest=manifest_path,
            measurement_microphone_label=args.measurement_microphone_label,
            report=args.status_report,
            score_warning_only=False,
        )
    )
    if status_result != 0:
        return status_result

    manifest = load_manual_manifest(manifest_path)
    artifacts = manifest.get("artifact_paths")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    expected_recordings = manifest.get("expected_recording_paths")
    expected_recordings = expected_recordings if isinstance(expected_recordings, dict) else {}
    score_command = manifest.get("score_command")
    score_command = score_command if isinstance(score_command, list) else []

    def required_path(container: dict[str, Any], key: str) -> Path:
        return resolve_manual_manifest_path(manifest_path, container.get(key))

    score_args = argparse.Namespace(
        adapter_id=args.adapter_id,
        headphone_device_label=args.headphone_device_label,
        isolation_fixture_label=args.isolation_fixture_label,
        max_alignment_lag_ms=args.max_alignment_lag_ms,
        max_translated_distortion_db=args.max_translated_distortion_db,
        measurement_microphone_label=args.measurement_microphone_label,
        min_measurement_duration_s=args.min_measurement_duration_s,
        min_source_isolation_db=args.min_source_isolation_db,
        min_source_open_correlation=args.min_source_open_correlation,
        min_source_open_dbfs=args.min_source_open_dbfs,
        min_translated_correlation=args.min_translated_correlation,
        min_translated_dbfs=args.min_translated_dbfs,
        output_dir=Path(args.output_dir or score_command_option(score_command, "--output-dir") or DEFAULT_OUTPUT_DIR),
        procedure_note=args.procedure_note,
        run_id=args.run_id or score_command_option(score_command, "--run-id") or DEFAULT_RUN_ID,
        score_warning_only=args.score_warning_only,
        source_isolated_ear_recording=required_path(expected_recordings, "source_isolated_ear_recording"),
        source_open_ear_recording=required_path(expected_recordings, "source_open_ear_recording"),
        source_reference=required_path(artifacts, "source_reference"),
        translated_headphone_recording=required_path(expected_recordings, "translated_headphone_recording"),
        translated_playback_reference=required_path(artifacts, "translated_playback_reference"),
    )
    return score(score_args)


def read_manual_import_wav(
    path: Path,
    *,
    allow_downmix: bool,
    expected_sample_rate_hz: int,
    min_duration_s: float,
) -> tuple[dict[str, Any], np.ndarray | None]:
    if not path.exists():
        raise ValueError(f"{path} is missing")
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
        raise ValueError(f"{path} must be 16-bit PCM WAV before import")
    if sample_rate_hz != int(expected_sample_rate_hz):
        raise ValueError(f"{path} sample rate must be {int(expected_sample_rate_hz)} Hz before import")
    if frame_count <= 0:
        raise ValueError(f"{path} must contain frames")
    duration_s = float(frame_count) / float(sample_rate_hz) if sample_rate_hz > 0 else 0.0
    if duration_s < float(min_duration_s):
        raise ValueError(f"{path} duration must be >= {float(min_duration_s):.3f}s before import")

    raw = np.frombuffer(frames, dtype="<i2")
    expected_values = int(frame_count) * int(channels)
    if raw.size != expected_values:
        raise ValueError(f"{path} frame data length does not match its WAV header")
    samples: np.ndarray | None = None
    conversion_kind = "copy_mono_pcm16"
    decoded_mono_pcm_sha256 = hashlib.sha256(frames).hexdigest()
    if channels != 1:
        if not allow_downmix:
            raise ValueError(f"{path} has {channels} channels; pass --allow-downmix to import as mono")
        samples = raw.reshape(frame_count, channels).astype(np.float32) / 32768.0
        samples = np.mean(samples, axis=1).astype(np.float32)
        decoded_mono_pcm_sha256 = pcm16_bytes_sha256(mono_float_to_pcm16(samples))
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
        samples,
    )


def build_manual_import_plan(args: argparse.Namespace) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_path = Path(args.manifest)
    manifest = load_manual_manifest(manifest_path)
    if manifest.get("release_proof") is not False:
        raise ValueError("manual import manifest must remain release_proof=false")
    requirements = manifest.get("recording_requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    try:
        expected_sample_rate_hz = int(
            requirements.get("sample_rate_hz")
            or manifest.get("sample_rate_hz")
            or DEFAULT_SAMPLE_RATE_HZ
        )
        if expected_sample_rate_hz <= 0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("manual import manifest sample_rate_hz must be a positive integer") from exc
    try:
        min_duration_s = float(manifest.get("min_artifact_duration_s") or DEFAULT_MIN_MEASUREMENT_DURATION_S)
        if min_duration_s <= 0.0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("manual import manifest min_artifact_duration_s must be a positive number") from exc
    expected_recordings = manifest.get("expected_recording_paths")
    expected_recordings = expected_recordings if isinstance(expected_recordings, dict) else {}
    artifact_hashes = manifest.get("artifact_hashes")
    artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
    reference_hashes = {
        str(value)
        for key, value in artifact_hashes.items()
        if key in MANUAL_REQUIRED_REFERENCES and isinstance(value, str) and value
    }
    reference_pcm_hashes: dict[str, str] = {}
    artifacts = manifest.get("artifact_paths")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    for key in MANUAL_REQUIRED_REFERENCES:
        try:
            reference_pcm_hashes[key] = mono_wav_pcm_sha256(resolve_manual_manifest_path(manifest_path, artifacts.get(key)))
        except (OSError, ValueError, wave.Error) as exc:
            raise ValueError(f"{key} reference PCM could not be verified before import: {exc}") from exc

    for field in ("headphone_device_label", "isolation_fixture_label", "measurement_microphone_label"):
        value = getattr(args, field, None)
        if isinstance(value, str) and value.strip() and not specific_label(value):
            raise ValueError(f"{field} must be specific if supplied to import-manual")

    plan: list[dict[str, Any]] = []
    seen_source_paths: dict[str, str] = {}
    seen_input_hashes: dict[str, str] = {}
    for key in MANUAL_REQUIRED_RECORDINGS:
        take = MANUAL_IMPORT_TAKES[key]
        source_value = getattr(args, str(take["argument"]))
        source_path = Path(source_value)
        target_path = resolve_manual_manifest_path(manifest_path, expected_recordings.get(key))
        details, downmixed_samples = read_manual_import_wav(
            source_path,
            allow_downmix=bool(args.allow_downmix),
            expected_sample_rate_hz=expected_sample_rate_hz,
            min_duration_s=min_duration_s,
        )
        source_identity = str(source_path.resolve())
        duplicate_path_key = seen_source_paths.get(source_identity)
        if duplicate_path_key:
            raise ValueError(f"{key} reuses the same source file as {duplicate_path_key}: {source_path}")
        seen_source_paths[source_identity] = key
        input_sha256 = str(details["input_sha256"])
        duplicate_hash_key = seen_input_hashes.get(input_sha256)
        if duplicate_hash_key:
            raise ValueError(f"{key} has the same raw audio hash as {duplicate_hash_key}; record separate takes")
        seen_input_hashes[input_sha256] = key
        if input_sha256 in reference_hashes:
            raise ValueError(f"{key} matches a manual reference WAV hash; import a listener-ear recording instead")
        decoded_mono_pcm_sha256 = str(details["decoded_mono_pcm_sha256"])
        for reference_key, reference_pcm_sha256 in reference_pcm_hashes.items():
            if decoded_mono_pcm_sha256 == reference_pcm_sha256:
                raise ValueError(
                    f"{key} decoded PCM matches {reference_key}; import a listener-ear recording instead"
                )
        try:
            same_file = source_path.resolve() == target_path.resolve()
        except OSError:
            same_file = False
        action = str(details["conversion_kind"])
        if same_file and action != "copy_mono_pcm16":
            raise ValueError(f"{key} cannot be downmixed in place; import from a separate source WAV")
        if same_file:
            action = "already_in_expected_path"
        elif target_path.exists() and not bool(args.allow_overwrite):
            raise ValueError(f"{key} target already exists: {target_path}; pass --allow-overwrite to replace it")
        event = {
            **details,
            "dry_run": bool(args.dry_run),
            "key": key,
            "output_channels": 1,
            "output_sample_rate_hz": expected_sample_rate_hz,
            "source_path": str(source_path),
            "summary": str(take["summary"]),
            "target_path": str(target_path),
            "write_action": action,
        }
        plan.append(
            {
                "event": event,
                "source_path": source_path,
                "target_path": target_path,
                "samples": downmixed_samples,
                "write_action": action,
            }
        )
    return manifest_path, manifest, plan


def import_manual_recordings(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    log_path = Path(args.log) if args.log else manifest_path.parent / DEFAULT_MANUAL_IMPORT_LOG
    try:
        manifest_path, manifest, plan = build_manual_import_plan(args)
    except Exception as exc:
        log = json_safe(
            {
                "schema_version": 1,
                "generated_at_unix": int(time.time()),
                "manifest_sha256": sha256_file(manifest_path) if manifest_path.exists() else None,
                "manifest_path": str(manifest_path),
                "release_proof": False,
                "summary": {
                    "dry_run": bool(args.dry_run),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "manual_import_ready": False,
                    "release_proof": False,
                },
                "import_events": [],
                "detractor_loop": {
                    "strongest_objection": (
                        "A failed import plan does not prove the listener-ear recordings exist or are usable."
                    ),
                    "verdict": "Fix the source files or manifest before scoring release evidence.",
                },
            }
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(f"headphone/earpiece manual import NOT-READY: {type(exc).__name__}: {exc}")
        print(f"wrote manual import log to {log_path}")
        return 1

    import_events: list[dict[str, Any]] = []
    if not args.dry_run:
        for item in plan:
            source_path = Path(item["source_path"])
            target_path = Path(item["target_path"])
            target_path.parent.mkdir(parents=True, exist_ok=True)
            action = str(item["write_action"])
            if action == "already_in_expected_path":
                pass
            elif action == "copy_mono_pcm16":
                shutil.copy2(source_path, target_path)
            elif action == "downmix_to_mono_pcm16":
                write_mono_wav(target_path, item["samples"], int(item["event"]["output_sample_rate_hz"]))
            else:
                raise ValueError(f"unknown manual import write action: {action}")
            event = dict(item["event"])
            event["target_sha256"] = sha256_file(target_path)
            import_events.append(event)
    else:
        import_events = [dict(item["event"]) for item in plan]

    status_report = Path(args.status_report) if args.status_report else manifest_path.parent / DEFAULT_MANUAL_STATUS_REPORT
    post_import_summary: dict[str, Any] = {}
    post_import_error: str | None = None
    if not args.dry_run and not args.skip_check:
        try:
            check_manual_recordings(
                argparse.Namespace(
                    headphone_device_label=args.headphone_device_label,
                    isolation_fixture_label=args.isolation_fixture_label,
                    json=False,
                    manifest=manifest_path,
                    measurement_microphone_label=args.measurement_microphone_label,
                    report=status_report,
                    score_warning_only=True,
                )
            )
            status = json.loads(status_report.read_text(encoding="utf-8"))
            if isinstance(status, dict) and isinstance(status.get("summary"), dict):
                post_import_summary = dict(status["summary"])
            else:
                post_import_error = "post-import status report did not contain a summary object"
        except Exception as exc:
            post_import_error = str(exc)
    manual_recordings_ready = post_import_summary.get("manual_recordings_ready_for_score_input")
    post_import_check_failed = bool(post_import_error) or (
        bool((not args.dry_run) and (not args.skip_check)) and manual_recordings_ready is not True
    )
    log = json_safe(
        {
            "schema_version": 1,
            "generated_at_unix": int(time.time()),
            "manifest_sha256": sha256_file(manifest_path),
            "manifest_path": str(manifest_path),
            "release_proof": False,
            "summary": {
                "allow_downmix": bool(args.allow_downmix),
                "allow_overwrite": bool(args.allow_overwrite),
                "dry_run": bool(args.dry_run),
                "import_event_count": len(import_events),
                "manual_import_ready": True,
                "manual_recordings_ready_for_score_input": manual_recordings_ready,
                "manual_score_ready": post_import_summary.get("manual_score_ready"),
                "post_import_check_error": post_import_error,
                "post_import_check_failed": post_import_check_failed,
                "post_import_check_run": bool((not args.dry_run) and (not args.skip_check)),
                "post_import_issue_count": post_import_summary.get("issue_count"),
                "post_import_warning_count": post_import_summary.get("warning_count"),
                "release_proof": False,
                "status_report_path": str(status_report),
            },
            "manual_manifest": {
                "expected_recording_paths": manifest.get("expected_recording_paths", {}),
                "recording_requirements": manifest.get("recording_requirements", {}),
                "sample_rate_hz": manifest.get("sample_rate_hz"),
            },
            "import_events": import_events,
            "detractor_loop": {
                "strongest_objection": (
                    "This import log proves only local file normalization. It does not prove the recordings "
                    "came from the listener-ear fixture, that the headset was sealed, or that isolation passed."
                ),
                "verdict": "Keep release_proof=false; run check-manual and score-manual before using release evidence.",
            },
        }
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    mode = "DRY-RUN" if args.dry_run else "DONE"
    print(f"headphone/earpiece manual import {mode}: recordings={len(import_events)}")
    print(f"wrote manual import log to {log_path}")
    return 1 if post_import_check_failed else 0


def manual_take_names(values: list[str] | None) -> list[str]:
    requested = values or ["all"]
    if "all" in requested:
        return list(MANUAL_PLAYBACK_TAKES.keys())
    names: list[str] = []
    for value in requested:
        if value not in MANUAL_PLAYBACK_TAKES:
            raise ValueError(f"unknown manual playback take: {value}")
        if value not in names:
            names.append(value)
    return names


def manual_playback_output_device(args: argparse.Namespace, route: str) -> int | str | None:
    override = parse_device_selector(getattr(args, "output_device", None))
    if override is not None:
        return override
    if route == "source":
        output_device = parse_device_selector(getattr(args, "source_output_device", None))
        if output_device is None and not bool(getattr(args, "allow_default_output", False)):
            raise ValueError("source manual playback takes require --source-output-device or --output-device")
        return output_device
    if route == "headphone":
        output_device = parse_device_selector(getattr(args, "headphone_output_device", None))
        if output_device is None and not bool(getattr(args, "allow_default_output", False)):
            raise ValueError("translated manual playback takes require --headphone-output-device or --output-device")
        return output_device
    raise ValueError(f"unknown manual playback route: {route}")


def manual_reference_result(
    *,
    artifact_hashes: dict[str, Any],
    expected_sample_rate_hz: int,
    key: str,
    manifest_path: Path,
    min_duration_s: float,
    path: Path,
) -> dict[str, Any]:
    result = inspect_mono_pcm16_wav(
        path,
        expected_sample_rate_hz=expected_sample_rate_hz,
        min_duration_s=min_duration_s,
    )
    expected_hash = artifact_hashes.get(key)
    if not expected_hash:
        result["issues"].append("missing manifest hash")
        result["passed"] = False
    elif result["passed"]:
        actual_hash = sha256_file(path)
        result["sha256"] = actual_hash
        if actual_hash != expected_hash:
            result["issues"].append("hash does not match manifest")
            result["passed"] = False
    result["manifest_path"] = str(manifest_path)
    return result


def build_manual_playback_plan(args: argparse.Namespace) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
    manifest_path = Path(args.manifest)
    manifest = load_manual_manifest(manifest_path)
    artifacts = manifest.get("artifact_paths")
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    artifact_hashes = manifest.get("artifact_hashes")
    artifact_hashes = artifact_hashes if isinstance(artifact_hashes, dict) else {}
    expected_recordings = manifest.get("expected_recording_paths")
    expected_recordings = expected_recordings if isinstance(expected_recordings, dict) else {}
    requirements = manifest.get("recording_requirements")
    requirements = requirements if isinstance(requirements, dict) else {}
    try:
        expected_sample_rate_hz = int(
            requirements.get("sample_rate_hz")
            or manifest.get("sample_rate_hz")
            or DEFAULT_SAMPLE_RATE_HZ
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("manual playback manifest sample_rate_hz must be an integer") from exc
    try:
        min_duration_s = float(manifest.get("min_artifact_duration_s") or DEFAULT_MIN_MEASUREMENT_DURATION_S)
        if min_duration_s <= 0.0:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise ValueError("manual playback manifest min_artifact_duration_s must be a positive number") from exc
    if manifest.get("release_proof") is not False:
        raise ValueError("manual playback manifest must remain release_proof=false")

    reference_paths = {
        key: resolve_manual_manifest_path(manifest_path, artifacts.get(key))
        for key in MANUAL_REQUIRED_REFERENCES
    }
    reference_results = {
        key: manual_reference_result(
            artifact_hashes=artifact_hashes,
            expected_sample_rate_hz=expected_sample_rate_hz,
            key=key,
            manifest_path=manifest_path,
            min_duration_s=min_duration_s,
            path=path,
        )
        for key, path in reference_paths.items()
    }
    failed_references = {
        key: value.get("issues", [])
        for key, value in reference_results.items()
        if not value.get("passed")
    }
    if failed_references:
        raise ValueError(f"manual playback references are not ready: {failed_references}")

    plan: list[dict[str, Any]] = []
    for take_name in manual_take_names(args.take):
        take = MANUAL_PLAYBACK_TAKES[take_name]
        reference_key = str(take["reference_key"])
        recording_key = str(take["recording_key"])
        route = str(take["route"])
        reference_path = reference_paths[reference_key]
        reference_audio, reference_rate_hz = read_mono_wav(reference_path)
        output_device = manual_playback_output_device(args, route)
        plan.append(
            {
                "duration_s": round(float(reference_audio.size) / float(reference_rate_hz), 6),
                "expected_recording_path": str(
                    resolve_manual_manifest_path(manifest_path, expected_recordings.get(recording_key))
                ),
                "output_channels": int(args.output_channels),
                "reference_key": reference_key,
                "reference_path": str(reference_path),
                "reference_sha256": sha256_file(reference_path),
                "route": route,
                "sample_rate_hz": int(reference_rate_hz),
                "summary": str(take["summary"]),
                "take": take_name,
                "requested_output_device": output_device,
            }
        )
    return manifest_path, manifest, plan


def play_manual_references(args: argparse.Namespace) -> int:
    if int(args.output_channels) <= 0:
        raise ValueError("--output-channels must be positive")
    if int(args.repeat) <= 0:
        raise ValueError("--repeat must be positive")
    manifest_path = Path(args.manifest)
    log_path = Path(args.log) if args.log else manifest_path.parent / DEFAULT_MANUAL_PLAYBACK_LOG
    try:
        manifest_path, manifest, plan = build_manual_playback_plan(args)
    except Exception as exc:
        log = json_safe(
            {
                "schema_version": 1,
                "generated_at_unix": int(time.time()),
                "manifest_path": str(manifest_path),
                "release_proof": False,
                "summary": {
                    "dry_run": bool(args.dry_run),
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                    "manual_playback_plan_ready": False,
                    "playback_event_count": 0,
                    "release_proof": False,
                },
                "playback_events": [],
                "detractor_loop": {
                    "strongest_objection": (
                        "This failed playback-plan log is not evidence that audio was played or recorded."
                    ),
                    "verdict": "Fix the manual manifest or output-device arguments before recording.",
                },
            }
        )
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(log, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(f"headphone/earpiece manual playback NOT-READY: {type(exc).__name__}: {exc}")
        print(f"wrote manual playback log to {log_path}")
        return 1
    playback_events: list[dict[str, Any]] = []
    sd = None if args.dry_run else import_sounddevice()

    for repeat_index in range(int(args.repeat)):
        for index, item in enumerate(plan):
            message = (
                f"[{repeat_index + 1}/{int(args.repeat)}] {item['take']}: "
                f"record to {item['expected_recording_path']} while playing {item['reference_path']} "
                f"via {item['route']} output"
            )
            wait_for_operator(message, non_interactive=bool(args.non_interactive or args.dry_run))
            if float(args.countdown_s) > 0.0 and not args.dry_run:
                print(f"starting playback in {float(args.countdown_s):.1f}s")
                time.sleep(float(args.countdown_s))
            event = dict(item)
            event["dry_run"] = bool(args.dry_run)
            event["repeat_index"] = repeat_index
            event["played_at_unix"] = int(time.time())
            if args.dry_run:
                event["elapsed_s"] = 0.0
                event["output_device_info"] = {}
            else:
                audio, sample_rate_hz = read_mono_wav(Path(str(item["reference_path"])))
                playback = mono_playback(audio, int(args.output_channels))
                output_device = item["requested_output_device"]
                output_info = portaudio_device_identity(output_device, kind="output")
                start = time.perf_counter()
                sd.play(
                    playback,
                    samplerate=int(sample_rate_hz),
                    device=output_device,
                    blocking=True,
                )
                event["elapsed_s"] = round(time.perf_counter() - start, 6)
                event["output_device_info"] = output_info
            playback_events.append(event)
            if (
                not args.dry_run
                and float(args.inter_take_pause_s) > 0.0
                and (repeat_index < int(args.repeat) - 1 or index < len(plan) - 1)
            ):
                time.sleep(float(args.inter_take_pause_s))

    log = json_safe(
        {
            "schema_version": 1,
            "generated_at_unix": int(time.time()),
            "manifest_path": str(manifest_path),
            "release_proof": False,
            "summary": {
                "dry_run": bool(args.dry_run),
                "playback_event_count": len(playback_events),
                "release_proof": False,
                "take_count": len(plan),
            },
            "manual_manifest": {
                "artifact_hashes": manifest.get("artifact_hashes", {}),
                "artifact_paths": manifest.get("artifact_paths", {}),
                "expected_recording_paths": manifest.get("expected_recording_paths", {}),
                "sample_rate_hz": manifest.get("sample_rate_hz"),
            },
            "playback_events": playback_events,
            "detractor_loop": {
                "strongest_objection": (
                    "This log only records guided playback attempts. It does not prove the external "
                    "recorder captured listener-ear audio or that isolation passed."
                ),
                "verdict": "Keep release_proof=false; score the recorded WAVs before using release evidence.",
            },
        }
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(json.dumps(log, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    mode = "DRY-RUN" if args.dry_run else "DONE"
    print(f"headphone/earpiece manual playback {mode}: events={len(playback_events)}")
    print(f"wrote manual playback log to {log_path}")
    return 0


def capture(args: argparse.Namespace) -> int:
    for field in ("headphone_device_label", "isolation_fixture_label", "measurement_microphone_label"):
        if not specific_label(getattr(args, field)):
            raise ValueError(f"{field.replace('_', '-')} must be specific, not a placeholder")

    measurement_input_device = parse_device_selector(args.measurement_input_device)
    source_output_device = parse_device_selector(args.source_output_device)
    headphone_output_device = parse_device_selector(args.headphone_output_device)
    preflight_binding = capture_preflight_binding(
        preflight_report=Path(args.preflight_report),
        measurement_input_device=measurement_input_device,
        source_output_device=source_output_device,
        headphone_output_device=headphone_output_device,
        sample_rate_hz=int(args.sample_rate_hz),
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )
    run_dir = Path(args.output_dir) / "runs" / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    source_raw, translated_raw, reference_source_kind, reference_segments = _capture_reference_tracks(args)
    reference_segments = limit_reference_segments(
        reference_segments,
        sample_rate_hz=int(args.sample_rate_hz),
        max_duration_s=float(args.max_reference_duration_s),
    )
    source_raw, translated_raw = limit_track_pair(
        source_raw,
        translated_raw,
        sample_rate_hz=int(args.sample_rate_hz),
        max_duration_s=float(args.max_reference_duration_s),
    )
    source_reference = add_padding(
        apply_playback_gain(source_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    translated_reference = add_padding(
        apply_playback_gain(translated_raw, float(args.playback_gain_db), float(args.max_peak_dbfs)),
        int(args.sample_rate_hz),
        float(args.lead_s),
        float(args.tail_s),
    )
    if min(source_reference.size, translated_reference.size) / float(args.sample_rate_hz) < float(
        args.min_measurement_duration_s
    ):
        raise ValueError("capture reference artifacts are shorter than the minimum measurement duration")

    source_reference_path = run_dir / "source-reference.wav"
    translated_reference_path = run_dir / "translated-playback-reference.wav"
    source_open_path = run_dir / "source-open-ear-recording.wav"
    source_isolated_path = run_dir / "source-isolated-ear-recording.wav"
    translated_recording_path = run_dir / "translated-headphone-recording.wav"
    write_mono_wav(source_reference_path, source_reference, int(args.sample_rate_hz))
    write_mono_wav(translated_reference_path, translated_reference, int(args.sample_rate_hz))

    device_info = {
        "headphone_output_device": portaudio_device_identity(headphone_output_device, kind="output"),
        "measurement_input_device": portaudio_device_identity(measurement_input_device, kind="input"),
        "source_output_device": portaudio_device_identity(source_output_device, kind="output"),
    }
    device_mismatches = preflight_binding_device_mismatches(preflight_binding, device_info)
    if device_mismatches:
        raise ValueError("guided capture device identity changed since preflight: " + "; ".join(device_mismatches))
    device_fingerprint = measurement_device_fingerprint(
        device_info=device_info,
        sample_rate_hz=int(args.sample_rate_hz),
        input_channels=int(args.input_channels),
        output_channels=int(args.output_channels),
    )
    preflight_binding["capture_device_path_fingerprint"] = device_fingerprint
    print(f"measurement device fingerprint: {device_fingerprint}")
    capture_context: dict[str, Any] = {
        "backend": CAPTURE_BACKEND_PORTAUDIO,
        "device_path_fingerprint": device_fingerprint,
        "device_info": device_info,
        "reference_segments": reference_segments,
        "sample_rate_hz": int(args.sample_rate_hz),
        "input_channels": int(args.input_channels),
        "output_channels": int(args.output_channels),
        "preflight_binding": preflight_binding,
        "playback_gain_db": float(args.playback_gain_db),
        "lead_s": float(args.lead_s),
        "tail_s": float(args.tail_s),
        "reference_source_kind": reference_source_kind,
        "source_route_control": (
            "source_open_ear_recording and source_isolated_ear_recording use the same "
            "source output device, source reference WAV, playback gain, sample rate, and channels"
        ),
    }

    source_playback = mono_playback(source_reference, int(args.output_channels))
    translated_playback = mono_playback(translated_reference, int(args.output_channels))
    artifact_paths = {
        "source_reference": str(source_reference_path),
        "source_open_ear_recording": str(source_open_path),
        "source_isolated_ear_recording": str(source_isolated_path),
        "translated_playback_reference": str(translated_reference_path),
        "translated_headphone_recording": str(translated_recording_path),
    }

    try:
        wait_for_operator(
            "Step 1/3: OPEN-EAR CONTROL. Put the listener-ear microphone in the measurement position, "
            "leave the headphone/earpiece isolation path off or removed, and route the source output to the original-source speaker.",
            non_interactive=bool(args.non_interactive),
        )
        source_open, elapsed = record_playback(
            source_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["source_open_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["source_open_recording"] = recording_diagnostics(source_open, int(args.sample_rate_hz))
        write_mono_wav(source_open_path, source_open, int(args.sample_rate_hz))

        wait_for_operator(
            "Step 2/3: ISOLATED SOURCE. Keep the source speaker route unchanged, place/enable the "
            "headphone or earpiece isolation fixture on the same listener-ear microphone, then record the source again.",
            non_interactive=bool(args.non_interactive),
        )
        source_isolated, elapsed = record_playback(
            source_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=source_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["source_isolated_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["source_isolated_recording"] = recording_diagnostics(source_isolated, int(args.sample_rate_hz))
        write_mono_wav(source_isolated_path, source_isolated, int(args.sample_rate_hz))

        wait_for_operator(
            "Step 3/3: TRANSLATED HEADPHONE PLAYBACK. Keep the listener-ear measurement fixture in place, "
            "route output to the headphone/earpiece device, and record the translated playback.",
            non_interactive=bool(args.non_interactive),
        )
        translated_recording, elapsed = record_playback(
            translated_playback,
            sample_rate_hz=int(args.sample_rate_hz),
            input_device=measurement_input_device,
            output_device=headphone_output_device,
            input_channels=int(args.input_channels),
        )
        capture_context["translated_headphone_capture_elapsed_s"] = round(elapsed, 6)
        capture_context["translated_headphone_recording"] = recording_diagnostics(
            translated_recording,
            int(args.sample_rate_hz),
        )
        write_mono_wav(translated_recording_path, translated_recording, int(args.sample_rate_hz))
    except Exception as exc:
        report_path = write_capture_failure_report(
            args=args,
            run_dir=run_dir,
            capture_context=capture_context,
            artifact_paths=artifact_paths,
            error=exc,
        )
        print(f"headphone/earpiece guided capture FAIL: {type(exc).__name__}: {exc}")
        print(f"wrote headphone isolation failure report to {report_path}")
        return 0 if args.score_warning_only else 1

    score_args = argparse.Namespace(**vars(args))
    score_args.adapter_id = args.adapter_id
    score_args.capture_backend = CAPTURE_BACKEND_PORTAUDIO
    score_args.capture_context = capture_context
    score_args.capture_source_kind = CAPTURE_SOURCE_KIND_PORTAUDIO
    score_args.device_info = device_info
    score_args.device_path_fingerprint = device_fingerprint
    score_args.device_path_identity_recorded = True
    score_args.reference_source_kind = reference_source_kind
    score_args.source_reference = source_reference_path
    score_args.source_open_ear_recording = source_open_path
    score_args.source_isolated_ear_recording = source_isolated_path
    score_args.translated_playback_reference = translated_reference_path
    score_args.translated_headphone_recording = translated_recording_path
    return score(score_args)


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        sample_rate_hz = DEFAULT_SAMPLE_RATE_HZ
        if specific_label("REPLACE_WITH_MIC_MODEL_AND_POSITION"):
            raise RuntimeError("REPLACE_WITH labels must be rejected as placeholders")
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
        silent_source_isolated_path = root / "source-isolated-silent.wav"
        write_mono_wav(source_path, source, sample_rate_hz)
        write_mono_wav(source_open_path, source_open, sample_rate_hz)
        write_mono_wav(source_isolated_path, source_isolated, sample_rate_hz)
        write_mono_wav(silent_source_isolated_path, np.zeros_like(source), sample_rate_hz)
        write_mono_wav(translated_path, translated, sample_rate_hz)
        write_mono_wav(translated_recording_path, translated_recording, sample_rate_hz)
        stereo_path = root / "stereo.wav"
        with wave.open(str(stereo_path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate_hz)
            stereo_pcm = np.repeat(
                np.round(source * 32767.0).astype("<i2").reshape(-1, 1),
                2,
                axis=1,
            )
            wav.writeframes(stereo_pcm.tobytes())
        try:
            read_mono_wav(stereo_path)
        except ValueError as exc:
            if "mono PCM_16 WAV" not in str(exc):
                raise RuntimeError("expected stereo WAV rejection to explain mono PCM_16 requirement") from exc
        else:
            raise RuntimeError("expected stereo WAV to be rejected before release scoring")
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
        passing_report_path = Path(args.output_dir) / "runs" / args.run_id / "headphone-isolation-report.json"
        passing_report = json.loads(passing_report_path.read_text(encoding="utf-8"))
        passing_summary = dict(passing_report["benchmarks"][BENCHMARK_NAME]["summary"])
        portaudio_summary = dict(passing_summary)
        portaudio_summary.update(
            {
                "capture_backend": CAPTURE_BACKEND_PORTAUDIO,
                "capture_source_kind": CAPTURE_SOURCE_KIND_PORTAUDIO,
                "device_path_fingerprint": "1" * 64,
                "device_path_identity_recorded": True,
            }
        )
        portaudio_gates = {gate["name"]: gate for gate in quality_gates(portaudio_summary, args)}
        if bool(portaudio_gates["headphone_guided_capture_preflight_bound"]["passed"]):
            raise RuntimeError("guided PortAudio scoring must fail without preflight binding")
        portaudio_summary["capture_preflight_binding"] = {
            "bound": True,
            "capture_device_path_fingerprint": "3" * 64,
            "physical_listener_ear_input_confirmed": True,
            "planning_passed": True,
            "preflight_report_sha256": "2" * 64,
            "recommended_path": "guided_capture_possible",
            "selected_route": "0:1:2",
            "selected_route_capture_ready": True,
        }
        portaudio_gates = {gate["name"]: gate for gate in quality_gates(portaudio_summary, args)}
        if not bool(portaudio_gates["headphone_guided_capture_preflight_bound"]["passed"]):
            raise RuntimeError("guided PortAudio scoring should pass with preflight binding")
        args.run_id = "wide-alignment-headphone-earpiece-isolation"
        args.max_alignment_lag_ms = DEFAULT_MAX_ALIGNMENT_LAG_MS + 250.0
        args.score_warning_only = True
        result = score(args)
        if result != 0:
            raise RuntimeError("warning-only wide-alignment self-test should return 0")
        wide_report_path = (
            Path(args.output_dir)
            / "runs"
            / args.run_id
            / "headphone-isolation-report.json"
        )
        wide_report = json.loads(wide_report_path.read_text(encoding="utf-8"))
        wide_gates = {gate["name"]: gate for gate in wide_report.get("summary", {}).get("quality_gates", [])}
        if bool(wide_gates["headphone_release_alignment_window"]["passed"]):
            raise RuntimeError("expected wide release alignment self-test gate to fail")
        args.max_alignment_lag_ms = DEFAULT_MAX_ALIGNMENT_LAG_MS
        args.score_warning_only = False
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
        args.run_id = "silent-isolated-headphone-earpiece-isolation"
        args.source_isolated_ear_recording = silent_source_isolated_path
        args.score_warning_only = True
        result = score(args)
        if result != 0:
            raise RuntimeError("warning-only silent-isolated self-test should return 0")
        report_path = (
            Path(args.output_dir)
            / "runs"
            / args.run_id
            / "headphone-isolation-report.json"
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if bool(report.get("summary", {}).get("passed")):
            raise RuntimeError("expected silent-isolated self-test fixture to fail")
        gates = {gate["name"]: gate for gate in report.get("summary", {}).get("quality_gates", [])}
        if bool(gates["headphone_core_metrics_finite"]["passed"]):
            raise RuntimeError("expected silent-isolated finite-metrics gate to fail")
        json.dumps(report, allow_nan=False)
        manual_result = prepare_manual_kit(
            argparse.Namespace(
                adapter_id=DEFAULT_MANUAL_KIT_ADAPTER_ID,
                gap_s=DEFAULT_GAP_S,
                lead_s=0.1,
                max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                max_reference_duration_s=0.0,
                min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
                output_dir=root / "manual-kit-out",
                playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                run_id="unit-manual-kit",
                sample_rate_hz=sample_rate_hz,
                score_run_id=DEFAULT_RUN_ID,
                source_reference=source_path,
                tail_s=0.1,
                translated_playback_reference=translated_path,
                tts_report=DEFAULT_TTS_REPORT,
            )
        )
        if manual_result != 0:
            raise RuntimeError("expected manual recording kit self-test fixture to pass")
        manual_manifest_path = (
            root
            / "manual-kit-out"
            / "runs"
            / "unit-manual-kit"
            / "manual-recording-manifest.json"
        )
        manual_manifest = json.loads(manual_manifest_path.read_text(encoding="utf-8"))
        if manual_manifest.get("release_proof") is not False:
            raise RuntimeError("manual recording kit must not set release_proof")
        for key in ("source_reference", "translated_playback_reference"):
            if not Path(manual_manifest["artifact_paths"][key]).exists():
                raise RuntimeError(f"manual recording kit missing {key}")
        if "score-manual" not in manual_manifest.get("score_command", []):
            raise RuntimeError("manual recording kit should include a score-manual command")
        expected_recording_paths = manual_manifest.get("expected_recording_paths", {})
        if not expected_recording_paths.get("source_open_ear_recording"):
            raise RuntimeError("manual recording kit should name expected recording paths")
        manual_checklist_path = manual_manifest_path.parent / DEFAULT_MANUAL_CHECKLIST
        if manual_manifest.get("operator_checklist_path") != str(manual_checklist_path):
            raise RuntimeError("manual recording kit should reference the generated checklist")
        if not manual_checklist_path.exists():
            raise RuntimeError("manual recording kit should write an operator checklist")
        manual_checklist = manual_checklist_path.read_text(encoding="utf-8")
        artifact_paths = manual_manifest.get("artifact_paths", {})
        score_report_path = manual_manifest.get("score_report_path")
        manual_manifest_arg = _powershell_quote(manual_manifest_path)
        score_report_arg = _powershell_quote(score_report_path)
        for expected_text in (
            "Headphone/Earpiece Manual Recording Checklist",
            "not release evidence",
            "source_open_ear_recording",
            "source_isolated_ear_recording",
            "translated_headphone_recording",
            f"headphone-isolation-play-manual --manifest {manual_manifest_arg}",
            f"headphone-isolation-import-manual --manifest {manual_manifest_arg}",
            f"headphone-isolation-check-manual --manifest {manual_manifest_arg}",
            f"headphone-isolation-score-manual --manifest {manual_manifest_arg}",
            f"release_audio_gate.py --json --headphone-isolation-report {score_report_arg}",
            str(score_report_path),
        ):
            if expected_text not in manual_checklist:
                raise RuntimeError(f"manual recording checklist missing {expected_text!r}")
        for key in (
            "source_open_ear_recording",
            "source_isolated_ear_recording",
            "translated_headphone_recording",
        ):
            expected_path = expected_recording_paths.get(key)
            if not expected_path or str(expected_path) not in manual_checklist:
                raise RuntimeError(f"manual recording checklist missing expected path for {key}")
        for key in ("source_reference", "translated_playback_reference"):
            expected_path = artifact_paths.get(key)
            if not expected_path or str(expected_path) not in manual_checklist:
                raise RuntimeError(f"manual recording checklist missing artifact path for {key}")
        playback_dry_run_result = play_manual_references(
            argparse.Namespace(
                countdown_s=0.0,
                dry_run=True,
                headphone_output_device="unit-headphone-output",
                inter_take_pause_s=0.0,
                log=manual_manifest_path.parent / "manual-playback-log-dry-run.json",
                manifest=manual_manifest_path,
                non_interactive=True,
                allow_default_output=False,
                output_channels=2,
                output_device=None,
                repeat=1,
                source_output_device="unit-source-output",
                take=["all"],
            )
        )
        if playback_dry_run_result != 0:
            raise RuntimeError("expected manual playback dry-run self-test fixture to pass")
        playback_log = json.loads(
            (manual_manifest_path.parent / "manual-playback-log-dry-run.json").read_text(encoding="utf-8")
        )
        if playback_log.get("release_proof") is not False:
            raise RuntimeError("manual playback log must not set release_proof")
        if int(playback_log.get("summary", {}).get("playback_event_count") or 0) != 3:
            raise RuntimeError("manual playback dry-run should plan three recording takes")
        playback_routes = {event.get("take"): event.get("route") for event in playback_log.get("playback_events", [])}
        if playback_routes != {
            "source-open": "source",
            "source-isolated": "source",
            "translated": "headphone",
        }:
            raise RuntimeError("manual playback dry-run should map takes to source/headphone routes")
        json.dumps(playback_log, allow_nan=False)
        missing_route_playback_result = play_manual_references(
            argparse.Namespace(
                countdown_s=0.0,
                dry_run=True,
                headphone_output_device=None,
                inter_take_pause_s=0.0,
                log=manual_manifest_path.parent / "manual-playback-log-missing-route.json",
                manifest=manual_manifest_path,
                non_interactive=True,
                allow_default_output=False,
                output_channels=2,
                output_device=None,
                repeat=1,
                source_output_device=None,
                take=["all"],
            )
        )
        if missing_route_playback_result == 0:
            raise RuntimeError("manual playback should fail closed without explicit output routes")
        missing_route_playback_log = json.loads(
            (manual_manifest_path.parent / "manual-playback-log-missing-route.json").read_text(encoding="utf-8")
        )
        if missing_route_playback_log.get("release_proof") is not False:
            raise RuntimeError("failed manual playback route log must not set release_proof")
        if bool(missing_route_playback_log.get("summary", {}).get("manual_playback_plan_ready", True)):
            raise RuntimeError("failed manual playback route log should mark plan not ready")
        missing_route_error = str(missing_route_playback_log.get("summary", {}).get("error") or "")
        if "--source-output-device" not in missing_route_error:
            raise RuntimeError("missing route playback log should explain required source output device")
        playback_malformed_manifest = json.loads(json.dumps(manual_manifest))
        playback_malformed_manifest["min_artifact_duration_s"] = "not-a-duration"
        playback_malformed_manifest_path = (
            manual_manifest_path.parent / "manual-recording-manifest-playback-malformed.json"
        )
        playback_malformed_manifest_path.write_text(
            json.dumps(playback_malformed_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        malformed_playback_result = play_manual_references(
            argparse.Namespace(
                countdown_s=0.0,
                dry_run=True,
                headphone_output_device="unit-headphone-output",
                inter_take_pause_s=0.0,
                log=manual_manifest_path.parent / "manual-playback-log-malformed.json",
                manifest=playback_malformed_manifest_path,
                non_interactive=True,
                allow_default_output=False,
                output_channels=2,
                output_device=None,
                repeat=1,
                source_output_device="unit-source-output",
                take=["all"],
            )
        )
        if malformed_playback_result == 0:
            raise RuntimeError("manual playback should fail for malformed manifest duration")
        malformed_playback_log = json.loads(
            (manual_manifest_path.parent / "manual-playback-log-malformed.json").read_text(encoding="utf-8")
        )
        malformed_playback_error = str(malformed_playback_log.get("summary", {}).get("error") or "")
        if "min_artifact_duration_s" not in malformed_playback_error:
            raise RuntimeError("malformed manual playback log should explain min_artifact_duration_s")
        missing_manual_result = check_manual_recordings(
            argparse.Namespace(
                json=False,
                manifest=manual_manifest_path,
                report=manual_manifest_path.parent / "manual-recording-status-missing.json",
                score_warning_only=True,
            )
        )
        if missing_manual_result != 0:
            raise RuntimeError("warning-only manual recording status should return 0 before recordings exist")
        missing_manual_status = json.loads(
            (manual_manifest_path.parent / "manual-recording-status-missing.json").read_text(encoding="utf-8")
        )
        if bool(missing_manual_status.get("summary", {}).get("manual_recordings_ready_for_score_input")):
            raise RuntimeError("expected manual recording status to reject missing listener-ear recordings")
        missing_manual_markdown = (
            manual_manifest_path.parent / "manual-recording-status-missing.md"
        ).read_text(encoding="utf-8")
        if "Status: **NOT-READY**" not in missing_manual_markdown:
            raise RuntimeError("manual recording status Markdown should show NOT-READY for missing recordings")
        if "manual-recording-checklist.md" not in missing_manual_markdown:
            raise RuntimeError("manual recording status Markdown should point back to the recording checklist")
        if "import-manual" not in missing_manual_markdown:
            raise RuntimeError("manual recording status Markdown should include the import-manual recovery path")
        missing_score_manual_result = score_manual_recordings(
            argparse.Namespace(
                adapter_id=DEFAULT_ADAPTER_ID,
                headphone_device_label="unit headphones",
                isolation_fixture_label="unit sealed-ear fixture",
                manifest=manual_manifest_path,
                max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
                measurement_microphone_label="unit ear microphone",
                min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
                min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
                min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
                min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
                min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
                output_dir=root / "missing-manual-score-out",
                procedure_note="unit external listener-ear manual recording",
                run_id="missing-unit-manual-score",
                score_warning_only=True,
                status_report=manual_manifest_path.parent / "manual-recording-status-score-manual-missing.json",
            )
        )
        if missing_score_manual_result == 0:
            raise RuntimeError("score-manual warning-only must not bypass missing listener-ear recordings")
        expected_recordings = manual_manifest.get("expected_recording_paths", {})
        raw_import_dir = manual_manifest_path.parent / "raw-import-fixtures"
        raw_import_dir.mkdir(parents=True, exist_ok=True)
        source_open_import = raw_import_dir / "phone-source-open.wav"
        source_isolated_import = raw_import_dir / "phone-source-isolated.wav"
        translated_import = raw_import_dir / "phone-translated-stereo.wav"
        source_reference_junk_import = raw_import_dir / "source-reference-with-junk-chunk.wav"
        translated_import_mono = add_padding(translated_recording, sample_rate_hz, 0.1, 0.1)
        write_mono_wav(
            source_open_import,
            add_padding(source_open, sample_rate_hz, 0.1, 0.1),
            sample_rate_hz,
        )
        write_mono_wav(
            source_isolated_import,
            add_padding(source * db_to_linear(-19.0), sample_rate_hz, 0.1, 0.1),
            sample_rate_hz,
        )
        translated_stereo = np.stack([translated_import_mono, translated_import_mono], axis=1)
        translated_pcm = np.round(np.clip(translated_stereo, -1.0, 1.0) * 32767.0).astype("<i2")
        with wave.open(str(translated_import), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate_hz)
            wav.writeframes(translated_pcm.tobytes())
        source_reference_path = Path(manual_manifest.get("artifact_paths", {})["source_reference"])
        source_reference_bytes = source_reference_path.read_bytes()
        junk_chunk = b"JUNK" + int(4).to_bytes(4, "little") + b"test"
        riff_size = int.from_bytes(source_reference_bytes[4:8], "little") + len(junk_chunk)
        source_reference_junk_import.write_bytes(
            source_reference_bytes[:4]
            + riff_size.to_bytes(4, "little")
            + source_reference_bytes[8:12]
            + junk_chunk
            + source_reference_bytes[12:]
        )
        import_without_downmix_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=False,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-no-downmix.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-no-downmix.json",
                translated_headphone_recording=translated_import,
            )
        )
        if import_without_downmix_result == 0:
            raise RuntimeError("manual import should reject stereo recordings unless --allow-downmix is explicit")
        duplicate_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-duplicate-source.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_open_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-duplicate-source.json",
                translated_headphone_recording=translated_import,
            )
        )
        if duplicate_import_result == 0:
            raise RuntimeError("manual import should reject duplicate raw recording files across takes")
        reference_clone_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-reference-clone.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=manual_manifest.get("artifact_paths", {})["source_reference"],
                status_report=manual_manifest_path.parent / "manual-recording-status-import-reference-clone.json",
                translated_headphone_recording=translated_import,
            )
        )
        if reference_clone_import_result == 0:
            raise RuntimeError("manual import should reject exact reference WAV clones as listener-ear recordings")
        reference_pcm_clone_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-reference-pcm-clone.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_reference_junk_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-reference-pcm-clone.json",
                translated_headphone_recording=translated_import,
            )
        )
        if reference_pcm_clone_import_result == 0:
            raise RuntimeError("manual import should reject reference PCM clones with different WAV containers")
        placeholder_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label="placeholder REPLACE_WITH_HEADPHONE_MODEL",
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-placeholder-label.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-placeholder-label.json",
                translated_headphone_recording=translated_import,
            )
        )
        if placeholder_import_result == 0:
            raise RuntimeError("manual import should reject placeholder labels when labels are supplied")
        dry_run_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-dry-run.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-dry-run.json",
                translated_headphone_recording=translated_import,
            )
        )
        if dry_run_import_result != 0:
            raise RuntimeError("expected manual import dry-run to pass with explicit downmix")
        dry_run_import_log = json.loads(
            (manual_manifest_path.parent / "manual-import-log-dry-run.json").read_text(encoding="utf-8")
        )
        if dry_run_import_log.get("release_proof") is not False:
            raise RuntimeError("manual import dry-run log must not set release_proof")
        if int(dry_run_import_log.get("summary", {}).get("import_event_count") or 0) != 3:
            raise RuntimeError("manual import dry-run should plan all three recordings")
        if any(Path(path).exists() for path in expected_recordings.values()):
            raise RuntimeError("manual import dry-run must not write expected recording paths")
        import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=False,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=False,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import.json",
                translated_headphone_recording=translated_import,
            )
        )
        if import_result != 0:
            raise RuntimeError("expected manual import to write valid listener-ear recording WAVs")
        import_log = json.loads((manual_manifest_path.parent / "manual-import-log.json").read_text(encoding="utf-8"))
        if import_log.get("release_proof") is not False:
            raise RuntimeError("manual import log must not set release_proof")
        import_actions = {event.get("key"): event.get("write_action") for event in import_log.get("import_events", [])}
        if import_actions.get("translated_headphone_recording") != "downmix_to_mono_pcm16":
            raise RuntimeError("manual import should record the explicit translated stereo downmix action")
        if import_log.get("summary", {}).get("manual_recordings_ready_for_score_input") is not True:
            raise RuntimeError("manual import log should expose post-import score-input readiness")
        if import_log.get("summary", {}).get("manual_score_ready") is not False:
            raise RuntimeError("manual import log should not claim score-ready when labels are still pending")
        repeated_import_result = import_manual_recordings(
            argparse.Namespace(
                allow_downmix=True,
                allow_overwrite=False,
                dry_run=True,
                headphone_device_label=None,
                isolation_fixture_label=None,
                log=manual_manifest_path.parent / "manual-import-log-existing-target.json",
                manifest=manual_manifest_path,
                measurement_microphone_label=None,
                skip_check=True,
                source_isolated_ear_recording=source_isolated_import,
                source_open_ear_recording=source_open_import,
                status_report=manual_manifest_path.parent / "manual-recording-status-import-existing-target.json",
                translated_headphone_recording=translated_import,
            )
        )
        if repeated_import_result == 0:
            raise RuntimeError("manual import should fail closed before replacing existing target recordings")
        ready_manual_result = check_manual_recordings(
            argparse.Namespace(
                json=False,
                manifest=manual_manifest_path,
                report=manual_manifest_path.parent / "manual-recording-status-ready.json",
                score_warning_only=False,
            )
        )
        if ready_manual_result != 1:
            raise RuntimeError("expected manual recording status to block score-ready state while labels are placeholders")
        placeholder_manual_status = json.loads(
            (manual_manifest_path.parent / "manual-recording-status-ready.json").read_text(encoding="utf-8")
        )
        if not bool(placeholder_manual_status.get("summary", {}).get("manual_recordings_ready_for_score_input")):
            raise RuntimeError("expected manual recording status to mark valid WAV recordings ready")
        if bool(placeholder_manual_status.get("summary", {}).get("manual_score_ready")):
            raise RuntimeError("manual recording status must not be score-ready with placeholder labels")
        if int(placeholder_manual_status.get("summary", {}).get("placeholder_label_count") or 0) <= 0:
            raise RuntimeError("manual recording status should warn about placeholder score-command labels")
        placeholder_manual_markdown = (
            manual_manifest_path.parent / "manual-recording-status-ready.md"
        ).read_text(encoding="utf-8")
        if "Status: **FILES-READY-LABELS-PENDING**" not in placeholder_manual_markdown:
            raise RuntimeError("manual recording status Markdown should show labels pending when WAVs are ready")
        if "REPLACE_WITH_HEADPHONE_MODEL" not in placeholder_manual_markdown:
            raise RuntimeError("manual recording status Markdown should keep label replacement prompts visible")
        placeholder_score_manual_result = score_manual_recordings(
            argparse.Namespace(
                adapter_id=DEFAULT_ADAPTER_ID,
                headphone_device_label="placeholder REPLACE_WITH_HEADPHONE_MODEL",
                isolation_fixture_label="placeholder REPLACE_WITH_EARCUP_AND_MIC_POSITION",
                manifest=manual_manifest_path,
                max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
                measurement_microphone_label="placeholder REPLACE_WITH_MIC_MODEL_AND_POSITION",
                min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
                min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
                min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
                min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
                min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
                output_dir=root / "placeholder-manual-score-out",
                procedure_note="unit external listener-ear manual recording",
                run_id="placeholder-unit-manual-score",
                score_warning_only=True,
                status_report=manual_manifest_path.parent / "manual-recording-status-score-manual-placeholder.json",
            )
        )
        if placeholder_score_manual_result == 0:
            raise RuntimeError("score-manual warning-only must not bypass placeholder score labels")
        ready_manual_result = check_manual_recordings(
            argparse.Namespace(
                headphone_device_label="unit headphones",
                isolation_fixture_label="unit sealed-ear fixture",
                json=False,
                manifest=manual_manifest_path,
                measurement_microphone_label="unit ear microphone",
                report=manual_manifest_path.parent / "manual-recording-status-ready-with-labels.json",
                score_warning_only=False,
            )
        )
        if ready_manual_result != 0:
            raise RuntimeError("expected manual recording status to pass after valid WAV recordings and labels exist")
        ready_manual_status = json.loads(
            (manual_manifest_path.parent / "manual-recording-status-ready-with-labels.json").read_text(
                encoding="utf-8"
            )
        )
        if not bool(ready_manual_status.get("summary", {}).get("manual_recordings_ready_for_score_input")):
            raise RuntimeError("expected manual recording status to mark valid listener-ear recordings ready")
        if not bool(ready_manual_status.get("summary", {}).get("manual_score_ready")):
            raise RuntimeError("expected manual recording status to mark valid listener-ear recordings score-ready")
        if ready_manual_status.get("summary", {}).get("release_proof") is not False:
            raise RuntimeError("manual recording status must not set release_proof")
        if ready_manual_status.get("score_report_path") != score_report_path:
            raise RuntimeError("manual recording status should carry the manifest score report path")
        if int(ready_manual_status.get("summary", {}).get("placeholder_label_count") or 0) != 0:
            raise RuntimeError("manual recording status should clear placeholder labels when explicit labels are supplied")
        ready_manual_markdown = (
            manual_manifest_path.parent / "manual-recording-status-ready-with-labels.md"
        ).read_text(encoding="utf-8")
        if "Status: **SCORE-READY**" not in ready_manual_markdown:
            raise RuntimeError("manual recording status Markdown should show score-ready when labels and WAVs pass")
        if "release_audio_gate.py --json" not in ready_manual_markdown:
            raise RuntimeError("manual recording status Markdown should include the release gate follow-up")
        if f"--headphone-isolation-report {score_report_arg}" not in ready_manual_markdown:
            raise RuntimeError("manual recording status Markdown should gate the manifest score report path")
        if "unit headphones" not in ready_manual_markdown:
            raise RuntimeError("manual recording status Markdown should carry concrete score labels")
        manual_score_result = score_manual_recordings(
            argparse.Namespace(
                adapter_id=DEFAULT_ADAPTER_ID,
                headphone_device_label="unit headphones",
                isolation_fixture_label="unit sealed-ear fixture",
                manifest=manual_manifest_path,
                max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
                measurement_microphone_label="unit ear microphone",
                min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
                min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
                min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
                min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
                min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
                output_dir=root / "manual-score-out",
                procedure_note="unit external listener-ear manual recording",
                run_id="unit-manual-score",
                score_warning_only=False,
                status_report=manual_manifest_path.parent / "manual-recording-status-score-manual.json",
            )
        )
        if manual_score_result != 0:
            raise RuntimeError("expected score-manual self-test fixture to pass")
        manual_score_report_path = (
            root
            / "manual-score-out"
            / "runs"
            / "unit-manual-score"
            / "headphone-isolation-report.json"
        )
        manual_score_report = json.loads(manual_score_report_path.read_text(encoding="utf-8"))
        if not bool(manual_score_report.get("summary", {}).get("passed")):
            raise RuntimeError("expected score-manual report to pass")
        if manual_score_report.get("release_proof") is not True:
            raise RuntimeError("score-manual should produce the release-gated scorer report")
        json.dumps(manual_score_report, allow_nan=False)
        missing_hash_manifest = json.loads(json.dumps(manual_manifest))
        missing_hash_manifest["artifact_hashes"].pop("source_reference", None)
        missing_hash_manifest_path = manual_manifest_path.parent / "manual-recording-manifest-missing-hash.json"
        missing_hash_manifest_path.write_text(
            json.dumps(missing_hash_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        missing_hash_result = check_manual_recordings(
            argparse.Namespace(
                json=False,
                manifest=missing_hash_manifest_path,
                report=manual_manifest_path.parent / "manual-recording-status-missing-hash.json",
                score_warning_only=True,
            )
        )
        if missing_hash_result != 0:
            raise RuntimeError("warning-only manual recording status should return 0 for malformed manifest")
        missing_hash_status = json.loads(
            (manual_manifest_path.parent / "manual-recording-status-missing-hash.json").read_text(encoding="utf-8")
        )
        if bool(missing_hash_status.get("summary", {}).get("manual_recordings_ready_for_score_input")):
            raise RuntimeError("manual recording status must reject references without manifest hashes")
        if not any("missing manifest hash" in issue for issue in missing_hash_status.get("issues", [])):
            raise RuntimeError("manual recording status should explain missing manifest hashes")
        missing_hash_score_manual_result = score_manual_recordings(
            argparse.Namespace(
                adapter_id=DEFAULT_ADAPTER_ID,
                headphone_device_label="unit headphones",
                isolation_fixture_label="unit sealed-ear fixture",
                manifest=missing_hash_manifest_path,
                max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
                measurement_microphone_label="unit ear microphone",
                min_measurement_duration_s=DEFAULT_MIN_MEASUREMENT_DURATION_S,
                min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
                min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
                min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
                min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
                output_dir=root / "missing-hash-manual-score-out",
                procedure_note="unit external listener-ear manual recording",
                run_id="missing-hash-unit-manual-score",
                score_warning_only=True,
                status_report=manual_manifest_path.parent / "manual-recording-status-score-manual-missing-hash.json",
            )
        )
        if missing_hash_score_manual_result == 0:
            raise RuntimeError("score-manual warning-only must not bypass missing manifest hashes")
        malformed_manifest = json.loads(json.dumps(manual_manifest))
        malformed_manifest["recording_requirements"]["sample_rate_hz"] = "not-a-sample-rate"
        malformed_manifest["min_artifact_duration_s"] = "not-a-duration"
        malformed_manifest_path = manual_manifest_path.parent / "manual-recording-manifest-malformed.json"
        malformed_manifest_path.write_text(
            json.dumps(malformed_manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        malformed_result = check_manual_recordings(
            argparse.Namespace(
                json=False,
                manifest=malformed_manifest_path,
                report=manual_manifest_path.parent / "manual-recording-status-malformed.json",
                score_warning_only=True,
            )
        )
        if malformed_result != 0:
            raise RuntimeError("warning-only manual recording status should return 0 for bad manifest fields")
        malformed_status = json.loads(
            (manual_manifest_path.parent / "manual-recording-status-malformed.json").read_text(encoding="utf-8")
        )
        malformed_issues = malformed_status.get("issues", [])
        if bool(malformed_status.get("summary", {}).get("manual_recordings_ready_for_score_input")):
            raise RuntimeError("manual recording status must reject malformed numeric manifest fields")
        if not any("sample_rate_hz" in issue for issue in malformed_issues):
            raise RuntimeError("manual recording status should explain malformed sample_rate_hz")
        if not any("min_artifact_duration_s" in issue for issue in malformed_issues):
            raise RuntimeError("manual recording status should explain malformed min_artifact_duration_s")
        json.dumps(manual_manifest, allow_nan=False)
        limited_segments = limit_reference_segments(
            [
                {"segment_index": 0, "start_sample": 0, "end_sample": 80},
                {"segment_index": 1, "start_sample": 90, "end_sample": 140},
                {"segment_index": 2, "start_sample": 120, "end_sample": 180},
            ],
            sample_rate_hz=100,
            max_duration_s=1.0,
        )
        if [item["segment_index"] for item in limited_segments] != [0, 1]:
            raise RuntimeError("expected manual reference segment metadata to drop segments outside the limit")
        if limited_segments[-1].get("end_sample") != 100 or not limited_segments[-1].get(
            "truncated_by_max_reference_duration"
        ):
            raise RuntimeError("expected manual reference segment metadata to mark truncated segments")
        route_args = argparse.Namespace(
            allow_shared_output_device=False,
            max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
            max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
            min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
            min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
        )
        route_summary = {
            "all_artifact_hashes_present": True,
            "device_info": {
                "headphone_output_device": {
                    "hostapi": 1,
                    "hostapi_name": "unit",
                    "index": 3,
                    "name": "unit headphone",
                    "requested_device": 3,
                },
                "source_output_device": {
                    "hostapi": 1,
                    "hostapi_name": "unit",
                    "index": 2,
                    "name": "unit source",
                    "requested_device": 2,
                },
            },
            "headphone_route_opened": True,
            "headphone_route_recording": {
                "clipped_sample_count": 0,
                "peak_dbfs": -18.0,
            },
            "headphone_route_recording_dbfs": -24.0,
            "headphone_route_recording_matches_reference": False,
            "headphone_route_reference_confidence": 0.95,
            "headphone_route_reference_correlation": 0.95,
            "headphone_route_reference_distortion_db": 3.0,
            "release_proof": False,
            "source_route_opened": True,
            "source_route_recording": {
                "clipped_sample_count": 0,
                "peak_dbfs": -18.0,
            },
            "source_route_recording_dbfs": -24.0,
            "source_route_recording_matches_reference": False,
            "source_route_reference_confidence": 0.95,
            "source_route_reference_correlation": 0.95,
            "source_route_reference_distortion_db": 3.0,
        }
        if not all(bool(gate["passed"]) for gate in route_probe_gates(route_summary, route_args)):
            raise RuntimeError("expected route probe gate self-test fixture to pass")
        route_summary["all_artifact_hashes_present"] = False
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_route_probe_artifacts_hashed"]["passed"]):
            raise RuntimeError("expected route probe missing-artifact self-test fixture to fail")
        route_summary["all_artifact_hashes_present"] = True
        route_summary["source_route_recording"]["clipped_sample_count"] = 1
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_source_route_not_clipped"]["passed"]):
            raise RuntimeError("expected route probe clipped-source self-test fixture to fail")
        route_summary["source_route_recording"]["clipped_sample_count"] = 0
        route_summary["device_info"]["headphone_output_device"] = dict(
            route_summary["device_info"]["source_output_device"]
        )
        route_gates = {gate["name"]: gate for gate in route_probe_gates(route_summary, route_args)}
        if bool(route_gates["headphone_route_outputs_distinct"]["passed"]):
            raise RuntimeError("expected route probe same-output self-test fixture to fail")
        failed_route_summary = dict(route_summary)
        failed_route_summary["source_route_reference_confidence"] = 0.0
        failed_route_summary["source_route_reference_distortion_db"] = 99.0
        failed_route_summary["sample_rate_hz"] = sample_rate_hz
        route_diagnosis_args = argparse.Namespace(
            max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
            max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
            max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
            min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
            min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
            sample_rate_hz=sample_rate_hz,
        )
        diagnosis = route_probe_diagnostics(failed_route_summary, route_diagnosis_args)
        if "source:reference_not_detected" not in diagnosis["blocking_reasons"]:
            raise RuntimeError("expected route diagnosis to flag missing source reference")
        if not diagnosis["next_actions"]:
            raise RuntimeError("expected route diagnosis to include next actions")
        quiet_route_summary = dict(failed_route_summary)
        quiet_route_summary["source_route_recording_dbfs"] = DEFAULT_MIN_SOURCE_OPEN_DBFS - 12.0
        quiet_diagnosis = route_probe_diagnostics(quiet_route_summary, route_diagnosis_args)
        if "source:recording_too_quiet" not in quiet_diagnosis["blocking_reasons"]:
            raise RuntimeError("expected quiet route diagnosis to flag recording_too_quiet")
        if "source:reference_not_detected" in quiet_diagnosis["blocking_reasons"]:
            raise RuntimeError("quiet route diagnosis should prioritize level before reference fidelity")
        if "source:reference_distorted" in quiet_diagnosis["blocking_reasons"]:
            raise RuntimeError("quiet route diagnosis should not claim reference distortion before level is adequate")
        same_output_failure_summary = route_sweep_failure_summary(
            [
                {
                    "diagnosis": diagnosis,
                    "failed_gates": [
                        name for name, gate in route_gates.items() if not bool(gate.get("passed"))
                    ],
                }
            ]
        )
        if same_output_failure_summary.get("gate:headphone_route_outputs_distinct") != 1:
            raise RuntimeError("expected route sweep failure summary to include same-output gate")
        if same_output_failure_summary.get("source:reference_not_detected") != 1:
            raise RuntimeError("expected route sweep failure summary to include diagnosis reasons")
        sweep_metrics = route_probe_attempt_metrics(
            {
                **route_summary,
                "device_path_fingerprint": "1" * 64,
                "input_channels": 1,
                "output_channels": 2,
                "sample_rate_hz": sample_rate_hz,
            },
            argparse.Namespace(
                input_channels=1,
                max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                output_channels=2,
                sample_rate_hz=sample_rate_hz,
            ),
        )
        if not isinstance(route_probe_score(sweep_metrics), float):
            raise RuntimeError("expected route probe sweep score to be numeric")
        json.dumps(
            {"quality_gates": route_probe_gates({"release_proof": False}, route_args)},
            allow_nan=False,
        )
        original_route_probe = globals()["route_probe"]

        def fake_passing_route_probe(child_args: argparse.Namespace) -> int:
            child_report_path = (
                Path(child_args.output_dir)
                / "runs"
                / child_args.run_id
                / "headphone-route-probe-report.json"
            )
            child_report_path.parent.mkdir(parents=True, exist_ok=True)
            child_summary = {
                **route_summary,
                "all_artifact_hashes_present": True,
                "device_info": {
                    "headphone_output_device": {
                        "hostapi": 1,
                        "hostapi_name": "unit",
                        "index": int(child_args.headphone_output_device),
                        "name": "unit headphone",
                    },
                    "measurement_input_device": {
                        "hostapi": 1,
                        "hostapi_name": "unit",
                        "index": int(child_args.measurement_input_device),
                        "name": "unit input",
                    },
                    "source_output_device": {
                        "hostapi": 1,
                        "hostapi_name": "unit",
                        "index": int(child_args.source_output_device),
                        "name": "unit source",
                    },
                },
                "device_path_fingerprint": "2" * 64,
                "input_channels": int(child_args.input_channels),
                "output_channels": int(child_args.output_channels),
                "sample_rate_hz": int(child_args.sample_rate_hz),
            }
            child_payload = {
                "schema_version": 1,
                "fixture_kind": "headphone_earpiece_route_probe",
                "measurement_kind": "headphone_earpiece_route_probe_triage",
                "release_proof": False,
                "summary": {
                    "passed": True,
                    "quality_gates": [{"name": "unit_route_probe_passed", "passed": True}],
                    "release_proof": False,
                },
                "benchmarks": {
                    "headphone_earpiece_route_probe": {
                        "adapter_id": child_args.adapter_id,
                        "summary": child_summary,
                    }
                },
                "artifact_hashes": {},
                "artifact_paths": {},
            }
            child_report_path.write_text(json.dumps(child_payload), encoding="utf-8")
            return 0

        globals()["route_probe"] = fake_passing_route_probe
        try:
            sweep_result = sweep_routes(
                argparse.Namespace(
                    adapter_id=DEFAULT_ROUTE_PROBE_SWEEP_ADAPTER_ID,
                    allow_shared_output_device=False,
                    channel_config=[(1, 2)],
                    duration_s=0.05,
                    hostapi=[],
                    include_cross_hostapi=False,
                    lead_s=0.0,
                    max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                    max_attempts=1,
                    max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                    max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                    max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                    max_triples=1,
                    min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                    min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                    output_dir=root / "route-sweep-out",
                    playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                    run_id=DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID,
                    sample_rate_hz=[sample_rate_hz],
                    score_warning_only=False,
                    tail_s=0.0,
                    triple=[("1", "2", "3")],
                )
            )
        finally:
            globals()["route_probe"] = original_route_probe
        if sweep_result != 0:
            raise RuntimeError("expected route probe sweep self-test fixture to pass")
        sweep_report_path = (
            root
            / "route-sweep-out"
            / "runs"
            / DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID
            / "headphone-route-probe-sweep-report.json"
        )
        sweep_report = json.loads(sweep_report_path.read_text(encoding="utf-8"))
        if sweep_report.get("release_proof") is not False:
            raise RuntimeError("route probe sweep must not set release_proof")
        if not bool(sweep_report.get("summary", {}).get("triage_candidate_found")):
            raise RuntimeError("expected route probe sweep self-test to find a candidate")
        json.dumps(sweep_report, allow_nan=False)
        original_portaudio_device_identity = globals()["portaudio_device_identity"]
        original_record_playback = globals()["record_playback"]

        def fake_portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
            index = int(device) if device is not None and str(device).isdigit() else 99
            return {
                "default": device is None,
                "default_samplerate": float(sample_rate_hz),
                "hostapi": 1,
                "hostapi_name": "unit",
                "index": index,
                "max_input_channels": 1 if kind == "input" else 0,
                "max_output_channels": 0 if kind == "input" else 2,
                "name": f"unit {kind} {index}",
                "requested_device": device,
            }

        def fake_silent_record_playback(
            playback: np.ndarray,
            *,
            sample_rate_hz: int,
            input_device: int | str | None,
            output_device: int | str | None,
            input_channels: int,
        ) -> tuple[np.ndarray, float]:
            return np.zeros(int(playback.shape[0]), dtype=np.float32), 0.001

        silent_report_path = (
            root
            / "route-out"
            / "runs"
            / "silent-route"
            / "headphone-route-probe-report.json"
        )
        silent_report_path.parent.mkdir(parents=True, exist_ok=True)
        silent_report_path.write_text('{"stale": true}\n', encoding="utf-8")
        globals()["portaudio_device_identity"] = fake_portaudio_device_identity
        globals()["record_playback"] = fake_silent_record_playback
        try:
            silent_result = route_probe(
                argparse.Namespace(
                    adapter_id=DEFAULT_ROUTE_PROBE_ADAPTER_ID,
                    allow_shared_output_device=False,
                    duration_s=0.05,
                    headphone_output_device="3",
                    input_channels=1,
                    lead_s=0.0,
                    max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                    max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                    max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                    max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                    measurement_input_device="1",
                    min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                    min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                    output_channels=2,
                    output_dir=root / "route-out",
                    playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                    run_id="silent-route",
                    sample_rate_hz=sample_rate_hz,
                    score_warning_only=True,
                    source_output_device="2",
                    tail_s=0.0,
                )
            )
        finally:
            globals()["portaudio_device_identity"] = original_portaudio_device_identity
            globals()["record_playback"] = original_record_playback
        if silent_result != 0:
            raise RuntimeError("warning-only silent route probe self-test should return 0")
        silent_report = json.loads(silent_report_path.read_text(encoding="utf-8"))
        if silent_report.get("stale"):
            raise RuntimeError("silent route probe should replace stale reports")
        if bool(silent_report.get("summary", {}).get("passed")):
            raise RuntimeError("expected silent route probe self-test fixture to fail")
        json.dumps(silent_report, allow_nan=False)
        preflight_report_path = (
            root
            / "route-out"
            / "runs"
            / "preflight-failure"
            / "headphone-route-probe-report.json"
        )
        preflight_report_path.parent.mkdir(parents=True, exist_ok=True)
        preflight_report_path.write_text('{"stale": true}\n', encoding="utf-8")

        def fake_failing_portaudio_device_identity(device: int | str | None, *, kind: str) -> dict[str, Any]:
            raise ValueError("unit preflight failure")

        globals()["portaudio_device_identity"] = fake_failing_portaudio_device_identity
        try:
            try:
                route_probe(
                    argparse.Namespace(
                        adapter_id=DEFAULT_ROUTE_PROBE_ADAPTER_ID,
                        allow_shared_output_device=False,
                        duration_s=0.05,
                        headphone_output_device="3",
                        input_channels=1,
                        lead_s=0.0,
                        max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                        max_peak_dbfs=DEFAULT_MAX_PEAK_DBFS,
                        max_route_probe_clipped_samples=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
                        max_route_probe_distortion_db=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
                        measurement_input_device="1",
                        min_route_probe_correlation=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
                        min_route_probe_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                        output_channels=2,
                        output_dir=root / "route-out",
                        playback_gain_db=DEFAULT_PLAYBACK_GAIN_DB,
                        run_id="preflight-failure",
                        sample_rate_hz=sample_rate_hz,
                        score_warning_only=True,
                        source_output_device="2",
                        tail_s=0.0,
                    )
                )
            except ValueError:
                pass
            else:
                raise RuntimeError("expected route probe preflight self-test fixture to raise")
        finally:
            globals()["portaudio_device_identity"] = original_portaudio_device_identity
        if preflight_report_path.exists():
            raise RuntimeError("route probe preflight failure should remove stale reports")

        class FakePreflightSoundDevice:
            default = argparse.Namespace(device=(0, 2))

            def __init__(self) -> None:
                self._hostapis = [{"name": "Windows WASAPI", "device_count": 3}]
                self._devices = [
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 0,
                        "max_input_channels": 1,
                        "max_output_channels": 0,
                        "name": "USB Lavalier Ear Mic",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 1,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Speakers (SoundWire Speakers)",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 2,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Headphones (WH-1000XM6)",
                    },
                ]

            def query_devices(self) -> list[dict[str, Any]]:
                return [dict(device) for device in self._devices]

            def query_hostapis(self, index: int | None = None) -> Any:
                if index is None:
                    return [dict(hostapi) for hostapi in self._hostapis]
                return dict(self._hostapis[int(index)])

        preflight_args = argparse.Namespace(
            adapter_id=DEFAULT_PREFLIGHT_ADAPTER_ID,
            allow_shared_output_device=False,
            confirm_physical_listener_ear_input=False,
            hostapi=[],
            include_cross_hostapi=False,
            input_channels=1,
            json=False,
            max_triples=DEFAULT_ROUTE_PROBE_SWEEP_MAX_TRIPLES,
            output_channels=2,
            output_dir=root / "preflight-out",
            run_id=DEFAULT_PREFLIGHT_RUN_ID,
            sample_rate_hz=48000,
            selected_route=None,
        )
        preflight_report = build_headphone_preflight_report(FakePreflightSoundDevice(), preflight_args)
        if preflight_report.get("release_proof") is not False:
            raise RuntimeError("headphone preflight must not set release_proof")
        if preflight_report.get("fixture_kind") == FIXTURE_KIND:
            raise RuntimeError("headphone preflight must not use release fixture_kind")
        if bool(preflight_report.get("summary", {}).get("planning_passed")):
            raise RuntimeError("preflight must require physical listener-ear input confirmation before planning passes")
        if (
            preflight_report.get("summary", {}).get("recommended_path")
            != "guided_capture_possible_after_physical_input_confirmation"
        ):
            raise RuntimeError("expected fake headphone preflight to require physical input confirmation")
        fake_candidates = preflight_report.get("benchmarks", {}).get("headphone_earpiece_preflight", {}).get(
            "candidate_route_triples",
            [],
        )
        if not fake_candidates:
            raise RuntimeError("expected fake headphone preflight to list candidate routes")
        fake_first_candidate = fake_candidates[0]
        if "headphone_output_candidate" not in fake_first_candidate.get("headphone_roles", []):
            raise RuntimeError("headphone preflight should rank headphone-labeled outputs into the headphone slot")
        if "source_output_candidate" not in fake_first_candidate.get("source_roles", []):
            raise RuntimeError("headphone preflight should rank source-labeled outputs into the source slot")
        commands = preflight_report.get("benchmarks", {}).get("headphone_earpiece_preflight", {}).get(
            "recommended_commands",
            {},
        )
        if "capture" in commands:
            raise RuntimeError("preflight must not emit capture commands before physical input confirmation")
        if "--selected-route 0:1:2" not in commands.get("confirm_physical_input_preflight", ""):
            raise RuntimeError("physical input confirmation command must bind the selected route")
        preflight_markdown = render_headphone_preflight_markdown(
            preflight_report,
            root / "preflight-out" / DEFAULT_PREFLIGHT_REPORT,
        )
        if "No audio was played or recorded" not in preflight_markdown:
            raise RuntimeError("headphone preflight markdown should state that no audio was played")
        json.dumps(preflight_report, allow_nan=False)

        preflight_args.confirm_physical_listener_ear_input = True
        unbound_confirmed_preflight_report = build_headphone_preflight_report(
            FakePreflightSoundDevice(),
            preflight_args,
        )
        unbound_confirmed_commands = unbound_confirmed_preflight_report.get("benchmarks", {}).get(
            "headphone_earpiece_preflight",
            {},
        ).get("recommended_commands", {})
        if bool(unbound_confirmed_preflight_report.get("summary", {}).get("planning_passed")):
            raise RuntimeError("confirmed headphone preflight must require a bound selected route")
        if "capture" in unbound_confirmed_commands:
            raise RuntimeError("unbound physical confirmation must not emit guided capture")
        preflight_args.selected_route = ("0", "1", "2")
        confirmed_preflight_report = build_headphone_preflight_report(
            FakePreflightSoundDevice(),
            preflight_args,
        )
        if not bool(confirmed_preflight_report.get("summary", {}).get("planning_passed")):
            raise RuntimeError("expected confirmed fake headphone preflight to pass planning gates")
        if confirmed_preflight_report.get("summary", {}).get("recommended_path") != "guided_capture_possible":
            raise RuntimeError("expected confirmed fake headphone preflight to recommend guided capture")
        confirmed_commands = confirmed_preflight_report.get("benchmarks", {}).get(
            "headphone_earpiece_preflight",
            {},
        ).get("recommended_commands", {})
        if "capture" not in confirmed_commands:
            raise RuntimeError("confirmed headphone preflight should emit guided capture command")
        if "--preflight-report" not in confirmed_commands["capture"]:
            raise RuntimeError("confirmed headphone preflight capture command should include preflight report")
        confirmed_preflight_path = root / "confirmed-headphone-preflight-report.json"
        confirmed_preflight_path.write_text(
            json.dumps(confirmed_preflight_report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        binding = capture_preflight_binding(
            preflight_report=confirmed_preflight_path,
            measurement_input_device="0",
            source_output_device="1",
            headphone_output_device="2",
            sample_rate_hz=48000,
            input_channels=1,
            output_channels=2,
        )
        if not bool(binding.get("bound")) or binding.get("selected_route") != "0:1:2":
            raise RuntimeError("confirmed headphone preflight should bind capture to selected route")
        matching_device_info = {
            "measurement_input_device": {
                "hostapi": 0,
                "hostapi_name": "Windows WASAPI",
                "index": 0,
                "name": "USB Lavalier Ear Mic",
            },
            "source_output_device": {
                "hostapi": 0,
                "hostapi_name": "Windows WASAPI",
                "index": 1,
                "name": "Speakers (SoundWire Speakers)",
            },
            "headphone_output_device": {
                "hostapi": 0,
                "hostapi_name": "Windows WASAPI",
                "index": 2,
                "name": "Headphones (WH-1000XM6)",
            },
        }
        if preflight_binding_device_mismatches(binding, matching_device_info):
            raise RuntimeError("preflight binding should accept unchanged device identities")
        changed_device_info = json.loads(json.dumps(matching_device_info))
        changed_device_info["source_output_device"]["name"] = "Different Speakers"
        if not preflight_binding_device_mismatches(binding, changed_device_info):
            raise RuntimeError("preflight binding should detect changed device identities")
        try:
            capture_preflight_binding(
                preflight_report=confirmed_preflight_path,
                measurement_input_device="9",
                source_output_device="1",
                headphone_output_device="2",
                sample_rate_hz=48000,
                input_channels=1,
                output_channels=2,
            )
        except ValueError as exc:
            if "do not match preflight selected_route" not in str(exc):
                raise RuntimeError("preflight binding route mismatch should be explicit") from exc
        else:
            raise RuntimeError("preflight binding must reject route mismatch")
        json.dumps(confirmed_preflight_report, allow_nan=False)

        class FakeBuiltinPreflightSoundDevice(FakePreflightSoundDevice):
            def __init__(self) -> None:
                self._hostapis = [{"name": "Windows WASAPI", "device_count": 3}]
                self._devices = [
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 0,
                        "max_input_channels": 1,
                        "max_output_channels": 0,
                        "name": "Input (SoundWire Microphone)",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 1,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Speakers (Realtek Audio)",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 2,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Headphones (WH-1000XM6)",
                    },
                ]

        builtin_args = argparse.Namespace(**vars(preflight_args))
        builtin_args.selected_route = ("0", "1", "2")
        builtin_args.confirm_physical_listener_ear_input = True
        builtin_preflight_report = build_headphone_preflight_report(
            FakeBuiltinPreflightSoundDevice(),
            builtin_args,
        )
        builtin_summary = builtin_preflight_report.get("summary", {})
        if int(builtin_summary.get("capture_ready_route_triple_count") or 0) != 0:
            raise RuntimeError("builtin laptop-style microphone must remain route triage only")
        if builtin_summary.get("recommended_path") != "route_probe_triage_only_manual_listener_ear_capture_required":
            raise RuntimeError("builtin laptop-style microphone should recommend triage only")
        builtin_commands = builtin_preflight_report.get("benchmarks", {}).get(
            "headphone_earpiece_preflight",
            {},
        ).get("recommended_commands", {})
        if "capture" in builtin_commands:
            raise RuntimeError("builtin laptop-style microphone must not emit guided capture")
        if "route_probe_triage_only" not in builtin_commands:
            raise RuntimeError("builtin laptop-style microphone should still emit route triage command")
        builtin_preflight_path = root / "builtin-headphone-preflight-report.json"
        builtin_preflight_path.write_text(
            json.dumps(builtin_preflight_report, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        try:
            capture_preflight_binding(
                preflight_report=builtin_preflight_path,
                measurement_input_device="0",
                source_output_device="1",
                headphone_output_device="2",
                sample_rate_hz=48000,
                input_channels=1,
                output_channels=2,
            )
        except ValueError as exc:
            if "preflight recommended_path is not guided_capture_possible" not in str(exc):
                raise RuntimeError("builtin preflight binding rejection should explain guided capture path") from exc
        else:
            raise RuntimeError("builtin laptop-style preflight must not bind guided capture")
        json.dumps(builtin_preflight_report, allow_nan=False)

        class FakeAmbiguousPreflightSoundDevice(FakePreflightSoundDevice):
            def __init__(self) -> None:
                self._hostapis = [{"name": "Windows WASAPI", "device_count": 3}]
                self._devices = [
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 0,
                        "max_input_channels": 1,
                        "max_output_channels": 0,
                        "name": "USB Lavalier Ear Mic",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 1,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Headphones Speakers Combo",
                    },
                    {
                        "default_samplerate": 48000.0,
                        "hostapi": 0,
                        "index": 2,
                        "max_input_channels": 0,
                        "max_output_channels": 2,
                        "name": "Headphones Speakers Combo 2",
                    },
                ]

        ambiguous_args = argparse.Namespace(**vars(preflight_args))
        ambiguous_args.selected_route = ("0", "1", "2")
        ambiguous_args.confirm_physical_listener_ear_input = True
        ambiguous_preflight_report = build_headphone_preflight_report(
            FakeAmbiguousPreflightSoundDevice(),
            ambiguous_args,
        )
        ambiguous_summary = ambiguous_preflight_report.get("summary", {})
        if int(ambiguous_summary.get("role_aligned_route_triple_count") or 0) <= 0:
            raise RuntimeError("ambiguous preflight fixture should still form role-aligned routes")
        if int(ambiguous_summary.get("capture_ready_route_triple_count") or 0) != 0:
            raise RuntimeError("cross-labeled source/headphone outputs must not be capture-ready")
        ambiguous_commands = ambiguous_preflight_report.get("benchmarks", {}).get(
            "headphone_earpiece_preflight",
            {},
        ).get("recommended_commands", {})
        if "capture" in ambiguous_commands:
            raise RuntimeError("ambiguous source/headphone route must not emit guided capture")
        json.dumps(ambiguous_preflight_report, allow_nan=False)

        virtual_result = virtual_lab(
            argparse.Namespace(
                adapter_id=DEFAULT_VIRTUAL_LAB_ADAPTER_ID,
                duration_s=1.25,
                lead_s=0.1,
                max_alignment_lag_ms=DEFAULT_MAX_ALIGNMENT_LAG_MS,
                max_translated_distortion_db=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
                min_source_isolation_db=DEFAULT_MIN_SOURCE_ISOLATION_DB,
                min_source_open_correlation=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
                min_source_open_dbfs=DEFAULT_MIN_SOURCE_OPEN_DBFS,
                min_translated_correlation=DEFAULT_MIN_TRANSLATED_CORRELATION,
                min_translated_dbfs=DEFAULT_MIN_TRANSLATED_DBFS,
                noise_dbfs=-72.0,
                output_dir=root / "virtual-out",
                reflection_db=-60.0,
                run_id=DEFAULT_VIRTUAL_LAB_RUN_ID,
                sample_rate_hz=sample_rate_hz,
                score_warning_only=False,
                source_isolation_db=18.0,
                source_lag_ms=0.0,
                source_open_gain_db=-3.0,
                tail_s=0.1,
                translated_gain_db=-3.0,
                translated_lag_ms=0.0,
            )
        )
        if virtual_result != 0:
            raise RuntimeError("expected virtual listener-ear lab self-test fixture to pass")
        virtual_report_path = (
            root
            / "virtual-out"
            / "runs"
            / DEFAULT_VIRTUAL_LAB_RUN_ID
            / "headphone-virtual-lab-report.json"
        )
        virtual_report = json.loads(virtual_report_path.read_text(encoding="utf-8"))
        if virtual_report.get("release_proof") is not False:
            raise RuntimeError("virtual listener-ear lab must not set release_proof")
        if virtual_report.get("fixture_kind") == FIXTURE_KIND:
            raise RuntimeError("virtual listener-ear lab must not use release fixture_kind")
        if not bool(virtual_report.get("summary", {}).get("passed")):
            raise RuntimeError("expected virtual listener-ear lab quality gates to pass")
        json.dumps(virtual_report, allow_nan=False)
    print("headphone/earpiece isolation contract self-test PASS")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score measured headphone/earpiece source isolation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list-devices", help="list PortAudio devices for guided host capture")
    subparsers.add_parser("self-test", help="validate scoring gates without external artifacts")
    preflight_parser = subparsers.add_parser(
        "preflight",
        help="inspect host audio devices and write a no-audio headphone isolation readiness report",
    )
    preflight_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    preflight_parser.add_argument("--run-id", default=DEFAULT_PREFLIGHT_RUN_ID)
    preflight_parser.add_argument("--adapter-id", default=DEFAULT_PREFLIGHT_ADAPTER_ID)
    preflight_parser.add_argument("--input-channels", type=int, default=DEFAULT_CAPTURE_INPUT_CHANNELS)
    preflight_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    preflight_parser.add_argument("--sample-rate-hz", type=int, default=48000)
    preflight_parser.add_argument("--hostapi", action="append", default=[])
    preflight_parser.add_argument("--max-triples", type=int, default=DEFAULT_ROUTE_PROBE_SWEEP_MAX_TRIPLES)
    preflight_parser.add_argument(
        "--allow-shared-output-device",
        action="store_true",
        help="allow source and headphone outputs to resolve to the same PortAudio device for diagnostics",
    )
    preflight_parser.add_argument("--include-cross-hostapi", action="store_true")
    preflight_parser.add_argument(
        "--confirm-physical-listener-ear-input",
        action="store_true",
        help="confirm the selected/input candidate is physically positioned at the listener-ear measurement point",
    )
    preflight_parser.add_argument(
        "--selected-route",
        type=parse_route_triple,
        help="bind physical confirmation to INPUT:SOURCE_OUTPUT:HEADPHONE_OUTPUT from the preflight report",
    )
    preflight_parser.add_argument("--json", action="store_true")
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
    manual_parser = subparsers.add_parser(
        "prepare-manual",
        help="prepare source/translated reference WAVs and a manifest for external listener-ear recording",
    )
    manual_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    manual_parser.add_argument("--run-id", default=DEFAULT_MANUAL_KIT_RUN_ID)
    manual_parser.add_argument("--score-run-id", default=DEFAULT_RUN_ID)
    manual_parser.add_argument("--adapter-id", default=DEFAULT_MANUAL_KIT_ADAPTER_ID)
    manual_parser.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    manual_parser.add_argument("--source-reference", type=Path)
    manual_parser.add_argument("--translated-playback-reference", type=Path)
    manual_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    manual_parser.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    manual_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    manual_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    manual_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    manual_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    manual_parser.add_argument("--max-reference-duration-s", type=float, default=8.0)
    manual_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    check_manual_parser = subparsers.add_parser(
        "check-manual",
        help="check whether manual listener-ear recordings are ready to pass into score",
    )
    check_manual_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR
        / "runs"
        / DEFAULT_MANUAL_KIT_RUN_ID
        / "manual-recording-manifest.json",
    )
    check_manual_parser.add_argument("--report", type=Path)
    check_manual_parser.add_argument("--markdown-report", type=Path)
    check_manual_parser.add_argument("--headphone-device-label")
    check_manual_parser.add_argument("--isolation-fixture-label")
    check_manual_parser.add_argument("--measurement-microphone-label")
    check_manual_parser.add_argument("--json", action="store_true")
    check_manual_parser.add_argument("--score-warning-only", action="store_true")
    play_manual_parser = subparsers.add_parser(
        "play-manual",
        help="play manual-kit reference WAVs through source/headphone outputs for external recording",
    )
    play_manual_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR
        / "runs"
        / DEFAULT_MANUAL_KIT_RUN_ID
        / "manual-recording-manifest.json",
    )
    play_manual_parser.add_argument("--log", type=Path)
    play_manual_parser.add_argument(
        "--take",
        choices=["all", *MANUAL_PLAYBACK_TAKES.keys()],
        action="append",
        help="manual take to play; defaults to all three takes",
    )
    play_manual_parser.add_argument("--source-output-device")
    play_manual_parser.add_argument("--headphone-output-device")
    play_manual_parser.add_argument("--output-device")
    play_manual_parser.add_argument(
        "--allow-default-output",
        action="store_true",
        help="allow unspecified source/headphone routes to use the system default output",
    )
    play_manual_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    play_manual_parser.add_argument("--countdown-s", type=float, default=3.0)
    play_manual_parser.add_argument("--inter-take-pause-s", type=float, default=1.0)
    play_manual_parser.add_argument("--repeat", type=int, default=1)
    play_manual_parser.add_argument("--non-interactive", action="store_true")
    play_manual_parser.add_argument("--dry-run", action="store_true")
    import_manual_parser = subparsers.add_parser(
        "import-manual",
        help="import externally recorded listener-ear WAVs into the manual kit paths",
    )
    import_manual_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR
        / "runs"
        / DEFAULT_MANUAL_KIT_RUN_ID
        / "manual-recording-manifest.json",
    )
    import_manual_parser.add_argument("--log", type=Path)
    import_manual_parser.add_argument("--status-report", type=Path)
    import_manual_parser.add_argument("--source-open-ear-recording", type=Path, required=True)
    import_manual_parser.add_argument("--source-isolated-ear-recording", type=Path, required=True)
    import_manual_parser.add_argument("--translated-headphone-recording", type=Path, required=True)
    import_manual_parser.add_argument("--headphone-device-label")
    import_manual_parser.add_argument("--isolation-fixture-label")
    import_manual_parser.add_argument("--measurement-microphone-label")
    import_manual_parser.add_argument("--allow-downmix", action="store_true")
    import_manual_parser.add_argument("--allow-overwrite", action="store_true")
    import_manual_parser.add_argument("--skip-check", action="store_true")
    import_manual_parser.add_argument("--dry-run", action="store_true")
    score_manual_parser = subparsers.add_parser(
        "score-manual",
        help="validate a manual recording manifest and score its listener-ear WAV artifacts",
    )
    score_manual_parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_OUTPUT_DIR
        / "runs"
        / DEFAULT_MANUAL_KIT_RUN_ID
        / "manual-recording-manifest.json",
    )
    score_manual_parser.add_argument("--status-report", type=Path)
    score_manual_parser.add_argument("--output-dir", type=Path)
    score_manual_parser.add_argument("--run-id")
    score_manual_parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    score_manual_parser.add_argument("--headphone-device-label", required=True)
    score_manual_parser.add_argument("--isolation-fixture-label", required=True)
    score_manual_parser.add_argument("--measurement-microphone-label", required=True)
    score_manual_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    score_manual_parser.add_argument("--procedure-note", default="external listener-ear manual recording")
    score_manual_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    score_manual_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    score_manual_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    score_manual_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    score_manual_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    score_manual_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    score_manual_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    score_manual_parser.add_argument("--score-warning-only", action="store_true")
    capture_parser = subparsers.add_parser(
        "capture",
        help="guide a host PortAudio measurement and then score the captured WAV artifacts",
    )
    capture_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    capture_parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    capture_parser.add_argument("--adapter-id", default=DEFAULT_ADAPTER_ID)
    capture_parser.add_argument("--tts-report", type=Path, default=DEFAULT_TTS_REPORT)
    capture_parser.add_argument("--source-reference", type=Path)
    capture_parser.add_argument("--translated-playback-reference", type=Path)
    capture_parser.add_argument("--measurement-input-device", required=True)
    capture_parser.add_argument("--source-output-device", required=True)
    capture_parser.add_argument("--headphone-output-device", required=True)
    capture_parser.add_argument(
        "--preflight-report",
        type=Path,
        required=True,
        help="passing preflight report generated with --selected-route and physical listener-ear confirmation",
    )
    capture_parser.add_argument("--input-channels", type=int, default=DEFAULT_CAPTURE_INPUT_CHANNELS)
    capture_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    capture_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    capture_parser.add_argument("--gap-s", type=float, default=DEFAULT_GAP_S)
    capture_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    capture_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    capture_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    capture_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    capture_parser.add_argument("--max-reference-duration-s", type=float, default=8.0)
    capture_parser.add_argument("--headphone-device-label", required=True)
    capture_parser.add_argument("--isolation-fixture-label", required=True)
    capture_parser.add_argument("--measurement-microphone-label", required=True)
    capture_parser.add_argument(
        "--min-measurement-duration-s",
        type=float,
        default=DEFAULT_MIN_MEASUREMENT_DURATION_S,
    )
    capture_parser.add_argument("--procedure-note", default="guided host listener-ear measurement")
    capture_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    capture_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    capture_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    capture_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    capture_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    capture_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    capture_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    capture_parser.add_argument("--score-warning-only", action="store_true")
    capture_parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="print measurement steps without waiting for Enter before each capture",
    )
    probe_parser = subparsers.add_parser(
        "probe-route",
        help="triage whether source/headphone output routes can open and be heard by the measurement input",
    )
    probe_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    probe_parser.add_argument("--run-id", default=DEFAULT_ROUTE_PROBE_RUN_ID)
    probe_parser.add_argument("--adapter-id", default=DEFAULT_ROUTE_PROBE_ADAPTER_ID)
    probe_parser.add_argument("--measurement-input-device", required=True)
    probe_parser.add_argument("--source-output-device", required=True)
    probe_parser.add_argument("--headphone-output-device", required=True)
    probe_parser.add_argument("--input-channels", type=int, default=DEFAULT_CAPTURE_INPUT_CHANNELS)
    probe_parser.add_argument("--output-channels", type=int, default=DEFAULT_CAPTURE_OUTPUT_CHANNELS)
    probe_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    probe_parser.add_argument("--duration-s", type=float, default=DEFAULT_ROUTE_PROBE_DURATION_S)
    probe_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    probe_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    probe_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    probe_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    probe_parser.add_argument("--min-route-probe-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    probe_parser.add_argument(
        "--min-route-probe-correlation",
        type=float,
        default=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
    )
    probe_parser.add_argument(
        "--max-route-probe-distortion-db",
        type=float,
        default=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
    )
    probe_parser.add_argument(
        "--max-route-probe-clipped-samples",
        type=int,
        default=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
    )
    probe_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    probe_parser.add_argument(
        "--allow-shared-output-device",
        action="store_true",
        help="allow source and headphone outputs to resolve to the same PortAudio device for explicit multi-channel hardware tests",
    )
    probe_parser.add_argument("--score-warning-only", action="store_true")
    sweep_parser = subparsers.add_parser(
        "sweep-routes",
        help="try bounded listener-ear input, source output, and headphone output route probes",
    )
    sweep_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    sweep_parser.add_argument("--run-id", default=DEFAULT_ROUTE_PROBE_SWEEP_RUN_ID)
    sweep_parser.add_argument("--adapter-id", default=DEFAULT_ROUTE_PROBE_SWEEP_ADAPTER_ID)
    sweep_parser.add_argument("--sample-rate-hz", type=int, action="append")
    sweep_parser.add_argument("--duration-s", type=float, default=DEFAULT_ROUTE_PROBE_DURATION_S)
    sweep_parser.add_argument("--channel-config", type=parse_channel_config, action="append")
    sweep_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    sweep_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    sweep_parser.add_argument("--playback-gain-db", type=float, default=DEFAULT_PLAYBACK_GAIN_DB)
    sweep_parser.add_argument("--max-peak-dbfs", type=float, default=DEFAULT_MAX_PEAK_DBFS)
    sweep_parser.add_argument("--min-route-probe-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    sweep_parser.add_argument(
        "--min-route-probe-correlation",
        type=float,
        default=DEFAULT_MIN_ROUTE_PROBE_CORRELATION,
    )
    sweep_parser.add_argument(
        "--max-route-probe-distortion-db",
        type=float,
        default=DEFAULT_MAX_ROUTE_PROBE_DISTORTION_DB,
    )
    sweep_parser.add_argument(
        "--max-route-probe-clipped-samples",
        type=int,
        default=DEFAULT_MAX_ROUTE_PROBE_CLIPPED_SAMPLES,
    )
    sweep_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    sweep_parser.add_argument(
        "--allow-shared-output-device",
        action="store_true",
        help="allow source and headphone outputs to resolve to the same PortAudio device",
    )
    sweep_parser.add_argument("--max-triples", type=int, default=DEFAULT_ROUTE_PROBE_SWEEP_MAX_TRIPLES)
    sweep_parser.add_argument("--max-attempts", type=int, default=DEFAULT_ROUTE_PROBE_SWEEP_MAX_ATTEMPTS)
    sweep_parser.add_argument("--hostapi", action="append", default=[])
    sweep_parser.add_argument("--include-cross-hostapi", action="store_true")
    sweep_parser.add_argument("--triple", type=parse_route_triple, action="append")
    sweep_parser.add_argument("--score-warning-only", action="store_true")
    virtual_parser = subparsers.add_parser(
        "virtual-lab",
        help="generate a deterministic synthetic listener-ear lab report that is never release proof",
    )
    virtual_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    virtual_parser.add_argument("--run-id", default=DEFAULT_VIRTUAL_LAB_RUN_ID)
    virtual_parser.add_argument("--adapter-id", default=DEFAULT_VIRTUAL_LAB_ADAPTER_ID)
    virtual_parser.add_argument("--sample-rate-hz", type=int, default=DEFAULT_SAMPLE_RATE_HZ)
    virtual_parser.add_argument("--duration-s", type=float, default=2.5)
    virtual_parser.add_argument("--lead-s", type=float, default=DEFAULT_LEAD_S)
    virtual_parser.add_argument("--tail-s", type=float, default=DEFAULT_TAIL_S)
    virtual_parser.add_argument("--source-open-gain-db", type=float, default=-3.0)
    virtual_parser.add_argument("--source-isolation-db", type=float, default=18.0)
    virtual_parser.add_argument("--translated-gain-db", type=float, default=-3.0)
    virtual_parser.add_argument("--source-lag-ms", type=float, default=0.0)
    virtual_parser.add_argument("--translated-lag-ms", type=float, default=0.0)
    virtual_parser.add_argument("--noise-dbfs", type=float, default=-72.0)
    virtual_parser.add_argument("--reflection-db", type=float, default=-60.0)
    virtual_parser.add_argument("--min-source-open-dbfs", type=float, default=DEFAULT_MIN_SOURCE_OPEN_DBFS)
    virtual_parser.add_argument("--min-translated-dbfs", type=float, default=DEFAULT_MIN_TRANSLATED_DBFS)
    virtual_parser.add_argument(
        "--min-source-open-correlation",
        type=float,
        default=DEFAULT_MIN_SOURCE_OPEN_CORRELATION,
    )
    virtual_parser.add_argument(
        "--min-translated-correlation",
        type=float,
        default=DEFAULT_MIN_TRANSLATED_CORRELATION,
    )
    virtual_parser.add_argument(
        "--min-source-isolation-db",
        type=float,
        default=DEFAULT_MIN_SOURCE_ISOLATION_DB,
    )
    virtual_parser.add_argument(
        "--max-translated-distortion-db",
        type=float,
        default=DEFAULT_MAX_TRANSLATED_DISTORTION_DB,
    )
    virtual_parser.add_argument("--max-alignment-lag-ms", type=float, default=DEFAULT_MAX_ALIGNMENT_LAG_MS)
    virtual_parser.add_argument("--score-warning-only", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "sweep-routes":
        if args.sample_rate_hz is None:
            args.sample_rate_hz = list(DEFAULT_ROUTE_PROBE_SWEEP_SAMPLE_RATES)
        if args.channel_config is None:
            args.channel_config = list(DEFAULT_ROUTE_PROBE_SWEEP_CHANNEL_CONFIGS)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "list-devices":
        return list_devices()
    if args.command == "self-test":
        return self_test()
    if args.command == "preflight":
        return headphone_preflight(args)
    if args.command == "score":
        return score(args)
    if args.command == "prepare-manual":
        return prepare_manual_kit(args)
    if args.command == "check-manual":
        return check_manual_recordings(args)
    if args.command == "play-manual":
        return play_manual_references(args)
    if args.command == "import-manual":
        return import_manual_recordings(args)
    if args.command == "score-manual":
        return score_manual_recordings(args)
    if args.command == "capture":
        return capture(args)
    if args.command == "probe-route":
        return route_probe(args)
    if args.command == "sweep-routes":
        return sweep_routes(args)
    if args.command == "virtual-lab":
        return virtual_lab(args)
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
