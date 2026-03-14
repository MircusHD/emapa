import os
import sqlite3
from pathlib import Path

BASE = Path(r"F:\doc-mapa-v2")

DB = BASE / "data" / "app.db"
MODULE = BASE / "modules" / "sesizari"
APP = BASE / "app.py"

print("=== PATCH SESIZARI START ===")

# -----------------------------
# CREATE TABLE
# -----------------------------

conn = sqlite3.connect(DB)
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS sesizari(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titlu TEXT,
    descriere TEXT,
    pdf_path TEXT,
    autor TEXT,
    departament TEXT,
    assigned_user TEXT,
    status TEXT,
    created_at TEXT
)
""")

conn.commit()
conn.close()

print("Tabela sesizari OK")

# -----------------------------
# CREATE FOLDER PDF
# -----------------------------

pdf_dir = BASE / "data" / "sesizari"
pdf_dir.mkdir(exist_ok=True)

print("Folder PDF OK")

# -----------------------------
# CREATE MODULE
# -----------------------------

MODULE.mkdir(exist_ok=True)

ui_file = MODULE / "sesizari_ui.py"

if not ui_file.exists():

    code = '''
import streamlit as st
import sqlite3
import os
from datetime import datetime

DB = "data/app.db"

def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def render_sesizari(username, role):

    st.title("Sesizari / Reclamatii")

    tab1, tab2 = st.tabs(["Sesizare noua", "Lista sesizari"])

    # -------------------------
    # SECRETARIAT - CREARE
    # -------------------------

    with tab1:

        if role != "secretariat":
            st.info("Doar secretariatul poate crea sesizari.")
            return

        titlu = st.text_input("Titlu")
        descriere = st.text_area("Descriere")
        pdf = st.file_uploader("PDF", type=["pdf"])

        if st.button("Salveaza sesizare"):

            if not pdf:
                st.warning("Trebuie incarcat un PDF")
                return

            os.makedirs("data/sesizari", exist_ok=True)

            path = f"data/sesizari/{pdf.name}"

            with open(path, "wb") as f:
                f.write(pdf.read())

            c = conn()
            cur = c.cursor()

            cur.execute(
                "INSERT INTO sesizari (titlu, descriere, pdf_path, autor, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (titlu, descriere, path, username, "NOU", datetime.now().isoformat())
            )

            c.commit()
            c.close()

            st.success("Sesizare salvata")
            st.rerun()

    # -------------------------
    # LISTA SESIZARI
    # -------------------------

    with tab2:

        c = conn()
        cur = c.cursor()

        rows = cur.execute("SELECT * FROM sesizari ORDER BY id DESC").fetchall()

        c.close()

        if not rows:
            st.info("Nu exista sesizari")
            return

        for r in rows:

            st.markdown(f"### Sesizare #{r[0]}")
            st.write("Titlu:", r[1])
            st.write("Autor:", r[4])
            st.write("Status:", r[7])

            if r[3] and os.path.exists(r[3]):

                with open(r[3], "rb") as f:

                    st.download_button(
                        "Descarca PDF",
                        f,
                        file_name=os.path.basename(r[3])
                    )

            st.divider()
'''

    ui_file.write_text(code, encoding="utf8")

    print("Modul sesizari creat")

else:

    print("Modul sesizari exista deja")

# -----------------------------
# PATCH APP IMPORT
# -----------------------------

text = APP.read_text(encoding="utf8")

if "render_sesizari" not in text:

    text = text.replace(
        "import streamlit as st",
        "import streamlit as st\nfrom modules.sesizari.sesizari_ui import render_sesizari"
    )

    APP.write_text(text, encoding="utf8")

    print("Import adaugat in app.py")

else:

    print("Import deja existent")

print("=== PATCH FINALIZAT ===")
