# Write-up: Student Enquiry Triage Agent

## Sources

Every routing category and the two guardrail-driving facts below are
grounded in these pages. Where a page's content wasn't available to cite
directly, that's stated rather than left implicit.

| URL | What it grounds |
|---|---|
| [eps.leeds.ac.uk/electronic-engineering/doc/contact-us-5](https://eps.leeds.ac.uk/electronic-engineering/doc/contact-us-5) | Student Information Service as a first-line, signposting contact point ("we can put you in touch with the right people if more specialist support or advice is needed") |
| [students.leeds.ac.uk/](https://students.leeds.ac.uk/) (the actual redirect target of the `ses.leeds.ac.uk/download/downloads/id/1610/...` URL) | LUU's help being "completely independent of the University"; general overview of disabled-student support |
| [leeds.ac.uk/undergraduate-offer/doc/wellbeing-and-support](https://leeds.ac.uk/undergraduate-offer/doc/wellbeing-and-support) | **Not retrieved in this session** — listed in the original brief but no page content was available to cite from it; nothing in this repo is attributed to it |
| [www.leeds.ac.uk/studentsupport](https://www.leeds.ac.uk/studentsupport) | LUU's advice described as "free, confidential and independent"; Counselling/wellbeing support listed as a University service with no independence claim; Academic Personal Tutor as an assigned contact |
| [students.leeds.ac.uk/support-disabled-students](https://students.leeds.ac.uk/support-disabled-students) | Disability Services requiring registration + "supporting information about your disability" before support is arranged (added mid-build once the original 4 pages turned out not to cover this fact — see `guidance/disability_evidence.md`) |

Two facts get a **verbatim, cited excerpt** wired into the agent's output
(not just described in this write-up) — see `guidance/`:

- `guidance/disability_evidence.md` — the registration/evidence requirement.
- `guidance/luu_vs_counselling_independence.md` — the LUU-independent vs
  Counselling-University-service contrast.

Both files carry an explicit "Honesty note" flagging anywhere this
project's phrasing (e.g. "diagnostic report/healthcare letter",
"University-run") goes slightly beyond the source's literal wording, and
what's actually verbatim vs. this project's reasonable gloss.

## The routing structure

Seven real Leeds services, modelled with their actual constraints rather
than generic labels (`triage_agent/routing.py`):

| Service | Internal/External | Special handling |
|---|---|---|
| Student Information Service | Internal | First-line, safe to auto-draft procedural replies |
| Disability Services | Internal | **Never** promise an adjustment without confirmed evidence |
| Student Counselling and Wellbeing | Internal | Ambiguous vs LUU for generic "struggling" enquiries |
| LUU Advice | **External** (Students' Union, not the University) | Different confidentiality/data-handling to Counselling |
| Student Funding Team | Internal | Financially sensitive, never auto-draft |
| Academic Personal Tutor | Internal | Needs a named tutor, not draftable generically |
| IT Helpdesk / Online Learning Support | Internal | Added later — see below. Often time-sensitive (deadlines), but safe to auto-draft generic self-service steps |

**IT Helpdesk / Online Learning Support was not in the original 6.** It was
added specifically to close a gap the brief itself flags: the brief's own
routing structure lists example categories including "access to online
learning," but none of the original 6 teams actually cover account/VLE
access issues (Minerva logins, password resets, locked accounts). Routing
one of those enquiries into, say, Student Information Service would have
been a wrong-but-plausible-looking guess. This team doesn't map to any
existing schema `category` value (`info`/`wellbeing`/`disability`/
`funding`/`academic`/`other`) — it uses `category: "other"` with
`suggested_team: ["it_helpdesk"]` and an `internal_note` saying so
explicitly, rather than silently forcing it into `info` just because it's
navigational-ish. See enquiry 6 in "Test results" below.

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

## LLM client: three implementations behind one interface

`triage_agent/llm_client.py` defines one `LLMClient` abstract interface
(`categorise(sender_name, sender_email, body) -> dict`) with three
implementations: `AnthropicClient`, `GroqClient`, and `MockClient`.
`agent.py` only ever talks to that interface.

**This demo actually runs on `GroqClient`, against Groq's free tier**
(`llama-3.3-70b-versatile`), not the Claude API — a deliberate,
cost-conscious swap for a self-funded interview prototype rather than
spending Anthropic API credits on an 8-enquiry demo. It's included here
specifically because it's a better argument for the abstraction than
another paragraph would be: the interface was designed assuming a second
provider might show up eventually, and when one actually did, `agent.py`,
`schema.py`, and every guardrail were untouched — only `llm_client.py`
grew a third class and `client_selection.py` grew a priority check.
`GroqClient` forces the same JSON-schema tool call as `AnthropicClient`
(Groq's chat completions API is OpenAI-compatible and supports the same
tool-calling shape, just wrapped as `{"type": "function", "function":
{...}}` instead of Anthropic's `{"type": "tool", "name": ...}`), so the
guardrail path downstream — evidence checks, confidence threshold,
citation lookup — runs identically regardless of which provider answered.

Client selection (`triage_agent/client_selection.py`, used by both
`run_tests.py` and `try_one.py`): **`GROQ_API_KEY`** first if set, else
**`ANTHROPIC_API_KEY`**, else `MockClient`. Groq is checked first because
it's what this demo is actually configured to use.

**Known constraint of the free tier: an 8,000 tokens/minute limit.** Firing
the sample enquiries at Groq back-to-back reliably 429s later in the
batch, regardless of which Groq model is used — this is a genuine
free-tier ceiling, not a bug in this project's prompt or schema size. Two
guardrails address it, one preventive and one a safety net:

- **Paced batch loop** (`run_tests.py`, `scripts/evaluate.py`):
  `INTER_ENQUIRY_SLEEP_SECONDS = 15` between enquiries, skipped entirely
  for `MockClient` (no API calls, no need to slow down). This is the
  actual fix — spacing calls 15s apart keeps the batch comfortably under
  the TPM ceiling instead of bursting it, and is the cheap, honest way to
  work within a free tier rather than disguising the constraint. The
  sample set grew from 5 to 8 enquiries without needing to change this —
  it just means a real-provider run takes ~30s longer
  (`evaluate.py`'s 8-enquiry batch is ~1:45 end to end on Groq, vs.
  `run_tests.py`'s original 5-enquiry ~1:00).
- **429 retry/backoff, as a reliability guardrail, not the primary fix**
  (`GroqClient.categorise`): if a 429 still happens, it parses the wait
  time Groq reports in the error body (`"Please try again in 6.96s"`, via
  `RETRY_WAIT_RE`; a fixed 10s fallback if that wording ever changes and
  the regex stops matching), sleeps that plus a 1s buffer, and retries
  exactly once. A second consecutive 429 raises a `RuntimeError` naming
  the free-tier TPM limit as the likely cause, rather than retrying
  forever — the same philosophy as the other guardrails in this project:
  fail loudly and specifically, don't paper over an unresolved state.
  This is a safety net for a rate-limit spike the fixed pacing didn't
  fully prevent (e.g. a longer draft pushing one call over the edge), not
  a substitute for pacing the batch in the first place.

This is worth being upfront about in interview: a paid tier or a smaller/
cheaper model would make both of these unnecessary in practice, and a real
production system would use a proper queue with backoff (see
"Scalability" below) rather than a fixed sleep in a batch script. Both
exist here because the actual constraint driving this demo is "run it for
free," and the honest response to a rate limit is to pace around it
and retry it, not silently swallow the failure.

## What the guardrail layer does (and why it's not just prompting)

`agent.py` runs four checks after every LLM response, independent of what
the model says:

1. **Never a disability draft without confirmed evidence.** If
   `evidence_attached != "yes"`, `suggested_response_draft` is
   unconditionally overwritten with a fixed, code-generated evidence-request
   template (`_evidence_request_draft()`), not left to whatever the model
   wrote. **This was a real bug, caught on a live Groq run, not a
   hypothetical**, and it went through two fix attempts before landing
   here:
   - *v1 (original):* only cleared the draft if its wording matched one of
     five hardcoded phrases (`"we will arrange..."`, `"this has been
     arranged"`, etc.) via a `_looks_like_a_promise()` helper. A real
     model drafted a differently worded promise ("your seminar room is
     being moved...") that matched none of them and went straight
     through — while `missing_info` correctly said `evidence_attached:
     unclear` in the same output. Two guardrails disagreeing with each
     other in a single result is a bug, not a corner case.
   - *v2 (first fix, briefly live):* unconditionally nulled the draft
     whenever evidence wasn't confirmed. This closed the promise leak but
     over-corrected: it also nulled the *legitimate* case the brief
     explicitly asks for (enquiry 2 — a draft that asks for evidence
     rather than promising an adjustment), which `MockClient` and the
     system prompt already produced correctly most of the time. Caught
     before it shipped, by re-running the full batch and checking enquiry
     2 against the brief's own stated expectation.
   - *v3 (current):* since the real failure mode is "can't trust the
     model's wording to be safe," the fix stops trusting it for this one
     piece of text — evidence-not-confirmed always gets the same
     code-generated, deterministic evidence-request draft, regardless of
     what (if anything) the model drafted. Guarantees both properties at
     once: never a promise, and always a usable, safe draft rather than a
     silent "deferred to human."
2. **Financially sensitive enquiries never carry a draft.** If
   `category == "funding"` or `"sensitive_financial"` is in `flags`,
   `suggested_response_draft` is unconditionally cleared. **Also a real
   bug, also caught on a live run:** this suppression previously existed
   only as system-prompt rule 4 ("set it to null if... sensitive"), with
   no corresponding code guardrail — `MockClient` hardcoded `None` for its
   funding branch, which made offline runs look consistent, but a real LLM
   call was free to draft one anyway whenever it judged confidence high
   enough to ignore that instruction. That's why the same enquiry
   suppressed its draft in one Groq run and drafted one in the next: there
   was nothing in code enforcing it either way.
3. **Confidence threshold (0.6).** Below it, `suggested_response_draft` is
   cleared and `needs_human_judgement` is forced `True`, whatever the model
   drafted. This is the concrete answer to "what would you do to catch a
   plausible misclassification" (see below).
4. **Ambiguous internal/external routing never carries a draft.** The
   Counselling-vs-LUU case specifically, because the two options have
   different data-handling implications and a wrong auto-reply there is
   worse than a wrong auto-reply on a timetable query.
5. **Multi-issue enquiries never carry a draft.** If `additional_issues`
   is non-empty or `"multi_issue"` is in `flags`, `suggested_response_draft`
   is unconditionally cleared, regardless of confidence. **Also found as a
   gap during testing, not designed in from the start** — same pattern as
   the funding guardrail above. ENQ-005's null draft looked correct in
   every run, but for the wrong reason: it was only null because its
   confidence (0.55) happened to also trip the *confidence* guardrail.
   Nothing checked for multi-issue enquiries specifically. A multi-issue
   result at confidence ≥ 0.6 would have sailed through with a single
   draft that addresses only the primary category and says nothing about
   whatever's in `additional_issues` — a single draft can't safely
   represent two independently-routed issues, so this needed to be its own
   check, not a side effect of a different one. Caught by asking "is this
   guardrail deliberate or incidental?" and checking the code rather than
   the output, then confirmed with a unit test that isolates it: a
   multi-issue result constructed at confidence=0.9 specifically, so the
   confidence guardrail provably doesn't fire, and the draft is still
   cleared (`tests/test_guardrails.py::TestMultiIssueGuardrail`).

The lesson from 1, 2, and 5, worth saying plainly in interview: a
guardrail that's conditional on the *shape* of the model's output
(phrasing, an instruction the model may or may not follow, or another
guardrail's unrelated threshold happening to also catch it) isn't really a
guardrail — it's a coin flip that happens to land right most of the time.
Every fix here was the same move: gate on a structured field the code
already controls (`evidence_attached`, `category`, `flags`,
`additional_issues`) instead of on free text or on borrowing another
check's side effect.

## Testing the guardrails directly

`tests/test_guardrails.py` (`python3 -m unittest discover -s tests`) unit-
tests `_apply_guardrails` in isolation via a `StubClient` that returns a
fixed payload, rather than going through a real or mock LLM call. Each
test is a regression test for a specific bug found in this project, not a
general "does it work" check — the point is that every one of them
reproduces the exact shape of output that previously slipped through
(a differently worded promise, high confidence masking a missing check,
a model ignoring a prompt-only instruction) and asserts the guardrail
catches it. This is deliberately separate from `run_tests.py`/`try_one.py`,
which exercise the full pipeline including the LLM call and are for
demonstrating and spot-checking behaviour, not for pinning down exactly
which guardrail is responsible for a given null draft.

This split matters for the interview: prompting can ask a model to behave
this way, and mostly it will — but "mostly" isn't good enough for the two
things in the brief marked as hard constraints. Guardrail code that runs
regardless of model output is the actual enforcement mechanism; the prompt
is a hint, the code after it is the constraint.

## Citing sources in the output: `source_citation`

The **`source_citation`** field on `TriageResult` carries the grounded
citation. It is populated by `guidance/retrieve.py`'s `citation_for()`,
called from `agent.py`'s guardrail step — deterministically, in Python,
*after* the LLM call, the same way `requires_human_review` is. The LLM
never generates the citation text; it can't, because it never sees
`guidance/retrieve.py`. This matters for the same reason the other
guardrails run in code: an LLM asked to "cite your source" will sometimes
paraphrase or invent a plausible-looking one, and a wrong citation on a
disability-evidence claim is worse than no citation.

Trigger conditions (see `citation_for`): `category == "disability"` →
the evidence-requirement excerpt; `internal_or_external == "ambiguous"` →
the LUU-independence excerpt. Everything else gets `source_citation: null`
— most enquiries (a routine address change, a funding query) don't touch
either grounded fact, and a null is more honest than attaching a citation
that isn't actually relevant.

**Known limitation of this wiring:** the citation only looks at the
top-level `category`/`internal_or_external`, not `additional_issues`. In
enquiry 5 (timetable + disability access), the disability issue lands in
`additional_issues` with the top-level category staying `info`, so no
citation is attached even though the disability fact is relevant to the
secondary issue. Fixing this properly means running `citation_for` per
issue, not just once per result — left out here because it's a small,
clearly-scoped prototype, but it's the first thing I'd fix if multi-issue
enquiries turned out to be common.

## Test results (8/8 sample enquiries, `outputs/results.json`)

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
   rather than the agent picking one. The no-auto-draft here is now the
   dedicated multi-issue guardrail (#5 above), not a side effect of this
   enquiry's confidence also being low — see that section for why the
   distinction matters.
6. **Minerva/VLE account locked, assignment due Friday** → new `it_helpdesk`
   team (see "The routing structure" — added because the brief explicitly
   names "access to online learning" as an illustrative example and
   nothing in the original 6 teams covered it), category `other` (no
   category in the schema maps cleanly to IT/account-access — see
   `internal_note`), confidence 0.85, urgency `high` (deadline pressure),
   safe auto-draft (generic self-service password-reset steps + escalation
   to IT Helpdesk, nothing sensitive or promised). Matches expectation.
7. **Library opening hours during exam period** → `info`, confidence 0.90,
   safe auto-draft, no flags — a second, independent routine/navigational
   case in a different domain from enquiry 1, to check that "safe to
   auto-draft" isn't just correct for address changes specifically.
   Matches expectation.
8. **Disputed essay mark** → deliberately the "nothing fits well" test
   case. Category `other`, confidence 0.35 (below threshold),
   `needs_human_judgement=True`, `suggested_team=[]` (empty, not a guess),
   no auto-draft, and an `internal_note` stating plainly that a mark
   dispute is an academic-judgement matter this tool has no grounded
   knowledge of the formal appeals process for, rather than confidently
   guessing `academic_personal_tutor` because the topic is loosely
   course-related. Matches expectation — the honest failure mode is an
   admitted "I don't know," not a wrong confident answer.

Run `python3 scripts/run_tests.py` to reproduce; it prints raw enquiry text
next to the structured output for each case and writes the full JSON.

## Evaluation

`scripts/evaluate.py` scores the agent against a hand-written answer key
instead of just printing output for a human to eyeball. It's deliberately
a **deterministic, exact-match evaluation against a small labelled set**,
not an LLM-graded/fuzzy eval — with 8 enquiries the whole answer key fits
on a screen, and every number it prints is checkable by hand: open
`data/sample_enquiries.json`, read the `expected_*` value, read the
actual output, done. That property (hand-defensible, not "trust the
grading model") mattered more here than scale, given the interview
context.

**Answer key fields**, on each enquiry in `data/sample_enquiries.json`,
starting as `null` (unfilled) and filled in by hand, not auto-generated
from the agent's own output — scoring an agent against its own answers
would be circular:

- `expected_category` — exact string match against `category`.
- `expected_team` — set match against `suggested_team` (order-independent).
- `expected_flags` — set match against `flags` (order-independent; `[]`
  is a valid, fillable expectation — only `null` means "not filled in
  yet," so a genuinely empty expected-flags list still gets scored).
- `expected_needs_human_judgement` — exact boolean match (same `null` vs.
  `false` distinction as above).

**A `null` field is skipped for scoring, not counted wrong.** This makes
the script safe to run at any point while the answer key is being filled
in — it reports fewer scored fields rather than failing or reporting false
negatives, and the denominator for a field only grows as that field gets
filled in across enquiries.

**Final scorecard**, answer key filled in by hand (not auto-generated from
this project's own prior "matches expectation" claims in "Test results"
above — an agent grading itself against its own author's assumptions
would hide exactly the kind of blind spot that produced the two guardrail
bugs found earlier in this project's history):

```
category                : 8/8 correct
team                     : 8/8 correct
flags                    : 8/8 correct
needs_human_judgement    : 8/8 correct

No mismatches on any scored field.
```

**The first real run wasn't 8/8 — it was 5/8 on `flags`,** and that's the
more useful thing to be able to say in interview than the clean final
number. `ENQ-003`, `ENQ-005`, and `ENQ-008` each initially had an answer
key entry naming only one of the two flags the code actually (and
correctly) produces — e.g. `ENQ-005`'s answer key said `["multi_issue"]`
but the code also correctly appends `low_confidence` (its confidence is
0.55, below the 0.6 threshold, an entirely separate guardrail). All three
were **answer-key gaps, not code bugs**: verified by checking each extra
flag against the specific guardrail or `MockClient` branch producing it,
then deciding by hand whether it belonged in the answer key
(`ambiguous_referral`+`low_confidence`, `multi_issue`+`low_confidence`,
`low_confidence`+`out_of_scope` — all correct, kept as-is; `evaluate.py`'s
exact-set flag matching was deliberately left as-is rather than loosened,
since a future *unexpected* extra flag is exactly the kind of regression
exact matching exists to catch). This is the eval doing its job on itself
before touching a single enquiry from real traffic — catching an
incomplete answer key is a legitimate, useful failure mode of a labelled
eval, not a sign the eval is broken.

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
- Longer term: `scripts/evaluate.py` now exists as the mechanism, but the
  set behind it is still 8 hand-picked enquiries. Growing it to 50-100
  real, anonymised past enquiries would let me measure precision/recall
  per category properly instead of eyeballing a small hand-picked set,
  and specifically test category *pairs* that are prone to overlap
  (funding/wellbeing, disability/academic, and now IT-access/info) rather
  than assuming the single-topic accuracy generalises.
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
- **Evaluation set is small and hand-picked, not statistically meaningful.**
  `scripts/evaluate.py` scores the agent against a hand-written answer key
  (see "Evaluation" below) — this closes the *mechanism* gap (there is now
  a real, deterministic, defensible scoring script, not just eyeballed
  output), but 8 enquiries covering 7 categories/teams is nowhere near
  enough to claim statistically meaningful accuracy. It tells you the
  happy path and a handful of known-hard cases work; it says nothing about
  the real distribution of enquiries a live inbox would produce, or about
  categories/phrasings this set doesn't happen to cover.
- **No real retrieval/RAG system.** `guidance/` grounds exactly two facts
  (disability evidence requirement, LUU independence) as hand-picked,
  hard-coded excerpts looked up by a Python `if`, not embeddings or search
  over actual University guidance. `routing.py`'s team descriptions beyond
  those two facts are still an illustrative, hand-written knowledge base,
  not verified against current Leeds documentation page by page. See
  "Scalability" below for what a real version needs.
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

## Scalability: what breaks first, and what I'd change

This is a script, not a service. Honestly, in order of what would break
first at real volume:

1. **Grounding stops at two facts.** `guidance/` has exactly two hand-picked,
   hard-coded excerpts (disability evidence, LUU independence). Every other
   claim the agent makes — portal navigation steps in a draft, "five
   information points on campus," specific team email addresses — is either
   from the LLM's general knowledge or this project's own `routing.py`
   descriptions, not verified against live Leeds guidance. At volume, this
   is the highest-risk gap: a confidently-worded wrong procedural detail in
   an auto-draft is a worse failure than a low-confidence flag.
   → **Fix:** a real retrieval layer (embeddings + a vector store, or even
   just a maintained, versioned set of scraped/curated Leeds guidance
   pages with a proper crawler and re-index job) so every factual claim in
   a draft is retrieved and citable, not just the two facts this prototype
   covers.

2. **Synchronous, single LLM call, no retry/queueing.** `agent.triage()` is
   one blocking API call. A transient API error, rate limit, or timeout
   currently just raises and kills the run. There's no retry, no backoff,
   no dead-letter handling for enquiries that fail categorisation twice.
   → **Fix:** an async task queue (e.g. Celery/RQ over Redis, or a cloud
   queue) so enquiry ingestion (email arriving) is decoupled from
   triage processing, with retries and a visible failure state instead of
   a crashed script.

3. **No persistence beyond a JSON file.** `outputs/results.json` is
   overwritten on every run, there's no history, no way to query "show me
   everything flagged `missing_evidence` this week," and no audit trail
   of what a human reviewer actually did with a draft (edited it? sent it
   as-is? overrode the category?).
   → **Fix:** a real datastore (even SQLite would beat a JSON file) with
   an append-only audit log — who reviewed what, what changed before
   sending, when.

4. **No ticketing/CRM integration.** Nothing here creates a ticket, assigns
   an owner, or tracks SLA/response time. A generalist team at real volume
   needs enquiries to land somewhere with ownership and status, not a
   script output a human has to manually action.
   → **Fix:** integrate with whatever the team already uses (e.g.
   Freshdesk, a Dynamics/CRM ticketing module, or even a shared inbox with
   labels) rather than building bespoke ticketing — triage output becomes
   ticket metadata (category, suggested team, urgency), not the ticket
   itself.

5. **The evaluation mechanism exists (`scripts/evaluate.py`) but the eval
   set is 8 hand-picked enquiries, so accuracy is measured but not
   tracked at any real scale.** At volume, model updates (a new Groq/
   Claude model, a prompt tweak) could silently regress accuracy on
   categories this 8-enquiry set doesn't exercise, and there's no CI
   wiring that runs the eval automatically or blocks a change that drops
   the score.
   → **Fix:** grow the labelled set from real (anonymised) historical
   enquiries — hundreds, not 8 — with tracked precision/recall per
   category and specific attention to the ambiguous pairs (funding/
   wellbeing, disability/academic, and now IT-access/info); run it in CI
   on every prompt/model change and fail the build on regression; add
   structured logging (every triage call, its input, output, and eventual
   human correction) to keep growing the set from real production data
   rather than more hand-written examples.

6. **No real human-review UI.** Reviewers currently read `run_tests.py`
   terminal output or a JSON file. There's no queue view, no way to
   edit-and-approve a draft in place, no per-reviewer accountability.
   → **Fix:** even a minimal internal web UI (a table of pending enquiries,
   click to see full structured output + raw text + editable draft, one
   button to mark reviewed) would be the actual production requirement —
   this prototype's script output is a stand-in for that, not a
   substitute.
