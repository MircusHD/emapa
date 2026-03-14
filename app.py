# app.py - eMapa Apa Prod (FULL, functional, PDF-only, workflow approvals, signatures, registry, secretariat)
#
# Install in venv:
#   pip install streamlit sqlalchemy pandas bcrypt pillow numpy pypdf reportlab streamlit-drawable-canvas
#
# NSSM recommended:
#   streamlit run F:\doc-mapa\app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false --server.fileWatcherType none
#
# Key requirements implemented:
# - Branding: eMapa Apa Prod (RO, fara diacritice in statusuri)
# - Upload DOAR PDF
# - "Titlu" eliminat: folosim doar "Denumire document" (doc_name) peste tot
# - Workflow simplu + builder: pasii definiti de user, DG/GENERAL fortat ultimul pas
# - Structura departamente parinte/copil (ex: SERV_LABORATOARE -> DEP_CALITATE)
# - Rol secretariat: vede TOATE documentele (Arhiva + Registratura), poate seta Nr/Data, poate descarca
# - Admin: vede tot, poate crea/edita useri, poate edita sefi de departamente (head) si parinti
# - Fiecare aprobator:
#     - are preview prin buton "Previzualizare document (deschide in Chrome)"
#     - vede PDF "curent" = original + pagina semnaturi/aprobari cu pasii deja decisi
#     - la APROBARE: semnatura cu mouse obligatorie
# - PDF final: la APROBAT final se genereaza automat (original + pagina semnaturi/aprobari)
# - Download din Arhiva:
#     - Original PDF
#     - FINAL (PDF semnat)
# - Stergere: UN SINGUR buton "Sterge document" (Admin/Secretariat), sterge din DB + toate fisierele (original/final/semnaturi)
#
# Notes:
# - DG_DEPT = "GENERAL" (nu exista "DG" separat)
# - Seteaza head pentru "GENERAL" in Admin -> Departments

import os
import json
import uuid
import hashlib
import sqlite3
import base64
import random
import re
import string
from io import BytesIO
from datetime import datetime, date, timedelta
from typing import List, Optional, Tuple

import bcrypt
import numpy as np
import pandas as pd
import streamlit as st

def is_dg():
    u = st.session_state.get("auth_user")
    return bool(u and (u.get("role") or "").strip().lower() == "dg")
import streamlit.components.v1 as components

from PIL import Image
from streamlit_drawable_canvas import st_canvas

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader

from pypdf import PdfReader, PdfWriter
from modules.sesizari.sesizari_ui import render_sesizari
from modules.dashboard import render_dashboard

from sqlalchemy import (
    create_engine,
    Column,
    String,
    DateTime,
    Text,
    Date,
    Integer,
    Boolean,
    func,
    select,
    desc,
    and_,
    or_,)
from sqlalchemy.orm import declarative_base, sessionmaker


# -----------------------
# Paths / Config
# -----------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SIGNATURE_DIR = os.path.join(DATA_DIR, "signatures")
DEFAULT_SIG_DIR = os.path.join(SIGNATURE_DIR, "defaults")
FINAL_DIR = os.path.join(DATA_DIR, "final")
DB_PATH = os.path.join(DATA_DIR, "app.db")
DB_URL = f"sqlite:///{DB_PATH}"

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SIGNATURE_DIR, exist_ok=True)
os.makedirs(DEFAULT_SIG_DIR, exist_ok=True)
os.makedirs(FINAL_DIR, exist_ok=True)

DG_DEPT = "GENERAL"

# Public document code (short, human-friendly)
PUBLIC_PREFIX = "EM"  # format: EM-A9K3X7

ORG_DEPARTMENTS = [
    "GENERAL",
    "SRV_UIP",
    "SRV_ACHIZITII_ADMINISTRATIV",
    "COMP_AUDIT_INTERN",
    "COMP_JURIDIC",
    "COMP_RESURSE_UMANE",
    "COMP_PREVENIRE_PROTECTIE",
    "DEP_ECONOMIC",
    "DEP_EXPLOATARE",
    "DEP_TEHNIC",
    "DEP_CALITATE",
    "SERV_FINANCIAR_CONTABILITATE",
    "COMP_CONTACT_CENTER",
    "SERV_COMERCIAL",
    "SECTIA_APA_CANAL",
    "SERV_DISPECERAT",
    "SECTIE_MENTENANTA",
    "SECTIE_AUTOMATIZARE_SCADA",
    "SECTIE_TRATARE_APA_ORLEA",
    "ADUCTIUNE_APA_ORLEA_DEVA",
    "SERV_TEHNIC_INVESTITII",
    "LAB_METROLOGIE",
    "SERV_MONITORIZARE_PIERDERI",
    "SERV_LABORATOARE",
    "SERV_MEDIU_PROCEDURI",
]

DEFAULT_PARENTS = {
    "SERV_LABORATOARE": "DEP_CALITATE",
    "SERV_MEDIU_PROCEDURI": "DEP_CALITATE",
    "SERV_FINANCIAR_CONTABILITATE": "DEP_ECONOMIC",
}


