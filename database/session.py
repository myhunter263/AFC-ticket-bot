import asyncio
import logging
from typing import AsyncGenerator

from asyncpg.exceptions import InvalidPasswordError, InvalidAuthorizationSpecificationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import config
from database.models import Base

logger = logging.getLogger(__name__)

# Ошибки, при которых ретрай бессмысленен — немедленно падаем с понятным сообщением
_FATAL_DB_ERRORS = (
    InvalidPasswordError,
    InvalidAuthorizationSpecificationError,
)

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

    for attempt in range(1, retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database initialized successfully.")
            return
        except Exception as exc:
            # Ищем причину в цепочке исключений (SQLAlchemy оборачивает asyncpg-ошибки)
            cause = exc
            while cause is not None:
                if isinstance(cause, _FATAL_DB_ERRORS):
                    logger.error(
                        "Database authentication failed — wrong POSTGRES_PASSWORD in .env. "
                        "Fix the password or remove the volume and restart. Error: %s",
                        cause,
                    )
                    raise SystemExit(1) from exc
                cause = getattr(cause, "__cause__", None) or getattr(cause, "__context__", None)
                if cause is exc:
                    break

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
