"""Shared connection settings for the bot, backend and Alembic."""
import os

from dotenv import load_dotenv
from sqlalchemy.engine import URL, make_url


def database_url() -> str:
    load_dotenv()
    # Existing deployments deliberately ignore stale DATABASE_URL values.
    # Opt in explicitly when using a single URL for the new backend.
    explicit = os.getenv("DATABASE_URL") if os.getenv("DATABASE_URL_MODE", "components") == "explicit" else None
    if explicit:
        url = make_url(explicit)
        if url.drivername in {"postgres", "postgresql"}:
            url = url.set(drivername="postgresql+asyncpg")
        if url.drivername != "postgresql+asyncpg":
            raise ValueError("DATABASE_URL must use PostgreSQL (asyncpg)")
    else:
        url = URL.create(
            "postgresql+asyncpg",
            username=os.getenv("POSTGRES_USER", "ticketbot"),
            password=os.getenv("POSTGRES_PASSWORD", ""),
            host=os.getenv("POSTGRES_HOST", "db"),
            port=int(os.getenv("POSTGRES_PORT", "5432")),
            database=os.getenv("POSTGRES_DB", "ticketbot"),
        )
    return url.render_as_string(hide_password=False)
