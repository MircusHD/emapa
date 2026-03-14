import os
from typing import Optional, Tuple
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import User
from modules.config import sig_abs_path, SIGNATURE_DIR
from modules.utils.files import safe_filename


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
