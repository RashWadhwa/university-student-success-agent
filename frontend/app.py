"""University Student Success Portal Streamlit entry point."""

import contextlib

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.config import FrontendConfig
from frontend.state import (
    clear_session,
    current_display_name,
    current_role,
    initialise_state,
    is_authenticated,
    set_session,
)
from frontend.views import (
    agent_activity,
    ask_support,
    auth,
    evaluation,
    evidence_explorer,
    knowledge_base,
    system,
)

st.set_page_config(
    page_title="University Student Success Assistant",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
      :root { --university-navy: #17324d; --university-gold: #d8a72d; }
      .stApp { background: var(--background-color); }
      [data-testid="stAppViewContainer"] h1,
      [data-testid="stAppViewContainer"] h2,
      [data-testid="stAppViewContainer"] h3,
      .app-subtitle { color: var(--text-color); }
      .app-subtitle { font-size: 1.1rem; line-height: 1.6; margin: -0.5rem 0 1.75rem; }
      [data-testid="stSidebar"] { background: #17324d; }
      [data-testid="stSidebar"] * { color: #f8fafc; }
      .stButton > button[kind="primary"] { background: #17324d; border-color: #17324d; }
      div[data-testid="stMetric"] { background: var(--secondary-background-color);
        border: 1px solid color-mix(in srgb, var(--text-color) 18%, transparent);
        border-radius: 12px; padding: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

initialise_state()
config = FrontendConfig.from_environment()
auth.handle_recovery_link_query_params()

client = StudentSuccessAPIClient(config, access_token=st.session_state.access_token)
try:
    public_config = client.public_config()
    st.session_state.primary_institution_name = public_config["primary_institution_name"]
except (KeyError, TypeError):
    st.session_state.primary_institution_name = "Configured university"
except Exception:
    # The page remains usable if the safe configuration endpoint is temporarily unavailable.
    pass

if not is_authenticated():
    with st.sidebar:
        st.title("Student Success")
        st.caption(f"Grounded policy guidance · {st.session_state.primary_institution_name}")
        st.divider()
        st.caption("This service provides guidance, not university decisions or legal advice.")
    auth.render_auth_gate(client, config)
    st.stop()

try:
    identity = client.current_user()
except FrontendAPIError as exc:
    if exc.status_code != 401:
        # Backend temporarily unreachable/erroring: keep the session, just report it.
        st.error(exc.safe_message)
        st.stop()
    refresh_token = st.session_state.refresh_token
    if refresh_token:
        try:
            refreshed = client.refresh_session(refresh_token=refresh_token)
        except FrontendAPIError:
            clear_session(notice="Your session has expired. Please sign in again.")
        else:
            set_session(refreshed)
        st.rerun()
    else:
        clear_session(notice="Your session has expired. Please sign in again.")
        st.rerun()
else:
    role = identity.get("role", current_role() or "student")

with st.sidebar:
    st.title("Student Success")
    st.caption(f"Grounded policy guidance · {st.session_state.primary_institution_name}")
    st.caption("Signed in as")
    st.markdown(f"**{current_display_name()}**")
    st.caption("Role")
    st.markdown(f"**{role.capitalize()}**")

    available_pages = [
        "Student Support",
        "Evidence Explorer",
        "Agent Workflow",
    ]
    if role in {"staff", "admin"}:
        available_pages.append("Knowledge Base")
    if role == "admin":
        available_pages.append("Evaluation Centre")
    if role in {"staff", "admin"}:
        available_pages.append("System Health")
    page = st.radio(
        "Navigate",
        available_pages,
        label_visibility="collapsed",
    )

    st.divider()
    if st.button("Sign out", use_container_width=True):
        with contextlib.suppress(FrontendAPIError):
            client.logout()
        clear_session()
        st.rerun()
    st.divider()
    st.caption("This service provides guidance, not university decisions or legal advice.")

st.title("University Student Success Assistant")
st.markdown(
    '<p class="app-subtitle">Grounded guidance from verified university policies, with '
    "transparent evidence and human escalation when needed.</p>",
    unsafe_allow_html=True,
)

pages = {
    "Student Support": ask_support.render,
    "Knowledge Base": knowledge_base.render,
    "Evidence Explorer": evidence_explorer.render,
    "Agent Workflow": agent_activity.render,
    "Evaluation Centre": evaluation.render,
    "System Health": system.render,
}
pages[page](client)
