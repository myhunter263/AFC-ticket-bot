import asyncio
import logging
import sys
from typing import AsyncGenerator, Optional

from asyncpg.exceptions import InvalidAuthorizationSpecificationError, InvalidPasswordError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import config
from database.models import Base

logger = logging.getLogger(__name__)

_FATAL_DB_ERRORS = (
    InvalidPasswordError,
    InvalidAuthorizationSpecificationError,
)

# config.DATABASE_URL — property, строится из POSTGRES_* переменных.
# load_dotenv() уже вызван в config.py до этой точки, поэтому значения верные.
engine = create_async_engine(
    config.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db() -> None:
    """Legacy standalone bot may migrate; Compose runs a single migration service."""
    import os
    from pathlib import Path

    migrate = os.getenv("DB_MIGRATE_ON_STARTUP", "true").lower() in {"1", "true", "yes"}
    for attempt in range(10):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT 1"))
                if migrate:
                    await conn.execute(text("SELECT pg_advisory_xact_lock(7410090)"))
                    has_guilds = await conn.scalar(text("SELECT to_regclass('public.guilds')"))
                    has_version = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
                    if has_guilds and not has_version:
                        raise RuntimeError("Existing database has no Alembic revision; inspect and stamp it explicitly before upgrading")
                    process = await asyncio.create_subprocess_exec(
                        sys.executable, "-m", "alembic", "upgrade", "head",
                        cwd=str(Path(__file__).resolve().parents[1]),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    stdout, stderr = await process.communicate()
                    if process.returncode:
                        logger.error("Migration process failed; run alembic upgrade head for diagnostics")
                        raise RuntimeError("Database migration failed")
                else:
                    await conn.execute(text("SELECT version_num FROM alembic_version"))
            logger.info("Database ready")
            return
        except RuntimeError:
            raise
        except Exception as exc:
            if attempt == 9:
                raise
            logger.warning("Database unavailable (%s); retry %s/10", type(exc).__name__, attempt + 1)
            await asyncio.sleep(3)
