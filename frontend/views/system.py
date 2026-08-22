"""Lightweight safe system status page."""

import streamlit as st

from frontend.api_client import FrontendAPIError, StudentSuccessAPIClient
from frontend.components.status import render_status_grid


def render(client: StudentSuccessAPIClient) -> None:
    st.header("System Health")
    st.write("Safe operational status without credentials, connection strings, or raw exceptions.")
    try:
        health = client.health()
        status = client.system_status()
        st.success(f"FastAPI is live · version {health.get('version', 'unknown')}")
        render_status_grid(status)
        with st.expander("Readiness probe"):
            try:
                readiness = client.ready()
                st.json(readiness.get("checks", {}))
            except FrontendAPIError as exc:
                st.warning(exc.safe_message)
    except FrontendAPIError as exc:
        st.error(exc.safe_message)
