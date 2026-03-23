import uuid

import pandas as pd
import streamlit as st
from sqlalchemy import select

from modules.database.session import SessionLocal
from modules.database.models import User, Department, Approval, Document, DocType
from modules.config import DG_DEPT, ORG_DEPARTMENTS
from modules.utils.files import normalize_dept
from modules.auth.auth import is_admin, _bcrypt_hash, _bcrypt_check
from modules.auth.remember_me import revoke_all_tokens_for_user
from modules.services.log_service import log_event, get_logs, get_log_stats, delete_old_logs
from modules.services.backup_service import (
    create_backup, list_backups, restore_from_file,
    restore_from_upload, get_backup_bytes, delete_backup,
)


def render_admin(auth_user: dict) -> None:
    if not is_admin():
        st.error("Fara acces.")
        st.stop()

    st.subheader("Admin")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Utilizatori", "Departamente (sef + parinte)", "Schimba parola mea", "Loguri sistem", "Backup / Restaurare"])

    with tab1:
        st.markdown("### Creeaza utilizator")
        nu = st.text_input("Username *", key="new_user")
        npw = st.text_input("Password *", type="password", key="new_pass")
        nr = st.selectbox("Role", ["user", "secretariat", "admin"], index=0, key="new_role")
        nfull = st.text_input("Nume complet (ex: Dorin Gligor)", key="new_full")
        njob = st.text_input("Functie (ex: Director General)", key="new_job")

        with SessionLocal() as db:
            deps = db.execute(select(Department).order_by(Department.name)).scalars().all()
        dep_names = [d.name for d in deps] if deps else ORG_DEPARTMENTS
        nd = st.selectbox("Department *", dep_names, key="new_dept")

        if st.button("Creeaza", type="primary", key="btn_create_user"):
            if not nu.strip() or not npw.strip():
                st.error("Username si password sunt obligatorii.")
            else:
                with SessionLocal() as db:
                    exists = db.execute(select(User).where(User.username == nu.strip())).scalar_one_or_none()
                    if exists:
                        st.error("User existent.")
                    else:
                        db.add(
                            User(
                                id=str(uuid.uuid4()),
                                username=nu.strip(),
                                password_hash=_bcrypt_hash(npw.strip()),
                                role=nr,
                                department=normalize_dept(nd),
                                is_active=True,
                                full_name=nfull.strip() or None,
                                job_title=njob.strip() or None,
                            )
                        )
                        db.commit()
                        log_event("create_user", category="admin", username=auth_user["username"], details=f"User creat: {nu.strip()} | rol: {nr} | dept: {nd}", target_id=nu.strip())
                        st.success("User creat.")
                        st.rerun()

        st.divider()
        with SessionLocal() as db:
            users = db.execute(select(User).order_by(User.username)).scalars().all()
        st.dataframe(
            pd.DataFrame([
                {
                    "username": u.username,
                    "nume": (u.full_name or ""),
                    "functie": (u.job_title or ""),
                    "role": u.role,
                    "department": u.department,
                    "active": bool(u.is_active),
                }
                for u in users
            ]),
            hide_index=True,
        )

        st.divider()
        st.markdown("### Editeaza utilizator (rol/departament/activ)")
        usernames = [u.username for u in users]
        if usernames:
            sel_u = st.selectbox("User", usernames, key="edit_sel")
            with SessionLocal() as db:
                u = db.execute(select(User).where(User.username == sel_u)).scalar_one()

            role_list = ["user", "secretariat", "admin"]
            idx_role = role_list.index(u.role) if u.role in role_list else 0
            new_role = st.selectbox("Role", role_list, index=idx_role, key="edit_role")

            idx_dept = dep_names.index(u.department) if u.department in dep_names else 0
            new_dept = st.selectbox("Department", dep_names, index=idx_dept, key="edit_dept")

            new_active = st.checkbox("Active", value=bool(u.is_active), key="edit_active")
            new_full = st.text_input("Nume complet", value=(u.full_name or ""), key="edit_full")
            new_job = st.text_input("Functie", value=(u.job_title or ""), key="edit_job")

            if st.button("Salveaza utilizator", type="primary", key="btn_save_user"):
                with SessionLocal() as db:
                    u2 = db.execute(select(User).where(User.username == sel_u)).scalar_one()
                    u2.role = new_role
                    u2.department = normalize_dept(new_dept)
                    u2.is_active = bool(new_active)
                    u2.full_name = new_full.strip() or None
                    u2.job_title = new_job.strip() or None
                    db.commit()
                log_event("edit_user", category="admin", username=auth_user["username"], details=f"Editat: {sel_u} | rol: {new_role} | dept: {new_dept} | activ: {new_active}", target_id=sel_u)
                st.success("Salvat.")
                st.rerun()
        st.divider()
        st.markdown("### Dezactivare / Stergere user")

        if usernames:
            target_u = st.selectbox("Selecteaza user", usernames, key="manage_user_sel")
            col_m1, col_m2 = st.columns([1, 1])

            with col_m1:
                conf_deact = st.checkbox("Confirm dezactivarea", key="conf_deactivate_user")
                if st.button("Dezactiveaza user", type="primary", key="btn_deactivate_user"):
                    if not conf_deact:
                        st.error("Bifeaza confirmarea pentru dezactivare.")
                    elif target_u == "admin":
                        st.error("Nu poti dezactiva contul admin principal.")
                    elif target_u == auth_user["username"]:
                        st.error("Nu poti dezactiva contul cu care esti logat.")
                    else:
                        with SessionLocal() as db:
                            u3 = db.execute(select(User).where(User.username == target_u)).scalar_one_or_none()
                            if not u3:
                                st.error("User inexistent.")
                            else:
                                u3.is_active = False
                                db.commit()
                                log_event("deactivate_user", category="admin", username=auth_user["username"], details=f"User dezactivat: {target_u}", target_id=target_u)
                                st.success("User dezactivat.")
                                st.rerun()

            with col_m2:
                st.caption("Stergere definitiva este permisa doar daca user-ul nu are referinte (documente/aprobari/sef departament/workflow).")
                conf_del = st.checkbox("Confirm stergerea definitiva", key="conf_hard_delete_user")
                token = st.text_input("Scrie exact username pentru confirmare", value="", key="hard_delete_token")
                if st.button("Sterge definitiv user", key="btn_hard_delete_user"):
                    if not conf_del:
                        st.error("Bifeaza confirmarea pentru stergere definitiva.")
                    elif token.strip() != target_u:
                        st.error("Confirmarea nu coincide (scrie exact username).")
                    elif target_u == "admin":
                        st.error("Nu poti sterge contul admin principal.")
                    elif target_u == auth_user["username"]:
                        st.error("Nu poti sterge contul cu care esti logat.")
                    else:
                        with SessionLocal() as db:
                            # Verificari referinte
                            docs_cnt = len(db.execute(select(Document.id).where(Document.created_by == target_u)).all())
                            appr_cnt = len(db.execute(select(Approval.id).where(Approval.approver_username == target_u)).all())
                            head_cnt = len(db.execute(select(Department.name).where(Department.head_username == target_u)).all())
                            dt_cnt = len(db.execute(select(DocType.name).where(DocType.workflow_json.like(f'%"{target_u}"%'))).all())
                            dw_cnt = len(db.execute(select(Document.id).where(Document.workflow_json.like(f'%"{target_u}"%'))).all())

                            total = docs_cnt + appr_cnt + head_cnt + dt_cnt + dw_cnt
                            if total > 0:
                                st.error(
                                    f"Nu pot sterge: exista referinte -> documente create: {docs_cnt}, aprobari: {appr_cnt}, "
                                    f"sef departament: {head_cnt}, doc types workflow: {dt_cnt}, document workflow: {dw_cnt}. "
                                    "Recomandare: Dezactiveaza user."
                                )
                            else:
                                udel = db.execute(select(User).where(User.username == target_u)).scalar_one_or_none()
                                if not udel:
                                    st.error("User inexistent.")
                                else:
                                    db.delete(udel)
                                    db.commit()
                                    log_event("delete_user", level="WARNING", category="admin", username=auth_user["username"], details=f"User șters definitiv: {target_u}", target_id=target_u)
                                    st.success("User sters definitiv.")
                                    st.rerun()


        st.divider()
        st.markdown("### Reseteaza parola utilizator")
        ru = st.text_input("Username", key="reset_user")
        rp = st.text_input("New password", type="password", key="reset_pass")
        if st.button("Reseteaza parola", key="btn_reset_pass"):
            if not ru.strip() or not rp.strip():
                st.error("Completeaza ambele campuri.")
            else:
                with SessionLocal() as db:
                    u = db.execute(select(User).where(User.username == ru.strip())).scalar_one_or_none()
                    if not u:
                        st.error("User inexistent.")
                    else:
                        u.password_hash = _bcrypt_hash(rp.strip())
                        db.commit()
                        revoke_all_tokens_for_user(ru.strip())
                        log_event("reset_password", category="admin", username=auth_user["username"], details=f"Parolă resetată pentru: {ru.strip()}", target_id=ru.strip())
                        st.success("Parola resetata.")

    with tab2:
        st.info(f"IMPORTANT: seteaza un sef pentru departamentul {DG_DEPT} (Director General / GENERAL).")

        with SessionLocal() as db:
            deps = db.execute(select(Department).order_by(Department.name)).scalars().all()
            active_users = db.execute(select(User).where(User.is_active == True).order_by(User.username)).scalars().all()

        dep_names = [d.name for d in deps]
        user_names = [u.username for u in active_users]

        st.dataframe(
            pd.DataFrame(
                [{"department": d.name, "head_username": d.head_username or "", "parent_department": d.parent_department or ""} for d in deps]
            ),
            hide_index=True,
        )

        st.divider()
        sd = st.selectbox("Departament", dep_names, key="dep_sel")

        with SessionLocal() as db:
            curd = db.execute(select(Department).where(Department.name == sd)).scalar_one()

        head_opts = ["(none)"] + user_names
        parent_opts = ["(none)"] + dep_names

        cur_head = curd.head_username or "(none)"
        cur_parent = curd.parent_department or "(none)"

        head_idx = head_opts.index(cur_head) if cur_head in head_opts else 0
        parent_idx = parent_opts.index(cur_parent) if cur_parent in parent_opts else 0

        sh = st.selectbox("Sef departament (utilizator)", head_opts, index=head_idx, key="head_sel")
        sp = st.selectbox("Departament parinte", parent_opts, index=parent_idx, key="parent_sel")

        if st.button("Salveaza departament", type="primary", key="btn_save_dept"):
            with SessionLocal() as db:
                d = db.execute(select(Department).where(Department.name == sd)).scalar_one()
                d.head_username = None if sh == "(none)" else sh
                d.parent_department = None if sp == "(none)" else sp
                db.commit()
            log_event("edit_department", category="admin", username=auth_user["username"], details=f"Dept: {sd} | șef: {sh} | părinte: {sp}")
            st.success("Salvat.")
            st.rerun()

    with tab3:
        st.markdown("### Schimba parola mea")
        oldp = st.text_input("Parola veche", type="password", key="oldp")
        newp = st.text_input("Parola noua", type="password", key="newp")
        if st.button("Schimba", type="primary", key="btn_change_my_pass"):
            if not oldp.strip() or not newp.strip():
                st.error("Completeaza ambele campuri.")
            else:
                with SessionLocal() as db:
                    me_u = db.execute(select(User).where(User.username == auth_user["username"])).scalar_one()
                    if not _bcrypt_check(oldp, me_u.password_hash):
                        st.error("Parola veche gresita.")
                    else:
                        me_u.password_hash = _bcrypt_hash(newp.strip())
                        db.commit()
                        log_event("change_own_password", category="admin", username=auth_user["username"], details="Schimbare parolă proprie")
                        st.success("Parola schimbata.")

    with tab4:
        st.subheader("Monitorizare loguri sistem")

        stats = get_log_stats()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total loguri", stats["total"])
        c2.metric("Erori", stats["errors"])
        c3.metric("Avertismente", stats["warnings"])
        c4.metric("Ultimele 24h", stats["recent_24h"])

        st.divider()
        st.markdown("**Filtrare loguri**")
        fc1, fc2, fc3, fc4 = st.columns(4)
        with fc1:
            filter_level = st.selectbox("Nivel", ["(toate)", "INFO", "WARNING", "ERROR"], key="log_filter_level")
        with fc2:
            filter_cat = st.selectbox("Categorie", ["(toate)", "auth", "document", "sesizare", "admin", "system"], key="log_filter_cat")
        with fc3:
            filter_user = st.text_input("Username", key="log_filter_user", placeholder="toți")
        with fc4:
            filter_search = st.text_input("Caută în acțiune/detalii", key="log_filter_search", placeholder="—")

        dc1, dc2 = st.columns(2)
        with dc1:
            filter_from = st.date_input("De la data", value=None, key="log_filter_from")
        with dc2:
            filter_to = st.date_input("Până la data", value=None, key="log_filter_to")

        from datetime import datetime, timezone

        logs = get_logs(
            level=filter_level if filter_level != "(toate)" else None,
            category=filter_cat if filter_cat != "(toate)" else None,
            username=filter_user.strip() if filter_user.strip() else None,
            from_dt=datetime.combine(filter_from, datetime.min.time()).replace(tzinfo=timezone.utc) if filter_from else None,
            to_dt=datetime.combine(filter_to, datetime.max.time()).replace(tzinfo=timezone.utc) if filter_to else None,
            search=filter_search.strip() if filter_search.strip() else None,
            limit=500,
        )

        st.divider()
        st.markdown(f"**{len(logs)} loguri găsite** (max 500)")

        if not logs:
            st.info("Nu există loguri pentru filtrele selectate.")
        else:
            rows = []
            for log in logs:
                ts = log.timestamp
                ts_str = ts.strftime("%d.%m.%Y %H:%M:%S") if hasattr(ts, "strftime") else str(ts)
                rows.append({
                    "Timestamp": ts_str,
                    "Nivel": log.level,
                    "Categorie": log.category,
                    "Acțiune": log.action,
                    "Username": log.username or "—",
                    "IP": log.ip_address or "—",
                    "Detalii": (log.details or "")[:120],
                    "Target ID": log.target_id or "—",
                })
            df_logs = pd.DataFrame(rows)

            def _color_level(val):
                if val == "ERROR":
                    return "background-color: #ffcccc"
                if val == "WARNING":
                    return "background-color: #fff3cd"
                return ""

            styled = df_logs.style.map(_color_level, subset=["Nivel"])
            st.dataframe(styled, width='stretch', hide_index=True)

            csv_bytes = df_logs.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Export CSV",
                data=csv_bytes,
                file_name=f"loguri_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                mime="text/csv",
                key="log_export_csv",
            )

        st.divider()
        st.markdown("**Curățare loguri vechi**")
        days_to_keep = st.number_input("Șterge logurile mai vechi de (zile)", min_value=7, max_value=365, value=90, key="log_days_keep")
        if st.button("Șterge loguri vechi", key="log_delete_old", type="secondary"):
            deleted = delete_old_logs(days=int(days_to_keep))
            if deleted:
                st.success(f"Au fost șterse {deleted} loguri mai vechi de {days_to_keep} zile.")
            else:
                st.info("Nu există loguri mai vechi de termenul selectat.")

    with tab5:
        st.subheader("Backup / Restaurare bază de date")
        st.warning("Operațiunile de restaurare sunt DISTRUCTIVE și înlocuiesc baza de date curentă. Înainte de orice restaurare se creează automat un backup de siguranță.")

        # --- Creare backup ---
        st.markdown("### Creare backup")
        if st.button("Creează backup acum", type="primary", key="btn_create_backup"):
            ok, filename, msg = create_backup()
            if ok:
                log_event("backup_create", category="admin", username=auth_user["username"], details=msg)
                st.success(msg)
            else:
                log_event("backup_create", level="ERROR", category="admin", username=auth_user["username"], details=msg)
                st.error(msg)
            st.rerun()

        st.divider()

        # --- Lista backup-uri ---
        st.markdown("### Backup-uri existente")
        backups = list_backups()
        if not backups:
            st.info("Nu există fișiere de backup.")
        else:
            for b in backups:
                bc1, bc2, bc3, bc4 = st.columns([4, 1, 1, 1])
                with bc1:
                    st.markdown(f"**{b['filename']}**")
                    st.caption(f"Creat: {b['created_at']} | Dimensiune: {b['size_mb']} MB")
                with bc2:
                    bdata = get_backup_bytes(b["filename"])
                    if bdata:
                        st.download_button(
                            "Descarcă",
                            data=bdata,
                            file_name=b["filename"],
                            mime="application/octet-stream",
                            key=f"dl_backup_{b['filename']}",
                        )
                with bc3:
                    if st.button("Restaurează", key=f"restore_sel_{b['filename']}", type="secondary"):
                        st.session_state["restore_confirm_file"] = b["filename"]
                        st.rerun()
                with bc4:
                    if st.button("Șterge", key=f"del_backup_{b['filename']}"):
                        ok, msg = delete_backup(b["filename"])
                        if ok:
                            log_event("backup_delete", category="admin", username=auth_user["username"], details=msg)
                            st.success(msg)
                        else:
                            st.error(msg)
                        st.rerun()

        # --- Confirmare restaurare din lista ---
        restore_file = st.session_state.get("restore_confirm_file")
        if restore_file:
            st.divider()
            st.error(f"Ești sigur că vrei să restaurezi din **{restore_file}**? Baza de date curentă va fi înlocuită!")
            cc1, cc2 = st.columns([1, 3])
            with cc1:
                if st.button("DA, restaurează", key="confirm_restore_yes", type="primary"):
                    ok, msg = restore_from_file(restore_file)
                    if ok:
                        log_event("backup_restore", category="admin", username=auth_user["username"], details=f"Restaurat din: {restore_file}")
                        st.session_state.pop("restore_confirm_file", None)
                        st.success(msg)
                        st.rerun()
                    else:
                        log_event("backup_restore", level="ERROR", category="admin", username=auth_user["username"], details=msg)
                        st.error(msg)
            with cc2:
                if st.button("Anulează", key="confirm_restore_cancel"):
                    st.session_state.pop("restore_confirm_file", None)
                    st.rerun()

        st.divider()

        # --- Restaurare din fișier uploadat ---
        st.markdown("### Restaurare din fișier uploadat")
        st.caption("Uploadează un fișier .db SQLite exportat anterior pentru a restaura baza de date.")
        uploaded_db = st.file_uploader("Selectează fișier .db", type=["db"], key="restore_upload_file")
        if uploaded_db:
            st.info(f"Fișier selectat: **{uploaded_db.name}** ({round(uploaded_db.size / 1024 / 1024, 2)} MB)")
            conf_upload = st.checkbox(
                "Confirm că vreau să înlocuiesc baza de date curentă cu fișierul uploadat",
                key="conf_upload_restore",
            )
            if st.button("Restaurează din fișier uploadat", key="btn_restore_upload", type="primary", disabled=not conf_upload):
                ok, msg = restore_from_upload(uploaded_db.getvalue())
                if ok:
                    log_event("backup_restore_upload", category="admin", username=auth_user["username"], details=f"Restaurat din upload: {uploaded_db.name}")
                    st.success(msg)
                    st.rerun()
                else:
                    log_event("backup_restore_upload", level="ERROR", category="admin", username=auth_user["username"], details=msg)
                    st.error(msg)
