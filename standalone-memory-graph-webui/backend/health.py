from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from db import get_db_manager


router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> JSONResponse:
    database_status = "disconnected"

    try:
        db = get_db_manager()
        async with db.session() as session:
            await session.execute(text("SELECT 1"))
        database_status = "connected"
    except Exception:
        database_status = "disconnected"

    status_code = 200 if database_status == "connected" else 503
    return JSONResponse(
        content={
            "status": "ok" if database_status == "connected" else "degraded",
            "database": database_status,
        },
        status_code=status_code,
    )


__all__ = ["router", "health_check"]
