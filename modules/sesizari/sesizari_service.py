import os
import json
from datetime import datetime, date, timezone
from io import BytesIO

from PIL import Image
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from pypdf import PdfReader, PdfWriter
from sqlalchemy import select, and_, or_, func, case

from modules.database.models import Department, Sesizare, SesizareFile, User
from modules.database.session import SessionLocal
from modules.config import BASE_DIR, DG_DEPT, FINAL_DIR, SIGNATURE_DIR
from modules.utils.formatting import user_display_name
from modules.services.log_service import log_event


# ---------------------------------------------------------------------------
# Funcții de interogare departamente / useri
# ---------------------------------------------------------------------------

def get_head_dept(username: str) -> tuple[bool, str | None]:
    """Returnează (True, dept_name) dacă username este head_username al unui departament (exclus DG_DEPT).
    Dacă e head doar al DG_DEPT (GENERAL), se tratează ca Director General, nu șef de departament."""
    with SessionLocal() as db:
        stmt = select(Department).where(
            and_(Department.head_username == username, Department.name != DG_DEPT)
        )
        dept = db.execute(stmt).scalars().first()
        if dept:
            return True, dept.name
        return False, None


def get_dept_users(dept_name: str) -> list[str]:
    """Returnează lista de username-uri active din departamentul dat."""
    with SessionLocal() as db:
        stmt = select(User.username).where(
            and_(User.department == dept_name, User.is_active == True)
        )
        rows = db.execute(stmt).scalars().all()
        return list(rows)


def get_all_departments() -> list[str]:
    """Returnează lista numelor de departamente sortată."""
    with SessionLocal() as db:
        stmt = select(Department.name).order_by(Department.name)
        rows = db.execute(stmt).scalars().all()
        return list(rows)


def get_dept_head_username(dept_name: str) -> str | None:
    """Returnează head_username al departamentului dat, sau None dacă nu e configurat."""
    if not dept_name:
        return None
    with SessionLocal() as db:
        dept = db.get(Department, dept_name)
        return dept.head_username if dept else None


# ---------------------------------------------------------------------------
# Funcții lanț de vizare ierarhică
# ---------------------------------------------------------------------------

def get_available_vizare_users(sesizare_id: int, current_user: str) -> list[str]:
    """Returnează toți șefii de departament activi disponibili pentru vizare,
    excluzând utilizatorul curent și pe cei deja în lanțul de vizare."""
    existing: set[str] = {current_user}
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare and sesizare.vizare_chain_json:
            try:
                for step in json.loads(sesizare.vizare_chain_json):
                    existing.add(step["username"])
            except Exception:
                pass

        depts = db.execute(select(Department)).scalars().all()
        result: list[str] = []
        seen: set[str] = set()
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


def set_vizare_chain(sesizare_id: int, usernames: list[str]) -> tuple[bool, str]:
    """Setează lanțul de vizare pe sesizare. Primul username devine PENDING, restul WAITING."""
    if not usernames:
        return False, "Trebuie specificat cel puțin un utilizator pentru vizare."
    chain = [
        {"username": u, "status": "PENDING" if i == 0 else "WAITING",
         "approved_at": None, "signature_path": None}
        for i, u in enumerate(usernames)
    ]
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.vizare_chain_json = json.dumps(chain)
        sesizare.vizare_current_approver = usernames[0]
        sesizare.necesita_aprobare_sef = True  # compatibilitate cu filtrele existente
        db.commit()
    log_event("sesizare_set_vizare_chain", category="sesizare",
              details=f"Sesizare #{sesizare_id} — lanț vizare: {', '.join(usernames)}", target_id=str(sesizare_id))
    return True, "Lanțul de vizare a fost setat."


