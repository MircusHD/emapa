import os
import streamlit as st
from datetime import datetime, date
from io import BytesIO
from sqlalchemy import select
import numpy as np
from PIL import Image
from streamlit_drawable_canvas import st_canvas

from modules.config import BASE_DIR, FINAL_DIR, SIGNATURE_DIR
from modules.services.signature_service import load_default_signature_bytes
from modules.database.models import User as UserModel
from modules.database.session import SessionLocal
import json
from modules.sesizari.sesizari_service import (
    get_head_dept,
    get_dept_users,
    get_all_departments,
    create_sesizare,
    trimite_la_dg,
    distribuie_la_dept,
    atribuie_user,
    finalizeaza,
    delete_sesizare,
    add_sesizare_file,
    get_sesizare_files,
    get_sesizari_for_secretariat,
    get_sesizari_for_dg,
    get_sesizari_for_dept,
    redistribuie_dept,
    set_necesita_aprobare_dg,
    aproba_dg,
    get_sesizari_de_aprobat_dg,
    raport_sesizari_per_dept,
    raport_timp_mediu_rezolvare,
    raport_sesizari_per_luna,
    raport_neatribuite,
    get_sesizari_finalizate_paginate,
    set_necesita_aprobare_sef,
    aproba_sef,
    get_sesizari_de_aprobat_sef,
    get_dept_head_username,
    get_available_vizare_users,
    set_vizare_chain,
    aproba_vizare_step,
    get_sesizari_de_vizat,
)

SIG_SESIZARI_DIR = os.path.join(SIGNATURE_DIR, "sesizari", "semnaturi")

