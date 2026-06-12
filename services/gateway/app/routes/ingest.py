from fastapi import APIRouter, Depends, Query

from app.auth import require_write_token
from app.models import DiarizationPredictionInput, SessionMode, SessionResponse
from app.services.diarization import apply_diarization_prediction
from app.services.session_store import SessionStore, get_session_store

router = APIRouter(prefix="/v1/ingest", tags=["ingest"])


@router.post(
    "/diarization",
    response_model=SessionResponse,
    dependencies=[Depends(require_write_token)],
)
def ingest_diarization(
    prediction: DiarizationPredictionInput,
    mode: SessionMode | None = Query(default=None),
    observed_end_s: float | None = Query(default=None, ge=0.0),
    store: SessionStore = Depends(get_session_store),
) -> SessionResponse:
    return apply_diarization_prediction(
        prediction,
        store,
        mode=mode,
        observed_end_s=observed_end_s,
    )
