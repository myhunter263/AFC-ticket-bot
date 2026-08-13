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
    retries = 10
    delay = 3

    logger.info("Database URL target: %s", config.DATABASE_URL.split("@")[-1])

    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                has_guilds = await conn.scalar(text("SELECT to_regclass('public.guilds')"))
                has_version = await conn.scalar(text("SELECT to_regclass('public.alembic_version')"))
                if has_guilds:
                    if not has_version:
                        await conn.execute(text(
                            "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"
                        ))
                    current_version = await conn.scalar(text(
                        "SELECT version_num FROM alembic_version LIMIT 1"
                    ))
                    if not current_version:
                        await conn.execute(text(
                            "INSERT INTO alembic_version (version_num) VALUES ('002')"
                        ))

            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "alembic",
                "upgrade",
                "head",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode:
                raise RuntimeError(stderr.decode("utf-8", errors="replace"))
            if stdout:
                logger.info(stdout.decode("utf-8", errors="replace").strip())
            logger.info("Database initialized successfully.")
            return
        except Exception as exc:
            # Обходим цепочку исключений — SQLAlchemy оборачивает asyncpg-ошибки
            cause: Optional[BaseException] = exc
            while cause is not None:
                if isinstance(cause, _FATAL_DB_ERRORS):
                    logger.error(
                        "FATAL: Authentication failed for user '%s'. "
                        "Check POSTGRES_PASSWORD in .env — it must match the password "
                        "with which the database volume was created. "
                        "To reset: docker compose down -v && docker compose up -d",
                        config.POSTGRES_USER,
                    )
                    raise SystemExit(1) from exc
                next_cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
                if next_cause is cause:
                    break
                cause = next_cause

            logger.warning(
                "Database not ready (attempt %d/%d): %s. Retrying in %ds...",
                attempt,
                retries,
                exc,
                delay,
            )
            if attempt == retries:
                logger.error("Could not connect to database after %d attempts.", retries)
                raise
            await asyncio.sleep(delay)
