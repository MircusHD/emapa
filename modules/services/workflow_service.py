import os
import json
import uuid
from typing import List, Optional, Tuple
from datetime import datetime
from sqlalchemy import select, and_
from modules.database.session import SessionLocal
from modules.database.models import User, Department, DocType, Document, Approval
from modules.config import DG_DEPT, sig_abs_path, abs_upload_path, final_abs_path
from modules.utils.files import normalize_dept, safe_filename
from modules.departments.dept_service import get_descendant_departments
from modules.services.log_service import log_event


def sig_rel_path(doc_id: str, step_order: int, username: str) -> str:
    return f"{doc_id}_pas{step_order}_{safe_filename(username)}.png"


def step_is_same(a: dict, b: dict) -> bool:
    if (a or {}).get("kind") != (b or {}).get("kind"):
        return False
    if a.get("kind") == "DEPT_HEAD_OF":
        return normalize_dept(a.get("department") or "") == normalize_dept(b.get("department") or "")
    if a.get("kind") == "USER":
        return (a.get("username") or "").strip().lower() == (b.get("username") or "").strip().lower()
    return True


def ensure_dg_final_step(wf: List[dict]) -> List[dict]:
    final = {"kind": "DEPT_HEAD_OF", "department": normalize_dept(DG_DEPT)}
    out: List[dict] = []
    for s in (wf or []):
        if step_is_same(s, final):
            continue
        out.append(s)
    out.append(final)
    return out


def load_doc_type_workflow(doc_type: str) -> List[dict]:
    with SessionLocal() as db:
        dt = db.execute(select(DocType).where(DocType.name == doc_type, DocType.is_active == True)).scalar_one_or_none()
        if not dt:
            return [{"kind": "DEPT_HEAD"}]
        try:
            wf = json.loads(dt.workflow_json or "[]")
            if isinstance(wf, list) and wf:
                return wf
            return [{"kind": "DEPT_HEAD"}]
        except Exception:
            return [{"kind": "DEPT_HEAD"}]


def effective_workflow(doc: Document) -> List[dict]:
    wf: List[dict] = []
    if doc.workflow_json:
        try:
            tmp = json.loads(doc.workflow_json or "[]")
            if isinstance(tmp, list) and tmp:
                wf = tmp
        except Exception:
            wf = []
    if not wf:
        wf = load_doc_type_workflow(doc.doc_type)
    return ensure_dg_final_step(wf)


