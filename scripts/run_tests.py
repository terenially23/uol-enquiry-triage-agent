#!/usr/bin/env python3
"""Run the triage agent over the 8 sample enquiries and save/print output.

Usage:
    python3 scripts/run_tests.py            # uses GroqClient if GROQ_API_KEY
                                              # is set, else AnthropicClient
                                              # if ANTHROPIC_API_KEY is set,
                                              # else the offline MockClient
    python3 scripts/run_tests.py --mock      # force the mock client
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.client_selection import build_client
from triage_agent.display import print_row
from triage_agent.llm_client import MockClient

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "sample_enquiries.json"
OUTPUT_PATH = ROOT / "outputs" / "results.json"

# Paces the batch under Groq's free-tier TPM (tokens-per-minute) limit --
# see WRITEUP.md's LLM client section. Not needed for MockClient (no API
# calls) so it's skipped there to keep --mock runs fast.
INTER_ENQUIRY_SLEEP_SECONDS = 15


def main() -> None:
    force_mock = "--mock" in sys.argv
    enquiries = json.loads(DATA_PATH.read_text())
    client = build_client(force_mock)
    agent = TriageAgent(client)
    pace_batch = not isinstance(client, MockClient)

    results = []
    for i, enquiry in enumerate(enquiries):
        if pace_batch and i > 0:
            print(f"[info] Pacing batch under the free-tier rate limit -- waiting {INTER_ENQUIRY_SLEEP_SECONDS}s.\n")
            time.sleep(INTER_ENQUIRY_SLEEP_SECONDS)

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
