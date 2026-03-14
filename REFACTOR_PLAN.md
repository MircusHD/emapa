# Plan de Refactorizare — app.py → Module

**Data:** 2026-03-14
**Fișier sursă:** `app.py` (~3007 linii)
**Obiectiv:** Separarea logicii monolitice în module coezive, fără modificarea comportamentului aplicației.

---

## Starea curentă

### Structura existentă

```
F:/doc-mapa-v2/
├── app.py                          # 3007 linii — tot codul
├── modules/
│   ├── sesizari/
│   │   └── sesizari_ui.py          # ✅ Modul funcțional (folosit)
│   ├── dashboard.py                # ✅ Modul funcțional (folosit)
│   ├── dashboard/dashboard.py      # ⚠️  Duplicat (nefolosit)
│   └── admin_panel.py              # ⚠️  Placeholder gol (neimportat în app.py)
├── core/models.py                  # ⚠️  Gol
├── services/audit.py               # ⚠️  Neintegrat
├── services/backup.py              # ⚠️  Neintegrat
└── api/api.py                      # ⚠️  FastAPI neintegrat
```

### Secțiunile din app.py (cu numărul de linii)

| Secțiune | Linii | Funcții cheie |
|----------|-------|---------------|
| Imports + Config | 1–131 | `BASE_DIR`, `ORG_DEPARTMENTS`, `DEFAULT_PARENTS` |
| DB Setup | 140–146 | `engine`, `SessionLocal`, `Base` |
| Models (ORM) | 148–238 | `User`, `Department`, `DocType`, `Document`, `Approval`, `AuthToken` |
| Migrations / Seed | 242–387 | `auto_migrate_and_seed`, `backfill_public_ids` |
| Utility | 389–564 | `sha256_bytes`, `normalize_dept`, `safe_filename`, `parse_tags`, `is_admin`, `is_secretariat`, `user_display_name`, `generate_public_id` |
| UX Helpers | 608–644 | `_set_scroll_to_workflow`, `_scroll_to_registry_if_needed` |
| Dept tree | 646–675 | `get_dept_children_map`, `get_descendant_departments` |
| Signatures / PDF | 782–1065 | `build_final_pdf`, `build_current_pdf_bytes`, `save_default_signature` |
| Workflow actions | 1067–1275 | `start_workflow`, `decide`, `cancel_to_draft`, `cancel_document`, `sterge_definitiv_document` |
| Workflow builder UI | 1276–1447 | `render_workflow_builder`, `wf_validate`, `wf_pretty` |
| DataFrame helpers | 1448–1509 | `_select_code_from_dataframe` |
| Auth / Remember-me | 1511–1697 | `create_remember_token`, `validate_remember_token`, `rememberme_bootstrap_js` |
| App init + Login | 1698–1833 | Sidebar, login form, meniu |
| **Pagina: Incarcare** | 1837–1943 | Upload PDF + pornire workflow |
| **Pagina: Dashboard** | 1947–1950 | → `render_dashboard()` |
| **Pagina: Sesizari** | 1955–1960 | → `render_sesizari()` |
| **Pagina: Arhiva** | 1964–2484 | 521 linii — cea mai complexă |
| **Pagina: Inbox aprobari** | 2485–2628 | 144 linii |
| **Pagina: Secretariat** | 2629–2768 | 140 linii |
| **Pagina: Administrare** | 2769–3007 | 239 linii (3 tab-uri) |

---

## Structura țintă a modulelor

