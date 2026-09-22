"""Structured output schema for the triage agent.

Design notes (see WRITEUP.md for the full rationale):

- `suggested_team` is a list, not a single string. The brief's own sample
  enquiries include a multi-issue case (timetable clash + disability access)
  that genuinely needs two teams. Forcing a single team would mean either
  silently dropping one issue or inventing a category that doesn't exist.
- `additional_issues` captures a genuinely separate second issue in the same
  email, each with its own mini routing decision, rather than mashing two
  problems into one summary/urgency/category.
- `needs_human_judgement` + `internal_note` exist specifically for the
  Counselling vs LUU ambiguity: the schema gives the agent an explicit,
  first-class way to say "I'm not picking one" instead of forcing a
  confidence number to do that job silently.
- `requires_human_review` is always True. It's kept as an explicit field
  (rather than just "it's always true, trust us") so downstream code/UI has
  something to literally check, and so any future prompt change that tries
  to relax it is caught by the guardrail in agent.py, not by convention.
- `source_citation` holds the source URL (from guidance/sources.py) backing
  a specific claim made elsewhere in the result -- e.g. the evidence
  requirement in `missing_info`, or the internal/external split in
  `internal_or_external`. It is set by agent.py's retrieval step
  (`guidance/retrieve.py`), not invented by the LLM, and is null when no
  guidance excerpt applies (most enquiries -- e.g. a routine address
  change -- don't touch a cited fact at all).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class MissingInfo:
    evidence_attached: str  # "yes" | "no" | "unclear" | "not_applicable"
    details: str | None = None


@dataclass
class AdditionalIssue:
    category: str
    suggested_team: list[str]
    summary: str
    urgency: str


@dataclass
class TriageResult:
    enquiry_id: str
    category: str  # info | wellbeing | disability | funding | academic | other
    confidence: float  # 0.0-1.0, agent's self-reported confidence
    summary: str
    suggested_team: list[str]
    internal_or_external: str  # internal | external | ambiguous | not_applicable
    missing_info: MissingInfo | None
    suggested_response_draft: str | None
    requires_human_review: bool  # hard constraint: always True
    urgency: str  # low | medium | high
    needs_human_judgement: bool
    internal_note: str | None
    flags: list[str] = field(default_factory=list)
    additional_issues: list[AdditionalIssue] = field(default_factory=list)
    source_citation: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)
