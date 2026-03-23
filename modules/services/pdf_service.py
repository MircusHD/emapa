import os
from io import BytesIO
from typing import Tuple
from datetime import datetime
from PIL import Image
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select
from modules.database.session import SessionLocal
from modules.database.models import Document, Approval
from modules.config import UPLOAD_DIR, FINAL_DIR, abs_upload_path, final_abs_path, sig_abs_path
from modules.utils.formatting import ro_approval_status, user_display_name, user_display_with_title


def final_rel_path(doc_id: str) -> str:
    return f"{doc_id}_final.pdf"


def build_final_pdf(doc_id: str) -> Tuple[bool, str]:
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, "Document inexistent."
        if doc.status != "APPROVED":
            return False, "PDF final se genereaza doar cand este APROBAT."
        approvals_raw = db.execute(
            select(Approval).where(Approval.document_id == doc_id).order_by(Approval.step_order)
        ).scalars().all()
        approvals = sorted(approvals_raw, key=lambda a: (a.step_order, a.created_at or datetime.min))

    op = abs_upload_path(doc.stored_path)
    if not os.path.exists(op):
        return False, "Fisier original lipseste."

    # approvals page
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "eMapa Apa Prod - Pagina de semnaturi si aprobari")

    c.setFont("Helvetica", 10)
    denumire = (doc.doc_name or "").strip() or (doc.title or "").strip() or "-"
    reg_no = str(doc.reg_no) if doc.reg_no else "-"
    reg_date = doc.reg_date or "-"

    c.drawString(40, h - 75, f"Cod document: {(doc.public_id or '-').strip()}")
    c.drawString(40, h - 90, f"Denumire document: {denumire}")
    c.drawString(40, h - 105, f"Departament: {doc.department}")
    c.drawString(40, h - 120, f"Creat de: {user_display_name(doc.created_by)}")
    c.drawString(40, h - 135, f"Inregistrare: Nr {reg_no} / Data {reg_date}")

    y = h - 170
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Aprobari:")
    y -= 18

    for a in approvals:
        status_ro = ro_approval_status(a.status)
        decided = a.decided_at.strftime("%Y-%m-%d %H:%M:%S") if a.decided_at else "-"
        is_esc = bool(a.is_escalation_node)
        indent = 60 if is_esc else 40
        prefix = f"  [Vizare] Pas {a.step_order}" if is_esc else f"Pas {a.step_order}"

        c.setFont("Helvetica-Bold", 10)
        c.drawString(indent, y, f"{prefix}: {user_display_with_title(a.approver_username)} - {status_ro}")
        c.setFont("Helvetica", 9)
        c.drawString(indent, y - 12, f"Data decizie: {decided}")

        if a.comment:
            cc = (a.comment or "").replace("\n", " ").strip()
            if len(cc) > 110:
                cc = cc[:110] + "..."
            c.drawString(indent, y - 24, f"Comentariu: {cc}")

        if a.signature_path and os.path.exists(sig_abs_path(a.signature_path)):
            try:
                img = Image.open(sig_abs_path(a.signature_path)).convert("RGBA")
                img_reader = ImageReader(img)
                c.drawImage(img_reader, 360, y - 42, width=180, height=60, mask="auto")
            except Exception:
                pass

        y -= 90
        if y < 110:
            c.showPage()
            y = h - 80

    c.showPage()
    c.save()
    buf.seek(0)

    # merge
    try:
        reader_orig = PdfReader(op)
        reader_sig = PdfReader(buf)
        writer = PdfWriter()
        for p in reader_orig.pages:
            writer.add_page(p)
        for p in reader_sig.pages:
            writer.add_page(p)

        rel_final = final_rel_path(doc_id)
        abs_final = final_abs_path(rel_final)
        with open(abs_final, "wb") as f:
            writer.write(f)
    except Exception as e:
        return False, f"Nu pot genera PDF final: {e}"

    with SessionLocal() as db:
        d2 = db.execute(select(Document).where(Document.id == doc_id)).scalar_one()
        d2.final_pdf_path = final_rel_path(doc_id)
        db.commit()

    return True, "PDF final generat."


