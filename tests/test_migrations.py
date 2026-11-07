from pathlib import Path

from alembic import command
from alembic.config import Config

ROOT = Path(__file__).resolve().parent.parent


def test_models_and_migrations_agree():
    """Fails if models.py has changes that no migration covers.
    The test database was already built from the migrations by the
    session fixture in conftest.py, so this compares models vs migrations."""
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    command.check(cfg)