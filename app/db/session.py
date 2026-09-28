from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings


database_url = settings.normalized_database_url
is_sqlite = database_url.startswith("sqlite")

engine_kwargs = {
    "pool_pre_ping": True,
}

if is_sqlite:
    engine_kwargs["connect_args"] = {"check_same_thread": False}
else:
    # Keep the app conservative with Neon connections, especially on small Render instances.
    engine_kwargs.update({
        "pool_size": 3,
        "max_overflow": 2,
        "pool_recycle": 300,
        "pool_timeout": 30,
    })

engine = create_engine(database_url, **engine_kwargs)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