def aproba_vizare_step(
    sesizare_id: int,
    approver_username: str,
    semnatura_png_bytes: bytes,
    semnatura_dir: str,
) -> tuple[bool, str]:
    """Aprobatorul curent semnează pasul său de vizare și activează pe următorul."""
    os.makedirs(semnatura_dir, exist_ok=True)
    sig_filename = f"vizare_{sesizare_id}_{approver_username}_{int(datetime.now().timestamp())}.png"
    sig_abs = os.path.join(semnatura_dir, sig_filename)
    with open(sig_abs, "wb") as f:
        f.write(semnatura_png_bytes)
    rel_path = os.path.join("signatures", "sesizari", "semnaturi", sig_filename)

    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        if sesizare.vizare_current_approver != approver_username:
            return False, "Nu ești aprobatorul curent al acestei sesizări."
        try:
            chain = json.loads(sesizare.vizare_chain_json or "[]")
        except Exception:
            return False, "Lanțul de vizare este corupt."

        approved = False
        next_approver = None
        for i, step in enumerate(chain):
            if step["username"] == approver_username and step["status"] == "PENDING":
                step["status"] = "APPROVED"
                step["approved_at"] = datetime.now().isoformat()
                step["signature_path"] = rel_path
                approved = True
                # Activează primul WAITING următor
                for nxt in chain[i + 1:]:
                    if nxt["status"] == "WAITING":
                        nxt["status"] = "PENDING"
                        next_approver = nxt["username"]
                        break
                break

        if not approved:
            return False, "Nu ai un pas de vizare în așteptare."

        sesizare.vizare_chain_json = json.dumps(chain)
        sesizare.vizare_current_approver = next_approver
        # Actualizăm și câmpurile sef pentru compatibilitate cu PDF-ul existent
        sesizare.sef_aprobat_la = datetime.now()
        sesizare.sef_semnatura_path = rel_path
        sesizare.sef_aprobator_username = approver_username
        db.commit()

    log_event("sesizare_vizare_step", category="sesizare", username=approver_username,
              details=f"Sesizare #{sesizare_id} vizată de {approver_username}", target_id=str(sesizare_id))
    pdf_ok, pdf_msg = build_sesizare_final_pdf(sesizare_id)
    if not pdf_ok:
        return True, f"Vizare înregistrată, dar PDF-ul nu s-a putut genera: {pdf_msg}"
    return True, "Sesizarea a fost vizată cu succes."


def get_sesizari_de_vizat(username: str) -> list[Sesizare]:
    """Returnează sesizările finalizate unde username este aprobatorul curent din lanțul de vizare."""
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            and_(
                Sesizare.vizare_current_approver == username,
                Sesizare.status == "finalizat",
            )
        ).order_by(Sesizare.finalizat_at.desc())
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


# ---------------------------------------------------------------------------
# Funcții CRUD sesizări
# ---------------------------------------------------------------------------

def get_next_numar_inregistrare() -> str:
    """Generează numărul de înregistrare format SZ-YYYY-NNN."""
    year = datetime.now().year
    prefix = f"SZ-{year}-"
    with SessionLocal() as db:
        stmt = select(func.count(Sesizare.id)).where(
            Sesizare.numar_inregistrare.like(f"{prefix}%")
        )
        count = db.execute(stmt).scalar() or 0
    return f"{prefix}{str(count + 1).zfill(3)}"


def create_sesizare(
    autor: str,
    titlu: str,
    numar_inreg: str,
    descriere: str | None,
    pdf_path: str | None,
) -> Sesizare:
    """Crează sesizare cu status='nou'. Returnează obiectul Sesizare creat."""
    with SessionLocal() as db:
        db.expire_on_commit = False
        sesizare = Sesizare(
            numar_inregistrare=numar_inreg,
            titlu=titlu,
            descriere=descriere,
            pdf_path=pdf_path,
            autor=autor,
            status="nou",
            created_at=datetime.now(timezone.utc),
        )
        db.add(sesizare)
        db.commit()
        log_event("sesizare_creare", category="sesizare", username=autor, details=f"Titlu: {titlu} | Nr: {numar_inreg}", target_id=str(sesizare.id))
        return sesizare


def trimite_la_dg(sesizare_id: int) -> tuple[bool, str]:
    """Setează status='in_derulare', trimis_la_dg_at=now(). Returnează (ok, mesaj)."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.status = "in_derulare"
        sesizare.trimis_la_dg_at = datetime.now(timezone.utc)
        db.commit()
    log_event("sesizare_trimis_dg", category="sesizare", details=f"Sesizare #{sesizare_id} trimisă la DG", target_id=str(sesizare_id))
    return True, "Sesizarea a fost trimisă la DG."


def distribuie_la_dept(sesizare_id: int, dept: str) -> tuple[bool, str]:
    """Setează departament=dept, distribuit_la_dept_at=now(). Returnează (ok, mesaj)."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.departament = dept
        sesizare.distribuit_la_dept_at = datetime.now(timezone.utc)
        db.commit()
    log_event("sesizare_distribuire_dept", category="sesizare", details=f"Sesizare #{sesizare_id} distribuită dept: {dept}", target_id=str(sesizare_id))
    return True, f"Sesizarea a fost distribuită departamentului '{dept}'."


