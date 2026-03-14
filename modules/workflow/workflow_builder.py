import json
from typing import List, Optional, Tuple
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import Department, Document, User
from modules.config import DG_DEPT
from modules.utils.files import normalize_dept
from modules.utils.ui_helpers import _set_scroll_to_workflow, _scroll_to_workflow_if_needed
from modules.services.workflow_service import ensure_dg_final_step, step_is_same


def wf_pretty(step: dict) -> str:
    """
    Afisare pas in UI (noul standard: sefi de departamente selectati explicit).
    """
    k = (step or {}).get("kind")
    if k == "DEPT_HEAD_OF":
        dept = normalize_dept(step.get("department") or "")
        if dept == DG_DEPT:
            return "Director General (GENERAL)"
        return f"Sef departament: {dept}"
    # compat (pentru workflow-uri vechi)
    if k == "DEPT_HEAD":
        return "Sef Sector (seful unitatii documentului) [legacy]"
    if k == "PARENT_HEAD":
        return "Sef Departament (seful departamentului parinte) [legacy]"
    if k == "USER":
        return f"Utilizator specific: {(step.get('username') or '').strip()} [legacy]"
    return str(step)


def wf_validate(steps: List[dict]) -> Tuple[bool, str]:
    """
    Noul standard: workflow manual compus EXCLUSIV din pasi de tip
    'DEPT_HEAD_OF' (sefi de departamente selectati explicit).
    DG/GENERAL este adaugat automat la final (nu trebuie inclus in pasi).
    """
    if not steps:
        return False, "Workflow gol."
    for s in steps:
        k = (s or {}).get("kind")
        if k != "DEPT_HEAD_OF":
            return False, "Workflow invalid: sunt permisi doar pasi cu sefi de departamente (DEPT_HEAD_OF)."
        dept = (s.get("department") or "").strip()
        if not dept:
            return False, "Workflow invalid: lipseste departamentul in pas."
        if normalize_dept(dept) == DG_DEPT:
            return False, "Nu adauga GENERAL in pasi; Directorul General este adaugat automat la final."
    return True, ""


def wf_normalize_force_dg(steps: List[dict]) -> List[dict]:
    out: List[dict] = []
    for s in steps:
        out.append({"kind": "DEPT_HEAD_OF", "department": normalize_dept(s.get("department") or "")})
    return ensure_dg_final_step(out)


def _display_name_for_user(username: str) -> str:
    with SessionLocal() as db:
        u = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if not u:
            return username
        fn = (getattr(u, "full_name", None) or "").strip()
        title = (getattr(u, "job_title", None) or "").strip()
        if fn and title:
            return f"{fn} ({title})"
        if fn:
            return fn
        return username


def render_workflow_builder(doc_id: str, initial_steps: Optional[List[dict]] = None) -> None:
    """
    Builder simplificat:
    - fara preset-uri
    - fiecare pas este un "sef de departament" (DEPT_HEAD_OF + department)
    - lista se actualizeaza automat din DB pe masura ce adaugi useri / schimbi sefi.
    """
    components.html('<div id="wf_anchor"></div>', height=0)
    _scroll_to_workflow_if_needed()

    with SessionLocal() as db:
        deps = db.execute(select(Department).order_by(Department.name)).scalars().all()

    # doar departamente cu sef setat (head_username); GENERAL exclus (adaugat automat)
    dept_options = []
    dept_labels = []
    for d in deps:
        dep_name = normalize_dept(d.name)
        if dep_name == DG_DEPT:
            continue
        head = (d.head_username or "").strip()
        if not head:
            continue
        dept_options.append(dep_name)
        dept_labels.append(f"{dep_name} - {_display_name_for_user(head)}")

    st.caption("Definire manuala: adauga pas cu seful unui departament. Directorul General (GENERAL) este adaugat automat la final.")

    key = f"wf_steps_{doc_id}"
    if key not in st.session_state:
        steps = []
        if initial_steps:
            for s in initial_steps:
                if (s or {}).get("kind") == "DEPT_HEAD_OF":
                    dep = normalize_dept(s.get("department") or "")
                    if dep and dep != DG_DEPT:
                        steps.append({"kind": "DEPT_HEAD_OF", "department": dep})
        if not steps:
            steps = [{"kind": "DEPT_HEAD_OF", "department": dept_options[0]}] if dept_options else []
        st.session_state[key] = steps

    steps = st.session_state[key]

    if not dept_options:
        st.warning("Nu exista departamente cu sef setat. Mergi la Administrare -> Departamente si seteaza 'Sef departament' pentru cel putin un departament (in afara de GENERAL).")
        return

    st.markdown("### Adauga pas")
    c1, c2 = st.columns([3, 1])
    with c1:
        sel_label = st.selectbox("Alege sef departament (pas)", dept_labels, key=f"wf_sel_dept_label_{doc_id}", on_change=_set_scroll_to_workflow)
        sel_dep = dept_options[dept_labels.index(sel_label)]
    with c2:
        if st.button("Adauga", key=f"wf_add_step_{doc_id}", type="primary"):
            steps.append({"kind": "DEPT_HEAD_OF", "department": sel_dep})
            st.session_state[key] = steps
            _set_scroll_to_workflow()
            st.rerun()

    st.divider()
    st.markdown("### Pasi curenti (GENERAL nu apare aici — se adauga automat la final)")
    if not steps:
        st.info("Nu exista pasi inca.")
    for i, s in enumerate(steps):
        a, b, c, d = st.columns([6, 1, 1, 1])
        with a:
            dept = normalize_dept(s.get("department") or "")
            with SessionLocal() as db:
                dep = db.execute(select(Department).where(Department.name == dept)).scalar_one_or_none()
            if dep and dep.head_username:
                label = f"{dept} - {_display_name_for_user(dep.head_username)}"
            else:
                label = f"{dept} - (sef nedefinit)"
            st.write(f"**{i+1}.** {label}")
        with b:
            if st.button("Up", key=f"wf_up_{doc_id}_{i}") and i > 0:
                steps[i - 1], steps[i] = steps[i], steps[i - 1]
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()
        with c:
            if st.button("Down", key=f"wf_down_{doc_id}_{i}") and i < len(steps) - 1:
                steps[i + 1], steps[i] = steps[i], steps[i + 1]
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()
        with d:
            if st.button("Del", key=f"wf_del_{doc_id}_{i}"):
                steps.pop(i)
                st.session_state[key] = steps
                _set_scroll_to_workflow()
                st.rerun()

    st.divider()
    if st.button("Salveaza workflow", type="primary", key=f"wf_save_{doc_id}"):
        ok, err = wf_validate(steps)
        if not ok:
            st.error(err)
            return
        final_steps = wf_normalize_force_dg(steps)
        with SessionLocal() as db:
            doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one()
            doc.workflow_json = json.dumps(final_steps, ensure_ascii=False)
            db.commit()
        st.success("Workflow salvat.")
