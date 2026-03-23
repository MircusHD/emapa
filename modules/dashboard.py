import streamlit as st
from sqlalchemy import select, func, and_
from modules.database.session import SessionLocal
from modules.database.models import Document, Approval, User
from modules.database.models import Sesizare


@st.cache_data(ttl=30)
def _load_dashboard_data() -> dict:
    """Încarcă metricile din DB. Rezultatul e cachat 30 de secunde."""
    with SessionLocal() as db:
        docs_draft     = db.execute(select(func.count(Document.id)).where(Document.status == "DRAFT")).scalar() or 0
        docs_pending   = db.execute(select(func.count(Document.id)).where(Document.status == "PENDING")).scalar() or 0
        docs_approved  = db.execute(select(func.count(Document.id)).where(Document.status == "APPROVED")).scalar() or 0
        docs_rejected  = db.execute(select(func.count(Document.id)).where(Document.status == "REJECTED")).scalar() or 0
        docs_cancelled = db.execute(select(func.count(Document.id)).where(Document.status == "CANCELLED")).scalar() or 0

        total_sez  = db.execute(select(func.count(Sesizare.id))).scalar() or 0
        sez_noi    = db.execute(select(func.count(Sesizare.id)).where(Sesizare.status == "nou")).scalar() or 0
        sez_active = db.execute(select(func.count(Sesizare.id)).where(Sesizare.status == "in_derulare")).scalar() or 0
        sez_fin    = db.execute(select(func.count(Sesizare.id)).where(Sesizare.status == "finalizat")).scalar() or 0

        total_aprobari = db.execute(select(func.count(Approval.id)).where(Approval.status == "PENDING")).scalar() or 0
        total_useri    = db.execute(select(func.count(User.id)).where(User.is_active == True)).scalar() or 0

    return {
        "docs_draft": docs_draft, "docs_pending": docs_pending,
        "docs_approved": docs_approved, "docs_rejected": docs_rejected,
        "docs_cancelled": docs_cancelled,
        "total_docs": docs_draft + docs_pending + docs_approved + docs_rejected + docs_cancelled,
        "total_sez": total_sez, "sez_noi": sez_noi,
        "sez_active": sez_active, "sez_fin": sez_fin,
        "total_aprobari": total_aprobari, "total_useri": total_useri,
    }


def render_dashboard():
    st.title("Dashboard Management")

    d = _load_dashboard_data()

    # --- Documente ---
    st.subheader("Documente")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total", d["total_docs"])
    c2.metric("Ciorne", d["docs_draft"])
    c3.metric("În aprobare", d["docs_pending"])
    c4.metric("Aprobate", d["docs_approved"])
    c5.metric("Respinse", d["docs_rejected"])
    c6.metric("Anulate", d["docs_cancelled"])

    st.divider()

    # --- Sesizări ---
    st.subheader("Sesizări")
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Total", d["total_sez"])
    s2.metric("Noi", d["sez_noi"])
    s3.metric("În derulare", d["sez_active"])
    s4.metric("Finalizate", d["sez_fin"])

    st.divider()

    # --- Aprobări + Useri ---
    st.subheader("Sistem")
    a1, a2 = st.columns(2)
    a1.metric("Aprobări în așteptare", d["total_aprobari"])
    a2.metric("Utilizatori activi", d["total_useri"])