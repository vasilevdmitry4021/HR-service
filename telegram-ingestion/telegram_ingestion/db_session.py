from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from telegram_ingestion.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def db_session() -> Session:
    return SessionLocal()
