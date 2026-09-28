import time
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import Base, SessionLocal, engine
from app.models import User

DEFAULT_USERS = [
    ("bauyrzhan", "Бауыржан", "ADMIN"),
    ("sanzhar", "Санжар", "USER"),
    ("yerzat", "Ерзат", "USER"),
]


def _create_schema_with_retry(max_attempts: int = 5) -> None:
    """Neon may need a moment to wake up. Retry schema creation on transient connection errors."""
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            if attempt == max_attempts:
                raise
            time.sleep(min(2 ** attempt, 10))


def init_db() -> None:
    _create_schema_with_retry()
    db = SessionLocal()
    try:
        for username, display_name, role in DEFAULT_USERS:
            exists = db.scalar(select(User).where(User.username == username))
            if not exists:
                db.add(User(
                    username=username,
                    display_name=display_name,
                    role=role,
                    password_hash=hash_password(settings.initial_user_password),
                ))
        db.commit()
    finally:
        db.close()
