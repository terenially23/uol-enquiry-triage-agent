"""Deliberately tiny "retrieval" step: two hand-sourced facts, looked up by
Python condition, not asked of the LLM. See guidance/*.md for the actual
excerpts and their source URLs.

This is NOT a RAG system. It's two grounded facts wired to the two guardrail
conditions that need them, so the citation attached to a result always
traces back to a real, checkable source rather than the model paraphrasing
"I think Leeds requires evidence for this." See WRITEUP.md "Scalability"
for what a real version of this would need to look like.
"""

from __future__ import annotations

DISABILITY_EVIDENCE_CITATION = (
    "https://students.leeds.ac.uk/support-disabled-students — "
    '"To get support, you will first need to register with Disability '
    'Services... Provide supporting information about your disability." '
    "(see guidance/disability_evidence.md)"
)

LUU_INDEPENDENCE_CITATION = (
    "https://www.leeds.ac.uk/studentsupport — "
    '"Leeds University Union (LUU) offers free, confidential and '
    'independent advice." '
    "(see guidance/luu_vs_counselling_independence.md)"
)


def citation_for(category: str, internal_or_external: str) -> str | None:
    """Return a source citation string if this result touches one of the
    two facts we have grounded guidance for, else None."""
    if category == "disability":
        return DISABILITY_EVIDENCE_CITATION
    if internal_or_external == "ambiguous":
        return LUU_INDEPENDENCE_CITATION
    return None
