#!/usr/bin/env python3
"""Run the triage agent over the 5 sample enquiries and save/print output.

Usage:
    python3 scripts/run_tests.py            # uses real Claude API if
                                              # ANTHROPIC_API_KEY is set,
                                              # otherwise falls back to the
                                              # deterministic MockClient
    python3 scripts/run_tests.py --mock      # force the mock client
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.llm_client import AnthropicClient, MockClient

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "sample_enquiries.json"
OUTPUT_PATH = ROOT / "outputs" / "results.json"


def build_client(force_mock: bool):
    if force_mock or not os.environ.get("ANTHROPIC_API_KEY"):
        if not force_mock:
            print("[info] No ANTHROPIC_API_KEY set -- using MockClient (deterministic, offline).\n")
        return MockClient()
    try:
        print(f"[info] Using AnthropicClient (model={os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')}).\n")
        return AnthropicClient()
    except ImportError:
        print("[warn] 'anthropic' package not installed -- falling back to MockClient.\n")
        return MockClient()


def print_row(enquiry: dict, result) -> None:
    print("=" * 88)
    print(f"{result.enquiry_id}  |  from: {enquiry['sender_name']} <{enquiry['sender_email']}>")
    print("-" * 88)
    print(f"RAW ENQUIRY : {enquiry['body']}")
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
    print(f"summary            : {result.summary}")
    if result.internal_note:
        print(f"internal_note      : {result.internal_note}")
    print(f"suggested_response : {result.suggested_response_draft or '<< none -- deferred to human >>'}")
    for issue in result.additional_issues:
        print(f"  + additional issue -> category={issue.category}, team={issue.suggested_team}, urgency={issue.urgency}")
        print(f"    summary: {issue.summary}")


def main() -> None:
    force_mock = "--mock" in sys.argv
    enquiries = json.loads(DATA_PATH.read_text())
    client = build_client(force_mock)
    agent = TriageAgent(client)

    results = []
    for enquiry in enquiries:
        result = agent.triage(
            sender_name=enquiry["sender_name"],
            sender_email=enquiry["sender_email"],
            body=enquiry["body"],
            enquiry_id=enquiry["enquiry_id"],
        )
        print_row(enquiry, result)
        results.append({"enquiry": enquiry, "triage_result": result.to_dict()})

    print("=" * 88)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nSaved structured output for {len(results)} enquiries to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
