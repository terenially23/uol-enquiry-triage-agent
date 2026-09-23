"""Routing knowledge base: the real service structure the agent routes against.

This is intentionally a small, hand-written knowledge base rather than an
ingested corpus of University of Leeds web pages / policy documents -- see
WRITEUP.md ("what this does NOT do") for why that's a deliberate scope cut
for a prototype, and what would be needed to make it production-safe.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Team:
    key: str
    name: str
    internal_or_external: str  # "internal" | "external"
    description: str
    notes: str = ""


TEAMS: dict[str, Team] = {
    "student_information_service": Team(
        key="student_information_service",
        name="Student Information Service",
        internal_or_external="internal",
        description=(
            "First-line University service for general/navigational student "
            "queries: address and contact detail changes, enrolment, "
            "timetables, ID cards, letters/proof of study, general policy "
            "questions."
        ),
        notes="Often safe to auto-draft a response for purely procedural asks.",
    ),
    "disability_services": Team(
        key="disability_services",
        name="Disability Services",
        internal_or_external="internal",
        description=(
            "Arranges exam adjustments, Student Support Plans and other "
            "disability-related adjustments. REQUIRES supporting evidence "
            "(diagnostic report / healthcare letter / medical evidence) "
            "before any adjustment can be arranged or promised."
        ),
        notes=(
            "Hard constraint: if evidence is not clearly stated as attached "
            "or already on file, the agent must not promise an adjustment "
            "and must flag missing_info instead."
        ),
    ),
    "counselling_and_wellbeing": Team(
        key="counselling_and_wellbeing",
        name="Student Counselling and Wellbeing",
        internal_or_external="internal",
        description=(
            "University-run mental health support: self-referral, "
            "drop-ins, 1:1 counselling, wellbeing advice. Part of the "
            "University; enquiry data is handled under University "
            "policies."
        ),
    ),
    "luu_advice": Team(
        key="luu_advice",
        name="Leeds University Union (LUU) Advice",
        internal_or_external="external",
        description=(
            "Independent, peer-run advice and support service operated by "
            "the Students' Union, not the University itself. Covers "
            "academic appeals support, housing, welfare and general "
            "student advice, including emotional/personal support framed "
            "as peer advice rather than clinical counselling."
        ),
        notes=(
            "Independent of the University -- different data-handling and "
            "confidentiality arrangements to an internal University "
            "service. This distinction must be surfaced to the student/"
            "reviewer, never silently resolved by the agent."
        ),
    ),
    "student_funding_team": Team(
        key="student_funding_team",
        name="Student Funding Team",
        internal_or_external="internal",
        description=(
            "Financial hardship support, discretionary/emergency funds, "
            "liaison with Student Finance England/Wales/NI/Scotland, "
            "scholarship and bursary queries."
        ),
        notes="Financially sensitive -- treat as at least medium urgency.",
    ),
    "academic_personal_tutor": Team(
        key="academic_personal_tutor",
        name="Academic Personal Tutor",
        internal_or_external="internal",
        description=(
            "Course-specific academic queries, personal academic "
            "development, module choices, progression concerns that need "
            "a named academic who knows the student's programme."
        ),
    ),
    "it_helpdesk": Team(
        key="it_helpdesk",
        name="IT Helpdesk / Online Learning Support",
        internal_or_external="internal",
        description=(
            "Account access issues (e.g. Minerva/VLE logins, password "
            "resets, locked accounts), online learning platform problems, "
            "and general IT support for accessing University systems and "
            "coursework submission portals."
        ),
        notes=(
            "Often time-sensitive -- account/access issues close to a "
            "deadline should be treated as urgent even though the request "
            "itself is routine and safe to auto-draft generic "
            "self-service steps for."
        ),
    ),
}

CATEGORY_TO_TEAM = {
    "info": "student_information_service",
    "disability": "disability_services",
    "wellbeing": None,  # ambiguous by design -- see counselling vs LUU
    "funding": "student_funding_team",
    "academic": "academic_personal_tutor",
    "other": None,
}

VALID_CATEGORIES = {"info", "wellbeing", "disability", "funding", "academic", "other"}
VALID_URGENCY = {"low", "medium", "high"}
VALID_INTERNAL_EXTERNAL = {"internal", "external", "ambiguous", "not_applicable"}


def routing_knowledge_prompt() -> str:
    """Render the routing knowledge base as text for the LLM system prompt."""
    lines = []
    for team in TEAMS.values():
        lines.append(f"- {team.name} [{team.internal_or_external}]: {team.description}")
        if team.notes:
            lines.append(f"  IMPORTANT: {team.notes}")
    return "\n".join(lines)
