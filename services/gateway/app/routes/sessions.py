from fastapi import APIRouter, Depends, Request

from app.models import SessionMode, SessionResponse
from app.services.mock_events import SessionStore

router = APIRouter(prefix="/v1/session", tags=["session"])


def get_store(request: Request) -> SessionStore:
    return request.app.state.session_store


@router.get("", response_model=SessionResponse)
def get_session(store: SessionStore = Depends(get_store)) -> SessionResponse:
    return store.get_session()


@router.post("/reset", response_model=SessionResponse)
def reset_session(store: SessionStore = Depends(get_store)) -> SessionResponse:
    return store.reset()