```
F:/doc-mapa-v2/
├── app.py                              # ~120 linii — DOAR routing + sidebar + login
│
└── modules/
    ├── config.py                       # NOU — constante și căi
    ├── database/
    │   ├── __init__.py
    │   ├── models.py                   # NOU — modele SQLAlchemy
    │   ├── session.py                  # NOU — engine, SessionLocal, Base
    │   └── migrations.py              # NOU — auto_migrate_and_seed
    ├── auth/
    │   ├── __init__.py
    │   ├── auth.py                     # NOU — bcrypt, login, is_admin, is_secretariat
    │   └── remember_me.py             # NOU — token-uri auto-login, JS helpers
    ├── services/
    │   ├── __init__.py
    │   ├── document_service.py        # NOU — CRUD documente, SHA256, public_id
    │   ├── workflow_service.py        # NOU — start_workflow, decide, cancel
    │   ├── pdf_service.py             # NOU — build_final_pdf, build_current_pdf_bytes
    │   └── signature_service.py       # NOU — semnături predefinite și per-pas
    ├── departments/
    │   ├── __init__.py
    │   └── dept_service.py            # NOU — get_dept_children_map, get_descendant_departments
    ├── utils/
    │   ├── __init__.py
    │   ├── formatting.py              # NOU — ro_doc_status, doc_label, user_display_name
    │   ├── files.py                   # NOU — safe_filename, parse_tags, path helpers
    │   └── ui_helpers.py              # NOU — ui_result, scroll helpers, open_pdf_in_chrome_tab
    ├── workflow/
    │   ├── __init__.py
    │   └── workflow_builder.py        # NOU — render_workflow_builder, wf_validate, wf_pretty
    ├── pages/
    │   ├── __init__.py
    │   ├── upload.py                  # NOU — Pagina "Incarcare"
    │   ├── archive.py                 # NOU — Pagina "Arhiva"
    │   ├── inbox.py                   # NOU — Pagina "Inbox aprobari"
    │   ├── secretariat_page.py        # NOU — Pagina "Secretariat"
    │   └── admin.py                   # NOU — Pagina "Administrare" (înlocuiește admin_panel.py gol)
    ├── dashboard.py                   # EXISTENT — păstrat, eventual îmbunătățit
    └── sesizari/
        └── sesizari_ui.py             # EXISTENT — păstrat neschimbat
```

---

## Planul de implementare pe etape

### Etapa 1 — Fundația (fără risc): `config`, `database`, `auth`
> Nicio pagină UI nu se schimbă. Doar mutăm definițiile.

#### 1.1 `modules/config.py`
Conținut mutat din `app.py` (liniile 85–137):
```python
# BASE_DIR, DATA_DIR, UPLOAD_DIR, SIGNATURE_DIR, DEFAULT_SIG_DIR, FINAL_DIR
# DB_PATH, DB_URL
# DG_DEPT, PUBLIC_PREFIX
# ORG_DEPARTMENTS, DEFAULT_PARENTS
# + funcțiile de cale: abs_upload_path, sig_abs_path, final_abs_path, rel_upload_path
```

#### 1.2 `modules/database/models.py` + `session.py`
Conținut mutat din `app.py` (liniile 140–239):
```python
# models.py: User, Department, DocType, Document, Approval, AuthToken
# session.py: Base, engine, SessionLocal
```

#### 1.3 `modules/database/migrations.py`
Conținut mutat din `app.py` (liniile 242–387):
```python
# _sqlite_add_column_if_missing, _bcrypt_hash (seed-only), auto_migrate_and_seed, backfill_public_ids
```

#### 1.4 `modules/auth/auth.py`
Conținut mutat din `app.py`:
```python
# _bcrypt_check (linia 392), _bcrypt_hash (linia 256)
# is_admin (linia 450), is_secretariat (linia 456), is_dg (linia 49)
# require_login (linia 461)
```

#### 1.5 `modules/auth/remember_me.py`
Conținut mutat din `app.py` (liniile 1515–1696):
```python
# REMEMBER_DAYS, REMEMBER_STORAGE_KEY
# _sha256_hex, _get_query_params, _get_query_param, _set_query_params_without_rt
# rememberme_bootstrap_js, create_remember_token, validate_remember_token
# revoke_current_remember_token, rememberme_set_token_js, rememberme_clear_token_js_and_reload
```

---

### Etapa 2 — Servicii (logică business): `utils`, `departments`, `services`
> Tot codul Python pur. Fără Streamlit. Testabil independent.

#### 2.1 `modules/utils/files.py`
```python
# sha256_bytes (linia 399)
# normalize_dept (linia 405)
# safe_filename (linia 410)
# parse_tags (linia 417)
```

#### 2.2 `modules/utils/formatting.py`
```python
# ro_approval_status (linia 473)
# ro_doc_status (linia 484)
# doc_label (linia 499)
# _title_from_username (linia 507)
# user_display_name (linia 514)
# user_display_with_title (linia 526)
```

#### 2.3 `modules/utils/ui_helpers.py`
```python
# ui_result (linia 466)
# open_pdf_in_chrome_tab (linia 579)
# _set_scroll_to_workflow, _scroll_to_workflow_if_needed (liniile 611–626)
# _set_scroll_to_registry, _scroll_to_registry_if_needed (liniile 629–644)
# _select_code_from_dataframe (linia 1451)
```

#### 2.4 `modules/departments/dept_service.py`
```python
# get_dept_children_map (linia 649)
# get_descendant_departments (linia 661)
```

#### 2.5 `modules/services/signature_service.py`
```python
# sig_rel_path (linia 785)
# default_sig_rel_path (linia 790)
# get_user_default_signature_rel (linia 794)
# load_default_signature_bytes (linia 809)
# save_default_signature (linia 823)
# delete_default_signature (linia 847)
```

