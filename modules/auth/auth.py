import bcrypt
import streamlit as st


def _bcrypt_hash(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def is_dg():
    u = st.session_state.get("auth_user")
    return bool(u and (u.get("role") or "").strip().lower() == "dg")


def _bcrypt_check(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def is_admin() -> bool:
    u = st.session_state.get("auth_user")
    role = (u.get("role") or "").strip().lower() if u else ""
    return role in {"admin", "administrator"}


def is_secretariat() -> bool:
    u = st.session_state.get("auth_user")
    return bool(u and (u.get("role") or "").strip().lower() == "secretariat")


def require_login() -> None:
    if st.session_state.get("auth_user") is None:
        st.stop()
