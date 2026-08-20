"""Ephemeral Streamlit interaction state; never durable student memory."""

from typing import Any

import streamlit as st


def initialise_state() -> None:
    defaults: dict[str, Any] = {
        "current_question": "",
        "selected_workflow": "Baseline",
        "last_response": None,
        "last_trace_id": None,
        "primary_institution_name": "Configured university",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def remember_response(response: dict[str, Any]) -> None:
    st.session_state.last_response = response
    st.session_state.last_trace_id = response.get("trace_id")
