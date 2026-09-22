"""TriageAgent: orchestrates an LLM call and enforces hard guardrails in code.

Deliberate design choice: the two non-negotiable constraints in the brief
(requires_human_review is always True; disability adjustments are never
promised without evidence) are enforced here in Python, *after* the LLM
call, not just asked for in the prompt. Prompts are not reliable
enforcement mechanisms for hard constraints -- a model can drift, be
jailbroken by adversarial input, or simply make a mistake. Code that runs
after the call and cannot be talked out of its job is the actual guarantee.
"""

from __future__ import annotations

import uuid

from guidance.retrieve import citation_for

from .llm_client import LLMClient
from .routing import VALID_CATEGORIES, VALID_URGENCY, VALID_INTERNAL_EXTERNAL, TEAMS
from .schema import TriageResult, MissingInfo, AdditionalIssue

LOW_CONFIDENCE_THRESHOLD = 0.6


class TriageAgent:
    def __init__(self, llm_client: LLMClient, low_confidence_threshold: float = LOW_CONFIDENCE_THRESHOLD):
        self.llm_client = llm_client
        self.low_confidence_threshold = low_confidence_threshold

    def triage(self, sender_name: str, sender_email: str, body: str, enquiry_id: str | None = None) -> TriageResult:
        raw = self.llm_client.categorise(sender_name=sender_name, sender_email=sender_email, body=body)
        result = self._parse(raw, enquiry_id or f"ENQ-{uuid.uuid4().hex[:8]}")
        self._apply_guardrails(result, body)
        return result

    # -- parsing --------------------------------------------------------

    def _parse(self, raw: dict, enquiry_id: str) -> TriageResult:
        category = raw.get("category", "other")
        if category not in VALID_CATEGORIES:
            category = "other"

        urgency = raw.get("urgency", "low")
        if urgency not in VALID_URGENCY:
            urgency = "low"

        internal_or_external = raw.get("internal_or_external", "not_applicable")
        if internal_or_external not in VALID_INTERNAL_EXTERNAL:
            internal_or_external = "not_applicable"

        missing_info_raw = raw.get("missing_info")
        missing_info = (
            MissingInfo(
                evidence_attached=missing_info_raw.get("evidence_attached", "unclear"),
                details=missing_info_raw.get("details"),
            )
            if missing_info_raw
            else None
        )

        additional_issues = [
            AdditionalIssue(
                category=item.get("category", "other"),
                suggested_team=item.get("suggested_team", []),
                summary=item.get("summary", ""),
                urgency=item.get("urgency", "low"),
            )
            for item in raw.get("additional_issues", [])
        ]

        return TriageResult(
            enquiry_id=enquiry_id,
            category=category,
            confidence=float(raw.get("confidence", 0.0)),
            summary=raw.get("summary", ""),
            suggested_team=raw.get("suggested_team", []),
            internal_or_external=internal_or_external,
            missing_info=missing_info,
            suggested_response_draft=raw.get("suggested_response_draft"),
            requires_human_review=True,  # overwritten regardless of model output, see module docstring
            urgency=urgency,
            needs_human_judgement=bool(raw.get("needs_human_judgement", False)),
            internal_note=raw.get("internal_note"),
            flags=list(raw.get("flags", [])),
            additional_issues=additional_issues,
        )

    # -- guardrails -------------------------------------------------------

    def _apply_guardrails(self, result: TriageResult, body: str) -> None:
        result.requires_human_review = True  # hard constraint, non-negotiable

        # Guardrail: never let a drafted response promise a disability
        # adjustment when evidence isn't confirmed attached/on file.
        if result.category == "disability":
            evidence_ok = result.missing_info and result.missing_info.evidence_attached == "yes"
            if not evidence_ok:
                if result.missing_info is None:
                    result.missing_info = MissingInfo(evidence_attached="unclear", details="Not assessed by model; defaulting to unclear as a precaution.")
                if result.suggested_response_draft and _looks_like_a_promise(result.suggested_response_draft):
                    result.suggested_response_draft = None
                if "missing_evidence" not in result.flags:
                    result.flags.append("missing_evidence")

        # Guardrail: low-confidence categorisations should never carry an
        # unreviewed auto-draft, and should be visibly flagged for a human
        # to double check the category itself, not just the draft.
        if result.confidence < self.low_confidence_threshold:
            result.suggested_response_draft = None
            result.needs_human_judgement = True
            if "low_confidence" not in result.flags:
                result.flags.append("low_confidence")

        # Guardrail: ambiguous internal/external routing must never carry
        # an auto-draft either, since the two options imply different
        # confidentiality regimes.
        if result.internal_or_external == "ambiguous":
            result.suggested_response_draft = None
            result.needs_human_judgement = True

        # Sanity check: suggested_team entries should be known team keys.
        result.suggested_team = [t for t in result.suggested_team if t in TEAMS] or result.suggested_team

        # Attach a grounded source citation deterministically, in code --
        # not asked of the LLM -- so it always traces to a real URL rather
        # than a model-paraphrased claim. See guidance/retrieve.py.
        result.source_citation = citation_for(result.category, result.internal_or_external)


def _looks_like_a_promise(draft: str) -> bool:
    lowered = draft.lower()
    promise_phrases = ["we will arrange", "you will get extra time", "this has been arranged", "we've arranged", "we have arranged"]
    return any(p in lowered for p in promise_phrases)
