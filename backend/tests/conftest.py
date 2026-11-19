"""Test setup: a dedicated `tradeflow_test` database, never the dev database."""

import os
from collections.abc import Iterator

import psycopg
import pytest
from sqlalchemy.engine import make_url

TEST_DB_NAME = "tradeflow_test"
_dev_url = make_url(
    os.environ.get("DATABASE_URL", "postgresql+psycopg://tradeflow:tradeflow_dev_password@localhost:5433/tradeflow")
)
_test_url = _dev_url.set(database=TEST_DB_NAME)

# Must be set before `app` modules are imported, because settings/engine are created at import time.
os.environ["DATABASE_URL"] = _test_url.render_as_string(hide_password=False)
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-not-for-production-use-0123456789")


def _ensure_test_database() -> None:
    admin_dsn = _dev_url.set(drivername="postgresql").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB_NAME,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')


_ensure_test_database()

from app.db.base import Base  # noqa: E402
from app.db.triggers import install_triggers  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
import app.models  # noqa: E402,F401


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        install_triggers(conn)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables(_schema: None) -> Iterator[None]:
    """Empty every table before each test for full isolation."""
    yield
    with engine.begin() as conn:
        # Allocations are append-only in production; lift that guard only for test cleanup.
        conn.exec_driver_sql("ALTER TABLE payment_allocations DISABLE TRIGGER trg_allocation_immutable")
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
        conn.exec_driver_sql("ALTER TABLE payment_allocations ENABLE TRIGGER trg_allocation_immutable")


@pytest.fixture
def db() -> Iterator["Session"]:  # noqa: F821
    with SessionLocal() as session:
        yield session


# ---------------------------------------------------------------- shared API fixtures


@pytest.fixture
def client(db):
    """API client with the three demo users seeded."""
    from fastapi.testclient import TestClient

    from app.db.seed import seed_users
    from app.main import app

    seed_users(db)
    db.commit()
    return TestClient(app)


def headers_for(client, email: str) -> dict[str, str]:
    from app.db.seed import DEMO_PASSWORD

    token = client.post("/api/v1/auth/login", json={"email": email, "password": DEMO_PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def finance(client):
    return headers_for(client, "finance@example.com")


@pytest.fixture
def ops(client):
    return headers_for(client, "operations@example.com")


@pytest.fixture
def admin(client):
    return headers_for(client, "admin@example.com")
