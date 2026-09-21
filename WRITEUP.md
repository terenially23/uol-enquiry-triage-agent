# Write-up: Student Enquiry Triage Agent

## The routing structure

Six real Leeds services, modelled with their actual constraints rather than
generic labels (`triage_agent/routing.py`):

| Service | Internal/External | Special handling |
|---|---|---|
| Student Information Service | Internal | First-line, safe to auto-draft procedural replies |
| Disability Services | Internal | **Never** promise an adjustment without confirmed evidence |
| Student Counselling and Wellbeing | Internal | Ambiguous vs LUU for generic "struggling" enquiries |
| LUU Advice | **External** (Students' Union, not the University) | Different confidentiality/data-handling to Counselling |
| Student Funding Team | Internal | Financially sensitive, never auto-draft |
| Academic Personal Tutor | Internal | Needs a named tutor, not draftable generically |

## The schema, and why it isn't a flat "one category per enquiry" shape

Starting from the brief's field list, I changed/added a few things:

- **`suggested_team` is a list, not a string.** Enquiry 5 (timetable clash +
  disability access) needs two teams. A single string field forces the
  agent to either drop one issue or invent a category — both are worse
  than a list.
- **Added `additional_issues`**: a list of `{category, suggested_team,
  summary, urgency}`. This is the mechanism for "don't force a single
  category" from the brief — the primary issue stays in the top-level
  fields (so simple, single-issue enquiries — the majority — stay simple
  to read), and any genuinely separate second issue gets its own mini
  routing decision rather than being mashed into one summary.
- **Added `needs_human_judgement` (bool) and `internal_note` (string)**,
  distinct from `confidence`. The brief specifically asks for the
  Counselling-vs-LUU ambiguity to be *surfaced*, not just scored low. A
  confidence number alone conflates "the topic is inherently ambiguous"
  with "the model wasn't sure" — those need different human follow-up. The
  explicit flag plus a short internal note (never shown to the student) is
  a more honest signal than a single float.
- **Added `flags` (list of short strings)**: `missing_evidence`,
  `ambiguous_referral`, `sensitive_financial`, `multi_issue`,
  `low_confidence`. Free-form but constrained in practice by what the
  guardrail code emits, so a reviewer scanning a queue can filter/sort on
  them without parsing prose.
- **`requires_human_review` stays a field, not just a convention.** It's
  hard-set to `True` in `agent.py` *after* the LLM call, regardless of
  what the model returns, specifically so this can't be prompt-drifted
  away later.
- **Kept `missing_info` as a small object** (`evidence_attached`,
  `details`) rather than a bare enum, so the "what's actually missing"
  detail travels with the yes/no/unclear flag instead of living only in
  free text.

## What the guardrail layer does (and why it's not just prompting)

`agent.py` runs three checks after every LLM response, independent of what
the model says:

1. **Never a disability draft without confirmed evidence.** If
   `evidence_attached != "yes"`, any draft that reads like a promise
   (`"we will arrange..."`, `"this has been arranged"`) is discarded.
2. **Confidence threshold (0.6).** Below it, `suggested_response_draft` is
   cleared and `needs_human_judgement` is forced `True`, whatever the model
   drafted. This is the concrete answer to "what would you do to catch a
   plausible misclassification" (see below).
3. **Ambiguous internal/external routing never carries a draft.** The
   Counselling-vs-LUU case specifically, because the two options have
   different data-handling implications and a wrong auto-reply there is
   worse than a wrong auto-reply on a timetable query.

This split matters for the interview: prompting can ask a model to behave
this way, and mostly it will — but "mostly" isn't good enough for the two
things in the brief marked as hard constraints. Guardrail code that runs
regardless of model output is the actual enforcement mechanism; the prompt
is a hint, the code after it is the constraint.

## Test results (5/5 sample enquiries, `outputs/results.json`)

1. **Routine address change** → `info`, confidence 0.90, auto-draftable.
   Matches expectation.
2. **Dyslexia, no evidence mentioned** → `disability`, evidence flagged
   `no`, draft asks for evidence rather than promising extra time. Matches
   expectation.
3. **"I've been struggling..."** → confidence 0.40 (below threshold),
   `needs_human_judgement=True`, `internal_or_external="ambiguous"`,
   routed to *both* Counselling and LUU with an internal note explaining
   why, no auto-draft. Matches expectation.
4. **Rent / financial hardship** → `funding`, confidence 0.75, urgency
   `high`, flagged `sensitive_financial`, no auto-draft (financial replies
   are treated as always needing a human-authored response, not just a
   confidence call). Matches expectation.
5. **Timetable clash + disability access in one email** → primary category
   `info` (timetable), `additional_issues` carries the disability access
   issue with its own team/urgency, `flags=["multi_issue", ...]`, no
   auto-draft. Matches expectation — the two issues are visibly split
   rather than the agent picking one.

Run `python3 scripts/run_tests.py` to reproduce; it prints raw enquiry text
next to the structured output for each case and writes the full JSON.

## Where it plausibly gets categorisation wrong

The most likely failure mode isn't the disability or ambiguous-wellbeing
cases (those have unambiguous trigger phrases) — it's a **worded-differently
funding-vs-wellbeing overlap**: e.g. *"I'm so stressed about money I can't
sleep, I don't know what to do."* This genuinely straddles Student Funding
(the practical problem) and Counselling/LUU (the emotional impact), and
unlike the enquiry-3 case, the ambiguity isn't a single well-known
either/or — it's "which is primary," which is a harder judgement call and
one the routing knowledge base doesn't explicitly model. A model could
confidently pick `funding` and miss that the student also needs a wellbeing
signpost, or vice versa, without the confidence score dropping enough to
trip the 0.6 threshold.

**What I'd do about it:**

- The confidence threshold is a blunt instrument — it only catches cases
  where the model *reports* low confidence, not cases where it's
  confidently wrong. The stronger mitigation already in this prototype is
  structural: raw enquiry text is always shown next to the structured
  output (see `run_tests.py`'s `print_row`), so a human reviewing a queue
  can spot-check without re-reading a separate source. That's a UI/process
  decision, not a model one, and it's the one that actually catches
  confident mistakes.
- Longer term: a small labelled eval set (50-100 real, anonymised past
  enquiries) would let me measure precision/recall per category instead of
  eyeballing 5 hand-picked examples, and specifically test category
  *pairs* that are prone to overlap (funding/wellbeing, disability/academic)
  rather than assuming the single-topic accuracy generalises.
- A cheap structural mitigation I'd add next: treat "financial AND
  emotional language both present" as its own trigger for
  `additional_issues`/`needs_human_judgement`, the same way multi-issue
  detection already works for the timetable+disability case — right now
  that pattern only exists for the specific case in the brief, not
  generalised.

## What this prototype does NOT do

Explicit scope cuts, because a 60-minute prototype should be honest about
them rather than implying more maturity than it has:

- **No real identity/authentication.** Sender name/email is taken at face
  value from the "signature" — there's no verification this is really the
  named student, no student-record lookup, no de-duplication of enquiry
  threads.
- **No evaluation set.** The 5 sample enquiries are the brief's own
  examples, hand-picked to be illustrative, not a statistically meaningful
  test of categorisation accuracy. See above.
- **No ingested Leeds guidance/policy documents.** `routing.py` is a small
  hand-written knowledge base of team names and one-line descriptions, not
  RAG over actual University web pages, so any specific procedural detail
  in a draft response (portal navigation steps, exact evidence
  requirements) is illustrative, not verified against current guidance.
- **No ticketing/CRM integration.** Output is a JSON file a human reads;
  there's no queue, no assignment, no SLA tracking, no way to mark an
  enquiry "actioned."
- **No conversation/thread memory.** Each enquiry is triaged independently;
  a follow-up email from the same student ("here's the evidence you asked
  for") would be triaged fresh rather than linked to the original.
- **No PII handling policy.** Enquiry text may contain sensitive data
  (health information, financial hardship details) and this prototype
  doesn't do anything special with storage, retention, or access control
  for `outputs/results.json` beyond it being a local file.
- **No send path at all**, by design (`requires_human_review` is hard-set
  `True`) — this is a drafting/triage aid, not an autoresponder, and
  nothing in this codebase sends email.
- **Mock fallback is not a categoriser.** `MockClient` is keyword matching
  used only so the prototype runs without API credentials; it's a testing
  convenience, not evidence the approach works without an LLM.
