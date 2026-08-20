"""Compact evaluation summary cards."""

from typing import Any

import streamlit as st


def render_evaluation_summaries(summaries: list[dict[str, Any]]) -> None:
    for summary in summaries:
        st.subheader(summary["workflow_mode"].title())
        cols = st.columns(4)
        cols[0].metric("Cases", summary["case_count"])
        cols[1].metric("Passed", summary["passed_count"])
        cols[2].metric("Latency", f"{summary['mean_latency_ms']:.0f} ms")
        cols[3].metric("Provider calls", summary["total_provider_calls"])
        combined = {**summary.get("deterministic", {}), **summary.get("judge", {})}
        if combined:
            chart_data = [
                {"metric": name.replace("_", " ").title(), "score": score}
                for name, score in combined.items()
            ]
            st.bar_chart(chart_data, x="metric", y="score")