def redistribuie_dept(sesizare_id: int, dept_nou: str) -> tuple[bool, str]:
    """Șeful de departament redirecționează sesizarea către alt departament. Resetează user_responsabil."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.departament = dept_nou
        sesizare.user_responsabil = None
        sesizare.atribuit_la_user_at = None
        sesizare.distribuit_la_dept_at = datetime.now(timezone.utc)
        db.commit()
    log_event("sesizare_redirectionare", category="sesizare", details=f"Sesizare #{sesizare_id} redirecționată → {dept_nou}", target_id=str(sesizare_id))
    return True, f"Sesizarea a fost redirecționată către departamentul '{dept_nou}'."


def atribuie_user(sesizare_id: int, user_responsabil: str) -> tuple[bool, str]:
    """Setează user_responsabil, atribuit_la_user_at=now(). Returnează (ok, mesaj)."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.user_responsabil = user_responsabil
        sesizare.atribuit_la_user_at = datetime.now(timezone.utc)
        db.commit()
    log_event("sesizare_atribuire_user", category="sesizare", username=user_responsabil, details=f"Sesizare #{sesizare_id} atribuită lui {user_responsabil}", target_id=str(sesizare_id))
    return True, f"Sesizarea a fost atribuită utilizatorului '{user_responsabil}'."


def finalizeaza(
    sesizare_id: int,
    observatii: str = "",
    necesita_aprobare_dg: bool = False,
    necesita_aprobare_sef: bool = False,
) -> tuple[bool, str]:
    """Setează status='finalizat', finalizat_at=now(), observatii_finalizare.
    Opțional setează flag-urile de aprobare DG/Șef. Returnează (ok, mesaj)."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.status = "finalizat"
        sesizare.finalizat_at = datetime.now(timezone.utc)
        sesizare.observatii_finalizare = observatii
        if necesita_aprobare_dg:
            sesizare.necesita_aprobare_dg = True
        if necesita_aprobare_sef:
            sesizare.necesita_aprobare_sef = True
        responsabil = sesizare.user_responsabil or "—"
        db.commit()
    log_event(
        "sesizare_finalizare",
        category="sesizare",
        username=responsabil,
        details=(
            f"Sesizare #{sesizare_id} finalizata | Obs: {observatii[:80] if observatii else '—'}"
            f" | apr_dg={necesita_aprobare_dg} | apr_sef={necesita_aprobare_sef}"
        ),
        target_id=str(sesizare_id),
    )
    return True, "Sesizarea a fost finalizata."


def set_necesita_aprobare_dg(sesizare_id: int, value: bool) -> tuple[bool, str]:
    """Bifează/debifează necesitatea aprobării DG pe o sesizare finalizată."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        if sesizare.status != "finalizat":
            return False, "Doar sesizările finalizate pot fi marcate pentru aprobare DG."
        sesizare.necesita_aprobare_dg = value
        if not value:
            sesizare.dg_aprobat_la = None
            sesizare.dg_semnatura_path = None
        db.commit()
    return True, ""


def aproba_dg(sesizare_id: int, semnatura_png_bytes: bytes, semnatura_dir: str) -> tuple[bool, str]:
    """DG aprobă sesizarea cu semnătură. Salvează PNG, setează dg_aprobat_la și generează PDF final."""
    os.makedirs(semnatura_dir, exist_ok=True)
    sig_filename = f"dg_sig_{sesizare_id}_{int(datetime.now(timezone.utc).timestamp())}.png"
    sig_path = os.path.join(semnatura_dir, sig_filename)
    with open(sig_path, "wb") as f:
        f.write(semnatura_png_bytes)
    rel_path = os.path.join("signatures", "sesizari", "semnaturi", sig_filename)
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.dg_aprobat_la = datetime.now(timezone.utc)
        sesizare.dg_semnatura_path = rel_path
        db.commit()
    log_event("sesizare_aprobare_dg", category="sesizare", details=f"Sesizare #{sesizare_id} aprobată de DG cu semnătură", target_id=str(sesizare_id))
    # generează PDF final cu pagina de semnături
    pdf_ok, pdf_msg = build_sesizare_final_pdf(sesizare_id)
    if not pdf_ok:
        return True, f"Sesizarea a fost aprobată, dar PDF-ul final nu s-a putut genera: {pdf_msg}"
    return True, "Sesizarea a fost aprobată cu semnătură."


