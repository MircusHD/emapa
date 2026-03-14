import hashlib
import uuid
import secrets
from datetime import datetime, timedelta
from typing import Optional
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import select, and_
from modules.database.session import SessionLocal
from modules.database.models import AuthToken, User


# -----------------------
# Remember-me (auto-login) helpers (90 zile)
# -----------------------
REMEMBER_DAYS = 90
REMEMBER_STORAGE_KEY = "emapaprod_remember_token"

def _sha256_hex(s: str) -> str:
    h = hashlib.sha256()
    h.update((s or "").encode("utf-8"))
    return h.hexdigest()

def _get_query_params() -> dict:
    # Compat Streamlit versions
    try:
        return dict(st.query_params)  # type: ignore[attr-defined]
    except Exception:
        try:
            return st.experimental_get_query_params()
        except Exception:
            return {}

def _get_query_param(name: str) -> str:
    qp = _get_query_params() or {}
    v = qp.get(name)
    if isinstance(v, list):
        return (v[0] or "").strip()
    return (v or "").strip()

def _set_query_params_without_rt() -> None:
    try:
        qp = _get_query_params() or {}
        qp2 = {k: v for k, v in qp.items() if k != "rt"}
        # normalize list values for experimental_set_query_params
        try:
            st.experimental_set_query_params(**{k: (v if isinstance(v, str) else v[0]) for k, v in qp2.items()})
        except Exception:
            # st.query_params write API
            try:
                st.query_params.clear()  # type: ignore[attr-defined]
                for k, v in qp2.items():
                    if isinstance(v, list):
                        st.query_params[k] = v[0]  # type: ignore[attr-defined]
                    else:
                        st.query_params[k] = v  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        pass

def rememberme_bootstrap_js() -> None:
    """JS: daca exista token in localStorage si nu avem ?rt=..., il pune temporar in URL ca sa ajunga la Python.
    Apoi curata URL-ul (sterge rt) folosind history.replaceState."""
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          const url = new URL(window.location.href);
          const params = url.searchParams;
          const hasRt = params.has("rt");
          if (!hasRt) {{
            const t = window.localStorage.getItem(KEY);
            if (t) {{
              params.set("rt", t);
              url.search = params.toString();
              window.location.replace(url.toString());
              return;
            }}
          }} else {{
            // curata URL-ul (nu mai afisa rt)
            params.delete("rt");
            const clean = url.pathname + (params.toString() ? ("?" + params.toString()) : "") + url.hash;
            window.history.replaceState({{}}, "", clean);
          }}
        }})();
        </script>
        """,
        height=0,
    )

def create_remember_token(username: str) -> str:
    token = secrets.token_urlsafe(32)
    th = _sha256_hex(token)
    exp = datetime.utcnow() + timedelta(days=REMEMBER_DAYS)
    with SessionLocal() as db:
        db.add(
            AuthToken(
                id=str(uuid.uuid4()),
                username=username,
                token_hash=th,
                expires_at=exp,
                created_at=datetime.utcnow(),
                last_used_at=None,
            )
        )
        db.commit()
    return token

def validate_remember_token(token: str) -> Optional[dict]:
    tok = (token or "").strip()
    if not tok:
        return None
    th = _sha256_hex(tok)
    now = datetime.utcnow()
    with SessionLocal() as db:
        t = db.execute(select(AuthToken).where(and_(AuthToken.token_hash == th))).scalar_one_or_none()
        if not t:
            return None
        if t.expires_at and t.expires_at < now:
            try:
                db.delete(t)
                db.commit()
            except Exception:
                pass
            return None
        u = db.execute(select(User).where(User.username == t.username, User.is_active == True)).scalar_one_or_none()
        if not u:
            return None
        # touch last_used
        try:
            t.last_used_at = now
            db.commit()
        except Exception:
            pass
        st.session_state["remember_token_hash"] = th
        return {
            "id": u.id,
            "username": u.username,
            "role": (u.role or "").strip().lower(),
            "department": u.department,
        }

def revoke_current_remember_token() -> None:
    th = (st.session_state.get("remember_token_hash") or "").strip()
    if not th:
        return
    try:
        with SessionLocal() as db:
            t = db.execute(select(AuthToken).where(AuthToken.token_hash == th)).scalar_one_or_none()
            if t:
                db.delete(t)
                db.commit()
    except Exception:
        pass
    st.session_state["remember_token_hash"] = None

def rememberme_set_token_js(token: str) -> None:
    token_js = (token or "").replace("\\", "\\\\").replace('"', '\"')
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          window.localStorage.setItem(KEY, "{token_js}");
          // curata URL-ul daca are rt
          const url = new URL(window.location.href);
          url.searchParams.delete("rt");
          const clean = url.pathname + (url.searchParams.toString() ? ("?" + url.searchParams.toString()) : "") + url.hash;
          window.history.replaceState({{}}, "", clean);
        }})();
        </script>
        """,
        height=0,
    )

def rememberme_clear_token_js_and_reload() -> None:
    components.html(
        f"""
        <script>
        (function() {{
          const KEY = "{REMEMBER_STORAGE_KEY}";
          window.localStorage.removeItem(KEY);
          const url = new URL(window.location.href);
          url.searchParams.delete("rt");
          const clean = url.pathname + (url.searchParams.toString() ? ("?" + url.searchParams.toString()) : "") + url.hash;
          window.location.replace(clean);
        }})();
        </script>
        """,
        height=0,
    )
