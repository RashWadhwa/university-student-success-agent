"""Bounded citation presentation."""

from typing import Any

import streamlit as st


def render_citations(citations: list[dict[str, Any]]) -> None:
    if not citations:
        st.info("No policy citations were available for this response.")
        return
    for citation in citations:
        citation_id = citation.get("citation_id", "Evidence")
        document_title = citation.get("document_title", "Policy")
        label = f"{citation_id} · {document_title}"
        with st.expander(label):
            left, right = st.columns(2)
            left.caption(f"Section: {citation.get('section') or 'Not specified'}")
            right.caption(f"Page: {citation.get('page', '—')}")
            left.caption(f"Version: {citation.get('version') or 'Not specified'}")
            right.caption(f"Effective: {citation.get('effective_date') or 'Not specified'}")
            tier = citation.get("corpus_tier", "primary")
            authority = citation.get("authority_scope", "institution_policy")
            publisher = citation.get("institution") or "Not specified"
            left.caption(f"Corpus: {str(tier).replace('_', ' ').title()}")
            right.caption(f"Authority: {str(authority).replace('_', ' ').title()}")
            st.caption(f"Institution/publisher: {publisher}")
            source = citation.get("source")
            if source:
                st.caption(f"Source: {source}")
            st.markdown(f"> {str(citation.get('excerpt', ''))[:600]}")
