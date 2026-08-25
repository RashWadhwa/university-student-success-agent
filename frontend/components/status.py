"""System component status cards."""

from typing import Any

import streamlit as st

_DISPLAY_NAME_OVERRIDES = {
    "fastapi": "FastAPI",
    "pgvector": "pgvector",
}


def render_status_grid(status: dict[str, Any]) -> None:
    columns = st.columns(3)
    for index, (name, details) in enumerate(status.items()):
        state = details.get("status", "unavailable")
        icon = "🟢" if state == "operational" else ("⚪" if state == "disabled" else "🟠")
        display_name = _DISPLAY_NAME_OVERRIDES.get(name, name.replace("_", " ").title())
        with columns[index % 3]:
            st.markdown(f"#### {icon} {display_name}")
            st.caption(state.title())
            if details.get("provider"):
                st.caption(f"Provider: {details['provider']}")
            if details.get("model"):
                st.caption(f"Model: {details['model']}")
