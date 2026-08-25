"""Unauthenticated screens: login, registration, forgot/reset password.

Every call here goes through StudentSuccessAPIClient -> FastAPI -> the
identity provider. This module never talks to the identity provider directly
and never holds a privileged credential — only the short-lived access/refresh
tokens issued to the signed-in user, kept in st.session_state via
frontend.state.
"""

from typing import Any

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.config import FrontendConfig
from frontend.state import clear_session, set_session

_MIN_PASSWORD_LENGTH = 12

_DEMO_ROLES = (
    ("student", "Student Demo"),
    ("staff", "Staff Demo"),
    ("admin", "Admin Demo"),
)


def _password_is_weak(password: str) -> str | None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        return f"Password must be at least {_MIN_PASSWORD_LENGTH} characters."
    if not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
        return "Password must contain at least one letter and one number."
    return None


def _go_to(screen: str) -> None:
    st.session_state.auth_screen = screen
    st.session_state.auth_notice = None
    st.rerun()


def render_auth_gate(client: StudentSuccessAPIClient, config: FrontendConfig) -> None:
    st.title("University Student Success Assistant")
    st.markdown(
        '<p class="app-subtitle">Secure, grounded guidance from verified university policy.</p>',
        unsafe_allow_html=True,
    )

    notice = st.session_state.get("auth_notice")
    if notice:
        st.warning(notice)
        st.session_state.auth_notice = None

    screen = st.session_state.get("auth_screen", "login")
    renderers = {
        "login": lambda: _render_login(client, config),
        "register": lambda: _render_register(client),
        "forgot_password": lambda: _render_forgot_password(client),
        "reset_password": lambda: _render_reset_password(client),
        "pending_verification": _render_pending_verification,
    }
    renderers.get(screen, renderers["login"])()


def _render_login(client: StudentSuccessAPIClient, config: FrontendConfig) -> None:
    st.header("Sign in")
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

    if submitted:
        if not email or not password:
            st.error("Enter your email and password.")
        else:
            try:
                response = client.login(email=email.strip(), password=password)
            except FrontendAPIError as exc:
                st.error(exc.safe_message)
            else:
                set_session(response)
                st.rerun()

    left, right = st.columns(2)
    with left:
        if st.button("Forgot password?", use_container_width=True):
            _go_to("forgot_password")
    with right:
        if st.button("Create account", use_container_width=True):
            _go_to("register")

    if config.enable_demo_auth:
        st.divider()
        st.caption("Demo accounts (local/demo mode only)")
        columns = st.columns(len(_DEMO_ROLES))
        for column, (demo_role, label) in zip(columns, _DEMO_ROLES, strict=True):
            with column:
                if st.button(label, use_container_width=True, key=f"demo_{demo_role}"):
                    try:
                        response = client.demo_login(demo_role=demo_role)
                    except FrontendAPIError as exc:
                        st.error(exc.safe_message)
                    else:
                        set_session(response)
                        st.rerun()


def _render_register(client: StudentSuccessAPIClient) -> None:
    st.header("Create your Student Success account")
    with st.form("register_form", clear_on_submit=False):
        display_name = st.text_input("Full name")
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        confirm_password = st.text_input("Confirm password", type="password")
        st.caption(
            f"At least {_MIN_PASSWORD_LENGTH} characters, with at least one letter and one number."
        )
        submitted = st.form_submit_button(
            "Create account", type="primary", use_container_width=True
        )

    if submitted:
        errors = _register_validation_errors(display_name, email, password, confirm_password)
        if errors:
            for error in errors:
                st.error(error)
        else:
            try:
                response = client.register(
                    display_name=display_name.strip(),
                    email=email.strip(),
                    password=password,
                    confirm_password=confirm_password,
                )
            except FrontendAPIError as exc:
                st.error(exc.safe_message)
            else:
                if response.get("status") == "pending_verification":
                    st.session_state.auth_pending_email = email.strip()
                    _go_to("pending_verification")
                else:
                    set_session(response)
                    st.rerun()

    if st.button("Already have an account? Sign in"):
        _go_to("login")


