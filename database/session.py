import asyncio
import logging
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
                await conn.run_sync(Base.metadata.create_all)
                await conn.execute(
                    text("ALTER TABLE ticket_panels ADD COLUMN IF NOT EXISTS ping_role_ids JSONB")
                )
                await conn.execute(
                    text("ALTER TABLE ticket_panels ADD COLUMN IF NOT EXISTS viewer_role_ids JSONB")
                )
                await conn.execute(
                    text("ALTER TABLE audit_logs ALTER COLUMN target_id TYPE BIGINT")
                )
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