# ---------------------------------------------------------------------------
# Directorul de upload pentru sesizări
# ---------------------------------------------------------------------------
SESIZARI_UPLOAD_DIR = os.path.join(BASE_DIR, "data", "uploads", "sesizari")
os.makedirs(SESIZARI_UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Helper: salvează un fișier uploadat și returnează calea relativă
# ---------------------------------------------------------------------------
def _save_uploaded_file(uploaded_file) -> str:
    timestamp = datetime.now().timestamp()
    filename = f"{timestamp}_{uploaded_file.name}"
    abs_path = os.path.join(SESIZARI_UPLOAD_DIR, filename)
    with open(abs_path, "wb") as f:
        f.write(uploaded_file.getbuffer())
    rel_path = os.path.join("uploads", "sesizari", filename)
    return rel_path


# ---------------------------------------------------------------------------
# Helper: buton de descărcare pentru un fișier stocat cu cale relativă
# ---------------------------------------------------------------------------
def _download_button(label: str, rel_path: str, key: str) -> None:
    abs_path = os.path.join(BASE_DIR, "data", rel_path)
    if os.path.exists(abs_path):
        with open(abs_path, "rb") as f:
            st.download_button(
                label=label,
                data=f,
                file_name=os.path.basename(rel_path),
                key=key,
            )
    else:
        st.caption(f"Fișierul nu a fost găsit: {rel_path}")


# ---------------------------------------------------------------------------
# Helper: afișează detaliile unei sesizări (card expander)
# ---------------------------------------------------------------------------
def _render_sesizare_card(s, username: str, role: str, is_head: bool, head_dept: str | None) -> None:
    label = f"#{s.id} — {s.titlu} [{s.status.upper()}]"
    with st.expander(label):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Nr. înregistrare:** {s.numar_inregistrare or '—'}")
            st.markdown(f"**Titlu:** {s.titlu}")
            if s.descriere:
                st.markdown(f"**Descriere:** {s.descriere}")
            st.markdown(f"**Autor:** {s.autor or '—'}")
            st.markdown(f"**Departament:** {s.departament or '—'}")
            st.markdown(f"**Responsabil:** {s.user_responsabil or '—'}")
            st.markdown(f"**Status:** {s.status.upper()}")
        with col2:
            st.markdown(f"**Creat la:** {_fmt_dt(s.created_at)}")
            if s.trimis_la_dg_at:
                st.markdown(f"**Trimis la DG:** {_fmt_dt(s.trimis_la_dg_at)}")
            if s.distribuit_la_dept_at:
                st.markdown(f"**Distribuit la dept.:** {_fmt_dt(s.distribuit_la_dept_at)}")
            if s.atribuit_la_user_at:
                st.markdown(f"**Atribuit user:** {_fmt_dt(s.atribuit_la_user_at)}")
            if s.finalizat_at:
                st.markdown(f"**Finalizat la:** {_fmt_dt(s.finalizat_at)}")
            if s.observatii_finalizare:
                st.markdown(f"**Obs. finalizare:** {s.observatii_finalizare}")

        # PDF inițial
        if s.pdf_path:
            _download_button("Descarcă PDF inițial", s.pdf_path, key=f"pdf_init_{s.id}")

        # Fișiere atașate
        files = get_sesizare_files(s.id)
        if files:
            st.markdown("**Fișiere atașate:**")
            for idx, sf in enumerate(files):
                tip_label = sf.tip.upper() if sf.tip else "—"
                info = f"{tip_label} — {sf.uploaded_by} — {_fmt_dt(sf.uploaded_at)}"
                if sf.descriere:
                    info += f" — {sf.descriere}"
                fc1, fc2 = st.columns([3, 1])
                with fc1:
                    st.caption(info)
                with fc2:
                    _download_button(
                        "Descarcă",
                        sf.fisier_path,
                        key=f"sf_{s.id}_{idx}",
                    )

        st.divider()

        # ----------------------------------------------------------------
        # Acțiuni per rol
        # ----------------------------------------------------------------

        # --- SECRETARIAT ---
        if role == "secretariat":
            # Trimite la DG dacă status=nou
            if s.status == "nou":
                if st.button("Trimite la DG", key=f"trimite_dg_{s.id}"):
                    ok, msg = trimite_la_dg(s.id)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                    st.rerun()

            # Atribuire user dacă dept e setat dar user_responsabil lipsește
            if s.departament and not s.user_responsabil and s.status == "in_derulare":
                dept_users = get_dept_users(s.departament)
                if dept_users:
                    sel_user = st.selectbox(
                        "Atribuie user responsabil",
                        dept_users,
                        key=f"sec_sel_user_{s.id}",
                    )
                    if st.button("Atribuie user", key=f"sec_btn_user_{s.id}"):
                        ok, msg = atribuie_user(s.id, sel_user)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()

            # Ștergere sesizare (orice status)
            if st.button("Șterge sesizarea", key=f"del_{s.id}", type="secondary"):
                ok, msg = delete_sesizare(s.id)
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)
                st.rerun()

        # --- DIRECTOR GENERAL (dg fără head) ---
        elif role == "dg" and not is_head:
            if s.status == "in_derulare" and not s.departament:
                departments = get_all_departments()
                sel_dept = st.selectbox(
                    "Asociază departament",
                    departments,
                    key=f"dg_dept_{s.id}",
                )
                if st.button("Distribuie departament", key=f"dg_btn_dept_{s.id}"):
                    ok, msg = distribuie_la_dept(s.id, sel_dept)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
                    st.rerun()

        # --- ȘEF DE DEPARTAMENT (head_username al unui departament) ---
        elif is_head:
            if s.status == "in_derulare":
                # Redirecționare către alt departament
                with st.expander("Redirecționează către alt departament", expanded=False):
                    all_depts = [d for d in get_all_departments() if d != head_dept]
                    sel_dept_red = st.selectbox(
                        "Departament destinație",
                        all_depts,
                        key=f"head_redept_{s.id}",
                    )
                    if st.button("Redirecționează", key=f"head_btn_redept_{s.id}", type="secondary"):
                        ok, msg = redistribuie_dept(s.id, sel_dept_red)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()

                if not s.user_responsabil:
                    dept_users = get_dept_users(head_dept)
                    if dept_users:
                        sel_user = st.selectbox(
                            "Atribuie user din departament",
                            dept_users,
                            key=f"head_sel_user_{s.id}",
                        )
                        if st.button("Atribuie", key=f"head_btn_user_{s.id}"):
                            ok, msg = atribuie_user(s.id, sel_user)
                            if ok:
                                st.success(msg)
                            else:
                                st.error(msg)
                            st.rerun()
                    else:
                        st.warning("Nu există utilizatori activi în departament.")
                else:
                    st.info(f"Atribuit lui: {s.user_responsabil}")

        # --- USER SIMPLU ---
        else:
            if s.status == "in_derulare":
                if not s.user_responsabil:
                    btn_col1, btn_col2 = st.columns([1, 1])
                    with btn_col1:
                        if st.button("Preiau această sesizare", key=f"preiau_{s.id}"):
                            ok, msg = atribuie_user(s.id, username)
                            if ok:
                                st.success(msg)
                            else:
                                st.error(msg)
                            st.rerun()
                    with btn_col2:
                        all_depts = [d for d in get_all_departments() if d != s.departament]
                        sel_dept_r = st.selectbox("Redirecționează spre", all_depts, key=f"user_redept_sel_{s.id}", label_visibility="collapsed")
                        if st.button("Redirecționează", key=f"user_redept_btn_{s.id}", type="secondary"):
                            ok, msg = redistribuie_dept(s.id, sel_dept_r)
                            if ok:
                                st.success(msg)
                            else:
                                st.error(msg)
                            st.rerun()
                elif s.user_responsabil == username:
                    st.info("Ești responsabilul acestei sesizări.")
                    obs = st.text_area("Observații finalizare", key=f"obs_{s.id}")
                    pdf_rez = st.file_uploader(
                        "Upload PDF rezoluție (obligatoriu)",
                        type=["pdf"],
                        key=f"rez_pdf_{s.id}",
                    )

                    # Opțiuni aprobare la finalizare
                    st.markdown("**Solicitare aprobare (opțional)**")
                    fin_chk_dg = st.checkbox(
                        "Necesită aprobare Director General",
                        key=f"fin_chk_dg_{s.id}",
                    )

                    # Vizare ierarhică multi-select
                    from modules.utils.formatting import user_display_name as _udn
                    _viz_opts = get_available_vizare_users(s.id, username)
                    _viz_labels = [_udn(u) for u in _viz_opts]
                    _viz_selected_labels = st.multiselect(
                        "Trimite spre vizare (șefi, opțional):",
                        options=_viz_labels,
                        key=f"viz_sel_{s.id}",
                    )
                    _lbl_to_user = dict(zip(_viz_labels, _viz_opts))
                    _viz_usernames = [_lbl_to_user[l] for l in _viz_selected_labels if l in _lbl_to_user]

                    if st.button("Marchează finalizat", key=f"final_{s.id}"):
                        if not pdf_rez:
                            st.error("Trebuie să încarci PDF-ul rezoluției înainte de finalizare.")
                        else:
                            rel_path = _save_uploaded_file(pdf_rez)
                            add_sesizare_file(
                                sesizare_id=s.id,
                                fisier_path=rel_path,
                                tip="rezolutie",
                                uploaded_by=username,
                                descriere=obs if obs else None,
                            )
                            ok, msg = finalizeaza(
                                s.id,
                                observatii=obs,
                                necesita_aprobare_dg=fin_chk_dg,
                                necesita_aprobare_sef=False,
                            )
                            if ok and _viz_usernames:
                                set_vizare_chain(s.id, _viz_usernames)
                            if ok:
                                st.success(msg)
                            else:
                                st.error(msg)
                            st.rerun()
                else:
                    st.info(f"Se ocupă: {s.user_responsabil}")

            elif s.status == "finalizat" and s.user_responsabil == username:
                # Adaugă completare
                with st.form(key=f"completare_form_{s.id}"):
                    st.markdown("**Adaugă completare**")
                    desc_comp = st.text_area("Descriere completare (opțional)", key=f"desc_comp_{s.id}")
                    pdf_comp = st.file_uploader(
                        "Upload PDF completare",
                        type=["pdf"],
                        key=f"comp_pdf_{s.id}",
                    )
                    submitted = st.form_submit_button("Adaugă completare")
                    if submitted:
                        if not pdf_comp:
                            st.error("Trebuie să încarci un fișier PDF pentru completare.")
                        else:
                            rel_path = _save_uploaded_file(pdf_comp)
                            add_sesizare_file(
                                sesizare_id=s.id,
                                fisier_path=rel_path,
                                tip="completare",
                                uploaded_by=username,
                                descriere=desc_comp if desc_comp else None,
                            )
                            st.success("Completarea a fost adăugată.")
                            st.rerun()