def _register_validation_errors(
    display_name: str, email: str, password: str, confirm_password: str
) -> list[str]:
    errors: list[str] = []
    if not display_name.strip():
        errors.append("Enter your full name.")
    if not email.strip():
        errors.append("Enter your email address.")
    weakness = _password_is_weak(password)
    if weakness:
        errors.append(weakness)
    elif password != confirm_password:
        errors.append("Passwords do not match.")
    return errors


def _render_forgot_password(client: StudentSuccessAPIClient) -> None:
    st.header("Reset your password")
    st.write("Enter the email address associated with your account.")
    with st.form("forgot_password_form", clear_on_submit=False):
        email = st.text_input("Email")
        submitted = st.form_submit_button(
            "Send reset instructions", type="primary", use_container_width=True
        )

    if submitted:
        if not email.strip():
            st.error("Enter your email address.")
        else:
            try:
                response = client.forgot_password(email=email.strip())
            except FrontendAPIError as exc:
                st.error(exc.safe_message)
            else:
                st.success(
                    response.get(
                        "message",
                        "If an account exists for that email address, "
                        "password reset instructions have been sent.",
                    )
                )

    left, right = st.columns(2)
    with left:
        if st.button("Back to sign in"):
            _go_to("login")
    with right:
        if st.button("I have a reset code"):
            _go_to("reset_password")


def _render_reset_password(client: StudentSuccessAPIClient) -> None:
    st.header("Choose a new password")

    token_hash = st.session_state.get("auth_reset_token_hash")
    if token_hash:
        st.success("Reset link recognised. Choose a new password below.")
    else:
        st.write("Paste the reset code from your email.")
        token_hash = st.text_input("Reset code", type="password", key="manual_reset_token_hash")

    with st.form("reset_password_form", clear_on_submit=False):
        new_password = st.text_input("New password", type="password")
        confirm_password = st.text_input("Confirm password", type="password")
        submitted = st.form_submit_button(
            "Update password", type="primary", use_container_width=True
        )

    if submitted:
        weakness = _password_is_weak(new_password)
        if not token_hash:
            st.error("Enter the reset code from your email.")
        elif weakness:
            st.error(weakness)
        elif new_password != confirm_password:
            st.error("Passwords do not match.")
        else:
            try:
                client.reset_password(
                    token_hash=token_hash,
                    new_password=new_password,
                    confirm_password=confirm_password,
                )
            except FrontendAPIError as exc:
                st.error(exc.safe_message)
            else:
                st.session_state.auth_reset_token_hash = None
                clear_session(notice="Password updated successfully. Please sign in.")
                st.rerun()

    if st.button("Back to sign in"):
        st.session_state.auth_reset_token_hash = None
        _go_to("login")


def _render_pending_verification() -> None:
    st.header("Check your email")
    email = st.session_state.get("auth_pending_email")
    st.write(
        "We've sent you a verification link"
        + (f" at **{email}**." if email else ".")
        + " Verify your email before signing in."
    )
    if st.button("Back to sign in"):
        st.session_state.auth_pending_email = None
        _go_to("login")


def handle_recovery_link_query_params() -> None:
    """Route an emailed password-recovery link straight to the reset screen.

    The identity provider's recovery email (configured to use the token-hash
    template) redirects here as ``?token_hash=...&type=recovery`` in the query
    string (not the URL fragment), which Streamlit can read server-side.
    """

    params: Any = st.query_params
    token_hash = params.get("token_hash")
    recovery_type = params.get("type")
    if token_hash and recovery_type == "recovery":
        st.session_state.auth_reset_token_hash = token_hash
        st.session_state.auth_screen = "reset_password"
        st.query_params.clear()
