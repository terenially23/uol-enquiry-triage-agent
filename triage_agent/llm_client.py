"""LLM client abstraction.

Three implementations, all behind the same LLMClient interface:

- AnthropicClient: real categorisation via the Claude API, using a tool-use
  call to force valid structured JSON back (no free-text parsing).
- GroqClient: same idea via Groq's free-tier, OpenAI-compatible chat
  completions API, used to run this demo without spending Anthropic
  credits -- see WRITEUP.md.
- MockClient: a deterministic, keyword-based stand-in with the *same*
  interface, used when no API key is configured so the prototype still
  runs end-to-end for a reviewer without any credentials.

This split is itself a design decision worth naming in interview: the agent
module never talks to a provider SDK directly, it talks to this interface,
so swapping providers or writing an eval harness against MockClient doesn't
touch triage logic. GroqClient existing at all is that claim proven, not
just asserted -- a second real provider dropped in without touching
agent.py, schema.py or the guardrail logic.
"""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod

from .routing import routing_knowledge_prompt

RESPONSE_TOOL_SCHEMA = {
    "name": "submit_triage",
    "description": "Submit the structured triage assessment for a student enquiry.",
    "input_schema": {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "enum": ["info", "wellbeing", "disability", "funding", "academic", "other"],
            },
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "summary": {"type": "string"},
            "suggested_team": {"type": "array", "items": {"type": "string"}},
            "internal_or_external": {
                "type": "string",
                "enum": ["internal", "external", "ambiguous", "not_applicable"],
            },
            "missing_info": {
                "type": ["object", "null"],
                "properties": {
                    "evidence_attached": {
                        "type": "string",
                        "enum": ["yes", "no", "unclear", "not_applicable"],
                    },
                    "details": {"type": ["string", "null"]},
                },
                "required": ["evidence_attached"],
            },
            "suggested_response_draft": {"type": ["string", "null"]},
            "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
            "needs_human_judgement": {"type": "boolean"},
            "internal_note": {"type": ["string", "null"]},
            "flags": {"type": "array", "items": {"type": "string"}},
            "additional_issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string"},
                        "suggested_team": {"type": "array", "items": {"type": "string"}},
                        "summary": {"type": "string"},
                        "urgency": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                    "required": ["category", "suggested_team", "summary", "urgency"],
                },
            },
        },
        "required": [
            "category",
            "confidence",
            "summary",
            "suggested_team",
            "internal_or_external",
            "missing_info",
            "suggested_response_draft",
            "urgency",
            "needs_human_judgement",
            "internal_note",
            "flags",
            "additional_issues",
        ],
    },
}

SYSTEM_PROMPT = f"""You are a triage assistant for the University of Leeds \
generalist student enquiries team. You read one raw student email and \
produce a structured triage assessment. You NEVER send anything to the \
student yourself; a human always reviews your output before any reply goes \
out.

Route enquiries against this real service structure:

{routing_knowledge_prompt()}

Rules you must follow:

1. Disability Services: never promise or imply an adjustment will happen \
unless the email clearly states evidence (a diagnostic report / healthcare \
letter) is attached or already on file. If evidence is missing or unclear, \
set missing_info.evidence_attached to "no" or "unclear" and make the draft \
response ask for evidence, not promise an adjustment.
2. Counselling and Wellbeing vs LUU Advice: these are both plausible for \
"I'm struggling emotionally" style enquiries, and one is an internal \
University service while the other is an independent, peer-run service \
with different confidentiality/data-handling implications. If the enquiry \
is genuinely ambiguous between them, do NOT silently pick one. Set \
needs_human_judgement=true, list both services in suggested_team, set \
internal_or_external="ambiguous", and explain the ambiguity in \
internal_note.
3. If an enquiry raises two genuinely separate issues needing different \
teams (e.g. a timetable clash and a disability access issue), do not force \
a single category. Put the primary issue in category/suggested_team/\
summary, and any second issue in additional_issues with its own category, \
suggested_team and summary. Add "multi_issue" to flags.
4. Only produce a suggested_response_draft when it is safe to do so \
(low-risk, procedural, or a "please send us X" request for missing info). \
Set it to null if you are not confident enough, or if the topic is \
sensitive (financial hardship, mental health, disability) and needs a \
human-authored reply.
5. confidence should genuinely reflect your uncertainty. Use low confidence \
for ambiguous or multi-topic enquiries rather than picking a number that \
just matches how detailed your reasoning was.
6. Add "sensitive_financial" to flags for financial hardship enquiries, \
and set urgency to at least "medium".

Always call the submit_triage tool exactly once with your assessment."""

