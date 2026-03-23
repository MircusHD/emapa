"""
log_service.py — Serviciu de logare evenimente sistem eMapa.

Folosit pentru a înregistra acțiuni importante:
  log_event(action, level, category, username, details, target_id)

Categorii: auth | document | sesizare | admin | system
Niveluri:  INFO | WARNING | ERROR
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, and_, or_, func

from modules.database.models import SystemLog
from modules.database.session import SessionLocal


def get_client_ip() -> str:
    """Returnează IP-ul clientului curent din contextul Streamlit. Silent fail → '—'."""
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        from streamlit.runtime import get_instance
        ctx = get_script_run_ctx()
        if ctx is None:
            return "—"
        runtime = get_instance()
        if runtime is None:
            return "—"
        client = runtime.get_client(ctx.session_id)
        if client is None:
            return "—"
        # Încearcă X-Forwarded-For (proxy/reverse proxy), apoi remote_ip direct
        headers = getattr(getattr(client, "request", None), "headers", {}) or {}
        ip = (
            headers.get("X-Forwarded-For")
            or headers.get("X-Real-Ip")
            or getattr(getattr(client, "request", None), "remote_ip", None)
            or "—"
        )
        # X-Forwarded-For poate conține mai multe IP-uri separate prin virgulă
        return str(ip).split(",")[0].strip()
    except Exception:
        return "—"


def log_event(
    action: str,
    *,
    level: str = "INFO",
    category: str = "system",
    username: Optional[str] = None,
    details: Optional[str] = None,
    target_id: Optional[str] = None,
) -> None:
    """Înregistrează un eveniment în system_logs. Captează automat IP-ul. Silent fail."""
    try:
        ip = get_client_ip()
        with SessionLocal() as db:
            db.add(SystemLog(
                timestamp=datetime.now(),
                level=level,
                category=category,
                action=action,
                username=username,
                ip_address=ip,
                details=details,
                target_id=str(target_id) if target_id is not None else None,
            ))
            db.commit()
    except Exception:
        pass  # logging nu trebuie să blocheze fluxul aplicației


def get_logs(
    level: Optional[str] = None,
    category: Optional[str] = None,
    username: Optional[str] = None,
    from_dt: Optional[datetime] = None,
    to_dt: Optional[datetime] = None,
    search: Optional[str] = None,
    limit: int = 500,
) -> list[SystemLog]:
    """Returnează loguri filtrate, ordonate descrescător după timestamp."""
    with SessionLocal() as db:
        stmt = select(SystemLog).order_by(SystemLog.timestamp.desc())
        conditions = []
        if level:
            conditions.append(SystemLog.level == level)
        if category:
            conditions.append(SystemLog.category == category)
        if username:
            conditions.append(SystemLog.username == username)
        if from_dt:
            conditions.append(SystemLog.timestamp >= from_dt)
        if to_dt:
            conditions.append(SystemLog.timestamp <= to_dt)
        if search:
            like_pat = f"%{search}%"
            conditions.append(or_(
                SystemLog.action.like(like_pat),
                SystemLog.details.like(like_pat),
                SystemLog.username.like(like_pat),
            ))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        stmt = stmt.limit(limit)
        logs = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(logs)


def get_log_stats() -> dict:
    """Returnează statistici sumare pentru dashboard-ul de loguri."""
    with SessionLocal() as db:
        total = db.execute(select(func.count(SystemLog.id))).scalar() or 0
        errors = db.execute(
            select(func.count(SystemLog.id)).where(SystemLog.level == "ERROR")
        ).scalar() or 0
        warnings = db.execute(
            select(func.count(SystemLog.id)).where(SystemLog.level == "WARNING")
        ).scalar() or 0
        cutoff = datetime.now() - timedelta(hours=24)
        recent = db.execute(
            select(func.count(SystemLog.id)).where(SystemLog.timestamp >= cutoff)
        ).scalar() or 0
    return {
        "total": total,
        "errors": errors,
        "warnings": warnings,
        "recent_24h": recent,
    }


def delete_old_logs(days: int = 90) -> int:
    """Șterge logurile mai vechi de `days` zile. Returnează numărul de rânduri șterse."""
    cutoff = datetime.now() - timedelta(days=days)
    with SessionLocal() as db:
        logs = db.execute(
            select(SystemLog).where(SystemLog.timestamp < cutoff)
        ).scalars().all()
        count = len(logs)
        for log in logs:
            db.delete(log)
        db.commit()
    return count