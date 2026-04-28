from fastapi import FastAPI
import uvicorn

from app.config import get_settings
from app.observability import configure_request_logger, register_request_logging_middleware
from app.routes import events_router, health_router, mock_router, sessions_router, speakers_router
from app.services.session_store import SessionStore


def create_app() -> FastAPI:
    settings = get_settings()
    request_logger = configure_request_logger(settings.log_level)
    app = FastAPI(title="Language Gateway", version="0.1.0")
    app.state.settings = settings
    app.state.session_store = SessionStore()
    register_request_logging_middleware(app, logger=request_logger)
    app.include_router(health_router)
    app.include_router(events_router)
    app.include_router(sessions_router)
    app.include_router(speakers_router)
    app.include_router(mock_router)
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