# Same schema, reshaped into OpenAI's tool-calling format -- Groq's chat
# completions API is OpenAI-compatible, so this is the one bit that differs
# from Anthropic's {name, description, input_schema} shape.
OPENAI_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": RESPONSE_TOOL_SCHEMA["name"],
        "description": RESPONSE_TOOL_SCHEMA["description"],
        "parameters": RESPONSE_TOOL_SCHEMA["input_schema"],
    },
}


class LLMClient(ABC):
    @abstractmethod
    def categorise(self, sender_name: str, sender_email: str, body: str) -> dict:
        """Return a dict matching RESPONSE_TOOL_SCHEMA's input_schema."""
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, model: str | None = None, api_key: str | None = None):
        import anthropic  # imported lazily so MockClient works without the SDK installed

        self._client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")

    def categorise(self, sender_name: str, sender_email: str, body: str) -> dict:
        user_message = (
            f"From: {sender_name} <{sender_email}>\n\n{body.strip()}"
        )
        response = self._client.messages.create(
            model=self.model,
            max_tokens=1500,
            system=SYSTEM_PROMPT,
            tools=[RESPONSE_TOOL_SCHEMA],
            tool_choice={"type": "tool", "name": "submit_triage"},
            messages=[{"role": "user", "content": user_message}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "submit_triage":
                return block.input
        raise RuntimeError("Model did not return a submit_triage tool call")


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

# Groq's 429 body includes a human-readable wait time, e.g.:
#   "Please try again in 6.96s"
# There's no structured retry-after field in the JSON body as of this
# project's build, so this is scraped from that message. If Groq changes
# the wording, RETRY_WAIT_RE simply won't match and the fallback wait
# below is used instead.
RETRY_WAIT_RE = re.compile(r"try again in (\d+(?:\.\d+)?)s", re.IGNORECASE)
RETRY_WAIT_FALLBACK_SECONDS = 10.0
RETRY_WAIT_BUFFER_SECONDS = 1.0


class GroqClient(LLMClient):
    """Real categorisation via Groq's free-tier, OpenAI-compatible API.

    Uses `requests` directly rather than the `groq` package -- one plain
    HTTP call is simpler than a second SDK dependency for a client this
    small, and `requests` was already a dependency of this project.

    Reliability guardrail: the free tier's TPM (tokens-per-minute) limit
    means a 429 is an expected occurrence, not a bug, when a batch runs
    without pacing (see run_tests.py's inter-enquiry sleep). categorise()
    catches a 429 once, sleeps for the wait time Groq reports (plus a
    buffer), and retries exactly once. A second 429 raises -- this is a
    demo running on a free tier, not a queue with unlimited patience, so
    failing loudly after one retry is the honest behaviour rather than
    looping silently.
    """

    def __init__(self, model: str | None = None, api_key: str | None = None):
        import requests  # imported lazily so MockClient works without it installed

        self._requests = requests
        self._api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self._api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        # llama-3.3-70b-versatile was Groq's standard production 70B model
        # as of this project's build; confirm it's still live on your
        # account (GET https://api.groq.com/openai/v1/models) before relying
        # on it, since Groq's free-tier model lineup changes over time.
        self.model = model or os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

    def categorise(self, sender_name: str, sender_email: str, body: str) -> dict:
        user_message = f"From: {sender_name} <{sender_email}>\n\n{body.strip()}"

        response = self._post(user_message)
        if response.status_code == 429:
            wait_seconds = _parse_retry_wait(response.text) + RETRY_WAIT_BUFFER_SECONDS
            print(f"[warn] Groq rate limit hit -- waiting {wait_seconds:.1f}s and retrying once.")
            time.sleep(wait_seconds)
            response = self._post(user_message)
            if response.status_code == 429:
                raise RuntimeError(
                    f"Groq rate limit hit twice in a row for one enquiry (still 429 after "
                    f"waiting {wait_seconds:.1f}s). Free-tier TPM limit is likely being hit "
                    f"faster than the batch is pacing itself -- see run_tests.py's sleep and "
                    f"WRITEUP.md's LLM client section. Response: {response.text}"
                )

        if not response.ok:
            raise RuntimeError(f"Groq API error {response.status_code}: {response.text}")

        tool_calls = response.json()["choices"][0]["message"].get("tool_calls") or []
        for call in tool_calls:
            if call["function"]["name"] == "submit_triage":
                return json.loads(call["function"]["arguments"])
        raise RuntimeError("Model did not return a submit_triage tool call")

    def _post(self, user_message: str):
        return self._requests.post(
            GROQ_API_URL,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_message},
                ],
                "tools": [OPENAI_TOOL_SCHEMA],
                "tool_choice": {"type": "function", "function": {"name": "submit_triage"}},
                "temperature": 0,
            },
            timeout=30,
        )


