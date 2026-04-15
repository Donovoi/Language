from fastapi import APIRouter, Depends, Query

from app.models import MockSceneResponse, SessionMode
from app.routes.sessions import get_store
from app.services.mock_events import SessionStore

router = APIRouter(prefix="/v1/mock", tags=["mock"])


@router.get("/scene", response_model=MockSceneResponse)
def get_mock_scene(
    mode: SessionMode = Query(default=SessionMode.FOCUS),
    store: SessionStore = Depends(get_store),
) -> MockSceneResponse:
    return store.load_mock_scene(mode)