# ---------------------------------------------------------------------------
# Helper: card sesizare finalizată (refolosit în toate rolurile)
# ---------------------------------------------------------------------------
def _render_finalizat_card(
    s,
    key_prefix: str,
    can_set_approval: bool = False,
    can_set_approval_sef: bool = False,
) -> None:
    with st.expander(f"#{s.id} — {s.titlu} [FINALIZAT]"):
        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"**Nr. înregistrare:** {s.numar_inregistrare or '—'}")
            st.markdown(f"**Autor:** {s.autor or '—'}")
            st.markdown(f"**Departament:** {s.departament or '—'}")
            st.markdown(f"**Responsabil:** {s.user_responsabil or '—'}")
        with col2:
            st.markdown(f"**Creat la:** {_fmt_dt(s.created_at)}")
            st.markdown(f"**Finalizat la:** {_fmt_dt(s.finalizat_at)}")
            if s.observatii_finalizare:
                st.markdown(f"**Observații:** {s.observatii_finalizare}")
        if s.pdf_path:
            _download_button("Descarcă PDF inițial", s.pdf_path, key=f"{key_prefix}_pdf_{s.id}")
        files = get_sesizare_files(s.id)
        if files:
            st.markdown("**Fișiere atașate:**")
            for idx, sf in enumerate(files):
                tip_label = sf.tip.upper() if sf.tip else "—"
                info = f"{tip_label} — {sf.uploaded_by} — {_fmt_dt(sf.uploaded_at)}"
                if sf.descriere:
                    info += f" — {sf.descriere}"
                fc1, fc2 = st.columns([3, 1])
                with fc1:
                    st.caption(info)
                with fc2:
                    _download_button("Descarcă", sf.fisier_path, key=f"{key_prefix}_sf_{s.id}_{idx}")
        # Aprobare DG
        st.divider()
        if s.dg_aprobat_la:
            st.success(f"✔ Aprobat de DG la {_fmt_dt(s.dg_aprobat_la)}")
            # PDF final cu pagina de semnături
            if s.final_pdf_path:
                abs_final = os.path.join(FINAL_DIR, s.final_pdf_path)
                if os.path.exists(abs_final):
                    with open(abs_final, "rb") as f:
                        st.download_button(
                            label="Descarcă PDF final (cu semnături)",
                            data=f,
                            file_name=f"sesizare_{s.id}_final.pdf",
                            mime="application/pdf",
                            key=f"{key_prefix}_final_pdf_{s.id}",
                        )
        else:
            checked = st.checkbox(
                "Necesită aprobare DG",
                value=bool(s.necesita_aprobare_dg),
                key=f"{key_prefix}_chk_apr_{s.id}",
                disabled=not can_set_approval,
            )
            if can_set_approval and checked != bool(s.necesita_aprobare_dg):
                set_necesita_aprobare_dg(s.id, checked)
                st.rerun()

        # Aprobare Șef Departament
        st.divider()
        if s.sef_aprobat_la:
            sef_display = s.sef_aprobator_username or "—"
            st.success(f"✔ Aprobat de Șef Dept ({sef_display}) la {_fmt_dt(s.sef_aprobat_la)}")
            if s.final_pdf_path:
                abs_final_sef = os.path.join(FINAL_DIR, s.final_pdf_path)
                if os.path.exists(abs_final_sef):
                    with open(abs_final_sef, "rb") as f:
                        st.download_button(
                            label="Descarcă PDF final (cu semnături)",
                            data=f,
                            file_name=f"sesizare_{s.id}_final.pdf",
                            mime="application/pdf",
                            key=f"{key_prefix}_final_pdf_sef_{s.id}",
                        )
        elif can_set_approval_sef:
            checked_sef = st.checkbox(
                "Necesită aprobare Șef Departament",
                value=bool(s.necesita_aprobare_sef),
                key=f"{key_prefix}_chk_sef_{s.id}",
            )
            if checked_sef != bool(s.necesita_aprobare_sef):
                set_necesita_aprobare_sef(s.id, checked_sef)
                st.rerun()
        elif s.necesita_aprobare_sef:
            st.info("Sesizare trimisă pentru aprobare șef departament.")