def build_sesizare_final_pdf(sesizare_id: int) -> tuple[bool, str]:
    """Generează PDF final: PDF rezoluție + pagină semnături DG.
    Salvează în FINAL_DIR și actualizează sesizare.final_pdf_path."""
    # Citim datele sesizării și fișierele
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        # snapshot câmpuri necesare
        numar_inregistrare = sesizare.numar_inregistrare
        titlu = sesizare.titlu
        autor = sesizare.autor or ""
        departament = sesizare.departament or "—"
        user_responsabil = sesizare.user_responsabil or ""
        finalizat_at = sesizare.finalizat_at
        observatii = sesizare.observatii_finalizare or ""
        dg_aprobat_la = sesizare.dg_aprobat_la
        dg_semnatura_path = sesizare.dg_semnatura_path
        sef_aprobat_la = sesizare.sef_aprobat_la
        sef_semnatura_path = sesizare.sef_semnatura_path
        sef_aprobator_username = sesizare.sef_aprobator_username or ""
        necesita_aprobare_sef = sesizare.necesita_aprobare_sef

        rez_files = db.execute(
            select(SesizareFile).where(
                and_(SesizareFile.sesizare_id == sesizare_id, SesizareFile.tip == "rezolutie")
            ).order_by(SesizareFile.uploaded_at.desc())
        ).scalars().all()
        db.expunge_all()
        rez_files = list(rez_files)

    if not rez_files:
        return False, "Nu există fișier PDF rezoluție pentru această sesizare."

    _data_dir = os.path.normpath(os.path.join(BASE_DIR, "data"))
    rez_abs = os.path.normpath(os.path.join(_data_dir, rez_files[0].fisier_path))
    if not rez_abs.startswith(_data_dir + os.sep):
        return False, "Cale fișier invalidă."
    if not os.path.exists(rez_abs):
        return False, "Fișierul PDF rezoluție nu există pe disc."

    # Construiește pagina de semnături
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=A4)
    _, h = A4

    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, h - 50, "eMapa Apa Prod - Pagina de semnaturi si aprobari")

    c.setFont("Helvetica", 10)
    c.drawString(40, h - 75,  f"Nr. inregistrare: {numar_inregistrare or '—'}")
    c.drawString(40, h - 90,  f"Titlu: {titlu or '—'}")
    c.drawString(40, h - 105, f"Autor: {user_display_name(autor)}")
    c.drawString(40, h - 120, f"Departament: {departament}")
    c.drawString(40, h - 135, f"Responsabil: {user_display_name(user_responsabil)}")
    fin_str = finalizat_at.strftime("%d.%m.%Y %H:%M") if finalizat_at else "—"
    c.drawString(40, h - 150, f"Data finalizare: {fin_str}")
    if observatii:
        obs_short = observatii[:100] + ("..." if len(observatii) > 100 else "")
        c.drawString(40, h - 165, f"Observatii: {obs_short}")

    y = h - 200

    # ---- Coloana stânga: Aprobare Director General ----
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Aprobare Director General:")
    y_dg = y - 18
    c.setFont("Helvetica", 9)
    if dg_aprobat_la:
        apr_str = dg_aprobat_la.strftime("%d.%m.%Y %H:%M")
        c.drawString(40, y_dg, f"Aprobat la: {apr_str}")
        if dg_semnatura_path:
            sig_abs = os.path.normpath(os.path.join(_data_dir, dg_semnatura_path))
            if sig_abs.startswith(_data_dir + os.sep) and os.path.exists(sig_abs):
                try:
                    img = Image.open(sig_abs).convert("RGBA")
                    img_reader = ImageReader(img)
                    c.drawImage(img_reader, 40, y_dg - 62, width=180, height=60, mask="auto")
                except Exception:
                    pass
    else:
        c.drawString(40, y_dg, "Fara aprobare DG.")

    # ---- Coloana dreapta: Lanț de vizare / Aprobare Șef Departament ----
    c.setFont("Helvetica-Bold", 10)
    # Citim vizare_chain_json direct din DB pentru PDF
    try:
        import json as _json
        with SessionLocal() as _db:
            _sz = _db.get(Sesizare, sesizare_id)
            _vizare_chain = _json.loads(_sz.vizare_chain_json) if (_sz and _sz.vizare_chain_json) else None
    except Exception:
        _vizare_chain = None

    if _vizare_chain:
        c.drawString(310, y, "Vizare ierarhica:")
        y_sef = y - 15
        c.setFont("Helvetica", 9)
        for viz_step in _vizare_chain:
            viz_user = user_display_name(viz_step["username"])
            if viz_step["status"] == "APPROVED":
                apr_dt = viz_step.get("approved_at", "")
                apr_dt_str = apr_dt[:16].replace("T", " ") if apr_dt else "—"
                c.drawString(310, y_sef, f"[V] {viz_user} — {apr_dt_str}")
                if viz_step.get("signature_path"):
                    sig_viz_abs = os.path.normpath(os.path.join(_data_dir, viz_step["signature_path"]))
                    if sig_viz_abs.startswith(_data_dir + os.sep) and os.path.exists(sig_viz_abs):
                        try:
                            img_v = Image.open(sig_viz_abs).convert("RGBA")
                            c.drawImage(ImageReader(img_v), 310, y_sef - 42, width=150, height=40, mask="auto")
                        except Exception:
                            pass
                    y_sef -= 55
                else:
                    y_sef -= 18
            else:
                status_label = "In asteptare" if viz_step["status"] == "PENDING" else "—"
                c.drawString(310, y_sef, f"[ ] {viz_user} — {status_label}")
                y_sef -= 15
    else:
        c.drawString(310, y, "Aprobare Sef Departament:")
        y_sef = y - 18
        c.setFont("Helvetica", 9)
        if sef_aprobat_la:
            apr_str_sef = sef_aprobat_la.strftime("%d.%m.%Y %H:%M")
            c.drawString(310, y_sef, f"Aprobat la: {apr_str_sef}")
            if sef_aprobator_username:
                c.drawString(310, y_sef - 12, f"Aprobator: {user_display_name(sef_aprobator_username)}")
            if sef_semnatura_path:
                sig_sef_abs = os.path.normpath(os.path.join(_data_dir, sef_semnatura_path))
                if sig_sef_abs.startswith(_data_dir + os.sep) and os.path.exists(sig_sef_abs):
                    try:
                        img_sef = Image.open(sig_sef_abs).convert("RGBA")
                        img_sef_reader = ImageReader(img_sef)
                        c.drawImage(img_sef_reader, 310, y_sef - 62, width=180, height=60, mask="auto")
                    except Exception:
                        pass
        elif necesita_aprobare_sef:
            c.drawString(310, y_sef, "In asteptare aprobare sef dept.")
        else:
            c.drawString(310, y_sef, "Fara aprobare sef dept.")

    c.showPage()
    c.save()
    buf.seek(0)

    # Combină PDF rezoluție + pagina semnături
    try:
        reader_orig = PdfReader(rez_abs)
        reader_sig = PdfReader(buf)
        writer = PdfWriter()
        for p in reader_orig.pages:
            writer.add_page(p)
        for p in reader_sig.pages:
            writer.add_page(p)

        os.makedirs(FINAL_DIR, exist_ok=True)
        final_filename = f"sz_{sesizare_id}_final.pdf"
        final_abs = os.path.join(FINAL_DIR, final_filename)
        with open(final_abs, "wb") as f:
            writer.write(f)
    except Exception as e:
        return False, f"Nu pot genera PDF final: {e}"

    # Salvează calea în baza de date
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare:
            sesizare.final_pdf_path = final_filename
            db.commit()

    return True, final_filename


