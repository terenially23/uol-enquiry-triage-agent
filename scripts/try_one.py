#!/usr/bin/env python3
"""Triage a single, custom enquiry interactively -- for manual testing
outside the fixed 5-case batch in run_tests.py.

Usage:
    python3 scripts/try_one.py

You'll be prompted for a sender name, sender email, and the enquiry body
(paste it, then finish with a blank line or Ctrl-D). Structured output for
just that one enquiry is printed -- nothing is saved to outputs/.

Same client selection as run_tests.py: uses AnthropicClient if
ANTHROPIC_API_KEY is set, otherwise MockClient. Force mock with --mock.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.display import print_row
from triage_agent.llm_client import AnthropicClient, MockClient


def build_client(force_mock: bool):
    if force_mock or not os.environ.get("ANTHROPIC_API_KEY"):
        if not force_mock:
            print("[info] No ANTHROPIC_API_KEY set -- using MockClient (deterministic, offline).\n")
        return MockClient()
    try:
        return AnthropicClient()
    except ImportError:
        print("[warn] 'anthropic' package not installed -- falling back to MockClient.\n")
        return MockClient()


def read_multiline(prompt: str) -> str:
    print(prompt)
    lines: list[str] = []
    try:
        while True:
            line = input()
            if line == "" and lines:
                break
            lines.append(line)
    except EOFError:
        pass
    return "\n".join(lines).strip()


def main() -> None:
    force_mock = "--mock" in sys.argv
    client = build_client(force_mock)
    agent = TriageAgent(client)

    sender_name = input("Sender name: ").strip() or "Unknown Student"
    sender_email = input("Sender email: ").strip() or "unknown@leeds.ac.uk"
    body = read_multiline("Enquiry body (paste it, then an empty line or Ctrl-D to finish):")

    if not body:
        print("No enquiry text entered -- exiting.")
        return

    result = agent.triage(sender_name=sender_name, sender_email=sender_email, body=body)
    print()
    print_row(sender_name, sender_email, body, result)


if __name__ == "__main__":
    main()
