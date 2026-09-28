from sqlalchemy import text
from app.db.session import engine

with engine.connect() as connection:
    value = connection.execute(text("SELECT 1")).scalar_one()
    print(f"Database connection OK: SELECT 1 -> {value}")
