"""FastAPI-backed document ingestion and indexing page."""

from datetime import date

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient


def render(client: StudentSuccessAPIClient) -> None:
    st.header("Knowledge Base")
    st.write("Upload a text-based university policy PDF and index it for grounded retrieval.")
    upload = st.file_uploader("Policy PDF", type=["pdf"], accept_multiple_files=False)
    with st.expander("Optional policy metadata"):
        corpus_label = st.selectbox(
            "Source classification",
            ["Primary institution policy", "Secondary sector guidance"],
        )
        is_secondary = corpus_label == "Secondary sector guidance"
        title = st.text_input("Policy title", max_chars=512)
        institution = st.text_input(
            "Institution / official publisher",
            value=st.session_state.primary_institution_name,
            max_chars=255,
            help=(
                "For secondary guidance, replace this with the official publisher, "
                "for example Discover Uni."
            ),
        )
        version = st.text_input("Version", max_chars=100)
        effective_date = st.date_input("Effective date", value=None, max_value=date.today())
        source = st.text_input("Public source URL", max_chars=2048)
    submit = st.button("Upload and index", type="primary", disabled=upload is None)
    if not submit or upload is None:
        st.info("Choose a text-based PDF to begin. Image-only and encrypted PDFs are rejected.")
        return
    try:
        with st.spinner("Validating and ingesting the PDF…"):
            ingested = client.upload_document(upload.name, upload.getvalue())
        document = ingested["document"]
        metadata = {
            "title": title.strip() or None,
            "document_type": "policy",
            "institution": institution.strip() or None,
            "effective_date": effective_date.isoformat() if effective_date else None,
            "review_date": None,
            "version": version.strip() or None,
            "source": source.strip() or None,
            "corpus_tier": "secondary" if is_secondary else "primary",
            "authority_scope": "sector_guidance" if is_secondary else "institution_policy",
        }
        with st.spinner("Creating retrieval index…"):
            indexed = client.index_document(document["id"], metadata)
        st.success("The policy document is ready for retrieval.")
        cols = st.columns(3)
        cols[0].metric("Pages", document["page_count"])
        cols[1].metric("Chunks", indexed["chunk_count"])
        cols[2].metric("Status", indexed["status"].replace("_", " ").title())
    except FrontendAPIError as exc:
        st.error(exc.safe_message)
        if exc.request_id:
            st.caption(f"Request ID: {exc.request_id}")
