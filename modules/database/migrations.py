import os
import json
import uuid
import sqlite3
import random
import string
import bcrypt
from datetime import datetime
from sqlalchemy import select
from .session import SessionLocal, engine, Base
from .models import User, Department, DocType, Document, AuthToken
from modules.config import DB_PATH, DG_DEPT, ORG_DEPARTMENTS, DEFAULT_PARENTS, PUBLIC_PREFIX


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
    _sqlite_add_column_if_missing("approvals", "escalated_to_username", "escalated_to_username TEXT")
    _sqlite_add_column_if_missing("approvals", "escalation_status", "escalation_status TEXT")
    _sqlite_add_column_if_missing("approvals", "escalation_chain_json", "escalation_chain_json TEXT")
    _sqlite_add_column_if_missing("approvals", "is_escalation_node", "is_escalation_node INTEGER NOT NULL DEFAULT 0")
    _sqlite_add_column_if_missing("approvals", "created_at", "created_at DATETIME")


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


    # sesizari table
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sesizari (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numar_inregistrare TEXT NOT NULL UNIQUE,
                titlu TEXT NOT NULL,
                descriere TEXT,
                pdf_path TEXT,
                autor TEXT NOT NULL,
                departament TEXT,
                user_responsabil TEXT,
                status TEXT NOT NULL DEFAULT 'nou',
                created_at DATETIME NOT NULL,
                trimis_la_dg_at DATETIME,
                distribuit_la_dept_at DATETIME,
                atribuit_la_user_at DATETIME,
                finalizat_at DATETIME,
                observatii_finalizare TEXT
            )
            """
        )
        con.commit()
        con.close()
    except Exception:
        pass

    # sesizare_files table
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sesizare_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesizare_id INTEGER NOT NULL,
                fisier_path TEXT NOT NULL,
                tip TEXT NOT NULL,
                uploaded_by TEXT NOT NULL,
                uploaded_at DATETIME NOT NULL,
                descriere TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sesizare_files_sesizare_id ON sesizare_files(sesizare_id)")
        con.commit()
        con.close()
    except Exception:
        pass

    # system_logs table
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS system_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME NOT NULL DEFAULT (datetime('now')),
                level TEXT NOT NULL DEFAULT 'INFO',
                category TEXT NOT NULL DEFAULT 'system',
                action TEXT NOT NULL,
                username TEXT,
                details TEXT,
                target_id TEXT
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_timestamp ON system_logs(timestamp)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_username ON system_logs(username)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_system_logs_level ON system_logs(level)")
        con.commit()
        con.close()
    except Exception:
        pass

    _sqlite_add_column_if_missing("system_logs", "ip_address", "ip_address TEXT")

    # migrate sesizari columns (in case table existed with fewer columns)
    _sqlite_add_column_if_missing("sesizari", "numar_inregistrare",    "numar_inregistrare TEXT NOT NULL DEFAULT ''")
    _sqlite_add_column_if_missing("sesizari", "titlu",                 "titlu TEXT NOT NULL DEFAULT ''")
    _sqlite_add_column_if_missing("sesizari", "descriere",             "descriere TEXT")
    _sqlite_add_column_if_missing("sesizari", "pdf_path",              "pdf_path TEXT")
    _sqlite_add_column_if_missing("sesizari", "autor",                 "autor TEXT NOT NULL DEFAULT ''")
    _sqlite_add_column_if_missing("sesizari", "departament",           "departament TEXT")
    _sqlite_add_column_if_missing("sesizari", "user_responsabil",      "user_responsabil TEXT")
    _sqlite_add_column_if_missing("sesizari", "status",                "status TEXT NOT NULL DEFAULT 'nou'")
    _sqlite_add_column_if_missing("sesizari", "created_at",            "created_at DATETIME NOT NULL DEFAULT (datetime('now'))")
    _sqlite_add_column_if_missing("sesizari", "trimis_la_dg_at",       "trimis_la_dg_at DATETIME")
    _sqlite_add_column_if_missing("sesizari", "distribuit_la_dept_at", "distribuit_la_dept_at DATETIME")
    _sqlite_add_column_if_missing("sesizari", "atribuit_la_user_at",   "atribuit_la_user_at DATETIME")
    _sqlite_add_column_if_missing("sesizari", "finalizat_at",          "finalizat_at DATETIME")
    _sqlite_add_column_if_missing("sesizari", "observatii_finalizare", "observatii_finalizare TEXT")
    _sqlite_add_column_if_missing("sesizari", "necesita_aprobare_dg",   "necesita_aprobare_dg INTEGER NOT NULL DEFAULT 0")
    _sqlite_add_column_if_missing("sesizari", "dg_aprobat_la",          "dg_aprobat_la DATETIME")
    _sqlite_add_column_if_missing("sesizari", "dg_semnatura_path",      "dg_semnatura_path TEXT")
    _sqlite_add_column_if_missing("sesizari", "final_pdf_path",         "final_pdf_path TEXT")
    _sqlite_add_column_if_missing("sesizari", "necesita_aprobare_sef",  "necesita_aprobare_sef INTEGER NOT NULL DEFAULT 0")
    _sqlite_add_column_if_missing("sesizari", "sef_aprobat_la",         "sef_aprobat_la DATETIME")
    _sqlite_add_column_if_missing("sesizari", "sef_semnatura_path",     "sef_semnatura_path TEXT")
    _sqlite_add_column_if_missing("sesizari", "sef_aprobator_username", "sef_aprobator_username TEXT")
    _sqlite_add_column_if_missing("sesizari", "vizare_chain_json",      "vizare_chain_json TEXT")
    _sqlite_add_column_if_missing("sesizari", "vizare_current_approver","vizare_current_approver TEXT")

    # unique index for public_id (best effort)
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_public_id ON documents(public_id)")
        # performance indexes - documents
        cur.execute("CREATE INDEX IF NOT EXISTS ix_documents_status ON documents(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_documents_department ON documents(department)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_documents_created_by ON documents(created_by)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_documents_created_at ON documents(created_at)")
        # performance indexes - sesizari
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sesizari_status ON sesizari(status)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sesizari_departament ON sesizari(departament)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sesizari_user_responsabil ON sesizari(user_responsabil)")
        cur.execute("CREATE INDEX IF NOT EXISTS ix_sesizari_created_at ON sesizari(created_at)")
        # performance indexes - users
        cur.execute("CREATE INDEX IF NOT EXISTS ix_users_department ON users(department)")
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
