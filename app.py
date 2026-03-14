# app.py - eMapa Apa Prod (refactored)
# Punct de intrare: sidebar + login + routing catre module

import os
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select

from modules.config import BASE_DIR
from modules.database.session import SessionLocal
from modules.database.models import User
from modules.database.migrations import auto_migrate_and_seed
from modules.auth.auth import is_admin, is_secretariat, is_dg, _bcrypt_check
from modules.auth.remember_me import (
    rememberme_bootstrap_js,
    rememberme_set_token_js,
    rememberme_clear_token_js_and_reload,
    create_remember_token,
    validate_remember_token,
    revoke_current_remember_token,
    _get_query_param,
    _set_query_params_without_rt,
)
from modules.services.signature_service import (
    get_user_default_signature_rel,
    save_default_signature,
    delete_default_signature,
)
from modules.config import sig_abs_path
from modules.utils.ui_helpers import ui_result
from modules.pages.upload import render_upload
from modules.pages.archive import render_archive
from modules.pages.inbox import render_inbox
from modules.pages.secretariat_page import render_secretariat
from modules.pages.admin import render_admin
from modules.dashboard import render_dashboard
from modules.sesizari.sesizari_ui import render_sesizari

# -----------------------
# App init
# -----------------------
st.set_page_config(page_title="eMapa Apa Prod", layout="wide")
st.markdown(
    """
    <style>
      #MainMenu {visibility: hidden;}
    </style>
    """,
    unsafe_allow_html=True
)
auto_migrate_and_seed()

st.title("eMapa Apa Prod")

# Sidebar logo
logo_path = os.path.join(BASE_DIR, "assets", "logo Apa Prod v2.0.png")
if os.path.exists(logo_path):
    st.sidebar.image(logo_path)
else:
    st.sidebar.info("Lipseste logo: assets/logo Apa Prod v2.0.png")

# Auth + Menu
with st.sidebar:
    _auth_h, _auth_m = st.columns([5, 1])
    with _auth_h:
        st.header("Autentificare")
    with _auth_m:
        with st.popover("⋮"):
            st.caption("Optiuni")
            st.write("• Daca folosesti auto-login pe acest PC, poti sterge aici.")
            if st.button("Uita acest PC (sterge auto-login)", key="btn_forget_pc_pop"):
                rememberme_clear_token_js_and_reload()
                st.stop()
            st.write("• Recomandare: foloseste auto-login doar pe PC personal.")


    if "auth_user" not in st.session_state:
        st.session_state.auth_user = None

    # JS bootstrap pentru auto-login (citește token din localStorage, îl trimite temporar în ?rt=..., apoi curăță URL-ul)
    rememberme_bootstrap_js()

    # Auto-login (daca exista rt in URL)
    if st.session_state.auth_user is None:
        rt = _get_query_param("rt")
        if rt:
            au = validate_remember_token(rt)
            if au:
                st.session_state.auth_user = au
                _set_query_params_without_rt()
                st.rerun()

    if st.session_state.auth_user is None:

        with st.form("login_form", clear_on_submit=False):
            u = st.text_input("Username", key="login_user")
            p = st.text_input("Password", type="password", key="login_pass")
            remember_me = st.checkbox("Tine-ma minte (auto-login 90 zile)", key="remember_me")
            ok = st.form_submit_button("Autentificare")

        if ok:
            with SessionLocal() as db:
                user = db.execute(select(User).where(User.username == u.strip(), User.is_active == True)).scalar_one_or_none()
            if user and _bcrypt_check(p, user.password_hash):
                st.session_state.auth_user = {
                    "id": user.id,
                    "username": user.username,
                    "role": (user.role or "").strip().lower(),
                    "department": user.department,
                }
                if remember_me:
                    tok = create_remember_token(user.username)
                    rememberme_set_token_js(tok)
                st.success("Autentificat.")
                st.rerun()
            else:
                st.error("Credentiale invalide (sau user inactiv).")

        st.stop()

    st.write(f"User: **{st.session_state.auth_user['username']}** ({st.session_state.auth_user['role']})")
    st.write(f"Dept: **{st.session_state.auth_user['department']}**")

    st.divider()
    with st.expander("Semnatura predefinita (optional)", expanded=False):
        st.caption("Incarca o semnatura PNG. In Inbox aprobari poti aproba folosind semnatura predefinita (fara mouse).")
        me_u = st.session_state.auth_user["username"]

        existing_rel = get_user_default_signature_rel(me_u)
        if existing_rel and os.path.exists(sig_abs_path(existing_rel)):
            try:
                st.image(sig_abs_path(existing_rel), caption="Semnatura curenta", width=260)
            except Exception:
                st.info("Exista semnatura salvata, dar nu pot afisa preview.")

        up_sig = st.file_uploader("Incarca PNG", type=["png"], key="default_sig_upload")
        c_sig1, c_sig2 = st.columns([1, 1])
        with c_sig1:
            if st.button("Salveaza semnatura mea", type="primary", key="btn_save_default_sig"):
                if not up_sig:
                    st.error("Selecteaza un fisier PNG.")
                else:
                    okx, msgx = save_default_signature(me_u, up_sig.getvalue())
                    ui_result(okx, msgx)
                    if okx:
                        st.rerun()
        with c_sig2:
            if st.button("Sterge semnatura mea", key="btn_del_default_sig"):
                okd, msgd = delete_default_signature(me_u)
                ui_result(okd, msgd)
                st.rerun()

    if st.button("Deconectare", key="btn_logout"):
        # revoca tokenul curent (daca a fost folosit)
        revoke_current_remember_token()
        # sterge token local (browser) ca sa nu faca auto-login dupa logout
        rememberme_clear_token_js_and_reload()
        st.session_state.auth_user = None
        st.stop()

    st.divider()

# -----------------------
# Routing pagini
# -----------------------
if is_admin():
    menu = ["Dashboard", "Arhiva", "Sesizari", "Administrare"]
elif is_secretariat():
    menu = ["Dashboard", "Arhiva", "Sesizari"]
else:
    menu = ["Dashboard", "Incarcare", "Arhiva", "Inbox aprobari", "Sesizari"]

page = st.radio("Meniu", menu, index=0, key="main_menu")

if st.session_state.get("auth_user") is None:
    st.stop()

auth_user = st.session_state.auth_user

if page == "Incarcare":
    render_upload(auth_user)
elif page == "Dashboard":
    render_dashboard()
elif page == "Sesizari":
    render_sesizari(auth_user["username"], auth_user["role"])
elif page == "Arhiva":
    render_archive(auth_user)
elif page == "Inbox aprobari":
    render_inbox(auth_user)
elif page == "Secretariat":
    render_secretariat(auth_user)
elif page == "Administrare":
    render_admin(auth_user)
