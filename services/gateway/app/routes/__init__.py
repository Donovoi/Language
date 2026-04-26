from .events import router as events_router
from .health import router as health_router
from .mock import router as mock_router
from .sessions import router as sessions_router
from .speakers import router as speakers_router

__all__ = ["events_router", "health_router", "mock_router", "sessions_router", "speakers_router"]
