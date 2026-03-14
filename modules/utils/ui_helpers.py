import base64
from typing import Optional
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components


def ui_result(ok: bool, msg) -> None:
    if ok:
        st.success(str(msg))
    else:
        st.error(str(msg))


def open_pdf_in_chrome_tab(pdf_bytes: bytes) -> None:
    """
    Deschide PDF in tab nou (Chrome) folosind Blob URL (evita iframe/data: blocat).
    """
    if not pdf_bytes:
        st.warning("Nu exista PDF pentru previzualizare.")
        return

    b64 = base64.b64encode(pdf_bytes).decode("utf-8")
    html = f"""
    <script>
    (function() {{
      const b64 = "{b64}";
      const byteChars = atob(b64);
      const byteNumbers = new Array(byteChars.length);
      for (let i = 0; i < byteChars.length; i++) {{
        byteNumbers[i] = byteChars.charCodeAt(i);
      }}
      const byteArray = new Uint8Array(byteNumbers);
      const blob = new Blob([byteArray], {{ type: "application/pdf" }});
      const url = URL.createObjectURL(blob);
      window.open(url, "_blank");
      setTimeout(() => URL.revokeObjectURL(url), 60000);
    }})();
    </script>
    """
    components.html(html, height=0)


def _set_scroll_to_workflow() -> None:
    st.session_state["_scroll_to_workflow"] = True


def _scroll_to_workflow_if_needed() -> None:
    if st.session_state.get("_scroll_to_workflow"):
        components.html(
            """
            <script>
              const el = window.parent.document.getElementById("wf_anchor");
              if (el) { el.scrollIntoView({behavior: "instant", block: "start"}); }
            </script>
            """,
            height=0,
        )
        st.session_state["_scroll_to_workflow"] = False


def _set_scroll_to_registry() -> None:
    st.session_state["_scroll_to_registry"] = True


def _scroll_to_registry_if_needed() -> None:
    if st.session_state.get("_scroll_to_registry"):
        components.html(
            """
            <script>
              const el = window.parent.document.getElementById("reg_anchor");
              if (el) { el.scrollIntoView({behavior: "instant", block: "start"}); }
            </script>
            """,
            height=0,
        )
        st.session_state["_scroll_to_registry"] = False


def _select_code_from_dataframe(df: pd.DataFrame, key: str, code_col: str = "cod", id_col: str = "id") -> Optional[str]:
    """
    Returneaza codul documentului selectat dintr-un tabel.

    - In Streamlit recent, foloseste selectia de rand din st.dataframe (click pe rand).
    - In versiuni mai vechi, cade pe un selectbox (fallback stabil) + afiseaza tabelul fara selectie.
    """
    if df is None or getattr(df, "empty", True):
        return None

    df_view = df.reset_index(drop=True)

    # Preferam selectia directa pe rand (click). Daca nu e suportata, folosim fallback.
    try:
        evt = st.dataframe(
            df_view,
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key=key,
        )
        sel_rows = []
        try:
            sel_rows = evt.selection.rows  # type: ignore[attr-defined]
        except Exception:
            sel_rows = []
        if sel_rows:
            r = int(sel_rows[0])
            if 0 <= r < len(df_view):
                v = str(df_view.loc[r, code_col]) if code_col in df_view.columns else ""
                v = (v or "").strip()
                if not v and id_col in df_view.columns:
                    v = str(df_view.loc[r, id_col]).strip()
                return v or None
        return None
    except TypeError:
        # Fallback pentru Streamlit fara selection_mode/on_select
        label_cols = [c for c in [code_col, "denumire_document", "document", "status", "reg_no", "reg_date"] if c in df_view.columns]
        labels = []
        idx_map = {}
        for i in range(len(df_view)):
            parts = [str(df_view.loc[i, c]) for c in label_cols if str(df_view.loc[i, c]).strip() not in ("", "nan", "None")]
            label = " | ".join(parts) if parts else f"Rand {i+1}"
            labels.append(label)
            idx_map[label] = i

        sel_label = st.selectbox("Selecteaza document", labels, key=f"{key}_fallback_sel")
        i = idx_map.get(sel_label)
        # Afisam si tabelul ca referinta vizuala
        st.dataframe(df_view, hide_index=True)

        if i is None:
            return None
        v = str(df_view.loc[i, code_col]) if code_col in df_view.columns else ""
        v = (v or "").strip()
        if not v and id_col in df_view.columns:
            v = str(df_view.loc[i, id_col]).strip()
        return v or None
