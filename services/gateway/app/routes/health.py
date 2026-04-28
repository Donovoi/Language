from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/livez")
def livez() -> dict[str, str]:
    return {"status": "alive"}


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    checks = _build_readiness_checks(request)
    is_ready = all(state == "ok" for state in checks.values())
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        content={
            "status": "ready" if is_ready else "not_ready",
            "checks": checks,
        },
    )


def _build_readiness_checks(request: Request) -> dict[str, str]:
    checks: dict[str, str] = {
        "settings": "ok" if hasattr(request.app.state, "settings") else "missing",
    }

    session_store = getattr(request.app.state, "session_store", None)
    if session_store is None:
        checks["session_store"] = "missing"
        return checks

    try:
        session = session_store.current()
    except Exception:
        checks["session_store"] = "error"
        checks["session_snapshot"] = "error"
        return checks

    checks["session_store"] = "ok"
    checks["session_snapshot"] = "ok" if bool(session.session_id) else "error"
    return checks
