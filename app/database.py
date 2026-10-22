"""SQLAlchemy engine + session. SQLite by default; Postgres via DATABASE_URL."""
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
# pool_pre_ping recycles connections dropped by the DB after restart/idle, so a
# transient network/DB blip surfaces as a retry, not a 500. One flag, no config.
pool_kw = {} if settings.database_url.startswith("sqlite") else {
    "pool_size": int(os.getenv("DB_POOL_SIZE", "20")),
    "max_overflow": int(os.getenv("DB_MAX_OVERFLOW", "10")),
}
engine = create_engine(settings.database_url, connect_args=connect_args,
                       future=True, pool_pre_ping=True, **pool_kw)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        # Never leak a half-applied transaction back into the pooled connection.
        db.rollback()
        raise
    finally:
        db.close()
