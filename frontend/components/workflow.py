"""Safe agent workflow display without prompts or hidden reasoning."""

from typing import Any

import streamlit as st

_LABELS = {
    "coordinator": "Coordinator planned",
    "retrieval": "Retrieval completed",
    "policy_analyst": "Policy analysis completed",
    "student_support": "Student support completed",
    "verifier": "Verification completed",
}


def render_workflow(response: dict[str, Any]) -> None:
    workflow = response.get("workflow")
    if not workflow:
        st.info("Run an agentic request to see its safe workflow activity.")
        return
    st.markdown("✓ Request received")
    for agent in workflow.get("agents_used", []):
        st.markdown(f"✓ {_LABELS.get(agent, 'Workflow step completed')}")
    st.caption(
        f"Terminal state: {workflow.get('terminal_state', 'unknown')} · "
        f"Tool calls: {workflow.get('tool_calls', 0)} · "
        f"Provider calls: {workflow.get('provider_calls', 0)}"
    )
