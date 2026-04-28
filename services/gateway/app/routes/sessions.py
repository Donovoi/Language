from fastapi import APIRouter, Depends, Query

from app.auth import require_write_token
from app.models import SessionMode, SessionResetResponse, SessionResponse
from app.services.session_store import SessionStore, get_session_store

router = APIRouter(prefix="/v1/session", tags=["session"])


@router.get("", response_model=SessionResponse)
def get_session(
    mode: SessionMode | None = Query(default=None),
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    if mode is not None:
        return store.preview(mode)
    return store.current()


@router.put(
    "/mode",
    response_model=SessionResponse,
    dependencies=[Depends(require_write_token)],
)
def set_session_mode(
    mode: SessionMode = Query(default=SessionMode.FOCUS),
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    return store.set_mode(mode)


@router.post(
    "/reset",
    response_model=SessionResetResponse,
    dependencies=[Depends(require_write_token)],
)
def reset_session(
    mode: SessionMode = Query(default=SessionMode.FOCUS),
    store: SessionStore = Depends(get_session_store),
) -> SessionResetResponse:
    return SessionResetResponse(reset=True, session=store.reset(mode))
