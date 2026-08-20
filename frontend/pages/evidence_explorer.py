"""Bounded hybrid retrieval inspection page."""

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient


def render(client: StudentSuccessAPIClient) -> None:
    st.title("Evidence Explorer")
    st.write(
        "Inspect citation-ready hybrid retrieval results for "
        f"{st.session_state.primary_institution_name} without embeddings or raw SQL."
    )
    with st.form("evidence-search"):
        query = st.text_input("Search the policy knowledge base", max_chars=2000)
        top_k = st.slider("Results", min_value=1, max_value=10, value=5)
        corpus_tier = st.selectbox(
            "Source tier",
            ["Primary institution policy", "Secondary sector guidance"],
        )
        publisher = None
        if corpus_tier == "Secondary sector guidance":
            publisher = st.text_input("Official guidance publisher", max_chars=255)
        submitted = st.form_submit_button("Search", type="primary")
    if not submitted:
        st.info("Enter a policy question to inspect the evidence selected by retrieval.")
        return
    try:
        with st.spinner("Searching semantic and keyword indexes…"):
            filters = {}
            if corpus_tier == "Secondary sector guidance":
                filters = {
                    "institution": (publisher or "").strip(),
                    "corpus_tier": "secondary",
                    "authority_scope": "sector_guidance",
                }
            response = client.retrieval_search(query.strip(), top_k=top_k, filters=filters)
        results = response.get("results", [])
        if not results:
            st.info("No evidence met the search criteria.")
        for result in results:
            with st.expander(
                f"{result['title']} · page {result['page']} · score {result['score']:.3f}"
            ):
                st.caption(
                    f"Section: {result.get('section') or 'Not specified'} · "
                    f"Version: {result.get('metadata', {}).get('version') or 'Not specified'} · "
                    f"Sources: {', '.join(result.get('retrieval_sources', []))}"
                )
                metadata = result.get("metadata", {})
                authority = str(metadata.get("authority_scope", "institution_policy")).replace(
                    "_", " "
                )
                st.caption(
                    f"Institution/publisher: {metadata.get('institution') or 'Not specified'} · "
                    f"Corpus: {str(metadata.get('corpus_tier', 'primary')).replace('_', ' ')} · "
                    f"Authority: {authority}"
                )
                st.markdown(f"> {str(result.get('content', ''))[:600]}")
    except FrontendAPIError as exc:
        st.error(exc.safe_message)
