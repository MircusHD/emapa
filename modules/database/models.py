from sqlalchemy import Column, String, DateTime, Text, Date, Integer, Boolean
from datetime import datetime
from .session import Base
from modules.config import DG_DEPT


class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="user")  # admin/user/secretariat
    department = Column(String, nullable=False, default=DG_DEPT)
    is_active = Column(Boolean, nullable=False, default=True)
    full_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    default_signature_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Department(Base):
    __tablename__ = "departments"
    name = Column(String, primary_key=True)
    head_username = Column(String, nullable=True)
    parent_department = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class DocType(Base):
    __tablename__ = "doc_types"
    name = Column(String, primary_key=True)
    workflow_json = Column(Text, nullable=False, default="[]")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Document(Base):
    __tablename__ = "documents"
    id = Column(String, primary_key=True)

    # short public code (preferred in UI)
    public_id = Column(String, nullable=True, unique=True, index=True)

    # we show/use doc_name everywhere; keep title for backwards compat
    title = Column(String, nullable=False)
    doc_name = Column(String, nullable=True)

    # registry fields
    reg_no = Column(Integer, nullable=True)
    reg_date = Column(String, nullable=True)  # YYYY-MM-DD

    doc_type = Column(String, nullable=False)
    department = Column(String, nullable=False)
    project = Column(String, nullable=True)
    doc_date = Column(Date, nullable=True)
    tags_json = Column(Text, nullable=True)

    original_filename = Column(String, nullable=False)  # always .pdf
    stored_path = Column(String, nullable=False)        # under UPLOAD_DIR
    sha256 = Column(String, nullable=False, index=True)

    created_by = Column(String, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    status = Column(String, nullable=False, default="DRAFT")  # DRAFT/PENDING/APPROVED/REJECTED/CANCELLED
    current_step = Column(Integer, nullable=False, default=0)

    workflow_json = Column(Text, nullable=True)
    final_pdf_path = Column(String, nullable=True)  # under FINAL_DIR


class Approval(Base):
    __tablename__ = "approvals"
    id = Column(String, primary_key=True)
    document_id = Column(String, nullable=False, index=True)
    step_order = Column(Integer, nullable=False)
    approver_username = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="WAITING")  # WAITING/PENDING/APPROVED/REJECTED
    decided_at = Column(DateTime, nullable=True)
    comment = Column(Text, nullable=True)
    signature_path = Column(String, nullable=True)  # under SIGNATURE_DIR
    signed_at = Column(String, nullable=True)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id = Column(String, primary_key=True)
    username = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, index=True)  # sha256 hex
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
