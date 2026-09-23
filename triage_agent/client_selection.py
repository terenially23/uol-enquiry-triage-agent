"""Shared client-selection logic for scripts/run_tests.py and
scripts/try_one.py: Groq first (if GROQ_API_KEY is set), then Anthropic (if
ANTHROPIC_API_KEY is set), then the offline MockClient.

Groq is checked first because it's what this demo actually runs on -- see
WRITEUP.md's LLM client section for why.
"""

from __future__ import annotations

import os

from .llm_client import AnthropicClient, GroqClient, MockClient


def build_client(force_mock: bool = False):
    if force_mock:
        return MockClient()

    if os.environ.get("GROQ_API_KEY"):
        try:
            print(f"[info] Using GroqClient (model={os.environ.get('GROQ_MODEL', 'llama-3.3-70b-versatile')}).\n")
            return GroqClient()
        except ImportError:
            print("[warn] 'requests' package not installed -- falling back to MockClient.\n")
            return MockClient()

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            print(f"[info] Using AnthropicClient (model={os.environ.get('ANTHROPIC_MODEL', 'claude-sonnet-5')}).\n")
            return AnthropicClient()
        except ImportError:
            print("[warn] 'anthropic' package not installed -- falling back to MockClient.\n")
            return MockClient()

    print("[info] No GROQ_API_KEY or ANTHROPIC_API_KEY set -- using MockClient (deterministic, offline).\n")
    return MockClient()
