import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import create_engine, pool
from sqlalchemy.engine import make_url

load_dotenv()

from pos import models  # noqa: E402,F401  (registers the tables on Base.metadata)
from pos.database import Base  # noqa: E402

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# --- Where is this command aimed? Print it, and refuse production by accident. ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set (.env or the command line).")

_target = make_url(DATABASE_URL)
print(f"Alembic target: {_target.host} / {_target.database}")

if "neon.tech" in (_target.host or "") and os.getenv("ALEMBIC_ALLOW_PRODUCTION") != "1":
    raise RuntimeError(
        "Refusing to run against Neon. If you really mean it, put "
        "ALEMBIC_ALLOW_PRODUCTION=1 in front of this one command."
    )


def run_migrations_offline() -> None:
    """Emit SQL to the screen instead of running it (alembic ... --sql)."""
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(DATABASE_URL, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()