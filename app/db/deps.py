from app.db.session import SessionLocal


def get_db():
    """FastAPI dependency that yields a SQLAlchemy session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
