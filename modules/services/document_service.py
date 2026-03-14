import random
import string
import uuid
from typing import Optional
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import Document
from modules.config import PUBLIC_PREFIX


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