# -----------------------
# DB setup
# -----------------------
Base = declarative_base()
engine = create_engine(DB_URL, connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


# -----------------------
# Models
# -----------------------
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


Base.metadata.create_all(engine)


# -----------------------
# Migrations / Seed
# -----------------------
def _sqlite_add_column_if_missing(table: str, colname: str, coldef_sql: str) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(f"PRAGMA table_info({table})")
    cols = [r[1] for r in cur.fetchall()]
    if colname not in cols:
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {coldef_sql}")
    con.commit()
    con.close()


def _bcrypt_hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def auto_migrate_and_seed() -> None:
    # pragmatic sqlite settings (best effort)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL;")
        cur.execute("PRAGMA synchronous=NORMAL;")
        cur.execute("PRAGMA busy_timeout=5000;")
    except Exception:
        pass
    con.commit()
    con.close()

    # migrations
    _sqlite_add_column_if_missing("users", "is_active", "is_active INTEGER NOT NULL DEFAULT 1")
    _sqlite_add_column_if_missing("users", "full_name", "full_name TEXT")
    _sqlite_add_column_if_missing("users", "job_title", "job_title TEXT")
    _sqlite_add_column_if_missing("users", "default_signature_path", "default_signature_path TEXT")
    _sqlite_add_column_if_missing("departments", "parent_department", "parent_department TEXT")

    _sqlite_add_column_if_missing("documents", "workflow_json", "workflow_json TEXT")
    _sqlite_add_column_if_missing("documents", "doc_name", "doc_name TEXT")
    _sqlite_add_column_if_missing("documents", "reg_no", "reg_no INTEGER")
    _sqlite_add_column_if_missing("documents", "reg_date", "reg_date TEXT")
    _sqlite_add_column_if_missing("documents", "final_pdf_path", "final_pdf_path TEXT")
    _sqlite_add_column_if_missing("documents", "public_id", "public_id TEXT")

    _sqlite_add_column_if_missing("approvals", "signature_path", "signature_path TEXT")
    _sqlite_add_column_if_missing("approvals", "signed_at", "signed_at TEXT")


    # auth_tokens table (remember-me)
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_used_at TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS ix_auth_tokens_username ON auth_tokens(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_auth_tokens_token_hash ON auth_tokens(token_hash)")
        con.commit()
        con.close()
    except Exception:
        pass


    # unique index for public_id (best effort)
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_public_id ON documents(public_id)")
        con.commit()
        con.close()
    except Exception:
        pass

    # seed departments
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    for d in ORG_DEPARTMENTS:
        cur.execute(
            "INSERT OR IGNORE INTO departments(name, head_username, parent_department, created_at) "
            "VALUES (?, NULL, NULL, datetime('now'))",
            (d,),
        )
    for child, parent in DEFAULT_PARENTS.items():
        cur.execute(
            "UPDATE departments SET parent_department=? WHERE name=? AND (parent_department IS NULL OR parent_department='')",
            (parent, child),
        )
    con.commit()
    con.close()

    # seed admin + default doc type
    with SessionLocal() as db:
        any_user = db.execute(select(User).limit(1)).scalar_one_or_none()
        if not any_user:
            db.add(
                User(
                    id=str(uuid.uuid4()),
                    username="admin",
                    password_hash=_bcrypt_hash("admin123!"),
                    role="admin",
                    department=DG_DEPT,
                    is_active=True,
                )
            )

        dg = db.execute(select(Department).where(Department.name == DG_DEPT)).scalar_one_or_none()
        if not dg:
            db.add(Department(name=DG_DEPT, head_username=None, parent_department=None))

        # Keep legacy DocType for older records but hide it from UI (inactive)
        dt_legacy = db.execute(select(DocType).where(DocType.name == "Document_Generic")).scalar_one_or_none()
        if not dt_legacy:
            dt_legacy = DocType(
                name="Document_Generic",
                workflow_json=json.dumps([{"kind": "DEPT_HEAD"}]),
                is_active=False,
            )
            db.add(dt_legacy)
        else:
            if dt_legacy.is_active:
                dt_legacy.is_active = False

        # Ensure there is at least one active DocType for new uploads
        dt_default = db.execute(select(DocType).where(DocType.name == "Document")).scalar_one_or_none()
        if not dt_default:
            db.add(DocType(name="Document", workflow_json=json.dumps([{"kind": "DEPT_HEAD"}]), is_active=True))
        else:
            if not dt_default.is_active:
                dt_default.is_active = True

        db.commit()

    # backfill missing public codes (idempotent)
    backfill_public_ids()


# -----------------------
# Utility
# -----------------------
def _bcrypt_check(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def normalize_dept(dept: str) -> str:
    d = (dept or "").strip().upper().replace(" ", "_").replace("-", "_")
    return d if d else DG_DEPT


def safe_filename(name: str) -> str:
    name = (name or "file").replace("\\", "_").replace("/", "_")
    for ch in [":", "*", "?", "\"", "<", ">", "|"]:
        name = name.replace(ch, "_")
    return name


def parse_tags(tags_str: str) -> List[str]:
    tags = [t.strip() for t in (tags_str or "").split(",")]
    tags = [t for t in tags if t]
    out = []
    seen = set()
    for t in tags:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


def rel_upload_path(stored_filename: str, dt: datetime) -> str:
    yyyy = dt.strftime("%Y")
    mm = dt.strftime("%m")
    folder = os.path.join(UPLOAD_DIR, yyyy, mm)
    os.makedirs(folder, exist_ok=True)
    return os.path.join(yyyy, mm, stored_filename)


def abs_upload_path(rel_path: str) -> str:
    return os.path.join(UPLOAD_DIR, rel_path)


def sig_abs_path(rel: str) -> str:
    return os.path.join(SIGNATURE_DIR, rel)


def final_abs_path(rel: str) -> str:
    return os.path.join(FINAL_DIR, rel)


def is_admin() -> bool:
    u = st.session_state.get("auth_user")
    role = (u.get("role") or "").strip().lower() if u else ""
    return role in {"admin", "administrator"}


def is_secretariat() -> bool:
    u = st.session_state.get("auth_user")
    return bool(u and (u.get("role") or "").strip().lower() == "secretariat")


def require_login() -> None:
    if st.session_state.get("auth_user") is None:
        st.stop()


def ui_result(ok: bool, msg) -> None:
    if ok:
        st.success(str(msg))
    else:
        st.error(str(msg))


def ro_approval_status(s: str) -> str:
    s = (s or "").upper()
    if s == "APPROVED":
        return "APROBAT"
    if s == "REJECTED":
        return "RESPINS"
    if s in ("PENDING", "WAITING"):
        return "IN ASTEPTARE"
    return s or "-"


def ro_doc_status(s: str) -> str:
    s = (s or "").upper()
    if s == "DRAFT":
        return "CIORNA"
    if s == "PENDING":
        return "IN APROBARE"
    if s == "APPROVED":
        return "APROBAT"
    if s == "REJECTED":
        return "RESPINS"
    if s == "CANCELLED":
        return "ANULAT"
    return s or "-"


def doc_label(doc: Document) -> str:
    den = (doc.doc_name or "").strip() or (doc.title or "").strip() or "-"
    rn = str(doc.reg_no) if doc.reg_no else "-"
    rd = doc.reg_date or "-"
    pid = (doc.public_id or "").strip() or "-"
    return f"{pid} | {den} | Nr {rn} | {rd}"


def _title_from_username(username: str) -> str:
    """Fallback display if full_name missing."""
    u = (username or "").strip().replace("_", " ").replace(".", " ")
    u = re.sub(r"\s+", " ", u)
    return " ".join([p.capitalize() for p in u.split()]) if u else "-"


def user_display_name(username: str) -> str:
    """Returns 'Full Name' if set, else Title Case username."""
    uname = (username or "").strip()
    if not uname:
        return "-"
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
    if u and (u.full_name or "").strip():
        return u.full_name.strip()
    return _title_from_username(uname)


def user_display_with_title(username: str) -> str:
    uname = (username or "").strip()
    if not uname:
        return "-"
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
    name = (u.full_name or "").strip() if u else ""
    title = (u.job_title or "").strip() if u else ""
    if not name:
        name = _title_from_username(uname)
    return f"{name} ({title})" if title else name


def generate_public_id() -> str:
    """Generate short code EM-A9K3X7; guaranteed unique (best effort)."""
    chars = string.ascii_uppercase + string.digits
    for _ in range(50):
        code = "".join(random.choices(chars, k=6))
        pid = f"{PUBLIC_PREFIX}-{code}"
        with SessionLocal() as db:
            exists = db.execute(select(Document).where(Document.public_id == pid)).scalar_one_or_none()
        if not exists:
            return pid
    # extreme fallback
    return f"{PUBLIC_PREFIX}-{uuid.uuid4().hex[:6].upper()}"


def backfill_public_ids() -> None:
    try:
        with SessionLocal() as db:
            docs = db.execute(select(Document).where(Document.public_id.is_(None))).scalars().all()
            if not docs:
                return
            for d in docs:
                d.public_id = generate_public_id()
            db.commit()
    except Exception:
        pass


def get_document_by_identifier(identifier: str) -> Optional[Document]:
    """Accepts UUID or public_id; returns Document or None."""
    ident = (identifier or "").strip()
    if not ident:
        return None
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == ident)).scalar_one_or_none()
        if doc:
            return doc
        doc = db.execute(select(Document).where(Document.public_id == ident)).scalar_one_or_none()
        return doc


def open_pdf_in_chrome_tab(pdf_bytes: bytes) -> None:
    """
    Deschide PDF in tab nou (Chrome) folosind Blob URL (evita iframe/data: blocat).
    """
    if not pdf_bytes:
        st.warning("Nu exista PDF pentru previzualizare.")
        return

    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <script>
    (function() {{
      const b64 = "{b64}";
      const byteChars = atob(b64);
      const byteNumbers = new Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {{
        byteNumbers[i] = byteChars.charCodeAt(i);
      }}
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], {{ type: "application/pdf" }});
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }})();
    </script>
    """
    components.html(html, height=0)


# -----------------------
# UX helpers (scroll back to workflow after widget changes)
# -----------------------
def _set_scroll_to_workflow() -> None:
    st.session_state["_scroll_to_workflow"] = True


def _scroll_to_workflow_if_needed() -> None:
    if st.session_state.get("_scroll_to_workflow"):
        components.html(
            """
            <script>
              const el = window.parent.document.getElementById("wf_anchor");
              if (el) { el.scrollIntoView({behavior: "instant", block: "start"}); }
            </script>
            """,
            height=0,
        )
        st.session_state["_scroll_to_workflow"] = False


def _set_scroll_to_registry() -> None:
    st.session_state["_scroll_to_registry"] = True


def _scroll_to_registry_if_needed() -> None:
    if st.session_state.get("_scroll_to_registry"):
        components.html(
            """
            <script>
              const el = window.parent.document.getElementById("reg_anchor");
              if (el) { el.scrollIntoView({behavior: "instant", block: "start"}); }
            </script>
            """,
            height=0,
        )
        st.session_state["_scroll_to_registry"] = False

# -----------------------
# Dept tree (parent sees children)
# -----------------------
def get_dept_children_map() -> dict:
    with SessionLocal() as db:
        deps = db.execute(select(Department)).scalars().all()
    m = {}
    for d in deps:
        if d.parent_department:
            p = normalize_dept(d.parent_department)
            c = normalize_dept(d.name)
            m.setdefault(p, []).append(c)
    return m


def get_descendant_departments(root_dept: str) -> List[str]:
    root = normalize_dept(root_dept)
    m = get_dept_children_map()
    out = [root]
    seen = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        for child in m.get(cur, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                stack.append(child)
    return out


# -----------------------
# Workflow helpers
# -----------------------
def step_is_same(a: dict, b: dict) -> bool:
    if (a or {}).get("kind") != (b or {}).get("kind"):
        return False
    if a.get("kind") == "DEPT_HEAD_OF":
        return normalize_dept(a.get("department") or "") == normalize_dept(b.get("department") or "")
    if a.get("kind") == "USER":
        return (a.get("username") or "").strip().lower() == (b.get("username") or "").strip().lower()
    return True


def ensure_dg_final_step(wf: List[dict]) -> List[dict]:
    final = {"kind": "DEPT_HEAD_OF", "department": normalize_dept(DG_DEPT)}
    out: List[dict] = []
    for s in (wf or []):
        if step_is_same(s, final):
            continue
        out.append(s)
    out.append(final)
    return out


def load_doc_type_workflow(doc_type: str) -> List[dict]:
    with SessionLocal() as db:
        dt = db.execute(select(DocType).where(DocType.name == doc_type, DocType.is_active == True)).scalar_one_or_none()
        if not dt:
            return [{"kind": "DEPT_HEAD"}]
        try:
            wf = json.loads(dt.workflow_json or "[]")
            if isinstance(wf, list) and wf:
                return wf
            return [{"kind": "DEPT_HEAD"}]
        except Exception:
            return [{"kind": "DEPT_HEAD"}]


def effective_workflow(doc: Document) -> List[dict]:
    wf: List[dict] = []
    if doc.workflow_json:
        try:
            tmp = json.loads(doc.workflow_json or "[]")
            if isinstance(tmp, list) and tmp:
                wf = tmp
        except Exception:
            wf = []
    if not wf:
        wf = load_doc_type_workflow(doc.doc_type)
    return ensure_dg_final_step(wf)


def resolve_step_to_approver(step: dict, doc_department: str) -> Optional[str]:
    kind = (step or {}).get("kind")
    with SessionLocal() as db:
        if kind == "USER":
            uname = (step.get("username") or "").strip()
            if not uname:
                return None
            u = db.execute(select(User).where(User.username == uname, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "DEPT_HEAD":
            dep = db.execute(select(Department).where(Department.name == doc_department)).scalar_one_or_none()
            if not dep or not dep.head_username:
                return None
            u = db.execute(select(User).where(User.username == dep.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "PARENT_HEAD":
            dep = db.execute(select(Department).where(Department.name == doc_department)).scalar_one_or_none()
            if not dep or not dep.parent_department:
                return None
            parent = db.execute(select(Department).where(Department.name == dep.parent_department)).scalar_one_or_none()
            if not parent or not parent.head_username:
                return None
            u = db.execute(select(User).where(User.username == parent.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "DEPT_HEAD_OF":
            dept = normalize_dept(step.get("department") or "")
            dep = db.execute(select(Department).where(Department.name == dept)).scalar_one_or_none()
            if not dep or not dep.head_username:
                return None
            u = db.execute(select(User).where(User.username == dep.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

    return None


def user_can_view_document(doc: Document, user: dict) -> bool:
    if user.get("role") in ("admin", "secretariat"):
        return True
    if doc.created_by == user.get("username"):
        return True
    allowed_depts = get_descendant_departments(user.get("department") or DG_DEPT)
    if doc.department in allowed_depts:
        return True
    with SessionLocal() as db:
        a = db.execute(
            select(Approval).where(and_(Approval.document_id == doc.id, Approval.approver_username == user.get("username")))
        ).scalar_one_or_none()
        return a is not None


# -----------------------
# Signatures / Final PDFs
# -----------------------
def sig_rel_path(doc_id: str, step_order: int, username: str) -> str:
    return f"{doc_id}_pas{step_order}_{safe_filename(username)}.png"



def default_sig_rel_path(username: str) -> str:
    return f"defaults/{safe_filename(username)}.png"


def get_user_default_signature_rel(username: str) -> Optional[str]:
    uname = (username or "").strip()
    if not uname:
        return None
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
    if u and (getattr(u, "default_signature_path", None) or "").strip():
        return (u.default_signature_path or "").strip()
    # fallback: conventional path if file exists (for older DBs)
    rel = default_sig_rel_path(uname)
    if os.path.exists(sig_abs_path(rel)):
        return rel
    return None


def load_default_signature_bytes(username: str) -> Optional[bytes]:
    rel = get_user_default_signature_rel(username)
    if not rel:
        return None
    p = sig_abs_path(rel)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "rb") as f:
            return f.read()
    except Exception:
        return None


def save_default_signature(username: str, png_bytes: bytes) -> Tuple[bool, str]:
    uname = (username or "").strip()
    if not uname:
        return False, "Username invalid."
    if not png_bytes:
        return False, "Fisier lipsa."
    rel = default_sig_rel_path(uname)
    try:
        with open(sig_abs_path(rel), "wb") as f:
            f.write(png_bytes)
    except Exception as e:
        return False, f"Nu pot salva semnatura: {e}"
    try:
        with SessionLocal() as db:
            u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
            if not u:
                return False, "User inexistent."
            u.default_signature_path = rel
            db.commit()
    except Exception as e:
        return False, f"Nu pot salva in DB: {e}"
    return True, "Semnatura predefinita salvata."


def delete_default_signature(username: str) -> Tuple[bool, str]:
    uname = (username or "").strip()
    if not uname:
        return False, "Username invalid."
    rel = get_user_default_signature_rel(uname)
    try:
        with SessionLocal() as db:
            u = db.execute(select(User).where(User.username == uname)).scalar_one_or_none()
            if u:
                u.default_signature_path = None
                db.commit()
    except Exception:
        pass
    if rel:
        try:
            p = sig_abs_path(rel)
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    return True, "Semnatura predefinita stearsa."

def final_rel_path(doc_id: str) -> str:
    return f"{doc_id}_final.pdf"


def build_final_pdf(doc_id: str) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "APPROVED":
            return False, "PDF final se genereaza doar cand este APROBAT."
        approvals = db.execute(
            select(Approval).where(Approval.document_id == doc_id).order_by(Approval.step_order)
        ).scalars().all()

    op = abs_upload_path(doc.stored_path)
    if not os.path.exists(op):
        return False, "Fisier original lipseste."

    # approvals page
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "eMapa Apa Prod - Pagina de semnaturi si aprobari")

    c.setFont("Helvetica", 10)
    denumire = (doc.doc_name or "").strip() or (doc.title or "").strip() or "-"
    reg_no = str(doc.reg_no) if doc.reg_no else "-"
    reg_date = doc.reg_date or "-"

    c.drawString(40, h - 75, f"Cod document: {(doc.public_id or '-').strip()}")
    c.drawString(40, h - 90, f"Denumire document: {denumire}")
    c.drawString(40, h - 105, f"Departament: {doc.department}")
    c.drawString(40, h - 120, f"Creat de: {user_display_name(doc.created_by)}")
    c.drawString(40, h - 135, f"Inregistrare: Nr {reg_no} / Data {reg_date}")

    y = h - 170
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Aprobari:")
    y -= 18

    for a in approvals:
        status_ro = ro_approval_status(a.status)
        decided = a.decided_at.strftime("%Y-%m-%d %H:%M:%S") if a.decided_at else "-"

        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, f"Pas {a.step_order}: {user_display_with_title(a.approver_username)} - {status_ro}")
        c.setFont("Helvetica", 9)
        c.drawString(40, y - 12, f"Data decizie: {decided}")

        if a.comment:
            cc = (a.comment or "").replace("\n", " ").strip()
            if len(cc) > 110:
                cc = cc[:110] + "..."
            c.drawString(40, y - 24, f"Comentariu: {cc}")

        if a.signature_path and os.path.exists(sig_abs_path(a.signature_path)):
            try:
                img = Image.open(sig_abs_path(a.signature_path)).convert("RGBA")
                img_reader = ImageReader(img)
                c.drawImage(img_reader, 360, y - 42, width=180, height=60, mask="auto")
            except Exception:
                pass

        y -= 90
        if y < 110:
            c.showPage()
            y = h - 80

    c.showPage()
    c.save()
    buf.seek(0)

    # merge
    try:
        reader_orig = PdfReader(op)
        reader_sig = PdfReader(buf)
        writer = PdfWriter()
        for p in reader_orig.pages:
            writer.add_page(p)
        for p in reader_sig.pages:
            writer.add_page(p)

        rel_final = final_rel_path(doc_id)
        abs_final = final_abs_path(rel_final)
        with open(abs_final, "wb") as f:
            writer.write(f)
    except Exception as e:
        return False, f"Nu pot genera PDF final: {e}"

    with SessionLocal() as db:
        d2 = db.execute(select(Document).where(Document.id == doc_id)).scalar_one()
        d2.final_pdf_path = final_rel_path(doc_id)
        db.commit()

    return True, "PDF final generat."


def build_current_pdf_bytes(doc_id: str) -> Tuple[bool, bytes, str]:
    """
    PDF curent pentru previzualizare:
      - daca exista FINAL si doc e APROBAT -> folosim FINAL
      - altfel: original + pagina semnaturi cu pasii deja decisi + semnaturi existente
    """
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, b"", "Document inexistent."
        approvals = db.execute(
            select(Approval).where(Approval.document_id == doc_id).order_by(Approval.step_order)
        ).scalars().all()

    op = abs_upload_path(doc.stored_path)
    if not os.path.exists(op):
        return False, b"", "Fisier original lipseste."

    if (doc.status or "").upper() == "APPROVED" and doc.final_pdf_path:
        fp = final_abs_path(doc.final_pdf_path)
        if os.path.exists(fp):
            try:
                with open(fp, "rb") as f:
                    return True, f.read(), "OK"
            except Exception:
                pass

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "eMapa Apa Prod - Pagina de semnaturi si aprobari")
    c.setFont("Helvetica", 10)

    denumire = (doc.doc_name or "").strip() or (doc.title or "").strip() or "-"
    reg_no = str(doc.reg_no) if doc.reg_no else "-"
    reg_date = doc.reg_date or "-"

    c.drawString(40, h - 75, f"Cod document: {(doc.public_id or '-').strip()}")
    c.drawString(40, h - 90, f"Denumire document: {denumire}")
    c.drawString(40, h - 105, f"Departament: {doc.department}")
    c.drawString(40, h - 120, f"Creat de: {user_display_name(doc.created_by)}")
    c.drawString(40, h - 135, f"Inregistrare: Nr {reg_no} / Data {reg_date}")

    y = h - 170
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Aprobari:")
    y -= 18

    for a in approvals:
        status_ro = ro_approval_status(a.status)
        decided = a.decided_at.strftime("%Y-%m-%d %H:%M:%S") if a.decided_at else "-"

        c.setFont("Helvetica-Bold", 10)
        c.drawString(40, y, f"Pas {a.step_order}: {user_display_with_title(a.approver_username)} - {status_ro}")
        c.setFont("Helvetica", 9)
        c.drawString(40, y - 12, f"Data decizie: {decided}")

        if a.comment:
            cc = (a.comment or "").replace("\n", " ").strip()
            if len(cc) > 110:
                cc = cc[:110] + "..."
            c.drawString(40, y - 24, f"Comentariu: {cc}")

        if a.signature_path and os.path.exists(sig_abs_path(a.signature_path)):
            try:
                img = Image.open(sig_abs_path(a.signature_path)).convert("RGBA")
                img_reader = ImageReader(img)
                c.drawImage(img_reader, 360, y - 42, width=180, height=60, mask="auto")
            except Exception:
                pass

        y -= 90
        if y < 110:
            c.showPage()
            y = h - 80

    c.showPage()
    c.save()
    buf.seek(0)

    try:
        reader_orig = PdfReader(op)
        reader_sig = PdfReader(buf)
        writer = PdfWriter()
        for p in reader_orig.pages:
            writer.add_page(p)
        for p in reader_sig.pages:
            writer.add_page(p)

        out = BytesIO()
        writer.write(out)
        return True, out.getvalue(), "OK"
    except Exception as e:
        return False, b"", f"Nu pot genera PDF curent: {e}"


# -----------------------
# Workflow actions
# -----------------------
def start_workflow(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "DRAFT":
            return False, "Workflow poate porni doar din CIORNA."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat poate porni workflow."

        wf = effective_workflow(doc)
        approvers: List[str] = []
        for step in wf:
            a = resolve_step_to_approver(step, doc.department)
            if not a:
                return False, f"Nu pot rezolva aprobator pentru pas: {step}"
            approvers.append(a)

        old = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for x in old:
            db.delete(x)

        for i, uname in enumerate(approvers, start=1):
            db.add(
                Approval(
                    id=str(uuid.uuid4()),
                    document_id=doc.id,
                    step_order=i,
                    approver_username=uname,
                    status="PENDING" if i == 1 else "WAITING",
                )
            )

        doc.status = "PENDING"
        doc.current_step = 1
        db.commit()
        return True, "Workflow pornit."


def decide(doc_id: str, approver: str, decision: str, comment: str, signature_png_bytes: Optional[bytes]) -> Tuple[bool, str]:
    decision = (decision or "").strip().upper()
    if decision not in ("APPROVE", "REJECT"):
        return False, "Decizie invalida."

    if decision == "APPROVE" and not signature_png_bytes:
        return False, "Semnatura este obligatorie la APROBARE."

    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "PENDING":
            return False, "Documentul nu este in aprobare."

        cur = db.execute(
            select(Approval).where(
                and_(
                    Approval.document_id == doc.id,
                    Approval.step_order == doc.current_step,
                    Approval.status == "PENDING",
                )
            )
        ).scalar_one_or_none()

        if not cur:
            return False, "Nu exista pas curent IN ASTEPTARE."
        if cur.approver_username != approver:
            return False, "Nu esti aprobatorul pasului curent."

        now = datetime.utcnow()
        cur.comment = (comment or "").strip() or None
        cur.decided_at = now

        if decision == "REJECT":
            cur.status = "REJECTED"
            doc.status = "REJECTED"
            db.commit()
            return True, "RESPINS."

        # approve
        cur.status = "APPROVED"

        # save signature
        try:
            rel = sig_rel_path(doc.id, cur.step_order, approver)
            with open(sig_abs_path(rel), "wb") as f:
                f.write(signature_png_bytes)
            cur.signature_path = rel
            cur.signed_at = datetime.utcnow().isoformat()
        except Exception as e:
            return False, f"Nu am putut salva semnatura: {e}"

        nxt_order = doc.current_step + 1
        nxt = db.execute(
            select(Approval).where(
                and_(Approval.document_id == doc.id, Approval.step_order == nxt_order, Approval.status == "WAITING")
            )
        ).scalar_one_or_none()

        if nxt:
            nxt.status = "PENDING"
            doc.current_step = nxt_order
            db.commit()
            return True, "APROBAT (urmatorul pas)."

        doc.status = "APPROVED"
        db.commit()

    # generate final pdf
    ok2, msg2 = build_final_pdf(doc_id)
    if ok2:
        return True, "APROBAT final + PDF final generat."
    return True, "APROBAT final (PDF final negenerat: " + str(msg2) + ")"


def cancel_to_draft(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "PENDING":
            return False, "Doar IN APROBARE se poate anula la CIORNA."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for a in approvals:
            db.delete(a)

        doc.status = "DRAFT"
        doc.current_step = 0
        db.commit()
        return True, "Anulat la CIORNA."


def cancel_document(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status == "APPROVED":
            return False, "Nu anulam documente APROBATE."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for a in approvals:
            db.delete(a)

        doc.status = "CANCELLED"
        doc.current_step = 0
        db.commit()
        return True, "Document marcat ANULAT."


def sterge_definitiv_document(doc_id: str, actor: dict) -> Tuple[bool, str]:
    if actor.get("role") not in ("admin", "secretariat"):
        return False, "Doar Admin sau Secretariat poate sterge definitiv."

    doc_id = (doc_id or "").strip()
    if not doc_id:
        return False, "Lipseste ID-ul documentului."

    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()

        # delete signature files
        for ap in approvals:
            if ap.signature_path:
                try:
                    p = sig_abs_path(ap.signature_path)
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

        # delete original
        try:
            op = abs_upload_path(doc.stored_path)
            if os.path.exists(op):
                os.remove(op)
        except Exception:
            pass

        # delete final
        try:
            if doc.final_pdf_path:
                fp = final_abs_path(doc.final_pdf_path)
                if os.path.exists(fp):
                    os.remove(fp)
        except Exception:
            pass

        # db delete
        for ap in approvals:
            db.delete(ap)
        db.delete(doc)
        db.commit()

    return True, "Document sters definitiv (fisier + semnaturi + baza de date)."


# -----------------------
# Workflow builder UI (manual, department-head steps only)
# -----------------------
def wf_pretty(step: dict) -> str:
    """
    Afisare pas in UI (noul standard: sefi de departamente selectati explicit).
    """
    k = (step or {}).get("kind")
    if k == "DEPT_HEAD_OF":
        dept = normalize_dept(step.get("department") or "")
        if dept == DG_DEPT:
            return "Director General (GENERAL)"
        return f"Sef departament: {dept}"
    # compat (pentru workflow-uri vechi)
    if k == "DEPT_HEAD":
        return "Sef Sector (seful unitatii documentului) [legacy]"
    if k == "PARENT_HEAD":
        return "Sef Departament (seful departamentului parinte) [legacy]"
    if k == "USER":
        return f"Utilizator specific: {(step.get('username') or '').strip()} [legacy]"
    return str(step)


def wf_validate(steps: List[dict]) -> Tuple[bool, str]:
    """
    Noul standard: workflow manual compus EXCLUSIV din pasi de tip
    'DEPT_HEAD_OF' (sefi de departamente selectati explicit).
    DG/GENERAL este adaugat automat la final (nu trebuie inclus in pasi).
    """
    if not steps:
        return False, "Workflow gol."
    for s in steps:
        k = (s or {}).get("kind")
        if k != "DEPT_HEAD_OF":
            return False, "Workflow invalid: sunt permisi doar pasi cu sefi de departamente (DEPT_HEAD_OF)."
        dept = (s.get("department") or "").strip()
        if not dept:
            return False, "Workflow invalid: lipseste departamentul in pas."
        if normalize_dept(dept) == DG_DEPT:
            return False, "Nu adauga GENERAL in pasi; Directorul General este adaugat automat la final."
    return True, ""


def wf_normalize_force_dg(steps: List[dict]) -> List[dict]:
    out: List[dict] = []
    for s in steps:
        out.append({"kind": "DEPT_HEAD_OF", "department": normalize_dept(s.get("department") or "")})
    return ensure_dg_final_step(out)


def _display_name_for_user(username: str) -> str:
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not u:
            return username
        fn = (getattr(u, "full_name", None) or "").strip()
        title = (getattr(u, "job_title", None) or "").strip()
        if fn and title:
            return f"{fn} ({title})"
        if fn:
            return fn
        return username


def render_workflow_builder(doc_id: str, initial_steps: Optional[List[dict]] = None) -> None:
    """
    Builder simplificat:
    - fara preset-uri
    - fiecare pas este un "sef de departament" (DEPT_HEAD_OF + department)
    - lista se actualizeaza automat din DB pe masura ce adaugi useri / schimbi sefi.
    """
    components.html('<div id="wf_anchor"></div>', height=0)
    _scroll_to_workflow_if_needed()

    with SessionLocal() as db:
        deps = db.execute(select(Department).order_by(Department.name)).scalars().all()

    # doar departamente cu sef setat (head_username); GENERAL exclus (adaugat automat)
    dept_options = []
    dept_labels = []
    for d in deps:
        dep_name = normalize_dept(d.name)
        if dep_name == DG_DEPT:
            continue
        head = (d.head_username or "").strip()
        if not head:
            continue
        dept_options.append(dep_name)
        dept_labels.append(f"{dep_name} - {_display_name_for_user(head)}")

    st.caption("Definire manuala: adauga pas cu seful unui departament. Directorul General (GENERAL) este adaugat automat la final.")

    key = f"wf_steps_{doc_id}"
    if key not in st.session_state:
        steps = []
        if initial_steps:
            for s in initial_steps:
                if (s or {}).get("kind") == "DEPT_HEAD_OF":
                    dep = normalize_dept(s.get("department") or "")
                    if dep and dep != DG_DEPT:
                        steps.append({"kind": "DEPT_HEAD_OF", "department": dep})
        if not steps:
            steps = [{"kind": "DEPT_HEAD_OF", "department": dept_options[0]}] if dept_options else []
        st.session_state[key] = steps

    steps = st.session_state[key]

    if not dept_options:
        st.warning("Nu exista departamente cu sef setat. Mergi la Administrare -> Departamente si seteaza 'Sef departament' pentru cel putin un departament (in afara de GENERAL).")
        return

    st.markdown("### Adauga pas")
    c1, c2 = st.columns([3, 1])
    with c1:
        sel_label = st.selectbox("Alege sef departament (pas)", dept_labels, key=f"wf_sel_dept_label_{doc_id}", on_change=_set_scroll_to_workflow)
        sel_dep = dept_options[dept_labels.index(sel_label)]
    with c2:
        if st.button("Adauga", key=f"wf_add_step_{doc_id}", type="primary"):
            steps.append({"kind": "DEPT_HEAD_OF", "department": sel_dep})
            st.session_state[key] = steps
            _set_scroll_to_workflow()
            st.rerun()

    st.divider()
    st.markdown("### Pasi curenti (GENERAL nu apare aici — se adauga automat la final)")
    if not steps:
        st.info("Nu exista pasi inca.")
    for i, s in enumerate(steps):
        a, b, c, d = st.columns([6, 1, 1, 1])
        with a:
            dept = normalize_dept(s.get("department") or "")
            with SessionLocal() as db:
                dep = db.execute(select(Department).where(Department.name == dept)).scalar_one_or_none()
            if dep and dep.head_username:
                label = f"{dept} - {_display_name_for_user(dep.head_username)}"
            else:
                label = f"{dept} - (sef nedefinit)"
            st.write(f"**{i+1}.** {label}")
        with b:
            if st.button("Up", key=f"wf_up_{doc_id}_{i}") and i > 0:
                steps[i - 1], steps[i] = steps[i], steps[i - 1]
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()
        with c:
            if st.button("Down", key=f"wf_down_{doc_id}_{i}") and i < len(steps) - 1:
                steps[i + 1], steps[i] = steps[i], steps[i + 1]
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()
        with d:
            if st.button("Del", key=f"wf_del_{doc_id}_{i}"):
                steps.pop(i)
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()

    st.divider()
    if st.button("Salveaza workflow", type="primary", key=f"wf_save_{doc_id}"):
        ok, err = wf_validate(steps)
        if not ok:
            st.error(err)
            return
        final_steps = wf_normalize_force_dg(steps)
        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one()
            doc.workflow_json = json.dumps(final_steps, ensure_ascii=False)
            db.commit()
        st.success("Workflow salvat.")



# -----------------------
# DataFrame selection helpers (click row -> auto-fill code)
# -----------------------
def _select_code_from_dataframe(df: pd.DataFrame, key: str, code_col: str = "cod", id_col: str = "id") -> Optional[str]:
    """
    Returneaza codul documentului selectat dintr-un tabel.

    - In Streamlit recent, foloseste selectia de rand din st.dataframe (click pe rand).
    - In versiuni mai vechi, cade pe un selectbox (fallback stabil) + afiseaza tabelul fara selectie.
    """
    if df is None or getattr(df, "empty", True):
        return None

    df_view = df.reset_index(drop=True)

    # Preferam selectia directa pe rand (click). Daca nu e suportata, folosim fallback.
    try:
        evt = st.dataframe(
            df_view,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
        sel_rows = []
        try:
            sel_rows = evt.selection.rows  # type: ignore[attr-defined]
        except Exception:
            sel_rows = []
        if sel_rows:
            r = int(sel_rows[0])
            if 0 <= r < len(df_view):
                v = str(df_view.loc[r, code_col]) if code_col in df_view.columns else ""
                v = (v or "").strip()
                if not v and id_col in df_view.columns:
                    v = str(df_view.loc[r, id_col]).strip()
                return v or None
        return None
    except TypeError:
        # Fallback pentru Streamlit fara selection_mode/on_select
        label_cols = [c for c in [code_col, "denumire_document", "document", "status", "reg_no", "reg_date"] if c in df_view.columns]
        labels = []
        idx_map = {}
        for i in range(len(df_view)):
            parts = [str(df_view.loc[i, c]) for c in label_cols if str(df_view.loc[i, c]).strip() not in ("", "nan", "None")]
            label = " | ".join(parts) if parts else f"Rand {i+1}"
            labels.append(label)
            idx_map[label] = i

        sel_label = st.selectbox("Selecteaza document", labels, key=f"{key}_fallback_sel")
        i = idx_map.get(sel_label)
        # Afisam si tabelul ca referinta vizuala
        st.dataframe(df_view, hide_index=True)

        if i is None:
            return None
        v = str(df_view.loc[i, code_col]) if code_col in df_view.columns else ""
        v = (v or "").strip()
        if not v and id_col in df_view.columns:
            v = str(df_view.loc[i, id_col]).strip()
        return v or None


# -----------------------
# App init
# -----------------------

# -----------------------
# Remember-me (auto-login) helpers (90 zile)
# -----------------------
REMEMBER_DAYS = 90
REMEMBER_STORAGE_KEY = "emapaprod_remember_token"

def _sha256_hex(s: str) -> str:
    h = hashlib.sha256()
    h.update((s or "").encode("utf-8"))
    return h.hexdigest()

def _get_query_params() -> dict:
    # Compat Streamlit versions
    try:
        return dict(st.query_params)  # type: ignore[attr-defined]
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}

def _get_query_param(name: str) -> str:
    qp = _get_query_params() or {}
    v = qp.get(name)
    if isinstance(v, list):
        return (v[0] or "").strip()
    return (v or "").strip()

def _set_query_params_without_rt() -> None:
    try:
        qp = _get_query_params() or {}
        qp2 = {k: v for k, v in qp.items() if k != "rt"}
        # normalize list values for experimental_set_query_params
        try:
            st.experimental_set_query_params(**{k: (v if isinstance(v, str) else v[0]) for k, v in qp2.items()})
        except Exception:
            # st.query_params write API
            try:
                st.query_params.clear()  # type: ignore[attr-defined]
                for k, v in qp2.items():
                    if isinstance(v, list):
                        st.query_params[k] = v[0]  # type: ignore[attr-defined]
                    else:
                        st.query_params[k] = v  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass

def rememberme_bootstrap_js() -> None:
    """JS: daca exista token in localStorage si nu avem ?rt=..., il pune temporar in URL ca sa ajunga la Python.
    Apoi curata URL-ul (sterge rt) folosind history.replaceState."""
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          const url = new URL(window.location.href);
          const params = url.searchParams;
          const hasRt = params.has("rt");
          if (!hasRt) {{
            const t = window.localStorage.getItem(KEY);
            if (t) {{
              params.set("rt", t);
              url.search = params.toString();
              window.location.replace(url.toString());
              return;
            }}
          }} else {{
            // curata URL-ul (nu mai afisa rt)
            params.delete("rt");
            const clean = url.pathname + (params.toString() ? ("?" + params.toString()) : "") + url.hash;
            window.history.replaceState({{}}, "", clean);
          }}
        }})();
        </script>
        """,
        height=0,
    )

