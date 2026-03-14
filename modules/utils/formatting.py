import re
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import User


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


def doc_label(doc) -> str:
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