def resolve_step_to_approver(step: dict, doc_department: str) -> Optional[str]:
    kind = (step or {}).get("kind")
    with SessionLocal() as db:
        if kind == "USER":
            uname = (step.get("username") or "").strip()
            if not uname:
                return None
            u = db.execute(select(User).where(User.username == uname, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "DEPT_HEAD":
            dep = db.execute(select(Department).where(Department.name == doc_department)).scalar_one_or_none()
            if not dep or not dep.head_username:
                return None
            u = db.execute(select(User).where(User.username == dep.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "PARENT_HEAD":
            dep = db.execute(select(Department).where(Department.name == doc_department)).scalar_one_or_none()
            if not dep or not dep.parent_department:
                return None
            parent = db.execute(select(Department).where(Department.name == dep.parent_department)).scalar_one_or_none()
            if not parent or not parent.head_username:
                return None
            u = db.execute(select(User).where(User.username == parent.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

        if kind == "DEPT_HEAD_OF":
            dept = normalize_dept(step.get("department") or "")
            dep = db.execute(select(Department).where(Department.name == dept)).scalar_one_or_none()
            if not dep or not dep.head_username:
                return None
            u = db.execute(select(User).where(User.username == dep.head_username, User.is_active == True)).scalar_one_or_none()
            return u.username if u else None

    return None


def get_available_escalation_users(doc_id: str, current_approver: str) -> List[str]:
    """
    Returnează toți șefii de departament activi care nu sunt deja în workflow-ul documentului
    și care nu sunt utilizatorul curent.
    """
    with SessionLocal() as db:
        existing = set(
            db.execute(
                select(Approval.approver_username).where(Approval.document_id == doc_id)
            ).scalars().all()
        )
        existing.add(current_approver)

        depts = db.execute(select(Department)).scalars().all()
        result: List[str] = []
        seen: set = set()
        for dept in depts:
            head = dept.head_username
            if not head or head in existing or head in seen:
                continue
            u = db.execute(
                select(User).where(User.username == head, User.is_active == True)
            ).scalar_one_or_none()
            if u:
                result.append(head)
                seen.add(head)

    return result


def user_can_view_document(doc: Document, user: dict) -> bool:
    if user.get("role") in ("admin", "secretariat"):
        return True
    if doc.created_by == user.get("username"):
        return True
    allowed_depts = get_descendant_departments(user.get("department") or DG_DEPT)
    if doc.department in allowed_depts:
        return True
    with SessionLocal() as db:
        a = db.execute(
            select(Approval).where(and_(Approval.document_id == doc.id, Approval.approver_username == user.get("username")))
        ).scalar_one_or_none()
        return a is not None


def start_workflow(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "DRAFT":
            return False, "Workflow poate porni doar din CIORNA."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat poate porni workflow."

        wf = effective_workflow(doc)
        approvers: List[str] = []
        for step in wf:
            a = resolve_step_to_approver(step, doc.department)
            if not a:
                return False, f"Nu pot rezolva aprobator pentru pas: {step}"
            approvers.append(a)

        old = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for x in old:
            db.delete(x)

        for i, uname in enumerate(approvers, start=1):
            db.add(
                Approval(
                    id=str(uuid.uuid4()),
                    document_id=doc.id,
                    step_order=i,
                    approver_username=uname,
                    status="PENDING" if i == 1 else "WAITING",
                    created_at=datetime.now(),
                )
            )

        doc.status = "PENDING"
        doc.current_step = 1
        db.commit()
    log_event("document_workflow_start", category="document", username=actor.get("username"), details=f"Workflow pornit | {len(approvers)} pași", target_id=doc_id)
    return True, "Workflow pornit."


def decide(
    doc_id: str,
    approver: str,
    decision: str,
    comment: str,
    signature_png_bytes: Optional[bytes],
    escalate_to: Optional[List[str]] = None,
) -> Tuple[bool, str]:
    decision = (decision or "").strip().upper()
    if decision not in ("APPROVE", "REJECT", "APPROVE_AND_ESCALATE"):
        return False, "Decizie invalida."

    if decision in ("APPROVE", "APPROVE_AND_ESCALATE") and not signature_png_bytes:
        return False, "Semnatura este obligatorie la APROBARE."

    if decision == "APPROVE_AND_ESCALATE" and not escalate_to:
        return False, "Trebuie specificata cel putin o persoana pentru vizare."

    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "PENDING":
            return False, "Documentul nu este in aprobare."

        cur = db.execute(
            select(Approval).where(
                and_(
                    Approval.document_id == doc.id,
                    Approval.step_order == doc.current_step,
                    Approval.status == "PENDING",
                )
            )
        ).scalar_one_or_none()

        if not cur:
            return False, "Nu exista pas curent IN ASTEPTARE."
        if cur.approver_username != approver:
            return False, "Nu esti aprobatorul pasului curent."

        now = datetime.now()
        cur.comment = (comment or "").strip() or None
        cur.decided_at = now

        if decision == "REJECT":
            cur.status = "REJECTED"
            doc.status = "REJECTED"
            db.commit()
            log_event("document_reject", category="document", username=approver, details=f"Respins | Pas: {cur.step_order} | Comentariu: {comment or '—'}", target_id=doc_id)
            return True, "RESPINS."

        # approve
        cur.status = "APPROVED"

        # save signature
        try:
            rel = sig_rel_path(doc.id, cur.step_order, approver)
            with open(sig_abs_path(rel), "wb") as f:
                f.write(signature_png_bytes)
            cur.signature_path = rel
            cur.signed_at = datetime.now().isoformat()
        except Exception as e:
            return False, f"Nu am putut salva semnatura: {e}"

        if decision == "APPROVE_AND_ESCALATE":
            # Validare: toți din lista trebuie să fie disponibili
            available = get_available_escalation_users(doc_id, approver)
            for u in escalate_to:
                if u not in available:
                    return False, f"Utilizatorul '{u}' nu este disponibil pentru vizare."

            # Creăm nodurile de escalare secvențial: primul PENDING, restul WAITING
            for j, esc_user in enumerate(escalate_to):
                db.add(
                    Approval(
                        id=str(uuid.uuid4()),
                        document_id=doc.id,
                        step_order=doc.current_step,
                        approver_username=esc_user,
                        status="PENDING" if j == 0 else "WAITING",
                        is_escalation_node=1,
                        created_at=datetime.now(),
                    )
                )
            # doc.current_step rămâne neschimbat
            db.commit()
            from modules.utils.formatting import user_display_name
            names = ", ".join(user_display_name(u) for u in escalate_to)
            log_event("document_escalate", category="document", username=approver,
                      details=f"Aprobat + vizare: {names} | Pas: {cur.step_order}",
                      target_id=doc_id)
            return True, f"Aprobat si trimis spre vizare: {names}."

        # APPROVE normal: verificăm mai întâi dacă mai sunt noduri de escalare în așteptare
        next_esc = db.execute(
            select(Approval).where(
                and_(
                    Approval.document_id == doc.id,
                    Approval.step_order == cur.step_order,
                    Approval.status == "WAITING",
                    Approval.is_escalation_node == 1,
                )
            ).order_by(Approval.created_at).limit(1)
        ).scalar_one_or_none()

        if next_esc:
            next_esc.status = "PENDING"
            db.commit()
            from modules.utils.formatting import user_display_name
            log_event("document_approve", category="document", username=approver,
                      details=f"Vizat pas {cur.step_order} | urmează {next_esc.approver_username}",
                      target_id=doc_id)
            return True, f"Vizat. Urmează {user_display_name(next_esc.approver_username)}."

        nxt_order = doc.current_step + 1
        nxt = db.execute(
            select(Approval).where(
                and_(Approval.document_id == doc.id, Approval.step_order == nxt_order, Approval.status == "WAITING")
            )
        ).scalar_one_or_none()

        if nxt:
            nxt.status = "PENDING"
            doc.current_step = nxt_order
            db.commit()
            log_event("document_approve", category="document", username=approver, details=f"Aprobat pas {cur.step_order} | urmează pas {nxt_order}", target_id=doc_id)
            return True, "APROBAT (urmatorul pas)."

        doc.status = "APPROVED"
        db.commit()
        log_event("document_approve_final", category="document", username=approver, details=f"Aprobat final (pas {cur.step_order})", target_id=doc_id)

    # generate final pdf — import lazy pentru a evita circular import
    from modules.services.pdf_service import build_final_pdf
    ok2, msg2 = build_final_pdf(doc_id)
    if ok2:
        return True, "APROBAT final + PDF final generat."
    return True, "APROBAT final (PDF final negenerat: " + str(msg2) + ")"


def cancel_to_draft(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "PENDING":
            return False, "Doar IN APROBARE se poate anula la CIORNA."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for a in approvals:
            db.delete(a)

        doc.status = "DRAFT"
        doc.current_step = 0
        db.commit()
    log_event("document_cancel_to_draft", level="WARNING", category="document", username=actor.get("username"), details="Workflow anulat → CIORNĂ", target_id=doc_id)
    return True, "Anulat la CIORNA."


def cancel_document(doc_id: str, actor: dict) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status == "APPROVED":
            return False, "Nu anulam documente APROBATE."
        if actor.get("role") not in ("admin", "secretariat") and doc.created_by != actor.get("username"):
            return False, "Doar creatorul sau Admin/Secretariat."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()
        for a in approvals:
            db.delete(a)

        doc.status = "CANCELLED"
        doc.current_step = 0
        db.commit()
    log_event("document_cancel", level="WARNING", category="document", username=actor.get("username"), details="Document marcat ANULAT", target_id=doc_id)
    return True, "Document marcat ANULAT."


def sterge_definitiv_document(doc_id: str, actor: dict) -> Tuple[bool, str]:
    if actor.get("role") not in ("admin", "secretariat"):
        return False, "Doar Admin sau Secretariat poate sterge definitiv."

    doc_id = (doc_id or "").strip()
    if not doc_id:
        return False, "Lipseste ID-ul documentului."

    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."

        approvals = db.execute(select(Approval).where(Approval.document_id == doc.id)).scalars().all()

        # delete signature files
        for ap in approvals:
            if ap.signature_path:
                try:
                    p = sig_abs_path(ap.signature_path)
                    if os.path.exists(p):
                        os.remove(p)
                except Exception:
                    pass

        # delete original
        try:
            op = abs_upload_path(doc.stored_path)
            if os.path.exists(op):
                os.remove(op)
        except Exception:
            pass

        # delete final
        try:
            if doc.final_pdf_path:
                fp = final_abs_path(doc.final_pdf_path)
                if os.path.exists(fp):
                    os.remove(fp)
        except Exception:
            pass

        # db delete
        for ap in approvals:
            db.delete(ap)
        db.delete(doc)
        db.commit()

    log_event("document_delete", level="WARNING", category="document", username=actor.get("username"), details="Document șters definitiv (fișier + semnături + DB)", target_id=doc_id)
    return True, "Document sters definitiv (fisier + semnaturi + baza de date)."
