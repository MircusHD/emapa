import os
import json
import uuid
from datetime import datetime, date
from typing import List
import streamlit as st
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import Document, DocType
from modules.config import UPLOAD_DIR, abs_upload_path, rel_upload_path
from modules.utils.files import sha256_bytes, safe_filename, parse_tags, normalize_dept
from modules.utils.ui_helpers import ui_result
from modules.services.document_service import generate_public_id
from modules.services.workflow_service import start_workflow
from modules.workflow.workflow_builder import render_workflow_builder
from modules.auth.auth import is_dg
from modules.utils.formatting import ro_doc_status


def render_upload(auth_user: dict) -> None:
    if is_dg():
        st.error("Directorul General nu poate incarca documente.")
        st.stop()

    st.subheader("Upload document (PDF)")

    dept = auth_user["department"]
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
                        created_by=auth_user["username"],
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
                ok, msg = start_workflow(doc.id, auth_user)
                ui_result(ok, msg)
                if ok:
                    st.rerun()
