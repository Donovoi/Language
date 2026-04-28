from __future__ import annotations

from dataclasses import dataclass
from threading import Event, Lock, Thread, current_thread

from pydantic import BaseModel, ConfigDict, Field

from app.models import LaneStatus, SessionMode, SpeakerState
from app.services.session_store import SessionStore

_DEFAULT_INTERVAL_MS = 350
_SCENARIO_ID = "briefing"
_SUPPORTED_SCENARIOS = [_SCENARIO_ID]
_CONTROLLER_ATTR = "_mock_live_ingest_controller"


class MockLiveIngestStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    active: bool
    completed: bool
    scenario_id: str = Field(min_length=1)
    supported_scenarios: list[str] = Field(default_factory=lambda: list(_SUPPORTED_SCENARIOS))
    interval_ms: int | None = Field(default=None, ge=1)
    total_steps: int = Field(ge=0)
    applied_steps: int = Field(ge=0)
    remaining_steps: int = Field(ge=0)
    session_id: str = Field(min_length=1)
    mode: SessionMode
    top_speaker_id: str | None = None


class MockLiveIngestControlResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started: bool = False
    stopped: bool = False
    status: MockLiveIngestStatus


class MockLiveIngestAlreadyRunningError(RuntimeError):
    """Raised when a second live-ingest run is requested before the first stops."""


@dataclass(frozen=True)
class _SpeakerMutation:
    speaker_id: str
    updates: dict[str, object]


@dataclass(frozen=True)
class _SpeakerFrameStep:
    mutations: tuple[_SpeakerMutation, ...]
    mode: SessionMode | None = None


@dataclass(frozen=True)
class _ModeStep:
    mode: SessionMode


@dataclass(frozen=True)
class _LockStep:
    speaker_id: str
    is_locked: bool


_DemoStep = _SpeakerFrameStep | _ModeStep | _LockStep


def _speaker_mutation(speaker_id: str, **updates: object) -> _SpeakerMutation:
    return _SpeakerMutation(speaker_id=speaker_id, updates=updates)


class MockLiveIngestController:
    def __init__(self, store: SessionStore) -> None:
        self._store = store
        self._lock = Lock()
        self._interval_ms: int | None = None
        self._total_steps = 0
        self._applied_steps = 0
        self._active = False
        self._thread: Thread | None = None
        self._stop_event: Event | None = None

    def status(self) -> MockLiveIngestStatus:
        with self._lock:
            return self._build_status_locked()

    def start(
        self,
        *,
        mode: SessionMode = SessionMode.FOCUS,
        interval_ms: int = _DEFAULT_INTERVAL_MS,
    ) -> MockLiveIngestControlResponse:
        with self._lock:
            if self._active and self._thread is not None and self._thread.is_alive():
                raise MockLiveIngestAlreadyRunningError(
                    "A mock live ingest run is already active. Stop it before starting another one."
                )

            self._store.reset(mode)
            steps = _build_briefing_script(mode)
            self._interval_ms = interval_ms
            self._total_steps = len(steps)
            self._applied_steps = 0
            self._active = True
            self._stop_event = Event()
            worker = Thread(
                target=self._run_script,
                args=(steps,),
                name="mock-live-ingest",
                daemon=True,
            )
            self._thread = worker
            worker.start()
            return MockLiveIngestControlResponse(started=True, status=self._build_status_locked())

    def stop(self) -> MockLiveIngestControlResponse:
        with self._lock:
            stop_event = self._stop_event
            worker = self._thread
            was_active = self._active and worker is not None and worker.is_alive()

        if stop_event is not None:
            stop_event.set()

        if worker is not None:
            worker.join(timeout=1.0)

        with self._lock:
            self._active = False
            self._thread = None
            self._stop_event = None
            return MockLiveIngestControlResponse(stopped=was_active, status=self._build_status_locked())

    def _run_script(self, steps: tuple[_DemoStep, ...]) -> None:
        worker = current_thread()

        try:
            for step_index, step in enumerate(steps, start=1):
                stop_event = self._stop_event
                if stop_event is not None and step_index > 1 and stop_event.wait(self._interval_seconds):
                    return
                if stop_event is not None and step_index == 1 and stop_event.is_set():
                    return

                self._apply_step(step, step_index)
                with self._lock:
                    self._applied_steps = step_index
        finally:
            with self._lock:
                if self._thread is worker:
                    self._active = False
                    self._thread = None
                    self._stop_event = None

    @property
    def _interval_seconds(self) -> float:
        return (self._interval_ms or _DEFAULT_INTERVAL_MS) / 1000

    def _apply_step(self, step: _DemoStep, step_index: int) -> None:
        if isinstance(step, _SpeakerFrameStep):
            self._apply_speaker_frame(step, step_index)
            return

        if isinstance(step, _ModeStep):
            self._store.set_mode(step.mode)
            return

        session = self._store.set_speaker_lock(step.speaker_id, step.is_locked)
        if session is None:
            raise RuntimeError(f"Demo ingest step referenced missing speaker '{step.speaker_id}'.")

    def _apply_speaker_frame(self, step: _SpeakerFrameStep, step_index: int) -> None:
        session = self._store.current()
        updated_speakers = _apply_mutations_to_speakers(
            session.speakers,
            step.mutations,
            step_index=step_index,
        )
        self._store.replace_speakers(updated_speakers, mode=step.mode)

    def _build_status_locked(self) -> MockLiveIngestStatus:
        session = self._store.current()
        remaining_steps = max(self._total_steps - self._applied_steps, 0)
        completed = self._total_steps > 0 and not self._active and remaining_steps == 0
        return MockLiveIngestStatus(
            active=self._active,
            completed=completed,
            scenario_id=_SCENARIO_ID,
            interval_ms=self._interval_ms,
            total_steps=self._total_steps,
            applied_steps=self._applied_steps,
            remaining_steps=remaining_steps,
            session_id=session.session_id,
            mode=session.mode,
            top_speaker_id=session.top_speaker_id,
        )


