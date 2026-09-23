#!/usr/bin/env python3
"""Unit tests for agent.py's guardrail layer.

These exist because every guardrail fix in this project so far was found
by a bug in a live run, not by inspection -- see WRITEUP.md. Each test
below is a regression test for one of those found bugs: it constructs the
exact shape of LLM output that previously slipped through (a differently
worded promise, a model that ignored a prompt instruction, high confidence
masking a missing check) and asserts the guardrail catches it regardless.

Run with: python3 -m unittest discover -s tests
      or: python3 tests/test_guardrails.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.llm_client import LLMClient


class StubClient(LLMClient):
    """Returns a fixed payload regardless of input -- lets each test
    control exactly what the "model" said, including malformed/adversarial
    shapes a real model might produce."""

    def __init__(self, payload: dict):
        self.payload = payload

    def categorise(self, sender_name, sender_email, body):
        return self.payload


def base_payload(**overrides) -> dict:
    payload = {
        "category": "info",
        "confidence": 0.9,
        "summary": "s",
        "suggested_team": ["student_information_service"],
        "internal_or_external": "internal",
        "missing_info": None,
        "suggested_response_draft": None,
        "urgency": "low",
        "needs_human_judgement": False,
        "internal_note": None,
        "flags": [],
        "additional_issues": [],
    }
    payload.update(overrides)
    return payload


def triage(payload: dict, sender_name: str = "Test Student"):
    agent = TriageAgent(StubClient(payload))
    return agent.triage(sender_name, "test@leeds.ac.uk", "enquiry body")


class TestDisabilityEvidenceGuardrail(unittest.TestCase):
    def test_differently_worded_promise_is_still_replaced(self):
        # Regression: the original guardrail only caught 5 hardcoded
        # phrases. This wording matches none of them.
        payload = base_payload(
            category="disability",
            missing_info={"evidence_attached": "unclear", "details": None},
            suggested_response_draft="Great news -- your seminar room is being moved to an accessible location.",
        )
        result = triage(payload)
        self.assertIsNotNone(result.suggested_response_draft)
        self.assertNotIn("moved", result.suggested_response_draft.lower())
        self.assertIn("evidence", result.suggested_response_draft.lower())
        self.assertIn("missing_evidence", result.flags)

    def test_evidence_no_still_gets_a_safe_draft_not_silence(self):
        # Regression: an unconditional-null fix (briefly shipped, then
        # reverted) suppressed this legitimate case too.
        payload = base_payload(
            category="disability",
            missing_info={"evidence_attached": "no", "details": None},
            suggested_response_draft=None,
        )
        result = triage(payload)
        self.assertIsNotNone(result.suggested_response_draft)
        self.assertIn("evidence", result.suggested_response_draft.lower())

    def test_evidence_yes_passes_model_draft_through_untouched(self):
        payload = base_payload(
            category="disability",
            missing_info={"evidence_attached": "yes", "details": "On file"},
            suggested_response_draft="We can now proceed with your Student Support Plan.",
        )
        result = triage(payload)
        self.assertEqual(result.suggested_response_draft, "We can now proceed with your Student Support Plan.")


class TestSensitiveFinancialGuardrail(unittest.TestCase):
    def test_funding_draft_suppressed_even_at_high_confidence(self):
        # Regression: suppression previously only existed as a system-prompt
        # request the model was free to ignore.
        payload = base_payload(
            category="funding",
            confidence=0.9,
            suggested_response_draft="Sure, here is a payment plan you can use to cover your rent.",
        )
        result = triage(payload)
        self.assertIsNone(result.suggested_response_draft)
        self.assertIn("sensitive_financial", result.flags)

    def test_sensitive_financial_flag_alone_also_suppresses(self):
        payload = base_payload(
            category="other",
            confidence=0.9,
            flags=["sensitive_financial"],
            suggested_response_draft="Here's some financial advice.",
        )
        result = triage(payload)
        self.assertIsNone(result.suggested_response_draft)


class TestMultiIssueGuardrail(unittest.TestCase):
    def test_multi_issue_draft_suppressed_even_at_high_confidence(self):
        # Regression: ENQ-005's null draft was previously incidental to the
        # confidence-threshold guardrail (its confidence happened to be
        # below 0.6). This test uses confidence=0.9 specifically so the
        # confidence guardrail does NOT fire, isolating the multi-issue
        # guardrail as the thing that must catch it.
        payload = base_payload(
            category="info",
            confidence=0.9,
            suggested_response_draft="Sure, I've sorted your timetable clash for you.",
            additional_issues=[
                {
                    "category": "disability",
                    "suggested_team": ["disability_services"],
                    "summary": "Separate access issue.",
                    "urgency": "medium",
                }
            ],
        )
        result = triage(payload)
        self.assertGreaterEqual(result.confidence, 0.6)  # confirms the confidence guardrail didn't fire
        self.assertIsNone(result.suggested_response_draft)

    def test_multi_issue_flag_alone_also_suppresses_at_high_confidence(self):
        # additional_issues empty, but the model flagged multi_issue anyway.
        payload = base_payload(
            category="info",
            confidence=0.9,
            flags=["multi_issue"],
            suggested_response_draft="Here's a single draft covering everything.",
            additional_issues=[],
        )
        result = triage(payload)
        self.assertIsNone(result.suggested_response_draft)

    def test_single_issue_high_confidence_keeps_its_draft(self):
        # Sanity check: the new guardrail must not suppress ordinary,
        # single-issue enquiries.
        payload = base_payload(
            category="info",
            confidence=0.9,
            suggested_response_draft="Here's how to update your address.",
        )
        result = triage(payload)
        self.assertEqual(result.suggested_response_draft, "Here's how to update your address.")


class TestConfidenceAndAmbiguityGuardrails(unittest.TestCase):
    def test_low_confidence_suppresses_draft_and_forces_human_judgement(self):
        payload = base_payload(confidence=0.4, suggested_response_draft="A confident-sounding answer.")
        result = triage(payload)
        self.assertIsNone(result.suggested_response_draft)
        self.assertTrue(result.needs_human_judgement)
        self.assertIn("low_confidence", result.flags)

    def test_ambiguous_internal_external_suppresses_draft(self):
        payload = base_payload(
            category="wellbeing",
            confidence=0.9,
            internal_or_external="ambiguous",
            suggested_response_draft="Talk to counselling.",
        )
        result = triage(payload)
        self.assertIsNone(result.suggested_response_draft)
        self.assertTrue(result.needs_human_judgement)


class TestRequiresHumanReview(unittest.TestCase):
    def test_always_true_even_if_model_says_otherwise(self):
        payload = base_payload()
        payload["requires_human_review"] = False  # model output ignored on this field entirely
        result = triage(payload)
        self.assertTrue(result.requires_human_review)


if __name__ == "__main__":
    unittest.main()
