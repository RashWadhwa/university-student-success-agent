"""Explicit, bounded evaluation runner page."""

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.components.metrics import render_evaluation_summaries


def render(client: StudentSuccessAPIClient) -> None:
    st.title("Evaluation")
    st.write("Compare baseline and agentic workflows on the same synthetic policy cases.")
    try:
        datasets = client.evaluation_datasets().get("datasets", [])
    except FrontendAPIError as exc:
        st.warning(exc.safe_message)
        return
    if not datasets:
        st.info("No evaluation dataset is configured.")
        return
    names = [dataset["name"] for dataset in datasets]
    dataset = st.selectbox("Dataset", names)
    selected = next(item for item in datasets if item["name"] == dataset)
    workflow_label = st.segmented_control(
        "Workflow",
        options=["Baseline", "Agentic", "Both"],
        default="Both",
    )
    st.caption(
        f"{selected['case_count']} synthetic cases · "
        f"{len(selected.get('categories', []))} categories · hard server-side budgets apply"
    )
    if not st.button("Run evaluation", type="primary"):
        st.info("Evaluation never runs automatically. Start it explicitly when you are ready.")
        return
    try:
        with st.spinner("Running bounded evaluation cases…"):
            response = client.run_evaluation(
                dataset=dataset,
                workflow=(workflow_label or "Both").casefold(),
            )
        result = response["result"]
        st.success(f"Evaluation {result['status']}. Winner: {result['winner']}")
        render_evaluation_summaries(result.get("summaries", []))
        with st.expander("Per-case results"):
            st.dataframe(result.get("results", []), use_container_width=True)
    except FrontendAPIError as exc:
        st.error(exc.safe_message)
