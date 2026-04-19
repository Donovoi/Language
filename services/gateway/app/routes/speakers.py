from fastapi import APIRouter, Depends, Query

from app.models import SessionMode, SessionResponse, SpeakerState
from app.services.session_store import SessionStore, get_session_store

router = APIRouter(prefix="/v1/speakers", tags=["speakers"])


@router.get("", response_model=list[SpeakerState])
def list_speakers(store: SessionStore = Depends(get_session_store)) -> list[SpeakerState]:
    return store.current().speakers


@router.post("", response_model=SessionResponse)
def replace_speakers(
    speakers: list[SpeakerState],
    mode: SessionMode | None = Query(default=None),
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    return store.replace_speakers(speakers, mode=mode)
