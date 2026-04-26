import json
from collections.abc import Iterator
from queue import Empty, Queue

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from app.models import SessionMode, SessionStreamEvent, StreamEventType
from app.services.session_store import SessionStore, get_session_store

router = APIRouter(prefix="/v1/events", tags=["events"])

_KEEPALIVE_TIMEOUT_SECONDS = 15.0


def _encode_sse(event: SessionStreamEvent) -> str:
    payload = event.model_dump(mode="json")
    return f"event: {event.event.value}\ndata: {json.dumps(payload)}\n\n"


def _stream_events(
    queue: Queue[SessionStreamEvent],
    initial_event: SessionStreamEvent,
    store: SessionStore,
    max_events: int | None,
) -> Iterator[str]:
    emitted_events = 0

    yield _encode_sse(initial_event)
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

            yield _encode_sse(event)
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
    queue, session = store.subscribe(mode)
    return StreamingResponse(
        _stream_events(
            queue,
            SessionStreamEvent(
                event=StreamEventType.SESSION_SNAPSHOT,
                session=session,
            ),
            store,
            max_events,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )