"""University Student Success Portal Streamlit entry point."""

import streamlit as st

from frontend.api_client import StudentSuccessAPIClient
from frontend.config import FrontendConfig
from frontend.pages import (
    agent_activity,
    ask_support,
    evaluation,
    evidence_explorer,
    knowledge_base,
    system,
)
from frontend.state import initialise_state

st.set_page_config(
    page_title="Student Success Portal",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(
    """
    <style>
      :root { --university-navy: #17324d; --university-gold: #d8a72d; }
      .stApp { background: linear-gradient(180deg, #f7f9fc 0%, #ffffff 45%); }
      h1, h2, h3 { color: var(--university-navy); }
      [data-testid="stSidebar"] { background: #17324d; }
      [data-testid="stSidebar"] * { color: #f8fafc; }
      .stButton > button[kind="primary"] { background: #17324d; border-color: #17324d; }
      div[data-testid="stMetric"] { background: #ffffff; border: 1px solid #dbe4ee;
        border-radius: 12px; padding: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)

initialise_state()
config = FrontendConfig.from_environment()
client = StudentSuccessAPIClient(config)
try:
    public_config = client.public_config()
    st.session_state.primary_institution_name = public_config["primary_institution_name"]
except (KeyError, TypeError):
    st.session_state.primary_institution_name = "Configured university"
except Exception:
    # The page remains usable if the safe configuration endpoint is temporarily unavailable.
    pass

with st.sidebar:
    st.title("Student Success")
    st.caption(f"Grounded policy guidance · {st.session_state.primary_institution_name}")
    page = st.radio(
        "Navigate",
        [
            "Ask for Support",
            "Knowledge Base",
            "Evidence Explorer",
            "Agent Activity",
            "Evaluation",
            "System",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption("This service provides guidance, not university decisions or legal advice.")

pages = {
    "Ask for Support": ask_support.render,
    "Knowledge Base": knowledge_base.render,
    "Evidence Explorer": evidence_explorer.render,
    "Agent Activity": agent_activity.render,
    "Evaluation": evaluation.render,
    "System": system.render,
}
pages[page](client)
