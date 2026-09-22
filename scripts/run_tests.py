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
from triage_agent.display import print_row
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
        print_row(enquiry["sender_name"], enquiry["sender_email"], enquiry["body"], result)
        results.append({"enquiry": enquiry, "triage_result": result.to_dict()})

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(results, indent=2))
    print(f"\nSaved structured output for {len(results)} enquiries to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
