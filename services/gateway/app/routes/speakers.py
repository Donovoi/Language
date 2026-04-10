from fastapi import APIRouter, Depends, Request

from app.models import SessionResponse, SpeakersRequest, SpeakersResponse
from app.routes.sessions import get_store
from app.services.mock_events import SessionStore

router = APIRouter(prefix="/v1/speakers", tags=["speakers"])


@router.get("", response_model=SpeakersResponse)
def get_speakers(store: SessionStore = Depends(get_store)) -> SpeakersResponse:
    return store.get_speakers()


@router.post("", response_model=SessionResponse)
def update_speakers(
    payload: SpeakersRequest,
    store: SessionStore = Depends(get_store),
) -> SessionResponse:
    return store.apply_speakers(payload.speakers, mode=payload.mode)
