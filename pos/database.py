import os

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to your .env file before starting the app."
    )

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    pool_pre_ping=True,   # tests each connection with a cheap query before
                          # using it, and transparently reconnects if Neon's
                          # pooler already closed it — fixes the
                          # "SSL connection has been closed unexpectedly"
                          # error on the first request after an idle gap
    pool_recycle=300,     # proactively recycle connections older than 5
                          # minutes, so they're refreshed before Neon has a
                          # chance to close them from its side
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that provides a DB session per request and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()