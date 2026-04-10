from fastapi import FastAPI

from app.routes.health import router as health_router
from app.routes.mock import router as mock_router
from app.routes.sessions import router as sessions_router
from app.routes.speakers import router as speakers_router
from app.services.mock_events import SessionStore


def create_app() -> FastAPI:
    application = FastAPI(title="Language Gateway", version="0.1.0")
    application.state.session_store = SessionStore()
    application.include_router(health_router)
    application.include_router(sessions_router)
    application.include_router(speakers_router)
    application.include_router(mock_router)
    return application


app = create_app()
