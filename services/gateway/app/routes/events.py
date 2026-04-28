import json
from collections.abc import Iterator
from queue import Empty, Queue

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.models import SessionMode, SessionStreamEvent, StreamEventType
from app.services.session_store import (
    QueuedSessionStreamEvent,
    SessionStore,
    get_session_store,
)

router = APIRouter(prefix="/v1/events", tags=["events"])

_KEEPALIVE_TIMEOUT_SECONDS = 15.0
_STREAM_RETRY_MILLISECONDS = 1000


def _encode_sse(
    event: SessionStreamEvent,
    *,
    event_id: int | None = None,
    include_retry: bool = False,
) -> str:
    payload = event.model_dump(mode="json")
    lines: list[str] = []
    if include_retry:
        lines.append(f"retry: {_STREAM_RETRY_MILLISECONDS}")
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append(f"event: {event.event.value}")
    lines.append(f"data: {json.dumps(payload)}")
    return "\n".join(lines) + "\n\n"


def _stream_events(
    queue: Queue[QueuedSessionStreamEvent],
    initial_event: SessionStreamEvent,
    initial_event_id: int,
    store: SessionStore,
    max_events: int | None,
) -> Iterator[str]:
    emitted_events = 0

    yield _encode_sse(initial_event, event_id=initial_event_id, include_retry=True)
    emitted_events += 1

    if max_events is not None and emitted_events >= max_events:
        store.unsubscribe(queue)
        return

    try:
        while True:
            try:
                event = queue.get(timeout=_KEEPALIVE_TIMEOUT_SECONDS)
            except Empty:
                yield ": keep-alive\n\n"
                continue

            yield _encode_sse(event.event, event_id=event.event_id)
            emitted_events += 1
            if max_events is not None and emitted_events >= max_events:
                return
    finally:
        store.unsubscribe(queue)


@router.get("/stream")
def stream_events(
    mode: SessionMode | None = Query(default=None),
    max_events: int | None = Query(default=None, ge=1),
    store: SessionStore = Depends(get_session_store),
) -> StreamingResponse:
    queue, session, initial_event_id = store.subscribe(mode)
    return StreamingResponse(
        _stream_events(
            queue,
            SessionStreamEvent(
                event=StreamEventType.SESSION_SNAPSHOT,
                session=session,
            ),
            initial_event_id,
            store,
            max_events,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )