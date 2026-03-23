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
    department = Column(String, nullable=False, default=DG_DEPT, index=True)
    is_active = Column(Boolean, nullable=False, default=True)
    full_name = Column(String, nullable=True)
    job_title = Column(String, nullable=True)
    default_signature_path = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class Department(Base):
    __tablename__ = "departments"
    name = Column(String, primary_key=True)
    head_username = Column(String, nullable=True)
    parent_department = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


class DocType(Base):
    __tablename__ = "doc_types"
    name = Column(String, primary_key=True)
    workflow_json = Column(Text, nullable=False, default="[]")
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)


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
    department = Column(String, nullable=False, index=True)
    project = Column(String, nullable=True)
    doc_date = Column(Date, nullable=True)
    tags_json = Column(Text, nullable=True)

    original_filename = Column(String, nullable=False)  # always .pdf
    stored_path = Column(String, nullable=False)        # under UPLOAD_DIR
    sha256 = Column(String, nullable=False, index=True)

    created_by = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now, index=True)

    status = Column(String, nullable=False, default="DRAFT", index=True)  # DRAFT/PENDING/APPROVED/REJECTED/CANCELLED
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
    # Escalare ierarhica optionala
    escalated_to_username = Column(String, nullable=True)          # username superior ales
    escalation_status = Column(String, nullable=True)              # NULL / PENDING / APPROVED
    escalation_chain_json = Column(Text, nullable=True)            # JSON list superiori disponibili
    is_escalation_node = Column(Integer, nullable=False, default=0)  # 0=normal, 1=nod creat prin escalare
    created_at = Column(DateTime, nullable=True, default=datetime.now)


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    id = Column(String, primary_key=True)
    username = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, index=True)  # sha256 hex
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    last_used_at = Column(DateTime, nullable=True)


class Sesizare(Base):
    __tablename__ = "sesizari"
    id                    = Column(Integer, primary_key=True, autoincrement=True)
    numar_inregistrare    = Column(String, nullable=False, unique=True)
    titlu                 = Column(String, nullable=False)
    descriere             = Column(Text, nullable=True)
    pdf_path              = Column(String, nullable=True)        # fisier initial
    autor                 = Column(String, nullable=False)       # username secretara
    departament           = Column(String, nullable=True, index=True)   # setat de DG
    user_responsabil      = Column(String, nullable=True, index=True)   # setat de head/secretara
    status                = Column(String, nullable=False, default="nou", index=True)  # nou/in_derulare/finalizat
    created_at            = Column(DateTime, nullable=False, default=datetime.now, index=True)
    trimis_la_dg_at       = Column(DateTime, nullable=True)
    distribuit_la_dept_at = Column(DateTime, nullable=True)
    atribuit_la_user_at   = Column(DateTime, nullable=True)
    finalizat_at          = Column(DateTime, nullable=True)
    observatii_finalizare = Column(Text, nullable=True)
    necesita_aprobare_dg   = Column(Boolean, nullable=False, default=False)
    dg_aprobat_la          = Column(DateTime, nullable=True)
    dg_semnatura_path      = Column(String, nullable=True)
    final_pdf_path         = Column(String, nullable=True)   # relativ la FINAL_DIR
    # Aprobare opțională Șef Departament (independentă de aprobare DG)
    necesita_aprobare_sef  = Column(Boolean, nullable=False, default=False)
    sef_aprobat_la         = Column(DateTime, nullable=True)
    sef_semnatura_path     = Column(String, nullable=True)
    sef_aprobator_username = Column(String, nullable=True)   # cine a aprobat efectiv
    # Lanț de vizare ierarhică multi-select
    vizare_chain_json      = Column(Text, nullable=True)     # JSON: [{"username":..,"status":..,"approved_at":..,"signature_path":..}]
    vizare_current_approver = Column(String, nullable=True)  # aprobatorul curent PENDING (pentru query rapid)


class SesizareFile(Base):
    __tablename__ = "sesizare_files"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    sesizare_id  = Column(Integer, nullable=False, index=True)   # FK → sesizari.id
    fisier_path  = Column(String, nullable=False)
    tip          = Column(String, nullable=False)                # 'rezolutie' sau 'completare'
    uploaded_by  = Column(String, nullable=False)               # username
    uploaded_at  = Column(DateTime, nullable=False, default=datetime.now)
    descriere    = Column(Text, nullable=True)


class SystemLog(Base):
    __tablename__ = "system_logs"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    timestamp   = Column(DateTime, nullable=False, default=datetime.now, index=True)
    level       = Column(String, nullable=False, default="INFO")    # INFO / WARNING / ERROR
    category    = Column(String, nullable=False, default="system")  # auth / document / sesizare / admin / system
    action      = Column(String, nullable=False)
    username    = Column(String, nullable=True, index=True)
    ip_address  = Column(String, nullable=True)
    details     = Column(Text, nullable=True)
    target_id   = Column(String, nullable=True)