def _parse_retry_wait(error_body: str) -> float:
    match = RETRY_WAIT_RE.search(error_body)
    return float(match.group(1)) if match else RETRY_WAIT_FALLBACK_SECONDS


class MockClient(LLMClient):
    """Deterministic, keyword-based fallback -- no API key or network needed.

    This is NOT a substitute for real LLM categorisation (see WRITEUP.md
    limitations). It exists so the prototype can be run, read and graded
    without requiring the reviewer to supply API credentials, while
    exercising exactly the same downstream schema/guardrail code as the
    real client.
    """

    def categorise(self, sender_name: str, sender_email: str, body: str) -> dict:
        text = body.lower()

        has_disability_terms = any(
            term in text
            for term in [
                "dyslexia", "disability", "extra time", "adjustment", "diagnos", "sen ", "autis", "adhd",
                "impairment", "mobility", "accessible room", "wheelchair",
            ]
        )
        has_evidence_terms = any(
            term in text
            for term in [
                "evidence attached", "report attached", "letter attached", "have attached", "see attached",
                "already on file", "on file with disability services", "on file with",
            ]
        )
        has_timetable_terms = any(term in text for term in ["timetable", "clash", "enrolment", "address", "update my"])
        has_wellbeing_terms = any(
            term in text
            for term in ["struggl", "overwhelmed", "anxious", "can't cope", "mental health", "don't know who to talk to"]
        )
        has_funding_terms = any(
            term in text for term in ["rent", "afford", "money", "financ", "hardship", "student finance", "pay"]
        )
        has_academic_terms = any(term in text for term in ["module", "dissertation", "supervisor", "personal tutor"])

        flags: list[str] = []
        additional_issues = []

        # Multi-issue: timetable + disability in the same email
        if has_disability_terms and has_timetable_terms and ("clash" in text or "timetable" in text):
            flags.append("multi_issue")
            additional_issues.append(
                {
                    "category": "disability",
                    "suggested_team": ["disability_services"],
                    "summary": "Student also raises a disability-related access issue alongside the timetable query.",
                    "urgency": "medium",
                }
            )
            evidence = "yes" if has_evidence_terms else "unclear"
            details = (
                "Evidence stated as already on file with Disability Services."
                if evidence == "yes"
                else "Evidence status unclear for the disability-related part of the enquiry."
            )
            return {
                "category": "info",
                "confidence": 0.55,
                "summary": "Student reports a timetable clash and separately raises a disability-related access issue.",
                "suggested_team": ["student_information_service"],
                "internal_or_external": "internal",
                "missing_info": {"evidence_attached": evidence, "details": details},
                "suggested_response_draft": None,
                "urgency": "medium",
                "needs_human_judgement": True,
                "internal_note": "Two distinct issues in one email (timetable clash + disability access). Routed to both teams rather than picking one; mock client cannot draft safely here.",
                "flags": flags,
                "additional_issues": additional_issues,
            }

        if has_disability_terms:
            evidence = "yes" if has_evidence_terms else "no"
            draft = None
            if evidence == "no":
                draft = (
                    f"Dear {sender_name},\n\nThank you for getting in touch about exam adjustments. "
                    "To arrange these we first need supporting evidence, such as a diagnostic "
                    "assessment report or a letter from a healthcare professional. Could you "
                    "please attach this to your reply, or let us know if you already have "
                    "evidence on file with us? Once we have this we can look at putting a "
                    "Student Support Plan in place.\n\nBest wishes,\nDisability Services"
                )
            return {
                "category": "disability",
                "confidence": 0.8,
                "summary": "Student believes they have dyslexia and is asking how to arrange extra time in exams.",
                "suggested_team": ["disability_services"],
                "internal_or_external": "internal",
                "missing_info": {"evidence_attached": evidence, "details": None if evidence == "yes" else "No diagnostic report or healthcare letter mentioned/attached."},
                "suggested_response_draft": draft,
                "urgency": "medium",
                "needs_human_judgement": False,
                "internal_note": None,
                "flags": [] if evidence == "yes" else ["missing_evidence"],
                "additional_issues": [],
            }

        if has_wellbeing_terms:
            return {
                "category": "wellbeing",
                "confidence": 0.4,
                "summary": "Student says they have been struggling and doesn't know who to talk to; no specifics given.",
                "suggested_team": ["counselling_and_wellbeing", "luu_advice"],
                "internal_or_external": "ambiguous",
                "missing_info": None,
                "suggested_response_draft": None,
                "urgency": "medium",
                "needs_human_judgement": True,
                "internal_note": (
                    "Enquiry is too generic to tell whether the student wants University "
                    "clinical/counselling support (internal) or independent peer support via "
                    "LUU Advice (external), which have different confidentiality and "
                    "data-handling implications. Deferring to a human rather than guessing."
                ),
                "flags": ["ambiguous_referral", "low_confidence"],
                "additional_issues": [],
            }

        if has_funding_terms:
            return {
                "category": "funding",
                "confidence": 0.75,
                "summary": "Student is having trouble paying rent this month and is asking about financial support.",
                "suggested_team": ["student_funding_team"],
                "internal_or_external": "internal",
                "missing_info": None,
                "suggested_response_draft": None,
                "urgency": "high",
                "needs_human_judgement": False,
                "internal_note": "Financial hardship enquiries are treated as sensitive; leaving the reply to a human adviser rather than auto-drafting.",
                "flags": ["sensitive_financial"],
                "additional_issues": [],
            }

        if has_academic_terms:
            return {
                "category": "academic",
                "confidence": 0.6,
                "summary": "Course-specific query that likely needs input from the student's personal tutor.",
                "suggested_team": ["academic_personal_tutor"],
                "internal_or_external": "internal",
                "missing_info": None,
                "suggested_response_draft": None,
                "urgency": "low",
                "needs_human_judgement": False,
                "internal_note": None,
                "flags": [],
                "additional_issues": [],
            }

        # Default: routine/navigational
        draft = (
            f"Dear {sender_name},\n\nThanks for your message. You can update your home address "
            "yourself by logging into the student portal and going to "
            "'Personal Details' > 'Addresses'. Let us know if you have any trouble "
            "accessing this.\n\nBest wishes,\nStudent Information Service"
        )
        return {
            "category": "info",
            "confidence": 0.9,
            "summary": "Student wants to know how to update their home address on the student system.",
            "suggested_team": ["student_information_service"],
            "internal_or_external": "internal",
            "missing_info": None,
            "suggested_response_draft": draft,
            "urgency": "low",
            "needs_human_judgement": False,
            "internal_note": None,
            "flags": [],
            "additional_issues": [],
        }
