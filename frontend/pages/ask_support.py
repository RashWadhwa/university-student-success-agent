"""Primary student-facing grounded support page."""

from typing import Any

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.components.citations import render_citations
from frontend.components.workflow import render_workflow
from frontend.state import remember_response

_TOPICS = {
    "Missed Assessment": "I missed an assessment. What university process should I check?",
    "Extension": "How can I request an assessment extension?",
    "Mitigating Circumstances": "How does the mitigating circumstances process work?",
    "Reassessment": "What does the current policy say about reassessment?",
    "Academic Appeal": "What are the usual grounds and steps for an academic appeal?",
}


def render(client: StudentSuccessAPIClient) -> None:
    st.title("Ask for student support")
    st.write(
        "Get grounded guidance from the "
        f"{st.session_state.primary_institution_name} policy knowledge base."
    )
    st.caption("Choose a topic or write your own question. Do not include sensitive personal data.")
    columns = st.columns(5)
    for column, (label, question) in zip(columns, _TOPICS.items(), strict=True):
        if column.button(label, use_container_width=True):
            st.session_state.current_question = question

    with st.form("ask-support"):
        question = st.text_area(
            "Your question",
            value=st.session_state.current_question,
            max_chars=2000,
            height=150,
            placeholder="Ask about extensions, missed assessments, reassessment, or appeals…",
        )
        mode = st.segmented_control(
            "Support mode",
            options=["Baseline", "Agentic"],
            default=st.session_state.selected_workflow,
        )
        submitted = st.form_submit_button("Get grounded guidance", type="primary")

    if submitted:
        if not question.strip():
            st.warning("Please enter a question.")
        else:
            st.session_state.current_question = question.strip()
            st.session_state.selected_workflow = mode or "Baseline"
            try:
                with st.spinner("Checking current policy evidence…"):
                    response = client.ask(question.strip(), agentic=mode == "Agentic")
                remember_response(response)
            except FrontendAPIError as exc:
                _safe_error(exc)

    response: dict[str, Any] | None = st.session_state.last_response
    if response:
        st.divider()
        st.subheader("Grounded guidance")
        st.write(response.get("answer", "No answer was returned."))
        action_items = response.get("recommended_actions", [])
        if action_items:
            st.subheader("Recommended actions")
            for action in action_items:
                st.markdown(
                    f"**{action.get('priority', '—')}. {action.get('action', '')}**  \n"
                    f"{action.get('reason', '')}"
                )
        summary = st.columns(3)
        summary[0].metric("Confidence", str(response.get("confidence", "unknown")).title())
        summary[1].metric("Citations", len(response.get("citations", [])))
        summary[2].metric(
            "Human support",
            "Recommended" if response.get("requires_human_support") else "Not required",
        )
        if response.get("human_support_reason"):
            st.warning(response["human_support_reason"])
        limitations = response.get("limitations", [])
        if limitations:
            with st.expander("Limitations"):
                for limitation in limitations:
                    st.write(f"• {limitation}")
        st.subheader("Policy evidence")
        render_citations(response.get("citations", []))
        if response.get("workflow"):
            with st.expander("Safe agent activity"):
                render_workflow(response)
        with st.expander("Request details"):
            st.code(
                f"Request ID: {response.get('request_id', 'not available')}\n"
                f"Trace ID: {response.get('trace_id') or 'tracing disabled'}"
            )


def _safe_error(error: FrontendAPIError) -> None:
    st.error(error.safe_message)
    if error.request_id:
        st.caption(f"Request ID: {error.request_id}")
