
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Text
from app import Base, engine, SessionLocal

class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(String, primary_key=True)
    user = Column(String)
    action = Column(String)
    document_id = Column(String)
    message = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(engine)