def _apply_mutations_to_speakers(
    speakers: list[SpeakerState],
    mutations: tuple[_SpeakerMutation, ...],
    *,
    step_index: int,
) -> list[SpeakerState]:
    mutation_lookup = {mutation.speaker_id: mutation for mutation in mutations}
    mutation_order = {mutation.speaker_id: index for index, mutation in enumerate(mutations)}
    updated_speakers: list[SpeakerState] = []
    missing_speakers = set(mutation_lookup)
    baseline_timestamp = max((speaker.last_updated_unix_ms for speaker in speakers), default=1_710_000_000_000)

    for speaker in speakers:
        mutation = mutation_lookup.get(speaker.speaker_id)
        if mutation is None:
            updated_speakers.append(speaker)
            continue

        missing_speakers.discard(speaker.speaker_id)
        timestamp = baseline_timestamp + 1_000 + (step_index * 10) + mutation_order[speaker.speaker_id]
        updates = dict(mutation.updates)
        updates.setdefault("last_updated_unix_ms", timestamp)
        updated_speakers.append(speaker.model_copy(update=updates))

    if missing_speakers:
        missing = ", ".join(sorted(missing_speakers))
        raise RuntimeError(f"Demo ingest step referenced missing speakers: {missing}")

    return updated_speakers


def _build_briefing_script(start_mode: SessionMode) -> tuple[_DemoStep, ...]:
    listening = "Listening for a stable segment."
    translating = "Refreshing translation..."
    ready = "Translation live."
    waiting = "Waiting for the next handoff."
    standing_by = "Standing by."

    return (
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    priority=0.97,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.28,
                    source_caption="Let's open with field safety and timing.",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.52,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.08,
                    lane_status=LaneStatus.IDLE,
                    status_message=waiting,
                ),
                _speaker_mutation(
                    "speaker-carmen",
                    priority=0.46,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.06,
                    lane_status=LaneStatus.IDLE,
                    status_message=waiting,
                ),
                _speaker_mutation(
                    "speaker-devi",
                    priority=0.41,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.02,
                    lane_status=LaneStatus.IDLE,
                    status_message=standing_by,
                ),
                _speaker_mutation(
                    "speaker-ella",
                    priority=0.38,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.02,
                    lane_status=LaneStatus.IDLE,
                    status_message=standing_by,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    source_caption="Let's open with field safety and timing.",
                    translated_caption=None,
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    translated_caption="Let's open with field safety and timing.",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    priority=0.68,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.12,
                    lane_status=LaneStatus.READY,
                    status_message=waiting,
                ),
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.94,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.22,
                    source_caption="Tenho uma atualização da equipe de apoio.",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    translated_caption="I have an update from the support team.",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _ModeStep(mode=SessionMode.CROWD),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.78,
                    active=True,
                    front_facing=False,
                    persistence_bonus=0.18,
                    lane_status=LaneStatus.READY,
                    status_message="Ready for follow-up.",
                ),
                _speaker_mutation(
                    "speaker-carmen",
                    priority=0.93,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.24,
                    source_caption="La salida norte está despejada.",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-carmen",
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-carmen",
                    translated_caption="The north exit is clear.",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _LockStep(speaker_id="speaker-bruno", is_locked=True),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    priority=0.91,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.22,
                    source_caption="Then reroute the next group through the east gate.",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.61,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.1,
                    lane_status=LaneStatus.READY,
                ),
                _speaker_mutation(
                    "speaker-carmen",
                    priority=0.7,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.15,
                    lane_status=LaneStatus.READY,
                    status_message=waiting,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    translated_caption="Then reroute the next group through the east gate.",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _LockStep(speaker_id="speaker-bruno", is_locked=False),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-alice",
                    priority=0.69,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.12,
                    lane_status=LaneStatus.READY,
                    status_message=waiting,
                ),
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.92,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.24,
                    source_caption="Posso liberar os ônibus agora?",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    translated_caption="Can I release the buses now?",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-bruno",
                    priority=0.74,
                    active=False,
                    front_facing=False,
                    persistence_bonus=0.14,
                    lane_status=LaneStatus.READY,
                    status_message=waiting,
                ),
                _speaker_mutation(
                    "speaker-carmen",
                    priority=0.9,
                    active=True,
                    front_facing=True,
                    persistence_bonus=0.22,
                    source_caption="Confirmo que la salida ya está abierta.",
                    translated_caption=None,
                    target_language_code="en",
                    lane_status=LaneStatus.LISTENING,
                    status_message=listening,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-carmen",
                    lane_status=LaneStatus.TRANSLATING,
                    status_message=translating,
                ),
            )
        ),
        _SpeakerFrameStep(
            mutations=(
                _speaker_mutation(
                    "speaker-carmen",
                    translated_caption="I confirm the route is now open.",
                    lane_status=LaneStatus.READY,
                    status_message=ready,
                ),
            )
        ),
        _ModeStep(mode=start_mode),
    )


def get_mock_live_ingest_controller(store: SessionStore) -> MockLiveIngestController:
    controller = getattr(store, _CONTROLLER_ATTR, None)
    if isinstance(controller, MockLiveIngestController):
        return controller

    controller = MockLiveIngestController(store)
    setattr(store, _CONTROLLER_ATTR, controller)
    return controller