# ---------------------------------------------------------------------------
# Helper: formatare datetime
# ---------------------------------------------------------------------------
def _fmt_dt(dt) -> str:
    if dt is None:
        return "—"
    if isinstance(dt, datetime):
        return dt.strftime("%d.%m.%Y %H:%M")
    return str(dt)


# ---------------------------------------------------------------------------
# Tab: Rapoarte (comun pentru secretariat și DG)
# ---------------------------------------------------------------------------
def _render_tab_rapoarte() -> None:
    st.subheader("Rapoarte sesizări")

    # 1. Metrici rapide
    toate = get_sesizari_for_secretariat()
    total = len(toate)
    active = sum(1 for s in toate if s.status == "in_derulare")
    finalizate = sum(1 for s in toate if s.status == "finalizat")
    neatribuite_count = sum(
        1 for s in toate if s.status == "in_derulare" and not s.user_responsabil
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total sesizări", total)
    c2.metric("Active (în derulare)", active)
    c3.metric("Finalizate", finalizate)
    c4.metric("Neatribuite", neatribuite_count)

    st.divider()

    # 2. Sesizări per departament
    st.subheader("Sesizări per departament")
    dept_data = raport_sesizari_per_dept()
    if dept_data:
        import pandas as pd
        df_dept = pd.DataFrame(dept_data)
        st.dataframe(df_dept, width='stretch')
        chart_data = df_dept.set_index("dept")[["total", "active", "finalizate"]]
        st.bar_chart(chart_data)
    else:
        st.info("Nu există date per departament.")

    st.divider()

    # 3. Timp mediu rezolvare
    st.subheader("Timp mediu rezolvare (zile)")
    timp_data = raport_timp_mediu_rezolvare()
    if timp_data:
        import pandas as pd
        df_timp = pd.DataFrame(timp_data)
        st.dataframe(df_timp, width='stretch')
    else:
        st.info("Nu există sesizări finalizate pentru calcul.")

    st.divider()

    # 4. Sesizări pe luni (anul curent)
    an_curent = datetime.now().year
    st.subheader(f"Sesizări pe luni ({an_curent})")
    luna_data = raport_sesizari_per_luna(an_curent)
    if luna_data:
        import pandas as pd
        luni = ["Ian", "Feb", "Mar", "Apr", "Mai", "Iun", "Iul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        df_luna = pd.DataFrame(luna_data)
        df_luna["luna_label"] = df_luna["luna"].apply(lambda x: luni[x - 1])
        df_luna = df_luna.set_index("luna_label")[["total", "finalizate"]]
        st.bar_chart(df_luna)
    else:
        st.info("Nu există date pentru anul curent.")

    st.divider()

    # 5. Neatribuite
    st.subheader("Sesizări neatribuite")
    neatribuite_list = raport_neatribuite()
    if neatribuite_list:
        for s in neatribuite_list:
            st.markdown(
                f"- **#{s.id}** — {s.titlu} | Dept: {s.departament or '—'} | Creat: {_fmt_dt(s.created_at)}"
            )
    else:
        st.info("Nu există sesizări neatribuite.")


# ---------------------------------------------------------------------------
# Tab Finalizate — căutare + paginare (comun pentru toate rolurile)
# ---------------------------------------------------------------------------
_FIN_PAGE_SIZE = 20


def _render_tab_finalizate(
    key_prefix: str,
    visibility_mode: str,
    visibility_arg: str | None,
    show_dept_filter: bool = False,
    can_set_approval: bool = False,
    can_set_approval_sef: bool = False,
) -> None:
    """Randează tab-ul Finalizate cu filtre de căutare și paginare.

    visibility_mode: "all" | "dept_chain" | "user_only"
    visibility_arg: dept_name pentru "dept_chain", username pentru "user_only"
    """
    page_key = f"{key_prefix}_fin_page"
    if page_key not in st.session_state:
        st.session_state[page_key] = 0

    # --- Filtre ---
    col1, col2, col3 = st.columns([3, 2, 2])
    with col1:
        search_text = st.text_input(
            "Caută",
            key=f"{key_prefix}_fin_search",
            placeholder="titlu, autor, nr. înreg., responsabil...",
        )
    with col2:
        date_from: date | None = st.date_input(
            "De la (data creare)", value=None, key=f"{key_prefix}_fin_dfrom"
        )
    with col3:
        date_to: date | None = st.date_input(
            "Până la (data creare)", value=None, key=f"{key_prefix}_fin_dto"
        )

    filter_col1, filter_col2 = st.columns([2, 2])
    with filter_col1:
        aprobat_options = ["toate", "aprobate", "neaprobate"]
        aprobat_filter = st.selectbox(
            "Aprobare DG", aprobat_options, key=f"{key_prefix}_fin_aprobat"
        )
    if show_dept_filter:
        with filter_col2:
            dept_options = ["— toate —"] + get_all_departments()
            dept_sel = st.selectbox(
                "Departament", dept_options, key=f"{key_prefix}_fin_dept"
            )
            dept_filter = dept_sel if dept_sel != "— toate —" else None
    else:
        dept_filter = None

    # Resetează pagina când filtrele se schimbă
    fhash_key = f"{key_prefix}_fin_fhash"
    cur_hash = str((search_text, str(date_from), str(date_to), aprobat_filter, dept_filter))
    if st.session_state.get(fhash_key) != cur_hash:
        st.session_state[fhash_key] = cur_hash
        st.session_state[page_key] = 0

    current_page = st.session_state[page_key]

    # --- Interogare ---
    sesizari, total = get_sesizari_finalizate_paginate(
        visibility_mode=visibility_mode,
        visibility_arg=visibility_arg,
        search_text=search_text.strip() or None,
        departament_filter=dept_filter,
        data_from=date_from,
        data_to=date_to,
        aprobat_dg_filter=aprobat_filter,
        offset=current_page * _FIN_PAGE_SIZE,
        limit=_FIN_PAGE_SIZE,
    )

    total_pages = max(1, (total + _FIN_PAGE_SIZE - 1) // _FIN_PAGE_SIZE)
    st.caption(
        f"Total: **{total}** sesizări | Pagina **{current_page + 1}** din **{total_pages}**"
    )

    if not sesizari:
        st.info("Nu există sesizări finalizate pentru criteriile selectate.")
    else:
        for s in sesizari:
            _render_finalizat_card(
                s,
                key_prefix=f"{key_prefix}_p{current_page}",
                can_set_approval=can_set_approval,
                can_set_approval_sef=can_set_approval_sef,
            )

    # --- Paginare ---
    pc1, _pc2, pc3 = st.columns([1, 3, 1])
    with pc1:
        if current_page > 0 and st.button("◀ Anterior", key=f"{key_prefix}_fin_prev"):
            st.session_state[page_key] -= 1
            st.rerun()
    with pc3:
        if current_page < total_pages - 1 and st.button(
            "Următor ▶", key=f"{key_prefix}_fin_next"
        ):
            st.session_state[page_key] += 1
            st.rerun()


# ---------------------------------------------------------------------------
# Funcția principală
# ---------------------------------------------------------------------------
def render_sesizari(username: str, role: str) -> None:
    st.title("Sesizări / Reclamații")

    # Detectează șeful de departament
    is_head, head_dept = get_head_dept(username)

    # ========================================================================
    # SECRETARIAT
    # ========================================================================
    if role == "secretariat":
        tab_creare, tab_active, tab_finalizate, tab_rapoarte = st.tabs(
            ["Creare", "Active", "Finalizate", "Rapoarte"]
        )

        # --- Tab Creare ---
        with tab_creare:
            st.subheader("Creare sesizare nouă")
            titlu = st.text_input("Titlu *", key="creare_titlu")
            numar_inreg = st.text_input(
                "Nr. înregistrare",
                value="",
                key="creare_numar",
            )
            descriere = st.text_area("Descriere (opțional)", key="creare_descriere")
            pdf_file = st.file_uploader(
                "Upload PDF sesizare (opțional)", type=["pdf"], key="creare_pdf"
            )

            # Dezactivează butonul pe rerune-ul imediat după salvare (previne dublu-click)
            _btn_disabled = st.session_state.pop("creare_just_saved", False)

            if st.button("Salvează sesizarea", key="creare_btn_salveaza", disabled=_btn_disabled):
                if not titlu.strip():
                    st.warning("Titlul este obligatoriu.")
                elif not numar_inreg.strip():
                    st.warning("Numărul de înregistrare este obligatoriu.")
                else:
                    pdf_path = None
                    if pdf_file:
                        pdf_path = _save_uploaded_file(pdf_file)
                    sesizare = create_sesizare(
                        autor=username,
                        titlu=titlu.strip(),
                        numar_inreg=numar_inreg.strip(),
                        descriere=descriere.strip() if descriere else None,
                        pdf_path=pdf_path,
                    )
                    # Marchează: buton dezactivat pe rerune-ul următor + golește formularul
                    st.session_state["creare_just_saved"] = True
                    for _k in ["creare_titlu", "creare_numar", "creare_descriere"]:
                        st.session_state.pop(_k, None)
                    st.success(f"Sesizarea #{sesizare.id} a fost salvată cu succes.")
                    st.rerun()

        # --- Tab Active ---
        with tab_active:
            st.subheader("Sesizări active (nou + în derulare)")
            sesizari = get_sesizari_for_secretariat(status_filter=["nou", "in_derulare"])
            if not sesizari:
                st.info("Nu există sesizări active.")
            else:
                for s in sesizari:
                    _render_sesizare_card(s, username, role, is_head, head_dept)

        # --- Tab Finalizate ---
        with tab_finalizate:
            st.subheader("Sesizări finalizate")
            _render_tab_finalizate(
                key_prefix="sec",
                visibility_mode="all",
                visibility_arg=None,
                show_dept_filter=True,
                can_set_approval=False,
                can_set_approval_sef=False,
            )

        # --- Tab Rapoarte ---
        with tab_rapoarte:
            _render_tab_rapoarte()

    # ========================================================================
    # ȘEF DE DEPARTAMENT (head_username al unui departament, indiferent de rol)
    # ========================================================================
    elif is_head:
        tab_dept, tab_fin, tab_apr_sef = st.tabs(["Departament", "Finalizate", "De aprobat"])

        # --- Tab Departament ---
        with tab_dept:
            st.subheader(f"Sesizări departament: {head_dept}")
            sesizari = get_sesizari_for_dept(head_dept, status_filter=["in_derulare"])
            if not sesizari:
                st.info("Nu există sesizări în derulare pentru departamentul tău.")
            else:
                for s in sesizari:
                    _render_sesizare_card(s, username, role, is_head, head_dept)

        # --- Tab Finalizate ---
        with tab_fin:
            st.subheader(f"Sesizări finalizate — {head_dept}")
            _render_tab_finalizate(
                key_prefix="head",
                visibility_mode="dept_chain",
                visibility_arg=head_dept,
                show_dept_filter=False,
                can_set_approval=False,
                can_set_approval_sef=True,
            )

        # --- Tab De aprobat (șef dept) ---
        with tab_apr_sef:
            st.subheader(f"Sesizări în așteptare aprobare / vizare — {head_dept}")
            de_aprobat_sef = get_sesizari_de_aprobat_sef(username, head_dept)
            de_vizat = get_sesizari_de_vizat(username)
            # Combină și deduplică (vizare poate apărea și în lista veche dacă are necesita_aprobare_sef=True)
            _ids_sef = {s.id for s in de_aprobat_sef}
            de_aprobat_sef = de_aprobat_sef + [s for s in de_vizat if s.id not in _ids_sef]
            if not de_aprobat_sef:
                st.info("Nu există sesizări în așteptare de aprobare pentru departamentul tău.")
            else:
                for s in de_aprobat_sef:
                    with st.expander(f"#{s.id} — {s.titlu} | Responsabil: {s.user_responsabil or '—'}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Nr. înregistrare:** {s.numar_inregistrare or '—'}")
                            st.markdown(f"**Departament:** {s.departament or '—'}")
                            st.markdown(f"**Responsabil:** {s.user_responsabil or '—'}")
                        with col2:
                            st.markdown(f"**Finalizat la:** {_fmt_dt(s.finalizat_at)}")
                            if s.observatii_finalizare:
                                st.markdown(f"**Observații:** {s.observatii_finalizare}")
                        files = get_sesizare_files(s.id)
                        if files:
                            st.markdown("**Fișiere rezoluție:**")
                            for idx, sf in enumerate(files):
                                fc1, fc2 = st.columns([3, 1])
                                with fc1:
                                    st.caption(f"{sf.tip.upper()} — {sf.uploaded_by} — {_fmt_dt(sf.uploaded_at)}")
                                with fc2:
                                    _download_button("Descarcă", sf.fisier_path, key=f"sef_apr_sf_{s.id}_{idx}")

                st.divider()
                options_sef = {f"#{s.id} — {s.titlu}": s.id for s in de_aprobat_sef}
                sel_label_sef = st.selectbox(
                    "Selectează sesizarea de aprobat",
                    list(options_sef.keys()),
                    key="sef_apr_select",
                )
                sel_id_sef = options_sef[sel_label_sef] if sel_label_sef else None

                st.divider()
                st.markdown("### Semnătură aprobare (obligatorie)")

                default_sig_sef = load_default_signature_bytes(username)
                has_default_sef = bool(default_sig_sef)

                use_default_sef = st.checkbox(
                    "Folosește semnătura predefinită (fără mouse)",
                    value=True if has_default_sef else False,
                    key="sef_apr_use_default",
                )
                if use_default_sef and not has_default_sef:
                    st.warning("Nu ai semnătură predefinită salvată. În sidebar poți încărca una (PNG).")
                    use_default_sef = False

                if "sef_apr_show_manual" not in st.session_state:
                    st.session_state["sef_apr_show_manual"] = False

                if st.button("Semnătură manuală (cu mouse)", key="sef_apr_show_manual_btn"):
                    st.session_state["sef_apr_show_manual"] = True
                    st.rerun()

                sig_bytes_sef = None
                if use_default_sef and default_sig_sef:
                    sig_bytes_sef = default_sig_sef
                    st.caption("Se va folosi semnătura predefinită.")
                else:
                    if st.session_state["sef_apr_show_manual"]:
                        canvas_result_sef = st_canvas(
                            fill_color="rgba(0,0,0,0)",
                            stroke_width=3,
                            stroke_color="#000000",
                            background_color="#FFFFFF",
                            height=150,
                            width=520,
                            drawing_mode="freedraw",
                            key=f"sef_canvas_{sel_id_sef}",
                        )
                        if canvas_result_sef.image_data is not None:
                            try:
                                arr = np.array(canvas_result_sef.image_data).astype("uint8")
                                img_c = Image.fromarray(arr)
                                bbox = img_c.convert("RGB").point(lambda p: p < 250 and 255).getbbox()
                                if bbox:
                                    img_c = img_c.crop(bbox)
                                out = BytesIO()
                                img_c.save(out, format="PNG")
                                sig_bytes_sef = out.getvalue()
                            except Exception:
                                sig_bytes_sef = None
                    else:
                        st.info("Pentru semnătură cu mouse, apasă butonul de mai sus.")

                if st.button("Aprobă / Vizează sesizarea", type="primary", key="sef_apr_confirm"):
                    if not sel_id_sef:
                        st.error("Selectează o sesizare.")
                    elif not sig_bytes_sef:
                        st.error("Semnătura lipsește.")
                    else:
                        # Detectează tipul: vizare chain vs. aprobare simplă
                        _sel_sz = next((s for s in de_aprobat_sef if s.id == sel_id_sef), None)
                        if _sel_sz and _sel_sz.vizare_current_approver == username:
                            ok_sef, msg_sef = aproba_vizare_step(sel_id_sef, username, sig_bytes_sef, SIG_SESIZARI_DIR)
                        else:
                            ok_sef, msg_sef = aproba_sef(sel_id_sef, sig_bytes_sef, SIG_SESIZARI_DIR, username)
                        if ok_sef:
                            st.session_state["sef_apr_show_manual"] = False
                            st.success(msg_sef)
                            st.rerun()
                        else:
                            st.error(msg_sef)

    # ========================================================================
    # DIRECTOR GENERAL (dg fără head)
    # ========================================================================
    elif role == "dg":
        tab_derulare, tab_fin, tab_aprobare, tab_rapoarte = st.tabs(
            ["În derulare", "Finalizate", "De aprobat", "Rapoarte"]
        )

        # --- Tab În derulare ---
        with tab_derulare:
            st.subheader("Sesizări în derulare")
            sesizari = get_sesizari_for_dg(status_filter=["in_derulare"])
            if not sesizari:
                st.info("Nu există sesizări în derulare.")
            else:
                for s in sesizari:
                    _render_sesizare_card(s, username, role, is_head, head_dept)

        # --- Tab Finalizate ---
        with tab_fin:
            st.subheader("Sesizări finalizate")
            _render_tab_finalizate(
                key_prefix="dg",
                visibility_mode="all",
                visibility_arg=None,
                show_dept_filter=True,
                can_set_approval=True,
                can_set_approval_sef=True,
            )

        # --- Tab De aprobat ---
        with tab_aprobare:
            st.subheader("Sesizări trimise pentru aprobare DG")
            de_aprobat = get_sesizari_de_aprobat_dg()
            if not de_aprobat:
                st.info("Nu există sesizări în așteptare de aprobare.")
            else:
                # Lista sesizărilor cu detalii
                for s in de_aprobat:
                    with st.expander(f"#{s.id} — {s.titlu} | Responsabil: {s.user_responsabil or '—'}"):
                        col1, col2 = st.columns(2)
                        with col1:
                            st.markdown(f"**Nr. înregistrare:** {s.numar_inregistrare or '—'}")
                            st.markdown(f"**Departament:** {s.departament or '—'}")
                            st.markdown(f"**Responsabil:** {s.user_responsabil or '—'}")
                        with col2:
                            st.markdown(f"**Finalizat la:** {_fmt_dt(s.finalizat_at)}")
                            if s.observatii_finalizare:
                                st.markdown(f"**Observații:** {s.observatii_finalizare}")
                        files = get_sesizare_files(s.id)
                        if files:
                            st.markdown("**Fișiere rezoluție:**")
                            for idx, sf in enumerate(files):
                                fc1, fc2 = st.columns([3, 1])
                                with fc1:
                                    st.caption(f"{sf.tip.upper()} — {sf.uploaded_by} — {_fmt_dt(sf.uploaded_at)}")
                                with fc2:
                                    _download_button("Descarcă", sf.fisier_path, key=f"dg_apr_sf_{s.id}_{idx}")

                st.divider()

                # Selectare sesizare de aprobat
                options = {f"#{s.id} — {s.titlu}": s.id for s in de_aprobat}
                sel_label = st.selectbox(
                    "Selectează sesizarea de aprobat",
                    list(options.keys()),
                    key="dg_apr_select",
                )
                sel_id = options[sel_label] if sel_label else None

                st.divider()
                st.markdown("### Semnătură aprobare (obligatorie)")

                default_sig = load_default_signature_bytes(username)
                has_default = bool(default_sig)

                use_default = st.checkbox(
                    "Folosește semnătura predefinită (fără mouse)",
                    value=True if has_default else False,
                    key="dg_apr_use_default",
                )
                if use_default and not has_default:
                    st.warning("Nu ai semnătură predefinită salvată. În sidebar poți încărca una (PNG).")
                    use_default = False

                if "dg_apr_show_manual" not in st.session_state:
                    st.session_state["dg_apr_show_manual"] = False

                if st.button("Semnătură manuală (cu mouse)", key="dg_apr_show_manual_btn"):
                    st.session_state["dg_apr_show_manual"] = True
                    st.rerun()

                sig_bytes = None
                if use_default and default_sig:
                    sig_bytes = default_sig
                    st.caption("Se va folosi semnătura predefinită.")
                else:
                    if st.session_state["dg_apr_show_manual"]:
                        canvas_result = st_canvas(
                            fill_color="rgba(0,0,0,0)",
                            stroke_width=3,
                            stroke_color="#000000",
                            background_color="#FFFFFF",
                            height=150,
                            width=520,
                            drawing_mode="freedraw",
                            key=f"dg_canvas_{sel_id}",
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
                        st.info("Pentru semnătură cu mouse, apasă butonul de mai sus.")

                if st.button("Aprobă sesizarea", type="primary", key="dg_apr_confirm"):
                    if not sel_id:
                        st.error("Selectează o sesizare.")
                    elif not sig_bytes:
                        st.error("Semnătura lipsește.")
                    else:
                        ok, msg = aproba_dg(sel_id, sig_bytes, SIG_SESIZARI_DIR)
                        if ok:
                            st.session_state["dg_apr_show_manual"] = False
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        # --- Tab Rapoarte ---
        with tab_rapoarte:
            _render_tab_rapoarte()

    # ========================================================================
    # USER SIMPLU
    # ========================================================================
    else:
        # Determinăm departamentul userului
        with SessionLocal() as db:
            u = db.execute(
                select(UserModel).where(UserModel.username == username)
            ).scalars().first()
            user_dept = u.department if u else None

        tab_dept_ses, tab_ale_mele, tab_fin_dept = st.tabs(
            ["Sesizările departamentului", "Finalizate ale mele", "Finalizate departament"]
        )

        # --- Tab Sesizările departamentului ---
        with tab_dept_ses:
            st.subheader("Sesizări în derulare — departamentul meu")
            if not user_dept:
                st.warning("Nu ești asociat niciunui departament.")
            else:
                sesizari = get_sesizari_for_dept(user_dept, status_filter=["in_derulare"])
                if not sesizari:
                    st.info("Nu există sesizări în derulare pentru departamentul tău.")
                else:
                    for s in sesizari:
                        _render_sesizare_card(s, username, role, is_head, head_dept)

        # --- Tab Finalizate ale mele ---
        with tab_ale_mele:
            st.subheader("Sesizările mele finalizate")
            _render_tab_finalizate(
                key_prefix="user",
                visibility_mode="user_only",
                visibility_arg=username,
                show_dept_filter=False,
                can_set_approval=True,
                can_set_approval_sef=True,
            )

        # --- Tab Finalizate departament ---
        with tab_fin_dept:
            st.subheader("Sesizări finalizate — departamentul meu")
            if not user_dept:
                st.warning("Nu ești asociat niciunui departament.")
            else:
                _render_tab_finalizate(
                    key_prefix="user_dept_fin",
                    visibility_mode="dept_chain",
                    visibility_arg=user_dept,
                    show_dept_filter=False,
                    can_set_approval=False,
                    can_set_approval_sef=False,
                )