from fastapi import APIRouter, Request, Response
from sqlalchemy import text

router = APIRouter()


@router.get("/healthz")
async def healthz(request: Request, response: Response) -> dict[str, str]:
    checks = {"db": "ok", "redis": "ok"}
    try:
        async with request.app.state.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:
        checks["db"] = "unavailable"
    try:
        await request.app.state.redis.ping()
    except Exception:
        checks["redis"] = "unavailable"

    if any(v != "ok" for v in checks.values()):
        response.status_code = 503
    return checks
