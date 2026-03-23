# eMapa Apa Prod v2 — Documentație

## Cuprins

1. [Descriere generală](#1-descriere-generală)
2. [Tehnologii folosite](#2-tehnologii-folosite)
3. [Structura proiectului](#3-structura-proiectului)
4. [Modele de date](#4-modele-de-date)
5. [Instalare și pornire](#5-instalare-și-pornire)
6. [Funcționalități — Documente](#6-funcționalități--documente)
7. [Funcționalități — Sesizări](#7-funcționalități--sesizări)
8. [Roluri și permisiuni](#8-roluri-și-permisiuni)
9. [Fluxul documentelor](#9-fluxul-documentelor)
10. [Fluxul sesizărilor](#10-fluxul-sesizărilor)
11. [Semnături digitale și PDF](#11-semnături-digitale-și-pdf)
12. [Dashboard](#12-dashboard)
13. [Administrare](#13-administrare)
14. [Module și servicii](#14-module-și-servicii)
15. [Configurare server](#15-configurare-server)
16. [Securitate](#16-securitate)
17. [Date inițiale (seed)](#17-date-inițiale-seed)

---

## 1. Descriere generală

**eMapa Apa Prod v2** este o aplicație web enterprise pentru gestionarea documentelor și a fluxurilor de aprobare în cadrul organizației **Apa Prod**. Aplicația acoperă întregul ciclu de viață al unui document (upload → aprobare → arhivare) și include un modul complet de gestionare a sesizărilor/reclamațiilor.

**Caracteristici principale:**
- Încărcare și gestiune documente PDF cu deduplicare SHA256
- Workflow configurabil de aprobare pe mai mulți pași cu semnături
- Modul complet de sesizări / reclamații cu flux multi-rol
- Dashboard cu metrici în timp real
- Registratură (numerotare și arhivare documente)
- Administrare utilizatori și departamente cu structură ierarhică
- Autentificare persistentă cu token (90 zile)

---

## 2. Tehnologii folosite

| Componentă | Tehnologie |
|---|---|
| Framework UI | Streamlit |
| Bază de date | SQLite (mod WAL) |
| ORM | SQLAlchemy 2.0 |
| Hashing parole | BCrypt (12 rounds) |
| Generare PDF | ReportLab + PyPDF |
| Semnături canvas | streamlit-drawable-canvas |
| Procesare imagini | Pillow |
| Tabele date | Pandas |
| API opțional | FastAPI |

---

## 3. Structura proiectului

```
doc-mapa-v2/
├── app.py                          # Punct de intrare: login, sidebar, routing pagini
├── import_useri.py                 # Script import utilizatori în masă
│
├── install_and_start.bat           # Instalare dependențe + pornire server
├── start server.bat                # Pornire server (fără reinstalare)
├── update_app.bat                  # Actualizare app cu backup automat
│
├── modules/
│   ├── config.py                   # Căi directoare, constante globale (DG_DEPT etc.)
│   ├── dashboard.py                # Dashboard cu metrici reale din DB
│   │
│   ├── auth/
│   │   ├── auth.py                 # is_admin(), is_secretariat(), is_dg(), require_login()
│   │   └── remember_me.py          # Token-uri persistente "Ține-mă minte"
│   │
│   ├── database/
│   │   ├── models.py               # Modele SQLAlchemy (User, Department, Document, Sesizare, ...)
│   │   ├── migrations.py           # auto_migrate_and_seed() — migrare + seed la pornire
│   │   └── session.py              # Engine SQLite + SessionLocal
│   │
│   ├── departments/
│   │   └── dept_service.py         # Ierarhie departamente (descendenți, copii)
│   │
│   ├── pages/
│   │   ├── admin.py                # Panou administrare (useri, departamente)
│   │   ├── archive.py              # Arhivă documente cu căutare și filtrare
│   │   ├── inbox.py                # Inbox aprobări cu semnătură canvas
│   │   ├── secretariat_page.py     # Registratură secretariat
│   │   └── upload.py               # Încărcare documente + configurare workflow
│   │
│   ├── services/
│   │   ├── document_service.py     # CRUD documente
│   │   ├── pdf_service.py          # Generare PDF final cu semnături
│   │   ├── signature_service.py    # Gestionare semnături predefinite
│   │   └── workflow_service.py     # Motor workflow aprobare (decide, start, etc.)
│   │
│   ├── sesizari/
│   │   ├── sesizari_service.py     # Business logic sesizări (CRUD, filtrare, rapoarte)
│   │   └── sesizari_ui.py          # UI sesizări — interfață completă multi-rol
│   │
│   ├── utils/
│   │   ├── files.py                # Utilitare fișiere
│   │   ├── formatting.py           # Formatare etichete, statusuri, nume useri
│   │   └── ui_helpers.py           # Componente UI reutilizabile
│   │
│   └── workflow/
│       └── workflow_builder.py     # Constructor pași workflow
│
├── api/
│   └── api.py                      # Endpoint REST FastAPI (opțional, neintegrat)
│
├── services/
│   ├── audit.py                    # Model AuditLog (neintegrat activ)
│   ├── backup.py                   # Backup bază de date
│   └── notifications.py            # Interogare aprobări în așteptare
│
├── assets/
│   └── logo Apa Prod v2.0.png
│
└── data/                           # Generate la rulare (exclus din git)
    ├── app.db                      # Baza de date principală (toate tabelele)
    ├── uploads/                    # PDF-uri încărcate (organizate YYYY/MM)
    ├── uploads/sesizari/           # PDF-uri sesizări
    ├── signatures/                 # Semnături per document
    ├── signatures/defaults/        # Semnături predefinite per utilizator
    ├── signatures/sesizari/semnaturi/  # Semnături DG pentru aprobare sesizări
    └── final/                      # PDF-uri finale cu semnăturile aplicate
```

---

## 4. Modele de date

### 4.1 User

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `username` | str (unic) | Numele de login |
| `password_hash` | str | Parolă hashed BCrypt |
| `role` | str | `admin` / `user` / `secretariat` / `dg` |
| `department` | str | Departamentul utilizatorului |
| `is_active` | bool | Cont activ / dezactivat |
| `full_name` | str | Nume complet (opțional) |
| `job_title` | str | Funcție (opțional) |
| `default_signature_path` | str | Cale PNG semnătură predefinită |
| `created_at` | DateTime | Data creării contului |

---

### 4.2 Department

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
| `public_id` | str | Cod public (`EM-XXXXXX`) |
| `title` / `doc_name` | str | Denumirea documentului |
| `reg_no` | int | Număr registratură |
| `reg_date` | str | Data registraturii |
| `doc_type` | str | Tipul documentului |
| `department` | str | Departamentul creator |
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

### 4.4 Approval

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `document_id` | str | FK → Document |
| `step_order` | int | Ordinea pasului |
| `approver_username` | str | Aprobatorul responsabil |
| `status` | str | `WAITING` / `PENDING` / `APPROVED` / `REJECTED` |
| `decided_at` | DateTime | Data deciziei |
| `comment` | str | Comentariul aprobatorului |
| `signature_path` | str | Calea PNG a semnăturii |

---

### 4.5 Sesizare

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | Integer (PK, autoincrement) | Cheie primară |
| `numar_inregistrare` | str (unic) | Format `SZ-YYYY-NNN` (ex: `SZ-2026-001`) |
| `titlu` | str | Titlul sesizării |
| `descriere` | str | Descriere detaliată (opțional) |
| `pdf_path` | str | Calea PDF-ului inițial (opțional) |
| `autor` | str | Username-ul secretarei care a creat sesizarea |
| `departament` | str | Departamentul asociat (setat de DG) |
| `user_responsabil` | str | Userul responsabil (setat de șeful de dept) |
| `status` | str | `nou` / `in_derulare` / `finalizat` |
| `created_at` | DateTime | Data creării |
| `trimis_la_dg_at` | DateTime | Când secretara a trimis la DG |
| `distribuit_la_dept_at` | DateTime | Când DG a distribuit la departament |
| `atribuit_la_user_at` | DateTime | Când a fost atribuit unui user |
| `finalizat_at` | DateTime | Când a fost marcată finalizată |
| `observatii_finalizare` | str | Note la finalizare |
| `necesita_aprobare_dg` | bool | Dacă rezoluția necesită aprobare DG |
| `dg_aprobat_la` | DateTime | Când DG a aprobat rezoluția |
| `dg_semnatura_path` | str | Calea PNG a semnăturii DG de aprobare |

---

### 4.6 SesizareFile

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | Integer (PK, autoincrement) | Cheie primară |
| `sesizare_id` | int | FK → Sesizare |
| `fisier_path` | str | Calea relativă a fișierului |
| `tip` | str | `rezolutie` sau `completare` |
| `uploaded_by` | str | Username-ul celui care a încărcat |
| `uploaded_at` | DateTime | Data încărcării |
| `descriere` | str | Descriere opțională |

---

### 4.7 AuthToken

| Câmp | Tip | Descriere |
|---|---|---|
| `id` | UUID | Cheie primară |
| `username` | str | Utilizatorul asociat |
| `token_hash` | str | Hash SHA256 al token-ului |
| `expires_at` | DateTime | Expiră după 90 de zile |
| `created_at` | DateTime | Data creării |
| `last_used_at` | DateTime | Ultima utilizare |

---

## 5. Instalare și pornire

### 5.1 Prima instalare (Windows Server)

```bat
install_and_start.bat
```

Scriptul: creează `.venv`, instalează dependențele, creează directoarele `data/`, pornește serverul pe portul `2645` și deschide portul în firewall.

### 5.2 Pornire obișnuită

```bat
start server.bat
```

### 5.3 Actualizare aplicație

```bat
update_app.bat
```

### 5.4 Comandă manuală Streamlit

```bash
streamlit run app.py --server.address 0.0.0.0 --server.port 2645 --server.headless true --browser.gatherUsageStats false --server.fileWatcherType none
```

### 5.5 Accesare

```
http://<IP-SERVER>:2645
```

---

## 6. Funcționalități — Documente

### 6.1 Autentificare

- Login cu username și parolă
- **"Ține-mă minte"** — autentificare automată 90 de zile via token persistent în `localStorage`
- Logout cu revocare token
- Parole stocate cu BCrypt (12 rounds)

### 6.2 Încărcare documente

- Suportă **exclusiv PDF** (validare header `%PDF-`)
- Deduplicare automată prin hash SHA256
- Organizare pe disk: `data/uploads/YYYY/MM/`
- Cod unic public: **`EM-XXXXXX`**
- Status inițial: **DRAFT**
- Directorul General (`role=dg`) nu poate încărca documente

### 6.3 Workflow de aprobare

Documentul parcurge o secvență de pași configurați la încărcare.

| Tip pas | Descriere |
|---|---|
| `DEPT_HEAD_OF` | Șeful unui departament specificat explicit |
| `DEPT_HEAD` | Șeful departamentului documentului (legacy) |
| `PARENT_HEAD` | Șeful departamentului părinte (legacy) |
| `USER` | Un utilizator specificat direct (legacy) |

- Directorul General (dept `GENERAL`) este adăugat automat ca ultimul pas
- Semnătura este **obligatorie** la aprobare (canvas cu mouse sau semnătură predefinită)

### 6.4 Inbox aprobări

- Aprobatorul vede documentele `PENDING` alocate lui
- Click pe tabel completează automat codul documentului
- Acțiuni: **Aprobă** (cu semnătură) sau **Respinge**
- Previzualizare PDF în Chrome înainte de decizie

### 6.5 Registratură (Secretariat)

- Acces la toate documentele din sistem
- Căutare după cod, denumire, fișier, etichete
- Filtrare: documente neînregistrate, perioadă, număr registratură
- Editare număr și dată registratură
- Descărcare PDF original sau final (cu semnături)
- Ștergere definitivă

### 6.6 Arhivă

| Rol | Documente vizibile |
|---|---|
| **User** | Propriile documente + documentele la care este aprobator |
| **Secretariat / Admin** | Toate documentele |

---

## 7. Funcționalități — Sesizări

Modul complet de gestionare a sesizărilor/reclamațiilor, integrat în aceeași bază de date (`app.db`).

### 7.1 Creare sesizare (Secretariat)

- Câmpuri: titlu*, număr înregistrare (auto-generat `SZ-YYYY-NNN` sau manual), descriere, PDF atașat
- Status inițial: `nou`
- Secretara trimite sesizarea la DG (buton **"Trimite la DG"**) → status devine `in_derulare`

### 7.2 Distribuire la departament (Director General)

- DG vede toate sesizările cu status `in_derulare`
- Asociază sesizarea unui departament (selectbox)
- Poate vedea sesizările finalizate în tab separat

### 7.3 Atribuire user responsabil (Șef departament)

- Șeful de departament (`head_username` în tabelul `departments`, cu `role=dg`) vede sesizările departamentului său
- Atribuie sesizarea unui user din departament
- Poate **redirecționa** sesizarea către alt departament dacă DG a distribuit greșit

### 7.4 Preluare și redirecționare (User simplu)

- Userul vede toate sesizările `in_derulare` ale departamentului său (poate vedea cine se ocupă de fiecare)
- Dacă sesizarea nu are responsabil → buton **"Preiau această sesizare"** (se auto-atribuie)
- Lângă butonul de preluare → selectbox + buton **"Redirecționează"** (trimite la alt departament)

### 7.5 Finalizare sesizare (User responsabil)

- Userul responsabil marchează sesizarea ca finalizată
- **Obligatoriu**: upload PDF rezoluție
- Opțional: observații de finalizare
- După finalizare, userul poate adăuga **completări** (fișiere PDF suplimentare)

### 7.6 Aprobare opțională DG

- Pe orice sesizare finalizată, **userul responsabil** sau **directorul general** poate bifa **"Necesită aprobare DG"**
- Sesizările bifate apar în tab-ul **"De aprobat"** al DG
- DG aprobă cu **semnătură desenată pe canvas** (mouse)
- Semnătura apare vizibil pe sesizare pentru toți utilizatorii implicați

### 7.7 Rapoarte (Secretariat și DG)

- **Metrici rapide**: total, active, finalizate, neatribuite
- **Sesizări per departament**: tabel + bar chart
- **Timp mediu rezolvare**: per departament și user (în zile)
- **Sesizări pe luni**: bar chart pentru anul curent
- **Sesizări neatribuite**: lista sesizărilor fără responsabil

---

## 8. Roluri și permisiuni

### 8.1 Roluri în sistem

| Rol (DB) | Funcție | Cum se identifică |
|---|---|---|
| `admin` | Administrator sistem | `role = 'admin'` |
| `secretariat` | Secretară | `role = 'secretariat'` |
| `dg` | Șef departament | `role = 'dg'` + este `head_username` al unui departament (≠ GENERAL) |
| `dg` | Director General | `role = 'dg'` + nu este `head_username` al niciunui departament real |
| `user` | Utilizator obișnuit | `role = 'user'` |

> **Important:** Atât directorul general cât și șefii de departamente au `role = 'dg'` în baza de date. Distincția se face la runtime: dacă username-ul este `head_username` al unui departament (altul decât `GENERAL`), aplicația îl tratează ca **șef de departament**; altfel, ca **Director General**.

### 8.2 Tabel permisiuni

| Acțiune | Admin | Secretariat | DG (Director) | DG (Șef dept) | User |
|---|:---:|:---:|:---:|:---:|:---:|
| Vizualizare toate documentele | ✓ | ✓ | — | — | — |
| Încărcare documente | ✓ | — | — | — | ✓ |
| Aprobare documente | ✓ | — | ✓ | ✓ | ✓ |
| Editare registratură | ✓ | ✓ | — | — | — |
| Ștergere documente | ✓ | ✓ | — | — | — |
| Creare sesizări | — | ✓ | — | — | — |
| Trimitere sesizare la DG | — | ✓ | — | — | — |
| Distribuire sesizare la dept | — | — | ✓ | — | — |
| Atribuire user responsabil | — | ✓* | — | ✓ | — |
| Redirecționare sesizare | — | — | — | ✓ | ✓ |
| Preluare sesizare | — | — | — | — | ✓ |
| Finalizare sesizare | — | — | — | — | ✓ |
| Aprobare DG cu semnătură | — | — | ✓ | — | — |
| Vizualizare rapoarte sesizări | — | ✓ | ✓ | — | — |
| Administrare useri/dept | ✓ | — | — | — | — |

*Secretara poate atribui user când șeful de departament lipsește.

### 8.3 Meniu aplicație per rol

- **Admin**: Dashboard, Arhivă, Sesizări, Administrare
- **Secretariat**: Dashboard, Arhivă, Sesizări
- **DG / User**: Dashboard, Încărcare, Arhivă, Inbox Aprobări, Sesizări

---

## 9. Fluxul documentelor

```
[User] Încarcă PDF
        │
        ▼
   Status: DRAFT
        │
[User] Configurează workflow + Pornește
        │
        ▼
   Status: PENDING
        │
   ┌────▼──────────────────────────────┐
   │  Pas 1: Aprobator                │
   │  Semnează + Aprobă / Respinge    │
   └────┬──────────────────────────────┘
        │ APPROVED
   ┌────▼──────────────────────────────┐
   │  Pas 2..N: Alți aprobatori       │
   └────┬──────────────────────────────┘
        │
   ┌────▼──────────────────────────────┐
   │  Ultimul pas: Director General   │
   │  (adăugat automat)              │
   └────┬──────────────────────────────┘
        │ APPROVED
        ▼
   Status: APPROVED
   → PDF final generat automat (cu pagina de semnături)
        │
[Secretariat] Adaugă Nr. și Data registraturii
        ▼
   Document arhivat
```

---

## 10. Fluxul sesizărilor

```
[Secretară]         [DG]             [Șef Dept]         [User]
     │                │                   │                 │
     ▼                │                   │                 │
Creare sesizare       │                   │                 │
(status = nou)        │                   │                 │
     │                │                   │                 │
Trimite la DG ───────►│                   │                 │
(status = in_derulare)│                   │                 │
                 Asociază dept ──────────►│                 │
                 (departament = X)        │                 │
                                    Atribuie user ─────────►│
                                    SAU redirecționează     │
                                    spre alt dept           │
                                                       Preia sesizarea
                                                       SAU redirecționează
                                                            │
                                                       Marchează finalizat
                                                       + upload PDF rezoluție
                                                       (status = finalizat)
                                                            │
                                              [opțional] Bifează "Necesită aprobare DG"
                                                            │
                      Aprobă cu semnătură ◄─────────────────┘
                      (tab "De aprobat")
```

**Statusuri sesizare:**

| Status | Semnificație |
|---|---|
| `nou` | Creată de secretară, netrimisă |
| `in_derulare` | Trimisă la DG; în curs de atribuire / rezolvare |
| `finalizat` | Rezolvată de userul responsabil |

---

## 11. Semnături digitale și PDF

### 11.1 Tipuri de semnături

1. **Semnătură desenată pe canvas** — mouse pe widget `streamlit-drawable-canvas`
2. **Semnătură predefinită** — PNG salvat în `data/signatures/defaults/` și reutilizabil
3. **Semnătură DG sesizări** — PNG salvat în `data/signatures/sesizari/semnaturi/`

> Semnăturile sunt imagini PNG, nu certificate digitale X.509.

### 11.2 Generarea PDF-ului final (documente)

La aprobarea finală, se generează automat un PDF care conține:
1. PDF-ul original (toate paginile)
2. O pagină suplimentară cu: cod public, denumire, departament, creat de, registratură, tabel aprobători cu semnăturile lor

PDF-ul final: `data/final/{document_id}_final.pdf`

---

## 12. Dashboard

Dashboard-ul afișează metrici în timp real din baza de date, grupate în 3 secțiuni:

**Documente**
- Total documente, în aprobare, aprobate, respinse

**Sesizări**
- Total sesizări, noi, în derulare, finalizate

**Sistem**
- Aprobări în așteptare (din toate inbox-urile), utilizatori activi

---

## 13. Administrare

Accesibil exclusiv rolului **admin**.

### 13.1 Gestionare utilizatori

- Creare (username, parolă, rol, nume complet, funcție, departament)
- Editare (rol, departament, activ/inactiv, nume, funcție)
- Dezactivare cont / Ștergere definitivă / Resetare parolă

### 13.2 Gestionare departamente

- Structură ierarhică cu departament **părinte**
- Setarea **șefului de departament** (`head_username`) — determină cine are rol de șef în modulul sesizări
- `GENERAL` = departamentul Director General; șeful său semnează ultimul în orice workflow de documente

---

## 14. Module și servicii

### 14.1 `modules/sesizari/sesizari_service.py`

Funcții principale:

| Funcție | Descriere |
|---|---|
| `create_sesizare()` | Crează sesizare cu status `nou` |
| `trimite_la_dg()` | status → `in_derulare` |
| `distribuie_la_dept()` | Asociază departament |
| `redistribuie_dept()` | Redirecționează la alt departament, resetează responsabilul |
| `atribuie_user()` | Setează user responsabil |
| `finalizeaza()` | status → `finalizat`, salvează observații |
| `set_necesita_aprobare_dg()` | Bifează/debifează necesitatea aprobării DG |
| `aproba_dg()` | Salvează semnătura DG, setează `dg_aprobat_la` |
| `get_head_dept()` | Detectează dacă un user e șef de departament (exclus `GENERAL`) |
| `get_sesizari_de_aprobat_dg()` | Sesizări finalizate bifate pentru aprobare, neaprobate încă |
| `raport_sesizari_per_dept()` | Agregare per departament |
| `raport_timp_mediu_rezolvare()` | Medie zile rezolvare per dept+user |
| `raport_sesizari_per_luna()` | Distribuție lunară pentru un an |
| `raport_neatribuite()` | Sesizări fără responsabil |

### 14.2 `modules/services/workflow_service.py`

```python
start_workflow(doc_id, approvers)  # Pornește workflow cu lista de aprobatori
decide(doc_id, approver, decision, comment, signature_png_bytes)  # Aprobă/Respinge
```

### 14.3 `modules/database/migrations.py`

`auto_migrate_and_seed()` rulează la fiecare pornire și:
- Aplică PRAGMA SQLite (WAL, busy_timeout)
- Adaugă coloane lipsă (migrare non-distructivă)
- Creează tabelele noi dacă nu există (`auth_tokens`, `sesizari`, `sesizare_files`)
- Seed departamente și utilizator admin la prima rulare

### 14.4 `services/backup.py` și `notifications.py`

```python
backup_database(db_path, backup_dir)  # Copie DB cu timestamp
pending_for_user(username)             # Aprobări PENDING pentru un user
```

---

## 15. Configurare server

### 15.1 Port implicit

**2645** pe toate interfețele (`0.0.0.0`)

### 15.2 Parametri Streamlit

| Parametru | Valoare |
|---|---|
| `server.address` | `0.0.0.0` |
| `server.port` | `2645` |
| `server.headless` | `true` |
| `browser.gatherUsageStats` | `false` |
| `server.fileWatcherType` | `none` |

### 15.3 Baza de date SQLite

| PRAGMA | Valoare | Descriere |
|---|---|---|
| `journal_mode` | `WAL` | Write-Ahead Logging pentru concurență |
| `synchronous` | `NORMAL` | Echilibru performanță / siguranță |
| `busy_timeout` | `5000` ms | Așteptare la lock conflict |

---

## 16. Securitate

- Parole stocate cu **BCrypt** (factor cost 12)
- Token-uri "Ține-mă minte" stocate ca hash **SHA256**
- Expirare token automată după **90 de zile**
- Validare tip fișier: doar PDF (verificare header `%PDF-`)
- Deduplicare prin hash SHA256
- Autorizare bazată pe rol + departament + implicare în document

---

## 17. Date inițiale (seed)

### 17.1 Utilizator admin implicit

| Câmp | Valoare |
|---|---|
| Username | `admin` |
| Parolă | `admin123!` |
| Rol | `admin` |
| Departament | `GENERAL` |

> **Schimbați parola după prima autentificare!**

### 17.2 Departamente pre-configurate

25+ departamente pre-definite, incluzând `GENERAL`, `DEP_ECONOMIC`, `DEP_TEHNIC`, `DEP_EXPLOATARE` și sub-departamente cu relații ierarhice.

### 17.3 Tip document implicit

| Câmp | Valoare |
|---|---|
| Nume | `Document` |
| Activ | `true` |

---

---

## 18. Jurnal modificări

### 2026-03-22

#### Fix: Coloana `reg_no` provoca eroare Arrow la afișarea arhivei
- **Fișier:** `modules/pages/archive.py`
- **Problemă:** `d.reg_no or ""` returna string gol `""` când câmpul era `None`, în timp ce coloana este `Integer` în DB. PyArrow nu putea serializa un mix de `int` și `""`.
- **Fix:** `"reg_no": d.reg_no` — se păstrează `None` când nu există valoare.

#### Fix: Logout necesita 2 click-uri pe butonul "Deconectare"
- **Fișiere:** `app.py`, `modules/auth/remember_me.py`
- **Cauza:** `rememberme_bootstrap_js()` era apelat necondiționat la fiecare rerun, inclusiv la logout. În același render ajungeau 2 iframuri JS în browser: bootstrap JS (citea token din `localStorage` și naviga la `?rt=token`) și clear JS (ștergea `localStorage`). Bootstrap câștiga race condition-ul, re-autentificând userul.
- **Fix:**
  - `rememberme_bootstrap_js()` mutat în blocul `if auth_user is None` — rulează doar când userul nu este autentificat
  - Adăugată funcția `rememberme_clear_token_js()` (șterge `localStorage` fără reload de pagină)
  - Handler logout: înlocuit `rememberme_clear_token_js_and_reload()` cu `rememberme_clear_token_js()` și `st.stop()` cu `st.rerun()`
  - `revoke_current_remember_token()` revocă acum **toate** tokenurile active ale userului curent din DB, nu doar cel din sesiunea curentă

#### Fix: Vizibilitate sesizări în ierarhia de departamente
- **Fișier:** `modules/sesizari/sesizari_service.py`
- **Problemă:** `get_sesizari_for_dept()` folosea egalitate strictă (`departament == dept_name`). Exemple de cazuri ratate:
  - Sesizare trimisă la `DEP_TEHNIC` → `SERV_TEHNIC_INVESTITII` (sub-departament) nu o vedea
  - Sesizare trimisă la `SERV_MEDIU_PROCEDURI` → `DEP_CALITATE` (departamentul părinte) nu o vedea
- **Fix:** Adăugată funcția `get_dept_visibility_chain(dept_name)` care traversează ierarhia în **ambele direcții** (părinți și descendenți recursiv). `get_sesizari_for_dept()` folosește acum `.in_(dept_chain)` — funcționează pentru orice structură ierarhică din DB.

#### Adăugat `requirements.txt`
- Generat cu `pip freeze` — toate dependențele cu versiuni fixate
- Previne instalarea automată a versiunilor noi care pot introduce breaking changes

---

---

### 2026-03-23

#### Fix: Timestamp-uri incorecte (UTC în loc de ora locală Windows)
- **Fișiere:** `modules/database/models.py`, `modules/sesizari/sesizari_service.py`, `modules/services/workflow_service.py`, `modules/services/log_service.py`, `modules/pages/upload.py`, `app.py`
- **Problemă:** Toate înregistrările (documente, sesizări, loguri) foloseau `datetime.utcnow()` (UTC) în loc de ora locală a serverului Windows (UTC+2/+3).
- **Fix:** Înlocuit `datetime.utcnow()` → `datetime.now()` în toate modulele. Orele afișate corespund acum orei Windows.

#### Fix: Protecție timing attack la autentificare
- **Fișier:** `app.py`
- **Problemă:** Dacă userul nu exista în DB, aplicația sări peste verificarea BCrypt. Un atacator putea măsura diferența de timp de răspuns și enumera useri existenți.
- **Fix:** BCrypt se execută **întotdeauna** (cu un hash dummy pentru useri inexistenți). Timpul de răspuns este uniform indiferent dacă userul există sau nu.

#### Fix: `AttributeError` în `raport_sesizari_per_luna`
- **Fișier:** `modules/sesizari/sesizari_service.py`
- **Problemă:** `func.cast(func.strftime(...), func.Integer)` — `func.Integer` nu este valid în SQLAlchemy.
- **Fix:** Cast-ul SQLAlchemy eliminat; conversia lunii la `int` se face în Python (`int(r[0])`).

#### Performanță: Indexuri DB, cache dashboard, agregări SQL
- **`modules/database/models.py`** — adăugat `index=True` pe coloanele frecvent filtrate: `User.department`, `Document.department/created_by/created_at/status`, `Sesizare.departament/user_responsabil/status/created_at`
- **`modules/database/migrations.py`** — `CREATE INDEX IF NOT EXISTS` pentru toate indexurile noi (pentru baze existente)
- **`modules/dashboard.py`** — date extrase într-o funcție `@st.cache_data(ttl=30)`, eliminând interogările repetate la fiecare render
- **`modules/sesizari/sesizari_service.py`** — rapoartele `raport_sesizari_per_dept()` și `raport_timp_mediu_rezolvare()` rescrise cu `GROUP BY` + `func.sum(case(...))` și `func.avg(func.julianday(...))` în loc de procesare Python

#### Securitate: Validare path traversal în generarea PDF sesizări
- **Fișier:** `modules/sesizari/sesizari_service.py`
- **Fix:** Căile fișierelor de rezoluție și semnătură DG sunt validate cu `os.path.normpath` + `startswith(data_dir)` înainte de a fi deschise.

#### Revocare token la resetarea parolei de admin
- **Fișier:** `modules/pages/admin.py`, `modules/auth/remember_me.py`
- **Fix:** Adăugată funcția `revoke_all_tokens_for_user(username)`. La resetarea parolei unui user de către admin, toate sesiunile "ține-mă minte" ale acelui user sunt revocate automat.

#### Adăugat departamentul `SECTOR_IT` (subordonat `DEP_EXPLOATARE`)
- **Fișier:** `modules/config.py`
- `SECTOR_IT` adăugat în `ORG_DEPARTMENTS` și în `DEFAULT_PARENTS` cu părintele `DEP_EXPLOATARE`

#### Nou: Modul căutare + paginare pentru sesizări finalizate
- **Fișiere:** `modules/sesizari/sesizari_service.py`, `modules/sesizari/sesizari_ui.py`
- **Motivație:** Tab-ul „Finalizate" lista toate sesizările fără limită; în timp, cu sute de înregistrări, pagina devenea lentă și greu de navigat.
- **Implementare:**
  - `get_sesizari_finalizate_paginate()` — interogare SQL cu `LIMIT`/`OFFSET` și `COUNT` total; suportă vizibilitate per rol (`all` / `dept_chain` / `user_only`)
  - `_render_tab_finalizate()` — componentă UI reutilizabilă cu filtre: căutare text liberă (titlu, autor, nr. înreg., responsabil), interval date, filtru aprobare DG, filtru departament (la secretariat și DG); paginare 20 înregistrări/pagină cu resetare automată la schimbarea filtrelor
  - Cele 4 blocuri „Finalizate" din `render_sesizari()` (secretariat, șef departament, director general, user) înlocuite cu apeluri la `_render_tab_finalizate()`

#### Nou: Aprobare opțională Șef Departament pentru sesizări finalizate
- **Fișiere:** `modules/database/models.py`, `modules/database/migrations.py`, `modules/sesizari/sesizari_service.py`, `modules/sesizari/sesizari_ui.py`
- **Motivație:** Anterior, singura aprobare opțională disponibilă era cea a Directorului General. Șefii de departament (DEP_ECONOMIC, DEP_EXPLOATARE, DEP_TEHNIC, DEP_CALITATE și orice alt head_username) nu aveau posibilitatea de a solicita sau aproba rezoluțiile sesizărilor din departamentul lor.
- **Implementare:**
  - **Model DB** — 4 coloane noi în tabela `sesizari`: `necesita_aprobare_sef` (boolean), `sef_aprobat_la` (datetime), `sef_semnatura_path` (str), `sef_aprobator_username` (str)
  - **Migrare** — coloanele noi se adaugă automat la pornire prin `_sqlite_add_column_if_missing` (baze existente neafectate)
  - **Service** — funcții noi: `set_necesita_aprobare_sef()`, `aproba_sef()`, `get_sesizari_de_aprobat_sef(head_username, head_dept)` (filtrare după lanțul de departamente al șefului)
  - **PDF final** — pagina de semnături reorganizată pe **2 coloane**: Director General (stânga) și Șef Departament (dreapta); PDF-ul se regenerează la fiecare aprobare și conține ambele semnături dacă ambele aprobări există
  - **UI** — `_render_finalizat_card()` extinsă cu secțiunea „Aprobare Șef Departament" (independentă de secțiunea DG); șefii de departament au acum un al treilea tab **„De aprobat"** cu aceeași interfață de semnătură ca DG (canvas + semnătură predefinită)
- **Cine poate face ce:**
  - Bifează „Necesită aprobare Șef": userul responsabil, DG, șeful de departament
  - Aprobă cu semnătură (Șef): exclusiv head_username al departamentului din lanțul sesizării
  - Aprobările DG și Șef sunt **independente** — pot coexista pe aceeași sesizare

#### Fix: Dublu-click pe „Salvează sesizarea" crea duplicate
- **Fișier:** `modules/sesizari/sesizari_ui.py`
- **Problemă:** Click-uri rapide multiple pe butonul „Salvează sesizarea" (secretariat) salvau aceeași sesizare de mai multe ori înainte ca pagina să se reactualizeze.
- **Fix:** Protecție dublă:
  1. După salvare cu succes, câmpurile formularului (titlu, număr înregistrare, descriere) sunt șterse din `session_state` — formularul apare gol la rerenderare, orice click ulterior pică la validare
  2. Flag `creare_just_saved` în `session_state` dezactivează butonul (`disabled=True`) exact pe rerune-ul imediat după salvare, eliminând race condition-ul de dublu-click

---

*Documentație eMapa Apa Prod v2 — actualizată 2026-03-23*