from sqlalchemy.engine import make_url
from database.settings import database_url


def test_password_is_url_encoded(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_MODE", "components")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test@:/%#password")
    assert make_url(database_url()).password == "test@:/%#password"


def test_explicit_database_url_has_one_contract(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_MODE", "explicit")
    monkeypatch.setenv("DATABASE_URL", "postgresql://tester:p%40ss@localhost/example")
    from config import config
    assert config.DATABASE_URL == database_url()
    assert make_url(database_url()).drivername == "postgresql+asyncpg"


def test_existing_deployment_ignores_stale_url(monkeypatch):
    monkeypatch.setenv("DATABASE_URL_MODE", "components")
    monkeypatch.setenv("DATABASE_URL", "postgresql://old:old@old/old")
    monkeypatch.setenv("POSTGRES_HOST", "current")
    assert make_url(database_url()).host == "current"
