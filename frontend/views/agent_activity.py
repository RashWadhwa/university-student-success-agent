"""Safe workflow activity page for the latest in-session response."""

import streamlit as st

from frontend.api_client import StudentSuccessAPIClient
from frontend.components.workflow import render_workflow


def render(client: StudentSuccessAPIClient) -> None:
    del client
    st.header("Agent Workflow")
    st.write("Review safe workflow milestones for the latest agentic request.")
    response = st.session_state.get("last_response")
    if not response:
        st.info("Submit an agentic question in Student Support first.")
        return
    render_workflow(response)
    workflow = response.get("workflow")
    if workflow:
        cols = st.columns(3)
        cols[0].metric("Duration", f"{workflow.get('duration_ms', 0):.0f} ms")
        cols[1].metric("Tool calls", workflow.get("tool_calls", 0))
        cols[2].metric("Provider calls", workflow.get("provider_calls", 0))
    st.caption("Prompts, private messages, evidence bodies, and hidden reasoning are never shown.")
