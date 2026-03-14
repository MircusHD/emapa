
from sqlalchemy import select
from app import SessionLocal, Approval

def pending_for_user(username):
    with SessionLocal() as db:
        rows = db.execute(
            select(Approval).where(
                Approval.approver_username == username,
                Approval.status == "PENDING"
            )
        ).scalars().all()
    return rows
