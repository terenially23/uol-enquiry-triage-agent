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
        self._apply_guardrails(result, sender_name)
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

    def _apply_guardrails(self, result: TriageResult, sender_name: str) -> None:
        result.requires_human_review = True  # hard constraint, non-negotiable

        # Guardrail: in a multi-issue enquiry, a disability issue always
        # leads as the primary category/team/summary, never a general/
        # administrative one (e.g. a timetable clash) -- fixed and
        # deterministic, not left to whichever category the model (or
        # MockClient) happened to put first. Disability issues are more
        # consequential (evidence/adjustment implications, the guardrail
        # above) and specialist than administrative ones, so they should
        # get the reviewer's attention first. Runs before the disability
        # evidence guardrail below so a promoted disability issue still
        # gets evidence-checked exactly like a disability enquiry that
        # arrived as the sole issue.
        #
        # Known gap: AdditionalIssue doesn't carry a missing_info/evidence
        # field (only category/suggested_team/summary/urgency), so if the
        # top-level missing_info wasn't already populated for the
        # disability aspect specifically, the evidence guardrail below
        # will default it to "unclear" rather than lose the promotion
        # entirely -- safe, but means evidence status for a *demoted*
        # disability issue (the rare case of two disability-adjacent
        # issues) isn't separately tracked by this schema.
        if result.category != "disability":
            disability_issue = next((i for i in result.additional_issues if i.category == "disability"), None)
            if disability_issue is not None:
                demoted = AdditionalIssue(
                    category=result.category,
                    suggested_team=result.suggested_team,
                    summary=result.summary,
                    urgency=result.urgency,
                )
                result.additional_issues = [demoted] + [i for i in result.additional_issues if i is not disability_issue]
                result.category = disability_issue.category
                result.suggested_team = disability_issue.suggested_team
                result.summary = disability_issue.summary
                result.urgency = _higher_urgency(result.urgency, disability_issue.urgency)
                if "multi_issue" not in result.flags:
                    result.flags.append("multi_issue")

        # Guardrail: never let a drafted response promise a disability
        # adjustment when evidence isn't confirmed attached/on file.
        # Unconditional on evidence_ok, and the replacement draft is
        # generated here in code, not left to the model. An earlier version
        # only nulled the draft if its wording matched a hardcoded phrase
        # list ("we will arrange...", etc.) via a _looks_like_a_promise()
        # helper -- a real LLM response worded differently sailed straight
        # through it. Simply nulling unconditionally was the next attempt,
        # but that also swallowed the legitimate case: the brief wants a
        # SAFE draft here (one that asks for evidence), not no draft at
        # all, and MockClient/the system prompt already produce that safe
        # wording correctly most of the time. Since the actual failure mode
        # is "can't trust the model's wording to be safe," the fix is to
        # stop trusting it for this one piece of text: overwrite with a
        # fixed, deterministic evidence-request template whenever evidence
        # isn't confirmed, so the guardrail no longer depends on what the
        # model wrote at all.
        if result.category == "disability":
            evidence_ok = result.missing_info and result.missing_info.evidence_attached == "yes"
            if not evidence_ok:
                if result.missing_info is None:
                    result.missing_info = MissingInfo(evidence_attached="unclear", details="Not assessed by model; defaulting to unclear as a precaution.")
                result.suggested_response_draft = _evidence_request_draft(sender_name)
                if "missing_evidence" not in result.flags:
                    result.flags.append("missing_evidence")

        # Guardrail: financially sensitive enquiries never carry an
        # unreviewed auto-draft, regardless of confidence or wording, and
        # always require human judgement -- same as the multi-issue
        # guardrail below, for consistency: a financial hardship enquiry
        # is exactly the kind of case where a human should always be
        # deciding the response, not just reviewing a suppressed draft.
        # Draft suppression was previously only requested via the system
        # prompt (rule 4) and left the model free to draft one anyway --
        # suppression flip-flopped between runs depending on whether the
        # model complied that time. Enforced here in code so both are
        # unconditional.
        if result.category == "funding" or "sensitive_financial" in result.flags:
            result.suggested_response_draft = None
            result.needs_human_judgement = True
            if "sensitive_financial" not in result.flags:
                result.flags.append("sensitive_financial")

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

        # Guardrail: multi-issue enquiries never carry an auto-draft, and
        # always require human judgement. A single draft is written
        # against the primary category/team and says nothing about
        # whatever's in additional_issues, so it can't safely represent
        # both routed issues at once -- and a human should always be the
        # one deciding how to split the reply, not the tool. Unconditional
        # on additional_issues/flags, not on confidence -- found as a gap
        # during testing, not designed in from the start: ENQ-005 happened
        # to also trip the confidence-threshold guardrail, which masked
        # that nothing here actually checked for multi-issue enquiries. A
        # multi-issue result with confidence >= 0.6 would previously have
        # sailed through with an unlabelled, partial draft and
        # needs_human_judgement left False.
        if result.additional_issues or "multi_issue" in result.flags:
            result.suggested_response_draft = None
            result.needs_human_judgement = True

        # Sanity check: suggested_team entries should be known team keys.
        result.suggested_team = [t for t in result.suggested_team if t in TEAMS] or result.suggested_team

        # Attach a grounded source citation deterministically, in code --
        # not asked of the LLM -- so it always traces to a real URL rather
        # than a model-paraphrased claim. See guidance/retrieve.py.
        result.source_citation = citation_for(result.category, result.internal_or_external)


def _evidence_request_draft(sender_name: str) -> str:
    """Fixed, code-generated draft used whenever a disability enquiry's
    evidence isn't confirmed -- deliberately not model-generated text, so
    it can never phrase itself as a promise. See guidance/disability_evidence.md
    for the sourced fact this reflects (registration requires "supporting
    information about your disability")."""
    return (
        f"Dear {sender_name},\n\nThank you for getting in touch about exam "
        "adjustments. To arrange these we first need supporting evidence, "
        "such as a diagnostic assessment report or a letter from a "
        "healthcare professional. Could you please attach this to your "
        "reply, or let us know if you already have evidence on file with "
        "us? Once we have this we can look at putting a Student Support "
        "Plan in place.\n\nBest wishes,\nDisability Services"
    )


_URGENCY_RANK = {"low": 0, "medium": 1, "high": 2}


def _higher_urgency(a: str, b: str) -> str:
    """Used when promoting a disability issue to primary: keeps the more
    urgent of the two issues' urgency ratings rather than silently
    dropping whichever one didn't end up as the primary category."""
    return a if _URGENCY_RANK.get(a, 0) >= _URGENCY_RANK.get(b, 0) else b
