# core/database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


def init_db():
    """
    Creates tables for all imported models.
    NOTE: make sure every model module is imported here.
    """
    import auth.models  # noqa: F401
    import drinks.session_models  # noqa: F401
    # Do NOT import legacy drinks.models (DrinkLog)

    Base.metadata.create_all(bind=engine)