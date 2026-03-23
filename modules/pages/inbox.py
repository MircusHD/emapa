import streamlit as st
from streamlit_drawable_canvas import st_canvas
import numpy as np
import pandas as pd
from PIL import Image
from io import BytesIO
from sqlalchemy import select, and_
from modules.database.session import SessionLocal
from modules.database.models import Document, Approval
from modules.utils.formatting import doc_label, user_display_name, ro_approval_status, ro_doc_status
from modules.utils.ui_helpers import _select_code_from_dataframe, open_pdf_in_chrome_tab, ui_result
from modules.services.document_service import get_document_by_identifier
from modules.services.workflow_service import decide, get_available_escalation_users
from modules.services.pdf_service import build_current_pdf_bytes
from modules.services.signature_service import load_default_signature_bytes


def render_inbox(auth_user: dict) -> None:
    st.subheader("Inbox aprobari")

    me = auth_user["username"]
    with SessionLocal() as db:
        pending = db.execute(
            select(Approval).where(and_(Approval.approver_username == me, Approval.status == "PENDING"))
        ).scalars().all()

    if not pending:
        st.info("Nu ai aprobari in asteptare.")
        st.stop()

    rows = []
    with SessionLocal() as db:
        for a in pending:
            doc = db.execute(select(Document).where(Document.id == a.document_id)).scalar_one()
            rows.append(
                {
                    "cod": doc.public_id or "",
                    "document_id": doc.id,
                    "document": doc_label(doc),
                    "departament": doc.department,
                    "pas": a.step_order,
                    "tip": "Vizare" if a.is_escalation_node else "Aprobare",
                    "creat_de": user_display_name(doc.created_by),
                    "creat_la": doc.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
    # Tabel selectabil: click pe rand -> completeaza automat campul "Cod document"
    df_pending = pd.DataFrame(rows).reset_index(drop=True)
    sel_code = _select_code_from_dataframe(df_pending, key="approvals_table_select", code_col="cod", id_col="document_id")
    if sel_code:
        st.session_state["approvals_doc_id"] = sel_code

    st.divider()
    doc_id = st.text_input("Cod document (ex: EM-A9K3X7) pentru decizie", key="approvals_doc_id")
    comment = st.text_area("Comentariu (optional)", key="approvals_comment")

    # Secțiunea de vizare ierarhică opțională
    escalation_options = []
    escalation_user_labels = []
    if doc_id and doc_id.strip():
        _doc_esc = get_document_by_identifier(doc_id.strip())
        if _doc_esc:
            escalation_options = get_available_escalation_users(_doc_esc.id, me)
            escalation_user_labels = [user_display_name(u) for u in escalation_options]

    escalate_to = None
    if escalation_options:
        st.divider()
        st.markdown("### Vizare ierarhica (optional)")
        selected_labels = st.multiselect(
            "Trimite spre vizare (unul sau mai multi sefi):",
            options=escalation_user_labels,
            key="multisel_escalate",
        )
        if selected_labels:
            # Mapăm label → username
            label_to_user = dict(zip(escalation_user_labels, escalation_options))
            escalate_to = [label_to_user[lbl] for lbl in selected_labels if lbl in label_to_user]
            st.caption(f"Documentul va fi trimis spre vizare: **{', '.join(selected_labels)}**")

    st.divider()
    if st.button("Previzualizare document (deschide in Chrome)", key="btn_preview_chrome"):
        if not doc_id.strip():
            st.error("Introdu cod document.")
        else:
            doc = get_document_by_identifier(doc_id.strip())
            if not doc:
                st.error("Document inexistent.")
            else:
                okp, pdfb, msgp = build_current_pdf_bytes(doc.id)
            if not okp:
                st.error(str(msgp))
            else:
                open_pdf_in_chrome_tab(pdfb)

    st.divider()
    st.markdown("### Semnatura (obligatorie la APROBARE)")

    me_user = auth_user["username"]
    default_sig = load_default_signature_bytes(me_user)
    has_default = bool(default_sig)

    # Prefer default signature if available
    use_default = st.checkbox(
        "Foloseste semnatura predefinita (fara mouse)",
        value=True if has_default else False,
        key="use_default_signature",
    )

    if use_default and not has_default:
        st.warning("Nu ai semnatura predefinita salvata. In sidebar poti incarca una (PNG).")
        use_default = False

    if "show_manual_signature" not in st.session_state:
        st.session_state.show_manual_signature = False

    if st.button("Semnatura manuala (cu mouse)", key="btn_show_manual_sig"):
        st.session_state.show_manual_signature = True
        st.rerun()

    sig_bytes = None

    # If default selected, use it
    if use_default and default_sig:
        sig_bytes = default_sig
        st.caption("Se va folosi semnatura predefinita.")
    else:
        # Manual signature is hidden by default; show only after button
        if st.session_state.show_manual_signature:
            canvas_result = st_canvas(
                fill_color="rgba(0,0,0,0)",
                stroke_width=3,
                stroke_color="#000000",
                background_color="#FFFFFF",
                height=150,
                width=520,
                drawing_mode="freedraw",
                key="sig_canvas",
            )

            if canvas_result.image_data is not None:
                try:
                    arr = np.array(canvas_result.image_data).astype("uint8")
                    img = Image.fromarray(arr)
                    bbox = img.convert("RGB").point(lambda p: p < 250 and 255).getbbox()
                    if bbox:
                        img = img.crop(bbox)
                    out = BytesIO()
                    img.save(out, format="PNG")
                    sig_bytes = out.getvalue()
                except Exception:
                    sig_bytes = None
        else:
            st.info("Pentru semnatura cu mouse, apasa butonul de mai sus.")
    a, b = st.columns([1, 1])
    with a:
        approve_label = "Aproba + Trimite spre vizare" if escalate_to else "Aproba"
        if st.button(approve_label, type="primary", key="btn_approve"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    decision_type = "APPROVE_AND_ESCALATE" if escalate_to else "APPROVE"
                    ok, msg = decide(doc.id, me, decision_type, comment,
                                     signature_png_bytes=sig_bytes, escalate_to=escalate_to)
                ui_result(ok, msg)
                if ok:
                    st.rerun()
    with b:
        if st.button("Respinge", key="btn_reject"):
            if not doc_id.strip():
                st.error("Introdu cod document.")
            else:
                doc = get_document_by_identifier(doc_id.strip())
                if not doc:
                    ui_result(False, "Document inexistent.")
                else:
                    ok, msg = decide(doc.id, me, "REJECT", comment, signature_png_bytes=None)
                ui_result(ok, msg)
                if ok:
                    st.rerun()