def build_current_pdf_bytes(doc_id: str) -> Tuple[bool, bytes, str]:
    """
    PDF curent pentru previzualizare:
      - daca exista FINAL si doc e APROBAT -> folosim FINAL
      - altfel: original + pagina semnaturi cu pasii deja decisi + semnaturi existente
    """
    with SessionLocal() as db:
        doc = db.execute(select(Document).where(Document.id == doc_id)).scalar_one_or_none()
        if not doc:
            return False, b"", "Document inexistent."
        approvals_raw = db.execute(
            select(Approval).where(Approval.document_id == doc_id).order_by(Approval.step_order)
        ).scalars().all()
        approvals = sorted(approvals_raw, key=lambda a: (a.step_order, a.created_at or datetime.min))

    op = abs_upload_path(doc.stored_path)
    if not os.path.exists(op):
        return False, b"", "Fisier original lipseste."

    if (doc.status or "").upper() == "APPROVED" and doc.final_pdf_path:
        fp = final_abs_path(doc.final_pdf_path)
        if os.path.exists(fp):
            try:
                with open(fp, "rb") as f:
                    return True, f.read(), "OK"
            except Exception:
                pass

    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "eMapa Apa Prod - Pagina de semnaturi si aprobari")
    c.setFont("Helvetica", 10)

    denumire = (doc.doc_name or "").strip() or (doc.title or "").strip() or "-"
    reg_no = str(doc.reg_no) if doc.reg_no else "-"
    reg_date = doc.reg_date or "-"

    c.drawString(40, h - 75, f"Cod document: {(doc.public_id or '-').strip()}")
    c.drawString(40, h - 90, f"Denumire document: {denumire}")
    c.drawString(40, h - 105, f"Departament: {doc.department}")
    c.drawString(40, h - 120, f"Creat de: {user_display_name(doc.created_by)}")
    c.drawString(40, h - 135, f"Inregistrare: Nr {reg_no} / Data {reg_date}")

    y = h - 170
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Aprobari:")
    y -= 18

    for a in approvals:
        status_ro = ro_approval_status(a.status)
        decided = a.decided_at.strftime("%Y-%m-%d %H:%M:%S") if a.decided_at else "-"
        is_esc = bool(a.is_escalation_node)
        indent = 60 if is_esc else 40
        prefix = f"  [Vizare] Pas {a.step_order}" if is_esc else f"Pas {a.step_order}"

        c.setFont("Helvetica-Bold", 10)
        c.drawString(indent, y, f"{prefix}: {user_display_with_title(a.approver_username)} - {status_ro}")
        c.setFont("Helvetica", 9)
        c.drawString(indent, y - 12, f"Data decizie: {decided}")

        if a.comment:
            cc = (a.comment or "").replace("\n", " ").strip()
            if len(cc) > 110:
                cc = cc[:110] + "..."
            c.drawString(indent, y - 24, f"Comentariu: {cc}")

        if a.signature_path and os.path.exists(sig_abs_path(a.signature_path)):
            try:
                img = Image.open(sig_abs_path(a.signature_path)).convert("RGBA")
                img_reader = ImageReader(img)
                c.drawImage(img_reader, 360, y - 42, width=180, height=60, mask="auto")
            except Exception:
                pass

        y -= 90
        if y < 110:
            c.showPage()
            y = h - 80

    c.showPage()
    c.save()
    buf.seek(0)

    try:
        reader_orig = PdfReader(op)
        reader_sig = PdfReader(buf)
        writer = PdfWriter()
        for p in reader_orig.pages:
            writer.add_page(p)
        for p in reader_sig.pages:
            writer.add_page(p)

        out = BytesIO()
        writer.write(out)
        return True, out.getvalue(), "OK"
    except Exception as e:
        return False, b"", f"Nu pot genera PDF curent: {e}"
