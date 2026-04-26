from fastapi import APIRouter, Depends, HTTPException, Query, status

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


@router.put("/{speaker_id}/lock", response_model=SessionResponse)
def lock_speaker(
    speaker_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    session = store.set_speaker_lock(speaker_id, True)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Speaker '{speaker_id}' was not found.",
        )
    return session


@router.delete("/{speaker_id}/lock", response_model=SessionResponse)
def unlock_speaker(
    speaker_id: str,
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    session = store.set_speaker_lock(speaker_id, False)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Speaker '{speaker_id}' was not found.",
        )
    return session
