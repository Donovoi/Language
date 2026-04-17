from fastapi import FastAPI

from app.routes import health_router, mock_router, sessions_router, speakers_router


def create_app() -> FastAPI:
    app = FastAPI(title="Language Gateway", version="0.1.0")
    app.include_router(health_router)
    app.include_router(sessions_router)
    app.include_router(speakers_router)
    app.include_router(mock_router)
    return app


app = create_app()
