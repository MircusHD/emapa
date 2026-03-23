# Plan implementare modul Sesizări — eMapa Apa Prod v2

## Analiza situației actuale

Modulul `modules/sesizari/sesizari_ui.py` există deja, dar este incomplet și inconsistent:
- Folosește `sqlite3` raw în loc de SQLAlchemy (contrar restului aplicației)
- Folosește rolul `"sef"` care nu există în `auth.py` — șefii de departament au de fapt rolul `"dg"`
- Nu are `numar_inregistrare`
- Vizibilitatea sesizărilor nu este filtrată — toți văd tot
- Statusurile sunt inconsistente cu planul (`NOU`, `TRIMIS_DEPARTAMENT`, `IN_LUCRU`, `REZOLVAT`)
- Nu există tab pentru sesizări finalizate

---

## 1. Statusuri

Doar **3 statusuri**:

| Status       | Semnificație                                                    |
|------------- |-----------------------------------------------------------------|
| `nou`        | Sesizarea a fost creată de secretară, încă netrimisă           |
| `in_derulare`| Trimisă la DG; poate fi atribuită unui departament și/sau user |
| `finalizat`  | Marcată ca rezolvată de userul responsabil                      |

---

## 2. Schema bazei de date

Tabel: `sesizari`

```sql
CREATE TABLE sesizari (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    numar_inregistrare    TEXT NOT NULL UNIQUE,   -- ex: "SZ-2026-001" (manual sau auto)
    titlu                 TEXT NOT NULL,
    descriere             TEXT,                   -- detalii opționale
    pdf_path              TEXT,                   -- cale relativă fișier PDF
    autor                 TEXT NOT NULL,          -- username secretară
    departament           TEXT,                   -- FK → departments.name (setat de DG)
    user_responsabil      TEXT,                   -- FK → users.username (setat de head dept)
    status                TEXT NOT NULL DEFAULT 'nou',
    created_at            DATETIME NOT NULL,
    trimis_la_dg_at       DATETIME,               -- când secretara a trimis la DG
    distribuit_la_dept_at DATETIME,               -- când DG a distribuit la dept
    atribuit_la_user_at   DATETIME,               -- când head a atribuit userului
    finalizat_at          DATETIME,               -- când userul a marcat finalizat
    observatii_finalizare TEXT                    -- note opționale la finalizare
);
```

**Migrare:** se adaugă în `modules/database/migrations.py` via `auto_migrate_and_seed()`.

**Model SQLAlchemy** se adaugă în `modules/database/models.py`:
```python
class Sesizare(Base):
    __tablename__ = "sesizari"
    id                    = Column(Integer, primary_key=True, autoincrement=True)
    numar_inregistrare    = Column(String, nullable=False, unique=True)
    titlu                 = Column(String, nullable=False)
    descriere             = Column(Text, nullable=True)
    pdf_path              = Column(String, nullable=True)
    autor                 = Column(String, nullable=False)
    departament           = Column(String, nullable=True)
    user_responsabil      = Column(String, nullable=True)
    status                = Column(String, nullable=False, default="nou")
    created_at            = Column(DateTime, nullable=False, default=datetime.utcnow)
    trimis_la_dg_at       = Column(DateTime, nullable=True)
    distribuit_la_dept_at = Column(DateTime, nullable=True)
    atribuit_la_user_at   = Column(DateTime, nullable=True)
    finalizat_at          = Column(DateTime, nullable=True)
    observatii_finalizare = Column(Text, nullable=True)
```

---

## 3. Roluri și vizibilitate

Toți șefii de departament au rolul `dg` în baza de date — la fel ca directorul general. Distincția se face prin `departments.head_username`:

| Rol în DB     | Condiție suplimentară                              | Funcție                  | Ce vede?                                                                          |
|---------------|----------------------------------------------------|--------------------------|-----------------------------------------------------------------------------------|
| `secretariat` | —                                                  | Secretară                | Toate sesizările (toate statusurile)                                              |
| `dg`          | `departments.head_username == username` → **DA**   | Șef de departament       | Sesizările cu `departament = dept_al_sau` și status `in_derulare`                |
| `dg`          | `departments.head_username == username` → **NU**   | Director general         | Toate sesizările cu status `in_derulare`                                         |
| `user`        | —                                                  | Utilizator obișnuit      | Sesizările cu `user_responsabil = username` și status `in_derulare`              |

> **Prioritate la detecție:** Se verifică mai întâi dacă `username` este `head_username` într-un departament. Dacă da → UI de șef de departament, indiferent că rolul e `dg`. Dacă nu și rolul e `dg` → UI de director general.

---

## 4. Fluxul complet

```
[Secretară]          [DG]              [Șef Dept (dg+head)] [User simplu]
    │                  │                     │                    │
    ▼                  │                     │                    │
Crează sesizare        │                     │                    │
(status = nou)         │                     │                    │
    │                  │                     │                    │
    ▼                  │                     │                    │
Trimite la DG          │                     │                    │
(status = in_derulare)─►                     │                    │
                       │                     │                    │
                  Vede sesizarea             │                    │
                  Asociază dept ─────────────►                   │
                  (departament = X)          │                    │
                                        Vede sesizarea            │
                                        Asociază user ───────────►
                                        (user_responsabil = Y)   │
                                                              Vede sesizarea
                                                              Marchează finalizat
                                                              (status = finalizat)
```

