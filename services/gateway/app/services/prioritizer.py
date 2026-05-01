from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess

from app.models import SessionMode, SpeakerState


@dataclass(frozen=True)
class PriorityWeights:
    active_bonus: float
    inactive_penalty: float
    user_lock_bonus: float
    front_facing_bonus: float
    persistence_multiplier: float


# Derived mirror of `crates/focus_engine/src/lib.rs::ModeFocusPolicy::for_mode`.
# Keep this table aligned with the Rust authority and the shared parity vectors in
# `crates/focus_engine/testdata/prioritization_vectors.tsv`.
WEIGHTS_BY_MODE: dict[SessionMode, PriorityWeights] = {
    SessionMode.UNSPECIFIED: PriorityWeights(0.25, 1.0, 0.3, 0.1, 0.5),
    SessionMode.FOCUS: PriorityWeights(0.4, 1.1, 0.45, 0.2, 1.0),
    SessionMode.CROWD: PriorityWeights(0.2, 0.8, 0.2, 0.1, 0.6),
    SessionMode.LOCKED: PriorityWeights(0.3, 1.0, 0.9, 0.15, 0.8),
}

_SUPPORTED_PRIORITIZER_BACKENDS = {"auto", "python", "rust"}
_DEFAULT_RUST_RANKER_TIMEOUT_MS = 4_000
_RUST_RANKER_BUILD_TIMEOUT_SECONDS = 120


class PrioritizerRuntimeError(RuntimeError):
    """Raised when the Rust prioritizer bridge cannot satisfy a request."""


class PrioritizerRuntimeUnavailableError(PrioritizerRuntimeError):
    """Raised when the Rust bridge cannot be resolved or executed right now."""


class PrioritizerRuntimeProtocolError(PrioritizerRuntimeError):
    """Raised when the Rust bridge responds with invalid or inconsistent data."""


@dataclass(frozen=True)
class PrioritizerRuntimeSettings:
    backend: str
    rust_ranker_bin: str | None
    rust_ranker_timeout_ms: int


_resolved_rust_ranker_commands: dict[str | None, tuple[str, ...]] = {}


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _read_runtime_settings() -> PrioritizerRuntimeSettings:
    backend = os.getenv("LANGUAGE_GATEWAY_PRIORITIZER_BACKEND", "auto").strip().lower()
    if not backend:
        backend = "auto"
    if backend not in _SUPPORTED_PRIORITIZER_BACKENDS:
        supported = ", ".join(sorted(_SUPPORTED_PRIORITIZER_BACKENDS))
        raise ValueError(
            "LANGUAGE_GATEWAY_PRIORITIZER_BACKEND must be one of "
            f"{supported}, got {backend!r}"
        )

    raw_timeout = os.getenv(
        "LANGUAGE_GATEWAY_RUST_RANKER_TIMEOUT_MS",
        str(_DEFAULT_RUST_RANKER_TIMEOUT_MS),
    ).strip()
    try:
        rust_ranker_timeout_ms = int(raw_timeout)
    except ValueError as exc:
        raise ValueError(
            "LANGUAGE_GATEWAY_RUST_RANKER_TIMEOUT_MS must be an integer, "
            f"got {raw_timeout!r}"
        ) from exc

    if rust_ranker_timeout_ms <= 0:
        raise ValueError(
            "LANGUAGE_GATEWAY_RUST_RANKER_TIMEOUT_MS must be greater than zero, "
            f"got {rust_ranker_timeout_ms!r}"
        )

    rust_ranker_bin = os.getenv("LANGUAGE_GATEWAY_RUST_RANKER_BIN")
    if rust_ranker_bin is not None:
        rust_ranker_bin = rust_ranker_bin.strip() or None

    return PrioritizerRuntimeSettings(
        backend=backend,
        rust_ranker_bin=rust_ranker_bin,
        rust_ranker_timeout_ms=rust_ranker_timeout_ms,
    )


def _rust_ranker_binary_name() -> str:
    return "session_ranker.exe" if os.name == "nt" else "session_ranker"


def _rust_ranker_candidates(binary_override: str | None) -> list[Path]:
    if binary_override is not None:
        return [Path(binary_override).expanduser()]

    target_dir = os.getenv("CARGO_TARGET_DIR")
    if target_dir is None:
        root_target_dir = _workspace_root() / "target"
    else:
        root_target_dir = Path(target_dir).expanduser()

    binary_name = _rust_ranker_binary_name()
    return [
        root_target_dir / "debug" / binary_name,
        root_target_dir / "release" / binary_name,
    ]


def _resolve_rust_ranker_command(binary_override: str | None) -> tuple[str, ...] | None:
    cached_command = _resolved_rust_ranker_commands.get(binary_override)
    if cached_command is not None:
        return cached_command

    for candidate in _rust_ranker_candidates(binary_override):
        if candidate.is_file():
            command = (str(candidate),)
            _resolved_rust_ranker_commands[binary_override] = command
            return command

    cargo = shutil.which("cargo")
    if cargo is None:
        return None

    try:
        subprocess.run(
            [cargo, "build", "-q", "-p", "session_proto", "--bin", "session_ranker"],
            cwd=_workspace_root(),
            capture_output=True,
            check=True,
            text=True,
            timeout=_RUST_RANKER_BUILD_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, PermissionError, subprocess.SubprocessError):
        return None

    for candidate in _rust_ranker_candidates(binary_override):
        if candidate.is_file():
            command = (str(candidate),)
            _resolved_rust_ranker_commands[binary_override] = command
            return command
    return None


