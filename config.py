import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DISCORD_TOKEN: str = os.environ["DISCORD_TOKEN"]
    DISCORD_GUILD_ID: int | None = int(os.environ["DISCORD_GUILD_ID"]) if os.environ.get("DISCORD_GUILD_ID") else None

    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "db")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "ticketbot")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "ticketbot")
    POSTGRES_PASSWORD: str = os.environ["POSTGRES_PASSWORD"]

    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'ticketbot')}:"
        f"{os.getenv('POSTGRES_PASSWORD', '')}@"
        f"{os.getenv('POSTGRES_HOST', 'db')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'ticketbot')}",
    )

    BOT_PREFIX: str = os.getenv("BOT_PREFIX", "!")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    MAX_TICKETS_PER_USER: int = int(os.getenv("MAX_TICKETS_PER_USER", "5"))

    # Colors
    COLOR_PRIMARY: int = 0x5865F2
    COLOR_SUCCESS: int = 0x57F287
    COLOR_WARNING: int = 0xFEE75C
    COLOR_ERROR: int = 0xED4245
    COLOR_INFO: int = 0x5865F2

    # Limits
    MAX_FORM_FIELDS: int = 5  # Discord modal limit
    MAX_PANELS_PER_GUILD: int = 20
    MAX_STATUSES_PER_GUILD: int = 20
    MAX_FORMS_PER_GUILD: int = 30


config = Config()