---

## 5. Acțiuni per rol

### Secretară (`role == "secretariat"`)
- **Creare sesizare:** titlu, numar_inregistrare (manual sau auto-generat), descriere (opțional), upload PDF (opțional)
- **Trimitere la DG:** buton "Trimite la DG" pe sesizările cu status `nou` → setează `status='in_derulare'`, `trimis_la_dg_at=now()`
- **Tab 1 – Active:** sesizările cu status `nou` și `in_derulare`
- **Tab 2 – Finalizate:** sesizările cu status `finalizat`

### Director General (`role == "dg"`)
- **Tab 1 – In derulare:** sesizările cu status `in_derulare`
  - Pe fiecare sesizare fără `departament`: selectbox cu lista departamentelor + buton "Distribuie"
    - Setează `departament`, `distribuit_la_dept_at=now()`
  - Pe sesizările cu departament deja setat: afișează departamentul (read-only)
- **Tab 2 – Finalizate:** sesizările cu status `finalizat`

### Șef de departament (`role == "dg"` și `departments.head_username == username`)
- Vede sesizările cu `departament = dept_al_sau` și status `in_derulare`
- Pe fiecare sesizare fără `user_responsabil`: selectbox cu userii din acel departament + buton "Atribuie"
  - Setează `user_responsabil`, `atribuit_la_user_at=now()`
- Pe sesizările cu user deja atribuit: afișează userul (read-only)

### User simplu (`role == "user"`)
- Vede sesizările unde `user_responsabil == username` și status `in_derulare`
- Buton "Marchează finalizat" → setează `status='finalizat'`, `finalizat_at=now()`, câmp opțional `observatii_finalizare`

---

## 6. Structura UI (`sesizari_ui.py`)

```python
def render_sesizari(username, role):
    # detectează dacă e head de departament
    is_head, head_dept = _get_head_dept(username)

    if role == "secretariat":
        tab1, tab2 = st.tabs(["Active", "Finalizate"])
        # tab1: creare + lista active (nou + in_derulare)
        # tab2: lista finalizate

    elif role == "dg":
        tab1, tab2 = st.tabs(["În derulare", "Finalizate"])
        # tab1: lista in_derulare cu posibilitate distribuire
        # tab2: lista finalizate

    elif role == "dg" and is_head:
        # sef de departament (role="dg" + head_username in departments)
        st.subheader(f"Sesizări departament: {head_dept}")
        # lista sesizarilor pt departamentul sau

    else:
        # user simplu
        st.subheader("Sesizările mele")
        # lista sesizarilor atribuite userului curent
```

---

## 7. Funcții helper necesare

```python
# modules/sesizari/sesizari_service.py

def _get_head_dept(username: str) -> tuple[bool, str | None]:
    """Returnează (True, dept_name) dacă username este head al unui departament."""

def get_dept_users(dept_name: str) -> list[str]:
    """Returnează lista de useri (username) din departamentul dat."""

def create_sesizare(autor, titlu, numar_inreg, descriere, pdf_path) -> Sesizare:
    """Crează sesizare cu status='nou'."""

def trimite_la_dg(sesizare_id: int):
    """status='in_derulare', trimis_la_dg_at=now()."""

def distribuie_la_dept(sesizare_id: int, dept: str):
    """departament=dept, distribuit_la_dept_at=now()."""

def atribuie_user(sesizare_id: int, user: str):
    """user_responsabil=user, atribuit_la_user_at=now()."""

def finalizeaza(sesizare_id: int, observatii: str = ""):
    """status='finalizat', finalizat_at=now()."""
```

---

## 8. Generare automată `numar_inregistrare`

Dacă secretara nu completează manual, se generează automat:
```
SZ-{YYYY}-{NNN}   ex: SZ-2026-001
```
Unde `NNN` este numărul curent al sesizărilor din anul respectiv (padding 3 cifre).

---

## 9. Fișiere de creat/modificat

| Fișier | Acțiune |
|--------|---------|
| `modules/database/models.py` | Adaugă clasa `Sesizare` |
| `modules/database/migrations.py` | Adaugă migrare pentru tabelul `sesizari` |
| `modules/sesizari/sesizari_service.py` | Crează — logica de business |
| `modules/sesizari/sesizari_ui.py` | Rescrie complet — UI cu SQLAlchemy |

---

## 10. Restricții și edge-cases

- **Un șef de departament** (`role="dg"`, `head_username`) poate fi și `user_responsabil` pe o sesizare — vizibilitatea se cumulează; se verifică mai întâi dacă este head, altfel UI-ul de DG
- **Secretara nu poate distribui** direct (doar trimite la DG)
- **DG nu poate atribui direct unui user** (doar la departament)
- **Ștergerea** sesizărilor: doar admin sau secretara pe sesizari cu status `nou`
- **Fișierul PDF** se stochează în `uploads/sesizari/` cu prefix timestamp (păstrăm comportamentul actual)
- **SQLAlchemy Session** se folosește din `modules/database/session.py` (nu sqlite3 raw)