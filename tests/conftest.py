import os

import pytest
from dotenv import load_dotenv
from sqlalchemy.engine import make_url

load_dotenv()

# --- Safety guard: runs before any pos module is imported. ---
_test_url = os.getenv("TEST_DATABASE_URL")
if not _test_url:
    raise RuntimeError("TEST_DATABASE_URL is not set in .env")

_parsed = make_url(_test_url)
if _parsed.host not in ("localhost", "127.0.0.1") or not (_parsed.database or "").endswith("_test"):
    raise RuntimeError(
        "Refusing to run tests: TEST_DATABASE_URL must point at localhost "
        "and a database whose name ends in '_test'."
    )

# Overrides whatever .env says, before pos.database reads it.
os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("SECRET_KEY", "test-secret-key")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from pos import models  # noqa: E402
from pos.auth import create_access_token, hash_password  # noqa: E402
from pos.database import Base, SessionLocal, engine  # noqa: E402
from pos.main import app  # noqa: E402
from pathlib import Path  # noqa: E402

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

@pytest.fixture(scope="session", autouse=True)
def migrated_test_db():
    """Builds the test database with the real migrations, once per test run.
    (Replaces the old create_all that used to run when pos.main was imported.)"""
    assert engine.url.database.endswith("_test")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.upgrade(cfg, "head")


@pytest.fixture(autouse=True)
def clean_db():
    """Second safety check, then empty every table before each test."""
    assert engine.url.database.endswith("_test")
    names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
    yield


def make_user(username: str) -> dict:
    """Creates a user directly in the test DB and returns auth headers."""
    with SessionLocal() as db:
        user = models.Users(
            email=f"{username}@test.com",
            username=username,
            first_name="Test",
            last_name="User",
            hashed_password=hash_password("password123"),
            is_active=True,
            role="admin",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(user.username, user.id, user.role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    return make_user("shopowner")