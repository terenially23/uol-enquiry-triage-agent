"""Shared human-readable rendering of a TriageResult, used by run_tests.py
and try_one.py so both print identically -- one enquiry or five."""

from __future__ import annotations

from .schema import TriageResult


def print_row(sender_name: str, sender_email: str, body: str, result: TriageResult) -> None:
    print("=" * 88)
    print(f"{result.enquiry_id}  |  from: {sender_name} <{sender_email}>")
    print("-" * 88)
    print(f"RAW ENQUIRY : {body}")
    print("-" * 88)
    print(f"category           : {result.category}  (confidence={result.confidence:.2f})")
    print(f"suggested_team     : {', '.join(result.suggested_team) or '-'}")
    print(f"internal_or_ext.   : {result.internal_or_external}")
    print(f"urgency            : {result.urgency}")
    print(f"requires_review    : {result.requires_human_review}")
    print(f"needs_human_judge. : {result.needs_human_judgement}")
    print(f"flags              : {result.flags or '-'}")
    if result.missing_info:
        print(f"missing_info       : evidence_attached={result.missing_info.evidence_attached} ({result.missing_info.details or '-'})")
    if result.source_citation:
        print(f"source_citation    : {result.source_citation}")
    print(f"summary            : {result.summary}")
    if result.internal_note:
        print(f"internal_note      : {result.internal_note}")
    print(f"suggested_response : {result.suggested_response_draft or '<< none -- deferred to human >>'}")
    for issue in result.additional_issues:
        print(f"  + additional issue -> category={issue.category}, team={issue.suggested_team}, urgency={issue.urgency}")
        print(f"    summary: {issue.summary}")
    print("=" * 88)