def create_remember_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    th = _sha256_hex(token)
    exp = datetime.utcnow() + timedelta(days=REMEMBER_DAYS)
    with SessionLocal() as db:
        db.add(
            AuthToken(
                id=str(uuid.uuid4()),
                username=username,
                token_hash=th,
                expires_at=exp,
                created_at=datetime.utcnow(),
                last_used_at=None,
            )
        )
        db.commit()
    return token

def validate_remember_token(token: str) -> Optional[dict]:
    tok = (token or "").strip()
    if not tok:
        return None
    th = _sha256_hex(tok)
    now = datetime.utcnow()
    with SessionLocal() as db:
        t = db.execute(select(AuthToken).where(and_(AuthToken.token_hash == th))).scalar_one_or_none()
        if not t:
            return None
        if t.expires_at and t.expires_at < now:
            try:
                db.delete(t)
                db.commit()
            except Exception:
                pass
            return None
        u = db.execute(select(User).where(User.username == t.username, User.is_active == True)).scalar_one_or_none()
        if not u:
            return None
        # touch last_used
        try:
            t.last_used_at = now
            db.commit()
        except Exception:
            pass
        st.session_state["remember_token_hash"] = th
        return {
            "id": u.id,
            "username": u.username,
            "role": (u.role or "").strip().lower(),
            "department": u.department,
        }

