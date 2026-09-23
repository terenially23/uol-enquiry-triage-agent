#!/usr/bin/env python3
"""Minimal Streamlit demo -- a thin UI wrapper around the exact same
TriageAgent / client_selection logic scripts/try_one.py uses. No business
logic lives in this file: it only imports and calls into agent.py and
client_selection.py, then renders the TriageResult. See those modules
(and llm_client.py, routing.py) for the actual system -- this is a
presentation layer over it, not a reimplementation.

Usage:
    streamlit run scripts/demo_app.py

Client selection (GROQ_API_KEY -> ANTHROPIC_API_KEY -> MockClient) is
exactly client_selection.build_client()'s logic, same as run_tests.py,
try_one.py and evaluate.py -- not duplicated here.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from triage_agent.agent import TriageAgent
from triage_agent.client_selection import build_client
from triage_agent.llm_client import AnthropicClient, GroqClient, MockClient


@st.cache_resource(show_spinner=False)
def get_client():
    """Builds the client once per Streamlit session via the project's own
    selection logic, cached only because Streamlit re-executes this whole
    script on every interaction -- not a second decision about which
    client to use."""
    return build_client()


def client_label(client) -> str:
    """Describes the already-selected client for the top-of-page banner,
    matching the [info] line client_selection.build_client() prints to
    the terminal for the other scripts -- pure introspection of the
    result, not new selection logic."""
    if isinstance(client, GroqClient):
        return f"GroqClient (model={client.model})"
    if isinstance(client, AnthropicClient):
        return f"AnthropicClient (model={client.model})"
    if isinstance(client, MockClient):
        return "MockClient (deterministic, offline -- no GROQ_API_KEY or ANTHROPIC_API_KEY set)"
    return type(client).__name__


st.set_page_config(page_title="Student Enquiry Triage Agent")

st.title("Student Enquiry Triage Agent")
st.caption(
    "Thin UI wrapper around the same TriageAgent used by scripts/try_one.py. "
    "Every result is reviewed by a human before anything is sent -- this tool never sends a reply."
)

client = get_client()
st.info(f"Active LLM client: **{client_label(client)}**")

st.subheader("New enquiry")
sender_name = st.text_input("Sender name", placeholder="e.g. Megan Ashworth")
sender_email = st.text_input("Sender email", placeholder="e.g. ml19ma@leeds.ac.uk")
body = st.text_area("Enquiry body", height=180, placeholder="Paste the raw enquiry text here...")

if st.button("Triage", type="primary"):
    if not body.strip():
        st.warning("Enter an enquiry body first.")
    else:
        agent = TriageAgent(client)
        with st.spinner("Triaging..."):
            result = agent.triage(
                sender_name=sender_name.strip() or "Unknown Student",
                sender_email=sender_email.strip() or "unknown@leeds.ac.uk",
                body=body,
            )
        st.session_state["last_result"] = result
        st.session_state["last_body"] = body

if "last_result" in st.session_state:
    result = st.session_state["last_result"]

    st.divider()
    st.subheader(f"Result -- {result.enquiry_id}")
    st.text_area("Raw enquiry (for reference, shown next to the structured output for spot-checking)",
                 st.session_state["last_body"], height=100, disabled=True)

    col1, col2, col3 = st.columns(3)
    col1.metric("Category", result.category)
    col2.metric("Confidence", f"{result.confidence:.2f}")
    col3.metric("Urgency", result.urgency)

    st.write(f"**Suggested team:** {', '.join(result.suggested_team) or '-'}")
    st.write(f"**Internal / external:** {result.internal_or_external}")
    st.write(f"**Flags:** {', '.join(result.flags) if result.flags else '-'}")

    if result.missing_info:
        st.write(
            f"**Missing info:** evidence_attached={result.missing_info.evidence_attached} "
            f"({result.missing_info.details or '-'})"
        )

    if result.source_citation:
        st.write(f"**Source citation:** {result.source_citation}")

    st.write(f"**Requires human review:** {result.requires_human_review}")
    st.write(f"**Needs human judgement:** {result.needs_human_judgement}")

    if result.internal_note:
        st.write(f"**Internal note:** {result.internal_note}")

    st.write(f"**Summary:** {result.summary}")

    st.markdown("**Suggested response draft:**")
    if result.suggested_response_draft:
        st.text_area("Draft", result.suggested_response_draft, height=160, disabled=True, label_visibility="collapsed")
    else:
        st.write("-- deferred to human --")

    if result.additional_issues:
        st.markdown("**Additional issues** (split out rather than forced into one category):")
        for issue in result.additional_issues:
            st.write(f"- `{issue.category}` -> team={issue.suggested_team}, urgency={issue.urgency}: {issue.summary}")