#### 2.6 `modules/services/pdf_service.py`
```python
# final_rel_path (linia 869)
# build_final_pdf (linia 873)
# build_current_pdf_bytes (linia 969)
```

#### 2.7 `modules/services/workflow_service.py`
```python
# step_is_same (linia 680)
# ensure_dg_final_step (linia 690)
# load_doc_type_workflow (linia 701)
# effective_workflow (linia 715)
# resolve_step_to_approver (linia 729)
# user_can_view_document (linia 767)
# start_workflow (linia 1070)
# decide (linia 1109)
# cancel_to_draft (linia 1185)
# cancel_document (linia 1205)
# sterge_definitiv_document (linia 1225)
```

#### 2.8 `modules/services/document_service.py`
```python
# generate_public_id (linia 539)
# backfill_public_ids (linia 553)
# get_document_by_identifier (linia 566)
```

---

### Etapa 3 — Workflow builder UI: `modules/workflow/`

#### 3.1 `modules/workflow/workflow_builder.py`
```python
# wf_pretty (linia 1279)
# wf_validate (linia 1299)
# wf_normalize_force_dg (linia 1319)
# _display_name_for_user (linia 1326)
# render_workflow_builder (linia 1340)
```

---

### Etapa 4 — Paginile UI: `modules/pages/`
> Fiecare pagină devine o funcție `render_*()` care importă serviciile din etapele 1-3.

#### 4.1 `modules/pages/upload.py`
```python
def render_upload(auth_user: dict) -> None:
    # Conținut: liniile 1837–1943 din app.py
    # Importă: workflow_builder, workflow_service, document_service, pdf_service
```

#### 4.2 `modules/pages/archive.py`
```python
def render_archive(auth_user: dict) -> None:
    # Conținut: liniile 1964–2484 din app.py
    # Importă: toate serviciile (cel mai complex modul — 521 linii)
```

#### 4.3 `modules/pages/inbox.py`
```python
def render_inbox(auth_user: dict) -> None:
    # Conținut: liniile 2485–2628 din app.py
    # Importă: workflow_service, pdf_service, signature_service
```

#### 4.4 `modules/pages/secretariat_page.py`
```python
def render_secretariat(auth_user: dict) -> None:
    # Conținut: liniile 2629–2768 din app.py
    # Importă: document_service, pdf_service, workflow_service
```

#### 4.5 `modules/pages/admin.py`
```python
def render_admin(auth_user: dict) -> None:
    # Conținut: liniile 2769–3007 din app.py (3 tab-uri: Utilizatori, Departamente, Parolă)
    # Înlocuiește admin_panel.py (placeholder gol)
```

---

### Etapa 5 — Curățare `app.py`
> După migrarea tuturor modulelor, `app.py` rămâne cu ~120 linii.

```python
# app.py — versiunea finală (schelet)

import streamlit as st
from modules.config import *
from modules.database.session import SessionLocal
from modules.database.migrations import auto_migrate_and_seed
from modules.auth.auth import is_admin, is_secretariat, is_dg, require_login
from modules.auth.remember_me import (
    rememberme_bootstrap_js, validate_remember_token,
    create_remember_token, revoke_current_remember_token,
    rememberme_clear_token_js_and_reload, rememberme_set_token_js,
    _get_query_param, _set_query_params_without_rt
)
from modules.auth.auth import _bcrypt_check
from modules.database.models import User
from modules.services.signature_service import (
    get_user_default_signature_rel, save_default_signature, delete_default_signature
)
from modules.pages.upload import render_upload
from modules.pages.archive import render_archive
from modules.pages.inbox import render_inbox
from modules.pages.secretariat_page import render_secretariat
from modules.pages.admin import render_admin
from modules.dashboard import render_dashboard
from modules.sesizari.sesizari_ui import render_sesizari
from sqlalchemy import select

st.set_page_config(page_title="eMapa Apa Prod", layout="wide")
auto_migrate_and_seed()

# --- Sidebar + Login (logica existentă, mutată aci) ---
# ... ~80 linii

# --- Routing ---
if page == "Incarcare":       render_upload(auth_user)
elif page == "Dashboard":     render_dashboard()
elif page == "Sesizari":      render_sesizari(auth_user["username"], auth_user["role"])
elif page == "Arhiva":        render_archive(auth_user)
elif page == "Inbox aprobari": render_inbox(auth_user)
elif page == "Secretariat":   render_secretariat(auth_user)
elif page == "Administrare":  render_admin(auth_user)
```

---

