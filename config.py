import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    DISCORD_GUILD_ID: int | None = (
        int(os.environ["DISCORD_GUILD_ID"]) if os.environ.get("DISCORD_GUILD_ID") else None
    )

    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "db")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", "5432"))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "ticketbot")
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "ticketbot")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "")

    @property
    def DATABASE_URL(self) -> str:
        from database.settings import database_url
        return database_url()

    BOT_PREFIX: str = os.getenv("BOT_PREFIX", "!")
    BACKEND_URL: str = os.getenv("BACKEND_URL", "")
    BACKEND_TOKEN: str = os.getenv("BACKEND_TOKEN", "")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    MAX_TICKETS_PER_USER: int = int(os.getenv("MAX_TICKETS_PER_USER", "5"))
    FOXHOLEHQ_BASE_URL: str = os.getenv("FOXHOLEHQ_BASE_URL", "https://foxholehq.net").rstrip("/")
    FOXHOLEHQ_SYNC_INTERVAL_HOURS: int = int(
        os.getenv("FOXHOLEHQ_SYNC_INTERVAL_HOURS", "24")
    )
    FOXHOLEHQ_MIN_ITEMS: int = int(os.getenv("FOXHOLEHQ_MIN_ITEMS", "100"))
    FOXHOLE_WIKI_ENABLED: bool = os.getenv("FOXHOLE_WIKI_ENABLED", "true").casefold() in {
        "1", "true", "yes", "on",
    }
    FOXHOLE_WIKI_API_URL: str = os.getenv(
        "FOXHOLE_WIKI_API_URL", "https://foxhole.wiki.gg/api.php"
    )
    FOXHOLE_RESOLVE_AUTO_THRESHOLD: int = int(
        os.getenv("FOXHOLE_RESOLVE_AUTO_THRESHOLD", "90")
    )
    FOXHOLE_RESOLVE_CONFIRM_THRESHOLD: int = int(
        os.getenv("FOXHOLE_RESOLVE_CONFIRM_THRESHOLD", "75")
    )
    FOXHOLE_RESOURCE_LABELS: dict[str, str] = {
        "bmat": os.getenv("FOXHOLE_RESOURCE_BMAT", "BMat"),
        "rmat": os.getenv("FOXHOLE_RESOURCE_RMAT", "RMat"),
        "emat": os.getenv("FOXHOLE_RESOURCE_EMAT", "EMat"),
        "hemat": os.getenv("FOXHOLE_RESOURCE_HEMAT", "HEMat"),
        "processed_construction_materials": "PCon",
        "construction_materials": "CMat",
        "assembly_materials_i": "AM1",
        "assembly_materials_ii": "AM2",
        "assembly_materials_iii": "AM3",
        "assembly_materials_iv": "AM4",
        "assembly_materials_v": "AM5",
    }
    FOXHOLE_RESOURCE_COST_DISPLAY: str = os.getenv("FOXHOLE_RESOURCE_COST_DISPLAY", "both")

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
