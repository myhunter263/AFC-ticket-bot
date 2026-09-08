from contextlib import asynccontextmanager
import logging

from fastapi import Depends, FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from backend.auth import Principal, principal

logger = logging.getLogger(__name__)


def create_app(sessions=None) -> FastAPI:
    from backend.logging import configure
    configure()
    owned_engine = None
    if sessions is None:
        from database.session import async_session_maker, engine
        sessions, owned_engine = async_session_maker, engine

    @asynccontextmanager
    async def lifespan(app):
        import asyncio
        import os
        task = None
        if os.getenv("BACKEND_CATALOG_SYNC", "false").lower() == "true":
            from backend.worker import run
            task = asyncio.create_task(run(sessions), name="catalog-refresh")
        try:
            yield
        finally:
            if task:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if owned_engine is not None:
            await owned_engine.dispose()

    app = FastAPI(title="Hector Logistics", version="1.0.0", lifespan=lifespan)
    app.state.sessions = sessions
    from backend.orders import router
    app.include_router(router)
    from backend.events import router as events_router
    app.include_router(events_router)
    from backend.discord import router as discord_router
    app.include_router(discord_router)
    from backend.catalog import router as catalog_router
    app.include_router(catalog_router)
    from backend.admin import router as admin_router
    app.include_router(admin_router)
    from backend.operations import router as operations_router
    app.include_router(operations_router)

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        # SQLAlchemy exception strings may contain parameters and connection data.
        logger.error("Database operation failed: %s", type(exc).__name__)
        return JSONResponse(status_code=503, content={"detail": "База данных временно недоступна"})

    @app.get("/health/live")
    async def live():
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready():
        async with sessions() as session:
            await session.execute(text("SELECT 1"))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from pathlib import Path
        cfg = Config()
        cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
        if revision != ScriptDirectory.from_config(cfg).get_current_head():
            return JSONResponse(status_code=503, content={"detail": "Требуется обновить схему БД"})
        return {"status": "ok", "database": "ok", "revision": revision}

    @app.get("/api/v1/me")
    async def me(actor: Principal = Depends(principal)):
        return actor

    return app