def revoke_current_remember_token() -> None:
    th = (st.session_state.get("remember_token_hash") or "").strip()
    if not th:
        return
    try:
        with SessionLocal() as db:
            t = db.execute(select(AuthToken).where(AuthToken.token_hash == th)).scalar_one_or_none()
            if t:
                db.delete(t)
                db.commit()
    except Exception:
        pass
    st.session_state["remember_token_hash"] = None

def rememberme_set_token_js(token: str) -> None:
    token_js = (token or "").replace("\\", "\\\\").replace('"', '\"')
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          window.localStorage.setItem(KEY, "{token_js}");
          // curata URL-ul daca are rt
          const url = new URL(window.location.href);
          url.searchParams.delete("rt");
          const clean = url.pathname + (url.searchParams.toString() ? ("?" + url.searchParams.toString()) : "") + url.hash;
          window.history.replaceState({{}}, "", clean);
        }})();
        </script>
        """,
        height=0,
    )

def rememberme_clear_token_js_and_reload() -> None:
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          window.localStorage.removeItem(KEY);
          const url = new URL(window.location.href);
          url.searchParams.delete("rt");
          const clean = url.pathname + (url.searchParams.toString() ? ("?" + url.searchParams.toString()) : "") + url.hash;
          window.location.replace(clean);
        }})();
        </script>
        """,
        height=0,
    )