## Ordinea de execuție recomandată

```
Etapa 1 (Risc 0)     → config + database + auth
        ↓
Etapa 2 (Risc mic)   → utils + departments + services
        ↓
Etapa 3 (Risc mic)   → workflow builder
        ↓
Etapa 4 (Risc mediu) → pages (UI — testare manuală per pagină)
        ↓
Etapa 5 (Final)      → curățare app.py + ștergere fișiere orphan
```

**Regulă de aur la fiecare etapă:**
1. Mută codul în noul modul
2. Adaugă importul în `app.py` (backward-compat temporar)
3. Testează că aplicația pornește și funcționează
4. Abia apoi șterge codul din `app.py`

---

## Fișiere de curățat (post-refactorizare)

| Fișier | Acțiune | Motiv |
|--------|---------|-------|
| `modules/admin_panel.py` | **Șterge** | Placeholder gol, înlocuit de `modules/pages/admin.py` |
| `modules/dashboard/dashboard.py` | **Șterge** | Duplicat al `modules/dashboard.py` |
| `core/models.py` | **Șterge sau populează** | Gol — modelele merg în `modules/database/models.py` |
| `services/audit.py` | **Evaluează** | Neintegrat — decide dacă se integrează sau se șterge |
| `services/backup.py` | **Evaluează** | Neintegrat |

---

## Dependențe între module (diagrama de import)

```
app.py
├── modules/config.py
├── modules/database/
│   ├── models.py         ← config.py
│   ├── session.py        ← config.py, models.py
│   └── migrations.py     ← session.py, models.py, config.py
├── modules/auth/
│   ├── auth.py           ← session.py, models.py
│   └── remember_me.py    ← session.py, models.py
├── modules/utils/
│   ├── files.py          ← (fără dep. interne)
│   ├── formatting.py     ← session.py, models.py
│   └── ui_helpers.py     ← (fără dep. interne, doar streamlit)
├── modules/departments/
│   └── dept_service.py   ← session.py, models.py, utils/files.py
├── modules/services/
│   ├── document_service.py  ← session.py, models.py, config.py
│   ├── signature_service.py ← session.py, models.py, config.py
│   ├── pdf_service.py       ← session.py, models.py, signature_service.py, config.py
│   └── workflow_service.py  ← session.py, models.py, departments/, pdf_service.py
├── modules/workflow/
│   └── workflow_builder.py  ← session.py, models.py, workflow_service.py, utils/
└── modules/pages/
    ├── upload.py            ← workflow_builder.py, workflow_service.py, document_service.py
    ├── archive.py           ← TOATE serviciile
    ├── inbox.py             ← workflow_service.py, pdf_service.py, signature_service.py
    ├── secretariat_page.py  ← document_service.py, pdf_service.py, workflow_service.py
    └── admin.py             ← session.py, models.py, auth/auth.py
```

---

## Estimare dimensiuni module țintă

| Modul | Linii estimate |
|-------|---------------|
| `config.py` | ~60 |
| `database/models.py` | ~90 |
| `database/session.py` | ~10 |
| `database/migrations.py` | ~120 |
| `auth/auth.py` | ~40 |
| `auth/remember_me.py` | ~120 |
| `utils/files.py` | ~50 |
| `utils/formatting.py` | ~60 |
| `utils/ui_helpers.py` | ~80 |
| `departments/dept_service.py` | ~40 |
| `services/signature_service.py` | ~80 |
| `services/pdf_service.py` | ~200 |
| `services/workflow_service.py` | ~220 |
| `services/document_service.py` | ~50 |
| `workflow/workflow_builder.py` | ~170 |
| `pages/upload.py` | ~110 |
| `pages/archive.py` | ~520 |
| `pages/inbox.py` | ~145 |
| `pages/secretariat_page.py` | ~140 |
| `pages/admin.py` | ~240 |
| `app.py` (final) | ~120 |
| **TOTAL** | **~2715** *(vs. 3007 original — ~10% reducere prin eliminarea duplicatelor)* |

---

## Note importante

1. **Nu se schimbă comportamentul aplicației** — refactorizarea este pur structurală.
2. **Nu se modifică schema bazei de date** — modelele sunt mutate, nu modificate.
3. **Sesizari și Dashboard** rămân neschimbate — sunt deja module funcționale.
4. **Importul circular** trebuie evitat — respectați ierarhia: `config → database → services → pages`.
5. **`SessionLocal`** trebuie importat în fiecare modul care accesează BD — nu se pasează ca parametru.
6. **Sidebarului și logicii de login** rămân în `app.py` — sunt strâns legate de `st.session_state`.