from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import require_write_token
from app.models import MockSceneResponse, SessionMode
from app.services.mock_events import build_mock_scene
from app.services.mock_live_ingest import (
    MockLiveIngestAlreadyRunningError,
    MockLiveIngestControlResponse,
    MockLiveIngestStatus,
    get_mock_live_ingest_controller,
)
from app.services.session_store import SessionStore, get_session_store

router = APIRouter(prefix="/v1/mock", tags=["mock"])


@router.get("/scene", response_model=MockSceneResponse)
def get_mock_scene(mode: SessionMode = Query(default=SessionMode.FOCUS)) -> MockSceneResponse:
    return build_mock_scene(mode)


@router.get("/live-ingest", response_model=MockLiveIngestStatus)
def get_live_ingest_status(
    store: SessionStore = Depends(get_session_store),
) -> MockLiveIngestStatus:
    controller = get_mock_live_ingest_controller(store)
    return controller.status()


@router.post(
    "/live-ingest",
    response_model=MockLiveIngestControlResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_write_token)],
)
def start_live_ingest(
    mode: SessionMode = Query(default=SessionMode.FOCUS),
    interval_ms: int = Query(default=350, ge=1, le=10_000),
    store: SessionStore = Depends(get_session_store),
) -> MockLiveIngestControlResponse:
    controller = get_mock_live_ingest_controller(store)

    try:
        return controller.start(mode=mode, interval_ms=interval_ms)
    except MockLiveIngestAlreadyRunningError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.delete(
    "/live-ingest",
    response_model=MockLiveIngestControlResponse,
    dependencies=[Depends(require_write_token)],
)
def stop_live_ingest(
    store: SessionStore = Depends(get_session_store),
) -> MockLiveIngestControlResponse:
    controller = get_mock_live_ingest_controller(store)
    return controller.stop()
