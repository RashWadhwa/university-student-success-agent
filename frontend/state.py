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
        # Authentication session — tokens live only in this server-side
        # session_state for the duration of the browser session; never
        # persisted, logged, or sent anywhere except the Authorization
        # header on requests to our own FastAPI backend.
        "authenticated": False,
        "access_token": None,
        "refresh_token": None,
        "token_expires_at": None,
        "auth_user": None,
        "auth_screen": "login",
        "auth_notice": None,
        "auth_pending_email": None,
        "auth_reset_token_hash": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def remember_response(response: dict[str, Any]) -> None:
    st.session_state.last_response = response
    st.session_state.last_trace_id = response.get("trace_id")


def set_session(auth_response: dict[str, Any]) -> None:
    """Store a login/register/refresh/demo-login response's session and user."""

    session = auth_response["session"]
    st.session_state.authenticated = True
    st.session_state.access_token = session["access_token"]
    st.session_state.refresh_token = session["refresh_token"]
    st.session_state.token_expires_at = session["expires_at"]
    st.session_state.auth_user = auth_response["user"]


def clear_session(*, notice: str | None = None) -> None:
    """Clear the authentication session (sign-out or expiry); never touches memory."""

    st.session_state.authenticated = False
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.token_expires_at = None
    st.session_state.auth_user = None
    st.session_state.auth_screen = "login"
    st.session_state.auth_notice = notice


def is_authenticated() -> bool:
    return bool(st.session_state.get("authenticated") and st.session_state.get("access_token"))


def current_role() -> str | None:
    user = st.session_state.get("auth_user")
    return user.get("role") if user else None


def current_display_name() -> str:
    user = st.session_state.get("auth_user") or {}
    return user.get("display_name") or user.get("email") or "Signed-in user"
