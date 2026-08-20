"""System component status cards."""

from typing import Any

import streamlit as st


def render_status_grid(status: dict[str, Any]) -> None:
    columns = st.columns(3)
    for index, (name, details) in enumerate(status.items()):
        state = details.get("status", "unavailable")
        icon = "🟢" if state == "operational" else ("⚪" if state == "disabled" else "🟠")
        with columns[index % 3]:
            st.markdown(f"#### {icon} {name.replace('_', ' ').title()}")
            st.caption(state.title())
            if details.get("provider"):
                st.caption(f"Provider: {details['provider']}")
            if details.get("model"):
                st.caption(f"Model: {details['model']}")