def _rust_ranker_payload(mode: SessionMode, speakers: list[SpeakerState]) -> dict[str, object]:
    return {
        "mode": mode.value,
        "speakers": [
            {
                "speaker_id": speaker.speaker_id,
                "display_name": speaker.display_name,
                "language_code": speaker.language_code,
                "priority": speaker.priority,
                "active": speaker.active,
                "is_locked": speaker.is_locked,
                "front_facing": speaker.front_facing,
                "persistence_bonus": speaker.persistence_bonus,
                "last_updated_unix_ms": speaker.last_updated_unix_ms,
            }
            for speaker in speakers
        ],
    }


def _invoke_rust_ranker(
    mode: SessionMode,
    speakers: list[SpeakerState],
    settings: PrioritizerRuntimeSettings,
) -> tuple[list[str], str | None]:
    command = _resolve_rust_ranker_command(settings.rust_ranker_bin)
    if command is None:
        raise PrioritizerRuntimeUnavailableError(
            "Rust prioritizer bridge is unavailable; build session_ranker or configure "
            "LANGUAGE_GATEWAY_RUST_RANKER_BIN"
        )

    payload = json.dumps(_rust_ranker_payload(mode, speakers))

    try:
        result = subprocess.run(
            [*command],
            capture_output=True,
            check=True,
            input=payload,
            text=True,
            timeout=settings.rust_ranker_timeout_ms / 1000,
        )
    except FileNotFoundError as exc:
        raise PrioritizerRuntimeUnavailableError(
            "Rust prioritizer bridge command was not found after resolution"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise PrioritizerRuntimeUnavailableError(
            "Rust prioritizer bridge timed out while ranking speakers"
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        detail = f": {stderr}" if stderr else ""
        raise PrioritizerRuntimeProtocolError(
            f"Rust prioritizer bridge failed while ranking speakers{detail}"
        ) from exc

    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PrioritizerRuntimeProtocolError(
            "Rust prioritizer bridge returned invalid JSON output"
        ) from exc

    ordered_speaker_ids = response.get("ordered_speaker_ids")
    top_speaker_id = response.get("top_speaker_id")

    if not isinstance(ordered_speaker_ids, list) or not all(
        isinstance(speaker_id, str) for speaker_id in ordered_speaker_ids
    ):
        raise PrioritizerRuntimeProtocolError(
            "Rust prioritizer bridge response did not include a valid ordered_speaker_ids list"
        )

    if top_speaker_id is not None and not isinstance(top_speaker_id, str):
        raise PrioritizerRuntimeProtocolError(
            "Rust prioritizer bridge response included an invalid top_speaker_id"
        )

    return ordered_speaker_ids, top_speaker_id


def _sort_speakers_python(speakers: list[SpeakerState], mode: SessionMode) -> list[SpeakerState]:
    return sorted(
        speakers,
        key=lambda speaker: (
            -score_speaker(speaker, mode),
            speaker.speaker_id,
        ),
    )


def _reorder_speakers(
    speakers: list[SpeakerState],
    ordered_speaker_ids: list[str],
) -> list[SpeakerState]:
    available = {speaker.speaker_id: speaker for speaker in speakers}
    if len(available) != len(speakers):
        raise PrioritizerRuntimeProtocolError(
            "speaker ids must be unique for Rust prioritizer ordering"
        )

    ordered: list[SpeakerState] = []
    for speaker_id in ordered_speaker_ids:
        speaker = available.pop(speaker_id, None)
        if speaker is None:
            raise PrioritizerRuntimeProtocolError(
                f"Rust prioritizer bridge returned unknown speaker id {speaker_id!r}"
            )
        ordered.append(speaker)

    if available:
        missing = ", ".join(sorted(available))
        raise PrioritizerRuntimeProtocolError(
            "Rust prioritizer bridge omitted ranked speakers: "
            f"{missing}"
        )

    return ordered


def score_speaker(speaker: SpeakerState, mode: SessionMode) -> float:
    weights = WEIGHTS_BY_MODE[mode]
    score = speaker.priority + (speaker.persistence_bonus * weights.persistence_multiplier)
    score += weights.active_bonus if speaker.active else -weights.inactive_penalty
    if speaker.is_locked:
        score += weights.user_lock_bonus
    if speaker.front_facing:
        score += weights.front_facing_bonus
    return score


def sort_speakers(speakers: list[SpeakerState], mode: SessionMode) -> list[SpeakerState]:
    settings = _read_runtime_settings()
    if settings.backend == "python":
        return _sort_speakers_python(speakers, mode)

    try:
        ordered_speaker_ids, _ = _invoke_rust_ranker(mode, speakers, settings)
        return _reorder_speakers(speakers, ordered_speaker_ids)
    except PrioritizerRuntimeUnavailableError:
        if settings.backend == "rust":
            raise
        return _sort_speakers_python(speakers, mode)


def build_session(session_id: str, mode: SessionMode, speakers: list[SpeakerState]) -> dict[str, object]:
    ordered = sort_speakers(speakers, mode)
    return {
        "session_id": session_id,
        "mode": mode,
        "speakers": ordered,
        "top_speaker_id": ordered[0].speaker_id if ordered else None,
    }


def _clear_runtime_bridge_caches() -> None:
    _resolved_rust_ranker_commands.clear()
