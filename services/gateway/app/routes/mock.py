from fastapi import APIRouter, Query

from app.models import MockSceneResponse, SessionMode
from app.services.mock_events import build_mock_scene

router = APIRouter(prefix="/v1/mock", tags=["mock"])


@router.get("/scene", response_model=MockSceneResponse)
def get_mock_scene(mode: SessionMode = Query(default=SessionMode.FOCUS)) -> MockSceneResponse:
    return build_mock_scene(mode)
