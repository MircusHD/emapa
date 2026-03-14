from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from modules.config import DB_URL

Base = declarative_base()
engine = create_engine(DB_URL, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
