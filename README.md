# eMapa Apa Prod v2 — Documentație

## Cuprins

1. [Descriere generală](#1-descriere-generală)
2. [Tehnologii folosite](#2-tehnologii-folosite)
3. [Structura proiectului](#3-structura-proiectului)
4. [Modele de date](#4-modele-de-date)
5. [Instalare și pornire](#5-instalare-și-pornire)
6. [Funcționalități](#6-funcționalități)
7. [Roluri și permisiuni](#7-roluri-și-permisiuni)
8. [Fluxul documentelor](#8-fluxul-documentelor)
9. [Semnături digitale și PDF](#9-semnături-digitale-și-pdf)
10. [Administrare](#10-administrare)
11. [Module și servicii](#11-module-și-servicii)
12. [Configurare server](#12-configurare-server)
13. [Securitate](#13-securitate)
14. [Date inițiale (seed)](#14-date-inițiale-seed)
15. [Extensii planificate](#15-extensii-planificate)

---

## 1. Descriere generală

**eMapa Apa Prod v2** este o aplicație web enterprise pentru gestionarea documentelor și a fluxurilor de aprobare în cadrul organizației **Apa Prod**. Aplicația acoperă întregul ciclu de viață al unui document: de la încărcare (upload), prin etapele de aprobare cu semnături, până la arhivare și descărcare.

**Caracteristici principale:**
- Încărcare și gestiune documente PDF
- Workflow configurabil de aprobare pe mai mulți pași
- Semnături digitale (imagini PNG) aplicate pe PDF
- Registratură (numerotare și arhivare documente)
- Sesizări / reclamații
- Administrare utilizatori și departamente cu structură ierarhică

---

## 2. Tehnologii folosite

| Componentă | Tehnologie |
|---|---|
| Framework UI | [Streamlit](https://streamlit.io/) 1.55.0 |
| Bază de date | SQLite (mod WAL) |
| ORM | SQLAlchemy 2.0 |
| Hashing parole | BCrypt (12 rounds) |
| Generare PDF | ReportLab + PyPDF |
| Semnături | streamlit-drawable-canvas |
| Procesare imagini | Pillow |
| API opțional | FastAPI |
| Tabele date | Pandas |

---

## 3. Structura proiectului

```
doc-mapa-v2/
├── app.py                      # Aplicația principală (~3000 linii)
├── import_useri.py             # Script import utilizatori în masă
├── README.txt                  # Note inițiale (text simplu)
│
├── install_and_start.bat       # Instalare dependențe + pornire server
├── install_server.bat          # Instalare pe Windows Server
├── start server.bat            # Pornire server (fără reinstalare)
├── update_app.bat              # Actualizare app cu backup automat
│
├── api/
│   └── api.py                  # Endpoint REST FastAPI (opțional, neintegrat)
│
├── core/
│   └── models.py               # Modele de date (minimal, logica e în app.py)
│
├── modules/
│   ├── admin_panel.py          # Panou admin (placeholder)
│   ├── dashboard.py            # Dashboard metrici (placeholder)
│   └── sesizari/
│       └── sesizari_ui.py      # Modul sesizări / reclamații
│
├── services/
│   ├── audit.py                # Model AuditLog
│   ├── backup.py               # Funcție backup bază de date
│   ├── backup_service.py       # Backup complet director data/
│   └── notifications.py        # Interogare aprobări în așteptare
│
├── assets/
│   └── logo Apa Prod v2.0.png  # Logo organizație
│
└── data/                       # Date generate la rulare (exclus din git)
    ├── app.db                  # Baza de date principală
    ├── sesizari.db             # Baza de date sesizări
    ├── uploads/YYYY/MM/        # Fișiere PDF încărcate (organizate pe dată)
    ├── signatures/             # Semnături per document
    ├── signatures/defaults/    # Semnături predefinite per utilizator
    └── final/                  # PDF-uri finale cu semnăturile aplicate
```

---

## 4. Modele de date

### 4.1 User — Utilizator

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `username` | str (unic) | Numele de login |
| `password_hash` | str | Parolă hashed BCrypt |
| `role` | str | `admin` / `user` / `secretariat` |
| `department` | str | Departamentul utilizatorului |
| `is_active` | bool | Cont activ / dezactivat |
| `full_name` | str | Nume complet (opțional) |
| `job_title` | str | Funcție (opțional) |
| `default_signature_path` | str | Cale PNG semnătură predefinită |
| `created_at` | DateTime | Data creării contului |

---

### 4.2 Department — Departament

| Câmp | Tip | Descriere |
|---|---|---|
| `name` | str (PK) | Numele departamentului (ex: `DEP_TEHNIC`) |
| `head_username` | str | Username-ul șefului de departament |
| `parent_department` | str | Departamentul părinte (ierarhie) |
| `created_at` | DateTime | Data creării |

---

### 4.3 Document

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară internă |
| `public_id` | str | Cod public uman-friendly (`EM-XXXXXX`) |
| `title` / `doc_name` | str | Denumirea documentului |
| `reg_no` | int | Număr registratură |
| `reg_date` | str | Data registraturii |
| `doc_type` | str | Tipul documentului |
| `department` | str | Departamentul care a creat documentul |
| `project` | str | Proiect asociat (opțional) |
| `doc_date` | Date | Data documentului |
| `tags_json` | JSON | Lista de etichete |
| `original_filename` | str | Numele original al fișierului PDF |
| `stored_path` | str | Calea relativă în `UPLOAD_DIR` |
| `sha256` | str | Hash SHA256 pentru deduplicare |
| `created_by` | str | Username-ul creatorului |
| `created_at` | DateTime | Data încărcării |
| `status` | str | `DRAFT` / `PENDING` / `APPROVED` / `REJECTED` / `CANCELLED` |
| `current_step` | int | Pasul curent din workflow |
| `workflow_json` | JSON | Definirea pașilor de aprobare |
| `final_pdf_path` | str | Calea PDF-ului final cu semnături |

---

### 4.4 Approval — Aprobare

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `document_id` | str | FK către Document |
| `step_order` | int | Ordinea pasului în workflow |
| `approver_username` | str | Aprobatorul responsabil |
| `status` | str | `WAITING` / `PENDING` / `APPROVED` / `REJECTED` |
| `decided_at` | DateTime | Data deciziei |
| `comment` | str | Comentariul aprobatorului |
| `signature_path` | str | Calea PNG a semnăturii |
| `signed_at` | str | Timestamp ISO al semnăturii |

---

### 4.5 DocType — Tip Document

| Câmp | Tip | Descriere |
|---|---|---|
| `name` | str (PK) | Numele tipului (ex: `Document`) |
| `workflow_json` | JSON | Pașii impliciti de aprobare pentru acest tip |
| `is_active` | bool | Tip activ / inactiv |
| `created_at` | DateTime | Data creării |

---

### 4.6 AuthToken — Token autentificare

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `username` | str | Utilizatorul asociat |
| `token_hash` | str | Hash SHA256 al token-ului |
| `expires_at` | DateTime | Expiră după 90 de zile |
| `created_at` | DateTime | Data creării |
| `last_used_at` | DateTime | Ultima utilizare |

---

### 4.7 AuditLog — Jurnal de audit

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `user` | str | Utilizatorul care a efectuat acțiunea |
| `action` | str | Tipul acțiunii |
| `document_id` | str | Documentul asociat |
| `message` | str | Detalii suplimentare |
| `created_at` | DateTime | Data acțiunii |

---

## 5. Instalare și pornire

### 5.1 Prima instalare (Windows Server)

```bat
install_and_start.bat
```

Scriptul:
1. Creează un mediu virtual Python (`.venv`)
2. Instalează toate dependențele necesare
3. Creează directoarele `data/`, `data/uploads/`, `data/signatures/`, `data/final/`
4. Pornește serverul pe portul `2645`
5. Deschide portul în firewall-ul Windows

### 5.2 Pornire obișnuită

```bat
start server.bat
```

### 5.3 Actualizare aplicație

```bat
update_app.bat
```

Scriptul:
1. Creează un backup al bazei de date cu timestamp
2. Creează un backup al `app.py` curent
3. Oprește procesul Python
4. Copiază noul `app.py` din directorul `update/`
5. Repornește serverul

### 5.4 Comandă manuală Streamlit

```bash
streamlit run app.py \
  --server.address 0.0.0.0 \
  --server.port 2645 \
  --server.headless true \
  --browser.gatherUsageStats false \
  --server.fileWatcherType none
```

### 5.5 Accesare aplicație

Aplicația este disponibilă la:

```
http://<IP-SERVER>:2645
```

---

## 6. Funcționalități

### 6.1 Autentificare

- Login cu username și parolă
- Opțiunea **"Ține-mă minte"** — autentificare automată 90 de zile via token persistent
- Logout cu revocare token
- Parole stocate cu BCrypt (12 rounds)

### 6.2 Încărcare documente

- Suportă **exclusiv fișiere PDF** (validare header `%PDF-`)
- Deduplicare automată prin hash SHA256 (nu permite același fișier de două ori)
- Fișierele sunt organizate pe disk în `data/uploads/YYYY/MM/`
- Fiecare document primește un cod unic public de forma **`EM-XXXXXX`**
- Metadate obligatorii: denumire document
- Metadate opționale: tip document, proiect, data documentului, etichete (tags)
- Status inițial: **CIORNĂ (DRAFT)**
- Directorul General nu poate încărca documente

### 6.3 Workflow de aprobare

Documentul parcurge o secvență de pași configurați de utilizatorul care a încărcat documentul.

**Tipuri de pași suportate:**

| Tip | Descriere |
|---|---|
| `DEPT_HEAD_OF` | Șeful unui departament specificat explicit (standard) |
| `DEPT_HEAD` | Șeful departamentului documentului (legacy) |
| `PARENT_HEAD` | Șeful departamentului părinte (legacy) |
| `USER` | Un utilizator specificat direct (legacy) |

**Reguli:**
- **Directorul General** (departament `GENERAL`) este adăugat automat ca ultimul pas al oricărui workflow — nu poate fi adăugat manual
- Status-urile posibile: `WAITING → PENDING → APPROVED / REJECTED`
- Semnătura este **obligatorie** la aprobare
- Comentariul este opțional

### 6.4 Inbox aprobări

- Fiecare aprobator vede în **Inbox** documentele care îi sunt alocate și au status `PENDING`
- Click pe un rând din lista Inbox completează automat câmpul cod document
- Acțiuni disponibile: **Aprobă** sau **Respinge**
- Se poate previzualiza PDF-ul documentului înainte de decizie

### 6.5 Registratură (Secretariat)

- Secretariatul are acces la **toate documentele** din sistem
- Funcționalități:
  - Căutare avansată (după cod, denumire, fișier, etichete)
  - Filtrare: documente neînregistrate, perioadă, număr registratură
  - Editare **număr registratură** și **dată registratură**
  - Descărcare PDF original sau PDF final (cu semnături)
  - Previzualizare PDF în browser (tab Chrome)
  - Ștergere definitivă cu confirmare
- Paginare: 50 / 100 / 200 / 500 documente per pagină

### 6.6 Arhivă

| Rol | Documente vizibile |
|---|---|
| **User** | Propriile documente + documente la care este aprobator |
| **Secretariat** | Toate documentele din sistem |
| **Admin** | Toate documentele din sistem |

### 6.7 Sesizări / Reclamații

- Modul separat cu baza de date proprie (`sesizari.db`)
- **Secretariatul** poate crea sesizări (titlu, descriere, PDF, responsabil)
- **Utilizatorii** pot vizualiza sesizările și descărca PDF-ul asociat

---

## 7. Roluri și permisiuni

| Acțiune | Admin | Secretariat | User |
|---|:---:|:---:|:---:|
| Vizualizare toate documentele | ✓ | ✓ | — |
| Încărcare documente | ✓ | — | ✓ |
| Aprobare documente | ✓ | — | ✓ |
| Editare registratură | ✓ | ✓ | — |
| Ștergere documente | ✓ | ✓ | — |
| Creare sesizări | — | ✓ | — |
| Vizualizare sesizări | ✓ | ✓ | ✓ |
| Administrare utilizatori | ✓ | — | — |
| Administrare departamente | ✓ | — | — |

**Meniu aplicație per rol:**

- **Admin**: Dashboard, Arhivă, Sesizări, Administrare
- **Secretariat**: Dashboard, Arhivă, Sesizări
- **User**: Dashboard, Încărcare, Arhivă, Inbox Aprobări, Sesizări

---

## 8. Fluxul documentelor

```
[User] Încarcă PDF
        │
        ▼
   Status: DRAFT
        │
[User] Definește workflow (selectează șefi de departamente)
        │
[User] Pornește workflow
        │
        ▼
   Status: PENDING (IN APROBARE)
        │
   ┌────▼────────────────────────────────┐
   │  Pas 1: Aprobator primar           │
   │  (PENDING → APPROVED / REJECTED)   │
   └────┬────────────────────────────────┘
        │ APPROVED ↓ / REJECTED → Status document REJECTED
   ┌────▼────────────────────────────────┐
   │  Pas 2: ...                        │
   └────┬────────────────────────────────┘
        │
   ┌────▼────────────────────────────────┐
   │  Ultimul pas: Director General      │
   │  (adăugat automat)                 │
   └────┬────────────────────────────────┘
        │ APPROVED
        ▼
   Status: APPROVED (APROBAT)
   → PDF final generat automat (cu pagina de semnături)
        │
[Secretariat] Adaugă Nr. și Data registraturii
        │
        ▼
   Document arhivat și disponibil pentru descărcare
```

**Statusuri document (cu traducere în română):**

| Status intern | Afișare |
|---|---|
| `DRAFT` | CIORNĂ |
| `PENDING` | ÎN APROBARE |
| `APPROVED` | APROBAT |
| `REJECTED` | RESPINS |
| `CANCELLED` | ANULAT |

---

## 9. Semnături digitale și PDF

### 9.1 Tipuri de semnături

1. **Semnătură desenată în browser** — utilizatorul desenează cu mouse-ul pe canvas (widget `streamlit-drawable-canvas`)
2. **Semnătură predefinită** — imagine PNG salvată în `data/signatures/defaults/` și reutilizabilă la fiecare aprobare

> **Notă:** Semnăturile sunt imagini PNG, nu certificate digitale X.509.

### 9.2 Generarea PDF-ului final

La aprobarea finală a documentului, aplicația generează automat un PDF complet care conține:
1. **PDF-ul original** (toate paginile)
2. **O pagină suplimentară** generată cu ReportLab, care include:
   - Codul public al documentului (`EM-XXXXXX`)
   - Denumirea documentului
   - Departamentul
   - Creat de
   - Număr și dată registratură
   - Tabel cu toți aprobatorii, statusul, data deciziei, comentariile
   - Imaginile semnăturilor (180×60px fiecare)

PDF-ul final este salvat în `data/final/{document_id}_final.pdf`.

---

## 10. Administrare

Accesibil exclusiv rolului **admin**, din meniul **Administrare**.

### 10.1 Gestionare utilizatori

- Creare utilizator (username, parolă, rol, nume complet, funcție, departament)
- Editare (rol, departament, activ/inactiv, nume, funcție)
- Dezactivare cont
- Ștergere definitivă (cu verificare că nu există documente sau referințe)
- Resetare parolă

### 10.2 Gestionare departamente

- Structura ierarhică: fiecare departament poate avea un departament **părinte**
- Setarea **șefului de departament** (legat de un utilizator existent)
- Departamentul `GENERAL` reprezintă nivelul Director General — șeful acestuia semnează ultimul în orice workflow

### 10.3 Schimbare parolă proprie

Administratorul poate schimba propria parolă din același panou, cu verificarea parolei vechi.

---

## 11. Module și servicii

### 11.1 `api/api.py` — REST API (opțional)

Endpoint FastAPI disponibil dar **neintegrat** în aplicația principală:

```
GET /documents
→ Returnează lista de documente (id, doc_name, status)
```

### 11.2 `services/audit.py`

Definește modelul `AuditLog`. Modelul există în baza de date, dar **nu este populat activ** în versiunea curentă.

### 11.3 `services/backup.py`

```python
backup_database(db_path, backup_dir)
# Copiază fișierul DB cu timestamp în directorul de backup
```

### 11.4 `services/backup_service.py`

```python
run_backup()
# Copiază întregul director data/ în data/backups/backup_YYYYMMDD_HHMM/
```

### 11.5 `services/notifications.py`

```python
pending_for_user(username)
# Returnează lista de aprobări PENDING pentru un utilizator
```

### 11.6 `modules/sesizari/sesizari_ui.py`

```python
render_sesizari(username, role)
# Afișează interfața pentru sesizări/reclamații
```

### 11.7 `modules/dashboard.py`

```python
render_dashboard()
# Placeholder cu metrici (Documente, Sesizări, Aprobări) — neimplementat complet
```

---

## 12. Configurare server

### 12.1 Port implicit

Aplicația rulează pe portul **2645** pe toate interfețele de rețea (`0.0.0.0`).

### 12.2 Parametri Streamlit

| Parametru | Valoare | Descriere |
|---|---|---|
| `server.address` | `0.0.0.0` | Ascultă pe toate interfețele |
| `server.port` | `2645` | Port aplicație |
| `server.headless` | `true` | Nu deschide browser automat |
| `browser.gatherUsageStats` | `false` | Dezactivează telemetria |
| `server.fileWatcherType` | `none` | Dezactivează reîncărcarea automată |

### 12.3 Baza de date SQLite — optimizări

| PRAGMA | Valoare | Descriere |
|---|---|---|
| `journal_mode` | `WAL` | Write-Ahead Logging pentru concurență |
| `synchronous` | `NORMAL` | Echilibru performanță / siguranță |
| `busy_timeout` | `5000` ms | Așteptare la lock conflict |

---

## 13. Securitate

### 13.1 Autentificare

- Parole stocate cu **BCrypt** (factor cost 12)
- Token-uri "Ține-mă minte" stocate ca hash **SHA256** (nu în clar)
- Expirare token automată după **90 de zile**
- Sesiunile sunt gestionate server-side de Streamlit

### 13.2 Autorizare

- **Bazată pe rol** (`admin`, `secretariat`, `user`)
- **Bazată pe departament**: utilizatorii văd documentele departamentului propriu și ale sub-departamentelor
- **Bazată pe implicare**: utilizatorii văd și documentele la care sunt desemnați ca aprobatori

### 13.3 Integritatea documentelor

- Validare tip fișier: doar PDF (verificare header `%PDF-`)
- Deduplicare prin hash **SHA256** — nu se permite re-încărcarea unui fișier identic
- Ștergerea unui document elimină și toate fișierele asociate (original, final, semnături)

---

## 14. Date inițiale (seed)

La prima pornire, aplicația populează automat baza de date cu:

### 14.1 Utilizator admin implicit

| Câmp | Valoare |
|---|---|
| Username | `admin` |
| Parolă | `admin123!` |
| Rol | `admin` |
| Departament | `GENERAL` |

> **Important:** Schimbați parola după prima autentificare!

### 14.2 Departamente pre-configurate

Aplicația vine cu **31 de departamente** pre-definite, incluzând:
- `GENERAL` (Director General)
- `DEP_ECONOMIC`, `DEP_TEHNIC`, `DEP_EXPLOATARE`, etc.
- Sub-departamente cu relații ierarhice configurate

### 14.3 Tip document implicit

| Câmp | Valoare |
|---|---|
| Nume | `Document` |
| Activ | `true` |

---

## 15. Extensii planificate

Următoarele module există în proiect dar nu sunt complet implementate:

| Modul | Stare | Descriere |
|---|---|---|
| **Audit logging** | Model creat, neintegrat | Jurnalizarea completă a acțiunilor utilizatorilor |
| **API REST** | Stub FastAPI, neintegrat în app | Expunere endpoint-uri pentru integrări externe |
| **Panou admin** | Placeholder | Panou de administrare extins |
| **Notificări** | Funcție creată, fără UI | Notificări email / în-aplicație |
| **Backup scheduler** | Funcții create, fără declanșare automată | Backup automat periodic |
| **Dashboard metrici** | Placeholder cu date statice | Statistici și grafice în timp real |

---

*Documentație generată pentru eMapa Apa Prod v2 — versiunea curentă.*