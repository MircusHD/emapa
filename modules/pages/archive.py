import os
import json
from datetime import datetime, date
from typing import Optional
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select, and_, or_, desc, func
from modules.database.session import SessionLocal
from modules.database.models import Document, Approval, DocType
from modules.config import abs_upload_path, final_abs_path, sig_abs_path, FINAL_DIR
from modules.utils.files import safe_filename, normalize_dept
from modules.utils.formatting import (
    ro_doc_status, ro_approval_status, doc_label,
    user_display_name, user_display_with_title
)
from modules.utils.ui_helpers import (
    ui_result, open_pdf_in_chrome_tab,
    _set_scroll_to_workflow, _scroll_to_workflow_if_needed,
    _set_scroll_to_registry, _scroll_to_registry_if_needed,
    _select_code_from_dataframe
)
from modules.services.document_service import get_document_by_identifier
from modules.services.workflow_service import (
    start_workflow, cancel_to_draft, cancel_document,
    sterge_definitiv_document, effective_workflow, user_can_view_document
)
from modules.services.pdf_service import build_final_pdf, build_current_pdf_bytes
from modules.workflow.workflow_builder import render_workflow_builder, wf_pretty
from modules.auth.auth import is_admin, is_secretariat
from modules.services.log_service import log_event
from modules.departments.dept_service import get_descendant_departments


def render_archive(auth_user: dict) -> None:
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
                    Document.tags_json.ilike(qq),
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
                okd, msgd = sterge_definitiv_document(doc.id, auth_user)
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
            u = auth_user or {}
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
                "reg_no": d.reg_no,
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
                elif not user_can_view_document(doc, auth_user):
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
        elif not user_can_view_document(doc_dl, auth_user):
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
                    ok, msg = start_workflow(doc.id, auth_user)
                    if ok:
                        log_event("document_workflow_start", category="document", username=auth_user.get("username"), details=f"Workflow pornit din arhivă pentru doc {doc.public_id or doc.id}", target_id=doc.id)
                ui_result(ok, msg)

        if st.button("Anuleaza workflow -> CIORNA (IN APROBARE)", key="btn_archive_cancel_to_draft"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = cancel_to_draft(doc.id, auth_user)
                ui_result(ok, msg)

        if st.button("Anuleaza document (nu APROBAT)", key="btn_archive_cancel_doc"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = cancel_document(doc.id, auth_user)
                ui_result(ok, msg)

        st.divider()
        st.caption("Editare workflow (doar CIORNA)")
        if doc_id.strip():
            doc = get_document_by_identifier(doc_id.strip())
            if doc and doc.status == "DRAFT":
                if is_admin() or is_secretariat() or doc.created_by == auth_user["username"]:
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
                        ok, msg = sterge_definitiv_document(doc.id, auth_user)
                    ui_result(ok, msg)
                    if ok:
                        st.rerun()


    # -----------------------
    # Approvals inbox
    # -----------------------
