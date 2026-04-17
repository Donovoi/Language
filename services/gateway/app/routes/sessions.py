from fastapi import APIRouter, Query

from app.models import SessionMode, SessionResetResponse, SessionResponse
from app.services.session_store import store

router = APIRouter(prefix="/v1/session", tags=["session"])


@router.get("", response_model=SessionResponse)
def get_session(mode: SessionMode | None = Query(default=None)) -> SessionResponse:
    if mode is not None:
        return store.set_mode(mode)
    return store.current()


@router.post("/reset", response_model=SessionResetResponse)
def reset_session(mode: SessionMode = SessionMode.FOCUS) -> SessionResetResponse:
    return SessionResetResponse(reset=True, session=store.reset(mode))
