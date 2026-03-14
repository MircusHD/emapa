import json
import os
from datetime import date

import pandas as pd
import streamlit as st
from sqlalchemy import select, desc

from modules.database.session import SessionLocal
from modules.database.models import Document
from modules.utils.formatting import ro_doc_status, doc_label
from modules.utils.ui_helpers import ui_result, open_pdf_in_chrome_tab
from modules.config import abs_upload_path, final_abs_path
from modules.utils.files import safe_filename
from modules.services.workflow_service import sterge_definitiv_document
from modules.services.pdf_service import build_final_pdf, build_current_pdf_bytes
from modules.services.document_service import get_document_by_identifier
from modules.auth.auth import is_admin, is_secretariat


def render_secretariat(auth_user: dict) -> None:
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
                        okd, msgd = sterge_definitiv_document(doc.id, auth_user)
                        ui_result(okd, msgd)
                        if okd:
                            st.rerun()