def set_necesita_aprobare_sef(sesizare_id: int, value: bool) -> tuple[bool, str]:
    """Bifează/debifează necesitatea aprobării șefului de departament pe o sesizare finalizată."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        if sesizare.status != "finalizat":
            return False, "Doar sesizările finalizate pot fi marcate pentru aprobare șef."
        sesizare.necesita_aprobare_sef = value
        if not value:
            sesizare.sef_aprobat_la = None
            sesizare.sef_semnatura_path = None
        db.commit()
    return True, ""


def aproba_sef(
    sesizare_id: int,
    semnatura_png_bytes: bytes,
    semnatura_dir: str,
    sef_username: str,
) -> tuple[bool, str]:
    """Șeful de departament aprobă sesizarea cu semnătură PNG.
    Salvează PNG, setează sef_aprobat_la/sef_aprobator_username și regenerează PDF final."""
    os.makedirs(semnatura_dir, exist_ok=True)
    sig_filename = f"sef_sig_{sesizare_id}_{int(datetime.now().timestamp())}.png"
    sig_path = os.path.join(semnatura_dir, sig_filename)
    with open(sig_path, "wb") as f:
        f.write(semnatura_png_bytes)
    rel_path = os.path.join("signatures", "sesizari", "semnaturi", sig_filename)
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        sesizare.sef_aprobat_la = datetime.now()
        sesizare.sef_semnatura_path = rel_path
        sesizare.sef_aprobator_username = sef_username
        db.commit()
    log_event(
        "sesizare_aprobare_sef",
        category="sesizare",
        username=sef_username,
        details=f"Sesizare #{sesizare_id} aprobată de șef dept cu semnătură",
        target_id=str(sesizare_id),
    )
    pdf_ok, pdf_msg = build_sesizare_final_pdf(sesizare_id)
    if not pdf_ok:
        return True, f"Sesizarea a fost aprobată, dar PDF-ul final nu s-a putut genera: {pdf_msg}"
    return True, "Sesizarea a fost aprobată de șeful de departament."


def get_sesizari_de_aprobat_sef(head_username: str, head_dept: str) -> list[Sesizare]:
    """Returnează sesizările finalizate marcate pentru aprobare șef, neaprobate încă,
    din lanțul de departamente al șefului."""
    dept_chain = get_dept_visibility_chain(head_dept)
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            and_(
                Sesizare.status == "finalizat",
                Sesizare.necesita_aprobare_sef == True,
                Sesizare.sef_aprobat_la.is_(None),
                Sesizare.departament.in_(dept_chain),
            )
        ).order_by(Sesizare.finalizat_at.desc())
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


def get_sesizari_de_aprobat_dg() -> list[Sesizare]:
    """Returnează sesizările finalizate trimise la DG pentru aprobare, neaprobate încă."""
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            and_(
                Sesizare.status == "finalizat",
                Sesizare.necesita_aprobare_dg == True,
                Sesizare.dg_aprobat_la.is_(None),
            )
        ).order_by(Sesizare.finalizat_at.desc())
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


def delete_sesizare(sesizare_id: int) -> tuple[bool, str]:
    """Șterge sesizarea și fișierele asociate (SesizareFile). Returnează (ok, mesaj)."""
    with SessionLocal() as db:
        sesizare = db.get(Sesizare, sesizare_id)
        if sesizare is None:
            return False, f"Sesizarea cu id={sesizare_id} nu există."
        # Șterge fișierele asociate
        files_stmt = select(SesizareFile).where(SesizareFile.sesizare_id == sesizare_id)
        files = db.execute(files_stmt).scalars().all()
        for f in files:
            db.delete(f)
        db.delete(sesizare)
        db.commit()
    log_event("sesizare_stergere", level="WARNING", category="sesizare", details=f"Sesizare #{sesizare_id} ștearsă definitiv", target_id=str(sesizare_id))
    return True, "Sesizarea și fișierele asociate au fost șterse."


# ---------------------------------------------------------------------------
# Funcții pentru fișiere atașate
# ---------------------------------------------------------------------------

def add_sesizare_file(
    sesizare_id: int,
    fisier_path: str,
    tip: str,
    uploaded_by: str,
    descriere: str | None = None,
) -> SesizareFile:
    """Adaugă un fișier la sesizare. tip='rezolutie' sau 'completare'."""
    with SessionLocal() as db:
        db.expire_on_commit = False
        sf = SesizareFile(
            sesizare_id=sesizare_id,
            fisier_path=fisier_path,
            tip=tip,
            uploaded_by=uploaded_by,
            descriere=descriere,
            uploaded_at=datetime.now(timezone.utc),
        )
        db.add(sf)
        db.commit()
        return sf


def get_sesizare_files(sesizare_id: int) -> list[SesizareFile]:
    """Returnează toate fișierele unei sesizări, ordonate după uploaded_at."""
    with SessionLocal() as db:
        stmt = (
            select(SesizareFile)
            .where(SesizareFile.sesizare_id == sesizare_id)
            .order_by(SesizareFile.uploaded_at)
        )
        files = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(files)


# ---------------------------------------------------------------------------
# Funcții de interogare sesizări (cu filtrare per rol)
# ---------------------------------------------------------------------------

def _apply_status_filter(stmt, status_filter: list[str] | None):
    if status_filter:
        stmt = stmt.where(Sesizare.status.in_(status_filter))
    return stmt


def get_sesizari_for_secretariat(status_filter: list[str] | None = None) -> list[Sesizare]:
    """Returnează toate sesizările. Dacă status_filter e dat, filtrează după status."""
    with SessionLocal() as db:
        stmt = select(Sesizare).order_by(Sesizare.created_at.desc())
        stmt = _apply_status_filter(stmt, status_filter)
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


def get_sesizari_for_dg(status_filter: list[str] | None = None) -> list[Sesizare]:
    """Returnează sesizările cu status in_derulare sau finalizat (după filter)."""
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            Sesizare.status.in_(["in_derulare", "finalizat"])
        ).order_by(Sesizare.created_at.desc())
        stmt = _apply_status_filter(stmt, status_filter)
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


def get_dept_visibility_chain(dept_name: str) -> list[str]:
    """Returnează toate departamentele vizibile din perspectiva dept_name:
    - urcă ierarhia (părinți, bunici etc.)
    - coboară ierarhia (copii, nepoți etc.)
    Ex: 'DEP_CALITATE' → ['DEP_CALITATE', 'SERV_MEDIU_PROCEDURI', ...parinti...]"""
    with SessionLocal() as db:
        all_depts = db.execute(select(Department)).scalars().all()

    parent_map = {d.name: d.parent_department for d in all_depts}
    children_map: dict[str, list[str]] = {}
    for d in all_depts:
        if d.parent_department:
            children_map.setdefault(d.parent_department, []).append(d.name)

    result = set()

    # urcă: dept_name + toți părinții
    current = dept_name
    visited_up: set[str] = set()
    while current and current not in visited_up:
        result.add(current)
        visited_up.add(current)
        current = parent_map.get(current)

    # coboară: toți descendenții (BFS)
    queue = list(children_map.get(dept_name, []))
    visited_down: set[str] = set()
    while queue:
        child = queue.pop(0)
        if child in visited_down:
            continue
        visited_down.add(child)
        result.add(child)
        queue.extend(children_map.get(child, []))

    return list(result)


def get_sesizari_for_dept(dept_name: str, status_filter: list[str] | None = None) -> list[Sesizare]:
    """Returnează sesizările vizibile pentru dept_name:
    include sesizări adresate departamentului, părinților și sub-departamentelor sale."""
    dept_chain = get_dept_visibility_chain(dept_name)
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            Sesizare.departament.in_(dept_chain)
        ).order_by(Sesizare.created_at.desc())
        stmt = _apply_status_filter(stmt, status_filter)
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


def get_sesizari_for_user(username: str, dept_name: str | None = None) -> list[Sesizare]:
    """Returnează sesizările vizibile unui user simplu:
    - status='in_derulare' AND departament=dept_al_userului (toate din dept, nu doar ale lui)
    - SAU status='finalizat' AND user_responsabil=username (finalizatele proprii)
    """
    with SessionLocal() as db:
        conditions = []

        if dept_name:
            conditions.append(
                and_(Sesizare.status == "in_derulare", Sesizare.departament == dept_name)
            )

        conditions.append(
            and_(Sesizare.status == "finalizat", Sesizare.user_responsabil == username)
        )

        stmt = select(Sesizare).where(or_(*conditions)).order_by(Sesizare.created_at.desc())
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)


# ---------------------------------------------------------------------------
# Sesizări finalizate — căutare + paginare
# ---------------------------------------------------------------------------

def get_sesizari_finalizate_paginate(
    *,
    visibility_mode: str,
    visibility_arg: str | None,
    search_text: str | None = None,
    departament_filter: str | None = None,
    data_from: date | None = None,
    data_to: date | None = None,
    aprobat_dg_filter: str = "toate",
    offset: int = 0,
    limit: int = 20,
) -> tuple[list, int]:
    """Returnează (sesizari_paginate, total) cu filtre și paginare.

    visibility_mode:
      "all"       — toate sesizările finalizate (secretariat, dg)
      "dept_chain" — cele din lanțul de departamente al visibility_arg
      "user_only" — doar cele ale utilizatorului visibility_arg
    """
    conditions: list = [Sesizare.status == "finalizat"]

    if visibility_mode == "dept_chain" and visibility_arg:
        dept_chain = get_dept_visibility_chain(visibility_arg)
        conditions.append(Sesizare.departament.in_(dept_chain))
    elif visibility_mode == "user_only" and visibility_arg:
        conditions.append(Sesizare.user_responsabil == visibility_arg)

    if search_text:
        like_pat = f"%{search_text}%"
        conditions.append(
            or_(
                Sesizare.titlu.ilike(like_pat),
                Sesizare.descriere.ilike(like_pat),
                Sesizare.autor.ilike(like_pat),
                Sesizare.numar_inregistrare.ilike(like_pat),
                Sesizare.user_responsabil.ilike(like_pat),
            )
        )

    if departament_filter:
        conditions.append(Sesizare.departament == departament_filter)

    if data_from:
        conditions.append(
            Sesizare.created_at >= datetime(data_from.year, data_from.month, data_from.day, 0, 0, 0)
        )

    if data_to:
        conditions.append(
            Sesizare.created_at <= datetime(data_to.year, data_to.month, data_to.day, 23, 59, 59)
        )

    if aprobat_dg_filter == "aprobate":
        conditions.append(Sesizare.dg_aprobat_la.isnot(None))
    elif aprobat_dg_filter == "neaprobate":
        conditions.append(Sesizare.dg_aprobat_la.is_(None))

    where_clause = and_(*conditions)

    with SessionLocal() as db:
        total: int = db.execute(
            select(func.count(Sesizare.id)).where(where_clause)
        ).scalar() or 0

        rows = db.execute(
            select(Sesizare)
            .where(where_clause)
            .order_by(Sesizare.created_at.desc())
            .offset(offset)
            .limit(limit)
        ).scalars().all()
        db.expunge_all()

    return list(rows), total


# ---------------------------------------------------------------------------
# Funcții pentru rapoarte
# ---------------------------------------------------------------------------

def raport_sesizari_per_dept() -> list[dict]:
    """Returnează lista [{dept, total, active, finalizate}] — agregare SQL."""
    with SessionLocal() as db:
        rows = db.execute(
            select(
                Sesizare.departament,
                func.count(Sesizare.id).label("total"),
                func.sum(case((Sesizare.status == "in_derulare", 1), else_=0)).label("active"),
                func.sum(case((Sesizare.status == "finalizat", 1), else_=0)).label("finalizate"),
            )
            .where(Sesizare.departament.isnot(None))
            .group_by(Sesizare.departament)
            .order_by(Sesizare.departament)
        ).all()
    return [{"dept": r[0], "total": r[1], "active": r[2], "finalizate": r[3]} for r in rows]


def raport_timp_mediu_rezolvare() -> list[dict]:
    """Returnează [{dept, user, timp_mediu_zile}] — agregare SQL cu julianday."""
    with SessionLocal() as db:
        rows = db.execute(
            select(
                func.coalesce(Sesizare.departament, "Necunoscut").label("dept"),
                func.coalesce(Sesizare.user_responsabil, "Neatribuit").label("user"),
                func.round(
                    func.avg(func.julianday(Sesizare.finalizat_at) - func.julianday(Sesizare.created_at)),
                    2
                ).label("timp_mediu_zile"),
            )
            .where(and_(Sesizare.status == "finalizat", Sesizare.finalizat_at.isnot(None)))
            .group_by(Sesizare.departament, Sesizare.user_responsabil)
            .order_by(Sesizare.departament, Sesizare.user_responsabil)
        ).all()
    return [{"dept": r[0], "user": r[1], "timp_mediu_zile": r[2]} for r in rows]


def raport_sesizari_per_luna(an: int) -> list[dict]:
    """Returnează [{luna (1-12), total, finalizate}] pentru un an dat — agregare SQL."""
    with SessionLocal() as db:
        rows = db.execute(
            select(
                func.strftime("%m", Sesizare.created_at).label("luna"),
                func.count(Sesizare.id).label("total"),
                func.sum(case((Sesizare.status == "finalizat", 1), else_=0)).label("finalizate"),
            )
            .where(func.strftime("%Y", Sesizare.created_at) == str(an))
            .group_by(func.strftime("%m", Sesizare.created_at))
            .order_by(func.strftime("%m", Sesizare.created_at))
        ).all()

    monthly = {m: {"luna": m, "total": 0, "finalizate": 0} for m in range(1, 13)}
    for r in rows:
        luna = int(r[0])
        monthly[luna] = {"luna": luna, "total": r[1], "finalizate": r[2]}
    return [monthly[m] for m in range(1, 13)]


def raport_neatribuite() -> list[Sesizare]:
    """Returnează sesizările cu status='in_derulare' și user_responsabil IS NULL."""
    with SessionLocal() as db:
        stmt = select(Sesizare).where(
            and_(
                Sesizare.status == "in_derulare",
                Sesizare.user_responsabil.is_(None),
            )
        ).order_by(Sesizare.created_at)
        sesizari = db.execute(stmt).scalars().all()
        db.expunge_all()
        return list(sesizari)