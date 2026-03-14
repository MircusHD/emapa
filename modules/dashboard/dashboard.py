
import streamlit as st

def render_dashboard():

    st.title("Dashboard Management")

    col1, col2, col3 = st.columns(3)

    col1.metric("Documente", "--")
    col2.metric("Sesizari", "--")
    col3.metric("Aprobari", "--")

    st.info("Dashboard enterprise modul instalat.")