st.set_page_config(page_title="eMapa Apa Prod", layout="wide")
st.markdown(
    """
    <style>
      /* Ascunde meniul Streamlit (cele 3 puncte din dreapta sus) */
      #MainMenu {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True
)
auto_migrate_and_seed()

st.title("eMapa Apa Prod")

# Sidebar logo
logo_path = os.path.join(BASE_DIR, "assets", "logo Apa Prod v2.0.png")
if os.path.exists(logo_path):
    st.sidebar.image(logo_path)
else:
    st.sidebar.info("Lipseste logo: assets/logo Apa Prod v2.0.png")

# Auth + Menu
with st.sidebar:
    _auth_h, _auth_m = st.columns([5, 1])
    with _auth_h:
        st.header("Autentificare")
    with _auth_m:
        with st.popover("⋮"):
            st.caption("Optiuni")
            st.write("• Daca folosesti auto-login pe acest PC, poti sterge aici.")
            if st.button("Uita acest PC (sterge auto-login)", key="btn_forget_pc_pop"):
                rememberme_clear_token_js_and_reload()
                st.stop()
            st.write("• Recomandare: foloseste auto-login doar pe PC personal.")


    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None

    # JS bootstrap pentru auto-login (citește token din localStorage, îl trimite temporar în ?rt=..., apoi curăță URL-ul)
    rememberme_bootstrap_js()

    # Auto-login (daca exista rt in URL)
    if st.session_state.auth_user is None:
        rt = _get_query_param("rt")
        if rt:
            au = validate_remember_token(rt)
            if au:
                st.session_state.auth_user = au
                _set_query_params_without_rt()
                st.rerun()

    if st.session_state.auth_user is None:

        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Username", key="login_user")
            p = st.text_input("Password", type="password", key="login_pass")
            remember_me = st.checkbox("Tine-ma minte (auto-login 90 zile)", key="remember_me")
            ok = st.form_submit_button("Autentificare")

        if ok:
            with SessionLocal() as db:
                user = db.execute(select(User).where(User.username == u.strip(), User.is_active == True)).scalar_one_or_none()
            if user and _bcrypt_check(p, user.password_hash):
                st.session_state.auth_user = {
                    "id": user.id,
                    "username": user.username,
                    "role": (user.role or "").strip().lower(),
                    "department": user.department,
                }
                if remember_me:
                    tok = create_remember_token(user.username)
                    rememberme_set_token_js(tok)
                st.success("Autentificat.")
                st.rerun()
            else:
                st.error("Credentiale invalide (sau user inactiv).")

        st.stop()

    st.write(f"User: **{st.session_state.auth_user['username']}** ({st.session_state.auth_user['role']})")
    st.write(f"Dept: **{st.session_state.auth_user['department']}**")

    st.divider()
    with st.expander("Semnatura predefinita (optional)", expanded=False):
        st.caption("Incarca o semnatura PNG. In Inbox aprobari poti aproba folosind semnatura predefinita (fara mouse).")
        me_u = st.session_state.auth_user["username"]

        existing_rel = get_user_default_signature_rel(me_u)
        if existing_rel and os.path.exists(sig_abs_path(existing_rel)):
            try:
                st.image(sig_abs_path(existing_rel), caption="Semnatura curenta", width=260)
            except Exception:
                st.info("Exista semnatura salvata, dar nu pot afisa preview.")

        up_sig = st.file_uploader("Incarca PNG", type=["png"], key="default_sig_upload")
        c_sig1, c_sig2 = st.columns([1, 1])
        with c_sig1:
            if st.button("Salveaza semnatura mea", type="primary", key="btn_save_default_sig"):
                if not up_sig:
                    st.error("Selecteaza un fisier PNG.")
                else:
                    okx, msgx = save_default_signature(me_u, up_sig.getvalue())
                    ui_result(okx, msgx)
                    if okx:
                        st.rerun()
        with c_sig2:
            if st.button("Sterge semnatura mea", key="btn_del_default_sig"):
                okd, msgd = delete_default_signature(me_u)
                ui_result(okd, msgd)
                st.rerun()

    if st.button("Deconectare", key="btn_logout"):
        # revoca tokenul curent (daca a fost folosit)
        revoke_current_remember_token()
        # sterge token local (browser) ca sa nu faca auto-login dupa logout
        rememberme_clear_token_js_and_reload()
        st.session_state.auth_user = None
        st.stop()

    st.divider()

    # Meniu in romana + restrictii rol
if is_admin():
    menu = ["Dashboard", "Arhiva", "Sesizari", "Administrare"]

elif is_secretariat():
    menu = ["Dashboard", "Arhiva", "Sesizari"]

else:
    menu = ["Dashboard", "Incarcare", "Arhiva", "Inbox aprobari", "Sesizari"]

page = st.radio("Meniu", menu, index=0, key="main_menu")
require_login()


# -----------------------
# Upload
# -----------------------
if page == "Incarcare":
    if is_dg():
        st.error("Directorul General nu poate incarca documente.")
        st.stop()

    st.subheader("Upload document (PDF)")

    dept = st.session_state.auth_user["department"]
    st.caption(f"Departament document = {dept}")

    with SessionLocal() as db:
        dts = db.execute(select(DocType).where(DocType.is_active == True).order_by(DocType.name)).scalars().all()
    dt_names = [d.name for d in dts if d.name != "Document_Generic"]
    if not dt_names:
        dt_names = ["Document"]

    uploaded = st.file_uploader("Selecteaza fisier (PDF only)", type=["pdf"], key="upload_file")
    doc_name = st.text_input("Denumire document *", value="", key="upload_doc_name")
    doc_type = "Document"  # Setează direct tipul documentului la "Document")
    project = st.text_input("Proiect (optional)", key="upload_project")
    doc_date = st.date_input("Data document (optional)", value=None, key="upload_doc_date")
    tags_str = st.text_input("Tag-uri (virgula) (optional)", key="upload_tags")

    if "last_created_doc_id" not in st.session_state:
        st.session_state.last_created_doc_id = None

    if st.button("Salveaza", type="primary", disabled=(uploaded is None), key="btn_save_draft"):
        if uploaded is None:
            st.error("Selecteaza un PDF.")
        elif not doc_name.strip():
            st.error("Denumirea documentului este obligatorie.")
        else:
            b = uploaded.getvalue()
            name_ok = (uploaded.name or "").lower().endswith(".pdf")
            header_ok = (b[:5] == b"%PDF-")
            if not name_ok or not header_ok:
                st.error("Doar fisiere PDF sunt acceptate.")
                st.stop()

            digest = sha256_bytes(b)

            with SessionLocal() as db:
                dup = db.execute(select(Document).where(Document.sha256 == digest)).scalar_one_or_none()
                if dup:
                    st.warning("Fisier duplicat detectat (hash identic).")
                    st.info(f"Document existent: {dup.id} | status: {ro_doc_status(dup.status)}")
                    st.session_state.last_created_doc_id = dup.id
                else:
                    now = datetime.utcnow()
                    doc_id = str(uuid.uuid4())
                    pub_id = generate_public_id()

                    base = os.path.splitext(uploaded.name)[0]
                    stored_filename = f"{doc_id}_{safe_filename(base)}.pdf"
                    rel = rel_upload_path(stored_filename, now).replace("\\", "/")
                    abs_p = abs_upload_path(rel)

                    with open(abs_p, "wb") as f:
                        f.write(b)

                    orig_name = safe_filename(os.path.splitext(uploaded.name)[0]) + ".pdf"

                    doc = Document(
                        id=doc_id,
                        public_id=pub_id,
                        title=doc_name.strip(),
                        doc_name=doc_name.strip(),
                        reg_no=None,
                        reg_date=None,
                        doc_type=doc_type,
                        department=dept,
                        project=project.strip() or None,
                        doc_date=doc_date if isinstance(doc_date, date) else None,
                        tags_json=json.dumps(parse_tags(tags_str), ensure_ascii=False),
                        original_filename=orig_name,
                        stored_path=rel,
                        sha256=digest,
                        created_by=st.session_state.auth_user["username"],
                        created_at=now,
                        status="DRAFT",
                        current_step=0,
                        workflow_json=None,
                        final_pdf_path=None,
                    )
                    db.add(doc)
                    db.commit()
                    st.success("Ciorna creata.")
                    st.session_state.last_created_doc_id = doc_id

    doc_id = st.session_state.last_created_doc_id
    if doc_id:
        st.divider()
        st.subheader("Workflow pentru ciorna curenta")

        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()

        if doc and doc.status == "DRAFT":
            render_workflow_builder(doc.id, initial_steps=None)

            st.divider()
            if st.button("Porneste workflow (trimite la aprobari)", type="primary", key="btn_start_workflow_upload"):
                ok, msg = start_workflow(doc.id, st.session_state.auth_user)
                ui_result(ok, msg)
                if ok:
                    st.rerun()

# -----------------------
# Dashboard
# -----------------------
elif page == "Dashboard":

    render_dashboard()


# -----------------------
# Sesizari
# -----------------------
elif page == "Sesizari":

    render_sesizari(
        st.session_state["auth_user"]["username"],
        st.session_state["auth_user"]["role"]
    )
# -----------------------
# Archive
# -----------------------
elif page == "Arhiva":
    st.subheader("Arhiva")
    # =========================
    # SECRETARIAT: Arhiva (lista + cautare + paginare) + registratura + descarcare + previzualizare + stergere
    # =========================
    if is_secretariat() and not is_admin():
        components.html('<div id="reg_anchor"></div>', height=0)
        _scroll_to_registry_if_needed()

        st.caption("Secretariat: cauta documente (inclusiv vechi), seteaza/corecteaza numar si data de registratura, descarca/previzualizeaza si sterge documente.")

        if "sec_page" not in st.session_state:
            st.session_state.sec_page = 0

        # --- filtre
        r1 = st.columns([2, 1, 1])
        with r1[0]:
            q = st.text_input("Cautare (cod / denumire / fisier / tag)", key="sec_arch_search", on_change=_set_scroll_to_registry)
        with r1[1]:
            only_unreg = st.checkbox("Doar neinregistrate", value=True, key="sec_only_unreg", on_change=_set_scroll_to_registry)
        with r1[2]:
            limit = st.selectbox("Limita", [50, 100, 200, 500], index=1, key="sec_arch_limit", on_change=_set_scroll_to_registry)

        r2 = st.columns([1, 1, 2, 2])
        with r2[0]:
            reg_no_filter = st.number_input("Nr reg (0=orice)", min_value=0, step=1, value=0, key="sec_reg_no_filter", on_change=_set_scroll_to_registry)
        with r2[1]:
            use_date = st.checkbox("Perioada", value=False, key="sec_use_date_filter", on_change=_set_scroll_to_registry)
        with r2[2]:
            date_from = st.date_input("De la", value=date.today(), disabled=not use_date, key="sec_date_from", on_change=_set_scroll_to_registry)
        with r2[3]:
            date_to = st.date_input("Pana la", value=date.today(), disabled=not use_date, key="sec_date_to", on_change=_set_scroll_to_registry)

        nav = st.columns([1, 1, 1, 4])
        with nav[0]:
            if st.button("◀ Inapoi", key="sec_prev_page"):
                if st.session_state.sec_page > 0:
                    st.session_state.sec_page -= 1
                    _set_scroll_to_registry()
                    st.rerun()
        with nav[1]:
            if st.button("Inainte ▶", key="sec_next_page"):
                st.session_state.sec_page += 1
                _set_scroll_to_registry()
                st.rerun()
        with nav[2]:
            if st.button("Reset", key="sec_reset_filters"):
                    # Resetam filtrele in mod sigur: stergem cheile widget-urilor si relansam pagina
                    for k in [
                        "sec_page",
                        "sec_arch_search",
                        "sec_only_unreg",
                        "sec_arch_limit",
                        "sec_reg_no_filter",
                        "sec_use_date_filter",
                        "sec_date_from",
                        "sec_date_to",
                        "sec_sel_doc",
                    ]:
                        if k in st.session_state:
                            del st.session_state[k]
                    _set_scroll_to_registry()
                    st.rerun()
        with nav[3]:
            st.write(f"Pagina: **{st.session_state.sec_page + 1}**")

        offset = int(st.session_state.sec_page) * int(limit)

        # --- query
        with SessionLocal() as db:
            stmt = select(Document).order_by(Document.created_at.desc()).limit(int(limit)).offset(int(offset))

            if only_unreg:
                stmt = stmt.where(Document.reg_no.is_(None))

            if int(reg_no_filter) > 0:
                stmt = stmt.where(Document.reg_no == int(reg_no_filter))

            if use_date:
                dt_from = datetime.combine(date_from, datetime.min.time())
                dt_to = datetime.combine(date_to, datetime.max.time())
                stmt = stmt.where(and_(Document.created_at >= dt_from, Document.created_at <= dt_to))

            if q and q.strip():
                qq = f"%{q.strip()}%"
                stmt = stmt.where(or_(
                    Document.public_id.ilike(qq),
                    Document.doc_name.ilike(qq),
                    Document.title.ilike(qq),
                    Document.original_filename.ilike(qq),
                    Document.tags.ilike(qq),
                ))

            docs = db.execute(stmt).scalars().all()

        if not docs:
            st.info("Nu exista documente pentru filtrele/pagina selectata.")
            st.stop()

        # --- selectie document (max 500 intrari)
        options = {f"{(d.public_id or d.id)} | {doc_label(d)}": d.id for d in docs}
        sel_label = st.selectbox("Selecteaza document", list(options.keys()), key="sec_sel_doc", on_change=_set_scroll_to_registry)
        doc_id = options.get(sel_label)

        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one()

        st.write(f"Document selectat: **{doc_label(doc)}**")
        st.write(f"Cod: **{doc.public_id or '(lipsa)'}**")

        # --- registratura (fara rerun la fiecare schimbare)
        st.divider()
        st.subheader("Inregistrare / Corectare numar")
        with st.form("sec_reg_form"):
            cur_no = int(doc.reg_no or 0)
            cur_dt = date.today()
            if doc.reg_date:
                try:
                    cur_dt = date.fromisoformat(doc.reg_date)
                except Exception:
                    cur_dt = date.today()

            new_no = st.number_input("Numar registratura", min_value=0, step=1, value=cur_no)
            new_date = st.date_input("Data registratura", value=cur_dt)
            submitted = st.form_submit_button("Salveaza")

        if submitted:
            with SessionLocal() as db:
                d2 = db.execute(select(Document).where(Document.id == doc.id)).scalar_one()
                d2.reg_no = int(new_no) if int(new_no) > 0 else None
                d2.reg_date = new_date.isoformat() if new_date else None
                db.commit()

                # daca documentul e deja APROBAT, regenereaza FINAL ca sa includa Nr/Data registratura
                if (d2.status or "").upper() == "APPROVED":
                    build_final_pdf(d2.id)
            st.success("Inregistrare salvata.")
            st.rerun()

        # --- descarcare / previzualizare
        st.divider()
        st.subheader("Descarcare / Previzualizare")

        op = abs_upload_path(doc.stored_path)
        if os.path.exists(op):
            with open(op, "rb") as f:
                st.download_button(
                    "Descarca original (PDF)",
                    data=f.read(),
                    file_name=doc.original_filename,
                    key="sec_dl_orig",
                )
        else:
            st.warning("Fisierul original lipseste pe disk.")

        if (doc.status or "").upper() == "APPROVED":
            if not doc.final_pdf_path:
                okx, msgx = build_final_pdf(doc.id)
                if not okx:
                    st.warning(str(msgx))
            if doc.final_pdf_path:
                fp = final_abs_path(doc.final_pdf_path)
                if os.path.exists(fp):
                    with open(fp, "rb") as f:
                        name = safe_filename((doc.doc_name or doc.title or "document")) + "_FINAL.pdf"
                        st.download_button(
                            "Descarca FINAL (PDF semnat)",
                            data=f.read(),
                            file_name=name,
                            key="sec_dl_final",
                        )

        if st.button("Previzualizare document (deschide in Chrome)", key="sec_preview_chrome"):
            okp, pdfb, msgp = build_current_pdf_bytes(doc.id)
            if not okp:
                st.error(str(msgp))
            else:
                open_pdf_in_chrome_tab(pdfb)

        # --- stergere
        st.divider()
        st.subheader("Stergere document")
        confirm = st.checkbox("Confirm stergerea definitiva (nu se poate recupera)", key="sec_del_conf", on_change=_set_scroll_to_registry)
        if st.button("Sterge document", type="primary", key="sec_del_btn"):
            if not confirm:
                st.error("Bifeaza confirmarea.")
            else:
                okd, msgd = sterge_definitiv_document(doc.id, st.session_state.auth_user)
                ui_result(okd, msgd)
                if okd:
                    st.rerun()

        st.stop()

    # ARHIVA STANDARD (admin + user)
    st.caption("Utilizator: vezi doar documentele incarcate de tine.")
    # =========================
    c1, c2 = st.columns([2, 1])
    with c1:
        q = st.text_input("Cautare (denumire/tags/proiect/nr/data)", key="archive_search")
    with c2:
        f_status = st.selectbox(
            "Status",
            ["(all)", "DRAFT", "PENDING", "APPROVED", "REJECTED", "CANCELLED"],
            index=0,
            key="archive_status",
        )

    with SessionLocal() as db:
        stmt = select(Document).order_by(desc(Document.created_at))

        # Admin + Secretariat vad TOT
        if not (is_admin() or is_secretariat()):
            # Arhiva personala: utilizatorul vede doar documentele incarcate de el
            u = st.session_state.get("auth_user") or {}
            me = (u.get("username") or "").strip()
            my_id = str(u.get("id") or "").strip()
            if me or my_id:
                conds = []
                if me:
                    conds.append(Document.created_by == me)
                    # compat: unele DB-uri vechi pot salva username cu alte casing-uri
                    conds.append(func.lower(Document.created_by) == me.lower())
                if my_id:
                    # compat: versiuni vechi pot salva id-ul userului ca created_by
                    conds.append(Document.created_by == my_id)
                stmt = stmt.where(or_(*conds))


        if f_status != "(all)":

            stmt = stmt.where(Document.status == f_status)


        docs = db.execute(stmt).scalars().all()

    rows = []
    for d in docs:
        try:
            tags_list = json.loads(d.tags_json) if d.tags_json else []
        except Exception:
            tags_list = []
        rows.append(
            {
                "id": d.id,
                "cod": (d.public_id or ""),
                "denumire_document": (d.doc_name or d.title or ""),
                "department": d.department,
                "status": ro_doc_status(d.status),
                "reg_no": d.reg_no or "",
                "reg_date": d.reg_date or "",
                "creat_de": d.created_by,
                "creat_la": d.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                "tags": ", ".join(tags_list),
                "project": d.project or "",
                "fisier": d.original_filename,
            }
        )

    cols = ["cod", "denumire_document", "department", "status", "reg_no", "reg_date", "creat_de", "creat_la", "fisier", "id"]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

    def _match(row) -> bool:
        text = " ".join(
            [
                str(row.get("cod", "")),
                str(row.get("denumire_document", "")),
                str(row.get("tags", "")),
                str(row.get("project", "")),
                str(row.get("reg_no", "")),
                str(row.get("reg_date", "")),
            ]
        ).lower()
        if q and q.strip().lower() not in text:
            return False
        if f_status != "(all)" and row.get("status") != ro_doc_status(f_status):
            return False
        return True

    df2 = df[df.apply(_match, axis=1)] if not df.empty else df
    # Click pe rand (in tabel) -> completeaza automat campul "Cod document"
    df_table = (df2[cols] if not df2.empty else df2)
    sel_code = _select_code_from_dataframe(df_table, key="archive_table_select", code_col="cod", id_col="id")
    if sel_code:
        st.session_state["archive_doc_id"] = sel_code

    st.divider()
    st.subheader("Detalii document / actiuni")
    doc_id = st.text_input("Cod document (ex: EM-A9K3X7)", key="archive_doc_id")

    colA, colB, colC = st.columns([1, 1, 2])

    with colA:
        if st.button("Arata detalii", key="btn_archive_details"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    st.error("Document inexistent.")
                elif not user_can_view_document(doc, st.session_state.auth_user):
                    st.error("Fara acces.")
                else:
                    st.write(f"Public: **{doc_label(doc)}**")
                    st.write(f"Denumire document: **{(doc.doc_name or doc.title)}**")
                    st.write(f"Departament: **{doc.department}**")
                    st.write(f"Status: **{ro_doc_status(doc.status)}**")
                    st.write(f"Creat de: **{user_display_name(doc.created_by)}**")
                    st.write(f"Creat la: **{doc.created_at.strftime('%Y-%m-%d %H:%M:%S')}**")

                    wf = effective_workflow(doc)
                    st.markdown("### Workflow (DG/GENERAL este mereu ultimul)")
                    for i, s in enumerate(wf, start=1):
                        st.write(f"{i}. {wf_pretty(s)}")

                    with SessionLocal() as db:
                        approvals = db.execute(
                            select(Approval).where(Approval.document_id == doc.id).order_by(Approval.step_order)
                        ).scalars().all()
                    if approvals:
                        adf = pd.DataFrame(
                            [
                                {
                                    "pas": a.step_order,
                                    "aprobator": user_display_with_title(a.approver_username),
                                    "status": ro_approval_status(a.status),
                                    "data_decizie": a.decided_at.strftime("%Y-%m-%d %H:%M:%S") if a.decided_at else "",
                                    "comentariu": a.comment or "",
                                    "semnatura": "DA" if a.signature_path else "",
                                }
                                for a in approvals
                            ]
                        )
                        st.markdown("### Stare aprobari")
                        st.dataframe(adf, hide_index=True)
                    else:
                        st.info("Nu exista aprobari (CIORNA sau workflow neinceput).")

    with colB:
        st.caption("Download (fara copy/paste, fara dubluri)")

        if doc_id.strip():
            doc_dl = get_document_by_identifier(doc_id.strip())
        else:
            doc_dl = None

        if not doc_id.strip():
            st.info("Introdu cod document pentru descarcare.")
        elif not doc_dl:
            st.error("Document inexistent.")
        elif not user_can_view_document(doc_dl, st.session_state.auth_user):
            st.error("Fara acces.")
        else:
            # --- Original
            p = abs_upload_path(doc_dl.stored_path)
            if not os.path.exists(p):
                st.warning("Fisier lipsa pe disk.")
            else:
                with open(p, "rb") as f:
                    st.download_button(
                        "Descarca original (PDF)",
                        data=f.read(),
                        file_name=doc_dl.original_filename,
                        key="dl_orig_btn",
                    )

            st.divider()

            # --- FINAL (cu registratura la zi)
            if (doc_dl.status or "").upper() != "APPROVED":
                st.info("Nu exista PDF final (document neaprobat).")
            else:
                okx, msgx = build_final_pdf(doc_dl.id)  # regenereaza ca sa includa Nr/Data registratura
                if not okx:
                    st.warning(str(msgx))

                doc_tmp = get_document_by_identifier(doc_dl.id)
                if not doc_tmp or not doc_tmp.final_pdf_path:
                    st.info("Nu exista PDF final (inca).")
                else:
                    fp = final_abs_path(doc_tmp.final_pdf_path)
                    if not os.path.exists(fp):
                        st.error("PDF final lipsa pe disk.")
                    else:
                        with open(fp, "rb") as f:
                            name = safe_filename((doc_tmp.doc_name or doc_tmp.title or "document")) + "_FINAL.pdf"
                            st.download_button(
                                "Descarca FINAL (PDF semnat)",
                                data=f.read(),
                                file_name=name,
                                key="dl_final_btn",
                            )

    with colC:
        st.caption("Actiuni (Creator/Admin/Secretariat)")

        # Registratura + editari (doar Admin/Secretariat) in Arhiva
        if is_admin() or is_secretariat():
            if doc_id.strip():
                docx = get_document_by_identifier(doc_id.strip())
            else:
                docx = None

            with st.expander("Registratura / editare (Admin/Secretariat)", expanded=False):
                if not docx:
                    st.info("Introdu un cod document mai sus pentru editare registratura.")
                else:
                    st.write(f"Cod document: **{docx.public_id or '-'}**")

                    new_name = st.text_input(
                        "Denumire document",
                        value=(docx.doc_name or docx.title or ""),
                        key="arch_edit_name",
                    )
                    new_no = st.number_input(
                        "Numar registratura",
                        min_value=0,
                        step=1,
                        value=int(docx.reg_no or 0),
                        key="arch_edit_no",
                    )
                    cur_date = date.today()
                    if docx.reg_date:
                        try:
                            cur_date = date.fromisoformat(docx.reg_date)
                        except Exception:
                            cur_date = date.today()
                    new_date = st.date_input("Data registratura", value=cur_date, key="arch_edit_date")

                    if st.button("Salveaza registratura", type="primary", key="arch_save_reg"):
                        with SessionLocal() as db:
                            d2 = db.execute(select(Document).where(Document.id == docx.id)).scalar_one()
                            d2.doc_name = new_name.strip() or None
                            d2.title = (new_name.strip() or d2.title)
                            d2.reg_no = int(new_no) if int(new_no) > 0 else None
                            d2.reg_date = new_date.isoformat() if new_date else None
                            db.commit()

                            # daca documentul e deja APROBAT, regenereaza FINAL ca sa includa Nr/Data registratura
                            if (d2.status or "").upper() == "APPROVED":
                                build_final_pdf(d2.id)
                        st.success("Salvat.")
                        st.rerun()

                    st.divider()
                    if st.button("Previzualizare document (deschide in Chrome)", key="arch_preview_chrome"):
                        okp, pdfb, msgp = build_current_pdf_bytes(docx.id)
                        if not okp:
                            st.error(str(msgp))
                        else:
                            open_pdf_in_chrome_tab(pdfb)

        if st.button("Porneste workflow (CIORNA)", key="btn_archive_start_workflow"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = start_workflow(doc.id, st.session_state.auth_user)
                ui_result(ok, msg)

        if st.button("Anuleaza workflow -> CIORNA (IN APROBARE)", key="btn_archive_cancel_to_draft"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = cancel_to_draft(doc.id, st.session_state.auth_user)
                ui_result(ok, msg)

        if st.button("Anuleaza document (nu APROBAT)", key="btn_archive_cancel_doc"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = cancel_document(doc.id, st.session_state.auth_user)
                ui_result(ok, msg)

        st.divider()
        st.caption("Editare workflow (doar CIORNA)")
        if doc_id.strip():
            doc = get_document_by_identifier(doc_id.strip())
            if doc and doc.status == "DRAFT":
                if is_admin() or is_secretariat() or doc.created_by == st.session_state.auth_user["username"]:
                    try:
                        cur = json.loads(doc.workflow_json) if doc.workflow_json else None
                    except Exception:
                        cur = None
                    render_workflow_builder(doc.id, initial_steps=cur)

        if is_admin() or is_secretariat():
            st.divider()
            st.caption("Stergere definitiva (Admin/Secretariat)")
            confirm = st.checkbox("Confirm stergerea definitiva (nu se poate recupera)", key="conf_stergere_definitiva")
            if st.button("Sterge document", type="primary", key="btn_sterge_document"):
                if not doc_id.strip():
                    st.error("Introdu cod document.")
                elif not confirm:
                    st.error("Bifeaza confirmarea.")
                else:
                    doc = get_document_by_identifier(doc_id.strip())
                    if not doc:
                        ui_result(False, "Document inexistent.")
                    else:
                        ok, msg = sterge_definitiv_document(doc.id, st.session_state.auth_user)
                    ui_result(ok, msg)
                    if ok:
                        st.rerun()


    # -----------------------
    # Approvals inbox
    # -----------------------

elif page == "Inbox aprobari":
    st.subheader("Inbox aprobari")

    me = st.session_state.auth_user["username"]
    with SessionLocal() as db:
        pending = db.execute(
            select(Approval).where(and_(Approval.approver_username == me, Approval.status == "PENDING"))
        ).scalars().all()

    if not pending:
        st.info("Nu ai aprobari in asteptare.")
        st.stop()

    rows = []
    with SessionLocal() as db:
        for a in pending:
            doc = db.execute(select(Document).where(Document.id == a.document_id)).scalar_one()
            rows.append(
                {
                    "cod": doc.public_id or "",
                    "document_id": doc.id,
                    "document": doc_label(doc),
                    "departament": doc.department,
                    "pas": a.step_order,
                    "creat_de": user_display_name(doc.created_by),
                    "creat_la": doc.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    # Tabel selectabil: click pe rand -> completeaza automat campul "Cod document"
    df_pending = pd.DataFrame(rows).reset_index(drop=True)
    sel_code = _select_code_from_dataframe(df_pending, key="approvals_table_select", code_col="cod", id_col="document_id")
    if sel_code:
        st.session_state["approvals_doc_id"] = sel_code

    st.divider()
    doc_id = st.text_input("Cod document (ex: EM-A9K3X7) pentru decizie", key="approvals_doc_id")
    comment = st.text_area("Comentariu (optional)", key="approvals_comment")

    st.divider()
    if st.button("Previzualizare document (deschide in Chrome)", key="btn_preview_chrome"):
        if not doc_id.strip():
            st.error("Introdu cod document.")
        else:
            doc = get_document_by_identifier(doc_id.strip())
            if not doc:
                st.error("Document inexistent.")
            else:
                okp, pdfb, msgp = build_current_pdf_bytes(doc.id)
            if not okp:
                st.error(str(msgp))
            else:
                open_pdf_in_chrome_tab(pdfb)

    st.divider()
    st.markdown("### Semnatura (obligatorie la APROBARE)")

    me_user = st.session_state.auth_user["username"]
    default_sig = load_default_signature_bytes(me_user)
    has_default = bool(default_sig)

    # Prefer default signature if available
    use_default = st.checkbox(
        "Foloseste semnatura predefinita (fara mouse)",
        value=True if has_default else False,
        key="use_default_signature",
    )

    if use_default and not has_default:
        st.warning("Nu ai semnatura predefinita salvata. In sidebar poti incarca una (PNG).")
        use_default = False

    if "show_manual_signature" not in st.session_state:
        st.session_state.show_manual_signature = False

    if st.button("Semnatura manuala (cu mouse)", key="btn_show_manual_sig"):
        st.session_state.show_manual_signature = True
        st.rerun()

    sig_bytes = None

    # If default selected, use it
    if use_default and default_sig:
        sig_bytes = default_sig
        st.caption("Se va folosi semnatura predefinita.")
    else:
        # Manual signature is hidden by default; show only after button
        if st.session_state.show_manual_signature:
            canvas_result = st_canvas(
                fill_color="rgba(0,0,0,0)",
                stroke_width=3,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=150,
                width=520,
                drawing_mode="freedraw",
                key="sig_canvas",
            )

            if canvas_result.image_data is not None:
                try:
                    arr = np.array(canvas_result.image_data).astype("uint8")
                    img = Image.fromarray(arr)
                    bbox = img.convert("RGB").point(lambda p: p < 250 and 255).getbbox()
                    if bbox:
                        img = img.crop(bbox)
                    out = BytesIO()
                    img.save(out, format="PNG")
                    sig_bytes = out.getvalue()
                except Exception:
                    sig_bytes = None
        else:
            st.info("Pentru semnatura cu mouse, apasa butonul de mai sus.")
    a, b = st.columns([1, 1])
    with a:
        if st.button("Aproba", type="primary", key="btn_approve"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = decide(doc.id, me, "APPROVE", comment, signature_png_bytes=sig_bytes)
                ui_result(ok, msg)
                if ok:
                    st.rerun()
    with b:
        if st.button("Respinge", key="btn_reject"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = decide(doc.id, me, "REJECT", comment, signature_png_bytes=None)
                ui_result(ok, msg)
                if ok:
                    st.rerun()


# -----------------------
# Secretariat
# -----------------------
elif page == "Secretariat":
    if not (is_secretariat() or is_admin()):
        st.error("Fara acces.")
        st.stop()

    st.subheader("Secretariat - Registratura / Cautare / Download")

    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        q = st.text_input("Cauta (denumire/proiect/tags)", key="sec_search")
    with c2:
        q_no = st.text_input("Nr (exact)", key="sec_search_no")
    with c3:
        q_status = st.selectbox(
            "Status",
            ["(all)", "DRAFT", "PENDING", "APPROVED", "REJECTED", "CANCELLED"],
            index=0,
            key="sec_status",
        )

    with SessionLocal() as db:
        stmt = select(Document).order_by(desc(Document.created_at))
        if q_status != "(all)":
            stmt = stmt.where(Document.status == q_status)
        docs = db.execute(stmt).scalars().all()

    rows = []
    for d in docs:
        try:
            tags_txt = ", ".join(json.loads(d.tags_json or "[]"))
        except Exception:
            tags_txt = ""
        text = " ".join([d.doc_name or d.title or "", d.project or "", tags_txt]).lower()

        if q and q.strip().lower() not in text:
            continue
        if q_no.strip():
            try:
                if (d.reg_no or None) != int(q_no.strip()):
                    continue
            except Exception:
                continue

        rows.append(
            {
                "id": d.id,
                "document": doc_label(d),
                "dept": d.department,
                "status": ro_doc_status(d.status),
                "creat_de": d.created_by,
                "creat_la": d.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )

    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.divider()
    st.subheader("Editare registratura / download")
    doc_id = st.text_input("Document ID (editare)", key="sec_doc_id")

    if doc_id.strip():
        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.id == doc_id.strip())).scalar_one_or_none()

        if not doc:
            st.error("Nu exista.")
        else:
            st.write(f"Public: **{doc_label(doc)}**")
            st.write(f"Departament: **{doc.department}** | Status: **{ro_doc_status(doc.status)}**")

            new_name = st.text_input("Denumire document", value=(doc.doc_name or doc.title or ""), key="sec_edit_name")
            new_no = st.number_input("Numar registratura", min_value=0, step=1, value=int(doc.reg_no or 0), key="sec_edit_no")

            cur_date = date.today()
            if doc.reg_date:
                try:
                    cur_date = date.fromisoformat(doc.reg_date)
                except Exception:
                    cur_date = date.today()
            new_date = st.date_input("Data registratura", value=cur_date, key="sec_edit_date")

            col1, col2 = st.columns([1, 2])
            with col1:
                if st.button("Salveaza", type="primary", key="sec_save"):
                    with SessionLocal() as db:
                        d2 = db.execute(select(Document).where(Document.id == doc.id)).scalar_one()
                        d2.doc_name = new_name.strip() or None
                        d2.title = (new_name.strip() or d2.title)
                        d2.reg_no = int(new_no) if int(new_no) > 0 else None
                        d2.reg_date = new_date.isoformat() if new_date else None
                        db.commit()

                        # daca documentul e deja APROBAT, regenereaza FINAL ca sa includa Nr/Data registratura
                        if (d2.status or "").upper() == "APPROVED":
                            build_final_pdf(d2.id)
                    st.success("Salvat.")
                    st.rerun()

            with col2:
                st.caption("Download")
                op = abs_upload_path(doc.stored_path)
                if os.path.exists(op):
                    with open(op, "rb") as f:
                        st.download_button("Descarca original (PDF)", data=f.read(), file_name=doc.original_filename, key="sec_dl_orig")

                if doc.status == "APPROVED" and not doc.final_pdf_path:
                    okx, msgx = build_final_pdf(doc.id)
                    if not okx:
                        st.warning(str(msgx))

                if doc.final_pdf_path:
                    fp = final_abs_path(doc.final_pdf_path)
                    if os.path.exists(fp):
                        with open(fp, "rb") as f:
                            name = safe_filename((doc.doc_name or doc.title or "document")) + "_FINAL.pdf"
                            st.download_button("Descarca FINAL (PDF semnat)", data=f.read(), file_name=name, key="sec_dl_final")

                st.divider()
                if st.button("Previzualizare document (deschide in Chrome)", key="sec_preview_chrome"):
                    okp, pdfb, msgp = build_current_pdf_bytes(doc.id)
                    if not okp:
                        st.error(str(msgp))
                    else:
                        open_pdf_in_chrome_tab(pdfb)

                st.divider()
                confirm = st.checkbox("Confirm stergerea definitiva", key="sec_confirm_delete")
                if st.button("Sterge document", type="primary", key="sec_delete_doc"):
                    if not confirm:
                        st.error("Bifeaza confirmarea.")
                    else:
                        okd, msgd = sterge_definitiv_document(doc.id, st.session_state.auth_user)
                        ui_result(okd, msgd)
                        if okd:
                            st.rerun()


# -----------------------
# Admin
# -----------------------
elif page == "Administrare":
    if not is_admin():
        st.error("Fara acces.")
        st.stop()

    st.subheader("Admin")

    tab1, tab2, tab3 = st.tabs(["Utilizatori", "Departamente (sef + parinte)", "Schimba parola mea"])

    with tab1:
        st.markdown("### Creeaza utilizator")
        nu = st.text_input("Username *", key="new_user")
        npw = st.text_input("Password *", type="password", key="new_pass")
        nr = st.selectbox("Role", ["user", "secretariat", "admin"], index=0, key="new_role")
        nfull = st.text_input("Nume complet (ex: Dorin Gligor)", key="new_full")
        njob = st.text_input("Functie (ex: Director General)", key="new_job")

        with SessionLocal() as db:
            deps = db.execute(select(Department).order_by(Department.name)).scalars().all()
        dep_names = [d.name for d in deps] if deps else ORG_DEPARTMENTS
        nd = st.selectbox("Department *", dep_names, key="new_dept")

        if st.button("Creeaza", type="primary", key="btn_create_user"):
            if not nu.strip() or not npw.strip():
                st.error("Username si password sunt obligatorii.")
            else:
                with SessionLocal() as db:
                    exists = db.execute(select(User).where(User.username == nu.strip())).scalar_one_or_none()
                    if exists:
                        st.error("User existent.")
                    else:
                        db.add(
                            User(
                                id=str(uuid.uuid4()),
                                username=nu.strip(),
                                password_hash=_bcrypt_hash(npw.strip()),
                                role=nr,
                                department=normalize_dept(nd),
                                is_active=True,
                                full_name=nfull.strip() or None,
                                job_title=njob.strip() or None,
                            )
                        )
                        db.commit()
                        st.success("User creat.")
                        st.rerun()

        st.divider()
        with SessionLocal() as db:
            users = db.execute(select(User).order_by(User.username)).scalars().all()
        st.dataframe(
            pd.DataFrame([
                {
                    "username": u.username,
                    "nume": (u.full_name or ""),
                    "functie": (u.job_title or ""),
                    "role": u.role,
                    "department": u.department,
                    "active": bool(u.is_active),
                }
                for u in users
            ]),
            hide_index=True,
        )

        st.divider()
        st.markdown("### Editeaza utilizator (rol/departament/activ)")
        usernames = [u.username for u in users]
        if usernames:
            sel_u = st.selectbox("User", usernames, key="edit_sel")
            with SessionLocal() as db:
                u = db.execute(select(User).where(User.username == sel_u)).scalar_one()

            role_list = ["user", "secretariat", "admin"]
            idx_role = role_list.index(u.role) if u.role in role_list else 0
            new_role = st.selectbox("Role", role_list, index=idx_role, key="edit_role")

            idx_dept = dep_names.index(u.department) if u.department in dep_names else 0
            new_dept = st.selectbox("Department", dep_names, index=idx_dept, key="edit_dept")

            new_active = st.checkbox("Active", value=bool(u.is_active), key="edit_active")
            new_full = st.text_input("Nume complet", value=(u.full_name or ""), key="edit_full")
            new_job = st.text_input("Functie", value=(u.job_title or ""), key="edit_job")

            if st.button("Salveaza utilizator", type="primary", key="btn_save_user"):
                with SessionLocal() as db:
                    u2 = db.execute(select(User).where(User.username == sel_u)).scalar_one()
                    u2.role = new_role
                    u2.department = normalize_dept(new_dept)
                    u2.is_active = bool(new_active)
                    u2.full_name = new_full.strip() or None
                    u2.job_title = new_job.strip() or None
                    db.commit()
                st.success("Salvat.")
                st.rerun()
        st.divider()
        st.markdown("### Dezactivare / Stergere user")

        if usernames:
            target_u = st.selectbox("Selecteaza user", usernames, key="manage_user_sel")
            col_m1, col_m2 = st.columns([1, 1])

            with col_m1:
                conf_deact = st.checkbox("Confirm dezactivarea", key="conf_deactivate_user")
                if st.button("Dezactiveaza user", type="primary", key="btn_deactivate_user"):
                    if not conf_deact:
                        st.error("Bifeaza confirmarea pentru dezactivare.")
                    elif target_u == "admin":
                        st.error("Nu poti dezactiva contul admin principal.")
                    elif target_u == st.session_state.auth_user["username"]:
                        st.error("Nu poti dezactiva contul cu care esti logat.")
                    else:
                        with SessionLocal() as db:
                            u3 = db.execute(select(User).where(User.username == target_u)).scalar_one_or_none()
                            if not u3:
                                st.error("User inexistent.")
                            else:
                                u3.is_active = False
                                db.commit()
                                st.success("User dezactivat.")
                                st.rerun()

            with col_m2:
                st.caption("Stergere definitiva este permisa doar daca user-ul nu are referinte (documente/aprobari/sef departament/workflow).")
                conf_del = st.checkbox("Confirm stergerea definitiva", key="conf_hard_delete_user")
                token = st.text_input("Scrie exact username pentru confirmare", value="", key="hard_delete_token")
                if st.button("Sterge definitiv user", key="btn_hard_delete_user"):
                    if not conf_del:
                        st.error("Bifeaza confirmarea pentru stergere definitiva.")
                    elif token.strip() != target_u:
                        st.error("Confirmarea nu coincide (scrie exact username).")
                    elif target_u == "admin":
                        st.error("Nu poti sterge contul admin principal.")
                    elif target_u == st.session_state.auth_user["username"]:
                        st.error("Nu poti sterge contul cu care esti logat.")
                    else:
                        with SessionLocal() as db:
                            # Verificari referinte
                            docs_cnt = len(db.execute(select(Document.id).where(Document.created_by == target_u)).all())
                            appr_cnt = len(db.execute(select(Approval.id).where(Approval.approver_username == target_u)).all())
                            head_cnt = len(db.execute(select(Department.name).where(Department.head_username == target_u)).all())
                            dt_cnt = len(db.execute(select(DocType.name).where(DocType.workflow_json.like(f'%"{target_u}"%'))).all())
                            dw_cnt = len(db.execute(select(Document.id).where(Document.workflow_json.like(f'%"{target_u}"%'))).all())

                            total = docs_cnt + appr_cnt + head_cnt + dt_cnt + dw_cnt
                            if total > 0:
                                st.error(
                                    f"Nu pot sterge: exista referinte -> documente create: {docs_cnt}, aprobari: {appr_cnt}, "
                                    f"sef departament: {head_cnt}, doc types workflow: {dt_cnt}, document workflow: {dw_cnt}. "
                                    "Recomandare: Dezactiveaza user."
                                )
                            else:
                                udel = db.execute(select(User).where(User.username == target_u)).scalar_one_or_none()
                                if not udel:
                                    st.error("User inexistent.")
                                else:
                                    db.delete(udel)
                                    db.commit()
                                    st.success("User sters definitiv.")
                                    st.rerun()


        st.divider()
        st.markdown("### Reseteaza parola utilizator")
        ru = st.text_input("Username", key="reset_user")
        rp = st.text_input("New password", type="password", key="reset_pass")
        if st.button("Reseteaza parola", key="btn_reset_pass"):
            if not ru.strip() or not rp.strip():
                st.error("Completeaza ambele campuri.")
            else:
                with SessionLocal() as db:
                    u = db.execute(select(User).where(User.username == ru.strip())).scalar_one_or_none()
                    if not u:
                        st.error("User inexistent.")
                    else:
                        u.password_hash = _bcrypt_hash(rp.strip())
                        db.commit()
                        st.success("Parola resetata.")

    with tab2:
        st.info(f"IMPORTANT: seteaza un sef pentru departamentul {DG_DEPT} (Director General / GENERAL).")

        with SessionLocal() as db:
            deps = db.execute(select(Department).order_by(Department.name)).scalars().all()
            active_users = db.execute(select(User).where(User.is_active == True).order_by(User.username)).scalars().all()

        dep_names = [d.name for d in deps]
        user_names = [u.username for u in active_users]

        st.dataframe(
            pd.DataFrame(
                [{"department": d.name, "head_username": d.head_username or "", "parent_department": d.parent_department or ""} for d in deps]
            ),
            hide_index=True,
        )

        st.divider()
        sd = st.selectbox("Departament", dep_names, key="dep_sel")

        with SessionLocal() as db:
            curd = db.execute(select(Department).where(Department.name == sd)).scalar_one()

        head_opts = ["(none)"] + user_names
        parent_opts = ["(none)"] + dep_names

        cur_head = curd.head_username or "(none)"
        cur_parent = curd.parent_department or "(none)"

        head_idx = head_opts.index(cur_head) if cur_head in head_opts else 0
        parent_idx = parent_opts.index(cur_parent) if cur_parent in parent_opts else 0

        sh = st.selectbox("Sef departament (utilizator)", head_opts, index=head_idx, key="head_sel")
        sp = st.selectbox("Departament parinte", parent_opts, index=parent_idx, key="parent_sel")

        if st.button("Salveaza departament", type="primary", key="btn_save_dept"):
            with SessionLocal() as db:
                d = db.execute(select(Department).where(Department.name == sd)).scalar_one()
                d.head_username = None if sh == "(none)" else sh
                d.parent_department = None if sp == "(none)" else sp
                db.commit()
            st.success("Salvat.")
            st.rerun()

    with tab3:
        st.markdown("### Schimba parola mea")
        oldp = st.text_input("Parola veche", type="password", key="oldp")
        newp = st.text_input("Parola noua", type="password", key="newp")
        if st.button("Schimba", type="primary", key="btn_change_my_pass"):
            if not oldp.strip() or not newp.strip():
                st.error("Completeaza ambele campuri.")
            else:
                with SessionLocal() as db:
                    me_u = db.execute(select(User).where(User.username == st.session_state.auth_user["username"])).scalar_one()
                    if not _bcrypt_check(oldp, me_u.password_hash):
                        st.error("Parola veche gresita.")
                    else:
                        me_u.password_hash = _bcrypt_hash(newp.strip())
                        db.commit()
                        st.success("Parola schimbata.")
