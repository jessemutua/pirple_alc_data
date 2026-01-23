# core/database.py

from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import DATABASE_URL

# ===========================
# Database Configuration
# ===========================
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

def init_db():
    """Initializes the database, creating tables if not existing."""
    Base.metadata.create_all(bind=engine)
