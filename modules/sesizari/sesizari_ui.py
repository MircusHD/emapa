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

# -----------------------
# SECRETARIAT - creare
# -----------------------

    with tab1:

        if role != "secretariat":
            st.info("Doar secretariatul poate crea sesizari.")
            return

        titlu = st.text_input("Titlu sesizare")
        pdf = st.file_uploader("PDF sesizare", type=["pdf"])

        if st.button("Salveaza sesizare"):

            if not titlu:
                st.warning("Introdu titlul")
                return

            path = None

            if pdf:

                os.makedirs("uploads/sesizari", exist_ok=True)

                path = f"uploads/sesizari/{datetime.now().timestamp()}_{pdf.name}"

                with open(path, "wb") as f:
                    f.write(pdf.getbuffer())

            c = conn()
            cur = c.cursor()

            cur.execute("""
                INSERT INTO sesizari
                (titlu,pdf_path,autor,status,created_at)
                VALUES (?,?,?,?,?)
            """,(titlu,path,username,"NOU",datetime.now()))

            c.commit()
            c.close()

            st.success("Sesizare salvata")

# -----------------------
# LISTA SESIZARI
# -----------------------

    with tab2:

        c = conn()
        cur = c.cursor()

        rows = cur.execute(
            "SELECT * FROM sesizari ORDER BY id DESC"
        ).fetchall()

        c.close()

        if not rows:
            st.info("Nu exista sesizari")
            return

        for r in rows:

            id=r[0]
            titlu=r[1]
            pdf=r[2]
            autor=r[3]
            dept=r[4]
            user=r[5]
            status=r[6]

            st.markdown(f"### Sesizare #{id}")

            st.write("Titlu:",titlu)
            st.write("Autor:",autor)
            st.write("Departament:",dept)
            st.write("Responsabil:",user)
            st.write("Status:",status)

# -----------------------
# PDF
# -----------------------

            if pdf and os.path.exists(pdf):

                with open(pdf,"rb") as f:

                    st.download_button(
                        "Descarca PDF",
                        f,
                        file_name=os.path.basename(pdf),
                        key=f"pdf_{id}"
                    )

# -----------------------
# DG distribuie
# -----------------------

            if role=="dg" and status=="NOU":

                dept=st.selectbox(
                    "Trimite departament",
                    ["tehnic","economic","exploatare","calitate"],
                    key=f"dept_{id}"
                )

                if st.button("Distribuie",key=f"dg_{id}"):

                    c=conn()
                    cur=c.cursor()

                    cur.execute("""
                        UPDATE sesizari
                        SET departament=?,status='TRIMIS_DEPARTAMENT'
                        WHERE id=?
                    """,(dept,id))

                    c.commit()
                    c.close()

                    st.success("Trimis departament")

# -----------------------
# sef departament
# -----------------------

            if role=="sef":

                user_resp=st.text_input(
                    "User responsabil",
                    key=f"user_{id}"
                )

                if st.button("Atribuie",key=f"sef_{id}"):

                    c=conn()
                    cur=c.cursor()

                    cur.execute("""
                        UPDATE sesizari
                        SET user_responsabil=?,status='IN_LUCRU'
                        WHERE id=?
                    """,(user_resp,id))

                    c.commit()
                    c.close()

                    st.success("Atribuit")

# -----------------------
# user rezolva
# -----------------------

            if username==user and status=="IN_LUCRU":

                if st.button("Marcheaza rezolvat",key=f"done_{id}"):

                    c=conn()
                    cur=c.cursor()

                    cur.execute("""
                        UPDATE sesizari
                        SET status='REZOLVAT'
                        WHERE id=?
                    """,(id,))

                    c.commit()
                    c.close()

                    st.success("Sesizare rezolvata")

# -----------------------
# secretariat delete
# -----------------------

            if role=="secretariat":

                if st.button("Sterge",key=f"del_{id}"):

                    c=conn()
                    cur=c.cursor()

                    cur.execute(
                        "DELETE FROM sesizari WHERE id=?",(id,)
                    )

                    c.commit()
                    c.close()

                    st.warning("Sesizare stearsa")

            st.divider()
