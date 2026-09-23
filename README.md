# Student Enquiry Triage Agent (prototype)

A small triage agent for a University of Leeds "generalist team" inbox. It
takes a raw student enquiry (sender + free-text body), categorises it
against the real Leeds service structure, and produces a structured record
a human reviews before anything is sent. **It never sends anything itself.**

See [`WRITEUP.md`](WRITEUP.md) for the design rationale, sourced citations
(which real Leeds page grounds which routing decision), test results, a
known failure case, a scalability assessment, and an explicit list of what
this prototype does not do.

## Quick start

```bash
pip install -r requirements.txt        # only needed for the real LLM path
export GROQ_API_KEY=gsk_...            # this demo's actual setup -- free tier
# or: export ANTHROPIC_API_KEY=sk-...  # alternative -- see below
python3 scripts/run_tests.py           # batch: all 8 sample enquiries
python3 scripts/try_one.py             # interactive: paste one enquiry
python3 scripts/export_table.py        # markdown + CSV table from results.json
python3 scripts/evaluate.py            # scorecard against the hand-written answer key
python3 -m unittest discover -s tests  # guardrail unit tests, no API key needed
```

`run_tests.py` runs the 8 sample enquiries in `data/sample_enquiries.json`
through the agent, prints a human-readable summary of each (raw enquiry
text next to the agent's own output, deliberately, so a reviewer can
spot-check), and saves full structured output to `outputs/results.json`.
`try_one.py` does the same for a single custom enquiry you paste in,
without touching `outputs/`. `export_table.py` flattens `results.json`
into `outputs/results_table.md` / `.csv` -- one row per enquiry.
`evaluate.py` scores actual output against each enquiry's `expected_*`
fields in `data/sample_enquiries.json` and prints a per-field scorecard
plus a list of mismatches -- currently 7/8 with `MockClient` (the
remaining mismatch, ENQ-008, is an intentional mock/live-model divergence,
not a bug -- see WRITEUP.md). A live-Groq scorecard hasn't been captured
in this repo (this dev environment can't reach api.groq.com); run
`GROQ_API_KEY=... python3 scripts/evaluate.py` yourself for the real
number. See WRITEUP.md's "Evaluation" section for the field semantics and
the design decisions/answer-key updates a live run has surfaced so far.

Client selection (`triage_agent/client_selection.py`), checked in this
order:

1. **`GROQ_API_KEY`** set → `GroqClient`, Groq's free-tier
   `llama-3.3-70b-versatile` via their OpenAI-compatible API. What this
   demo actually runs on.
2. **`ANTHROPIC_API_KEY`** set (and no Groq key) → `AnthropicClient`, the
   real Claude API.
3. Neither set → `MockClient`, a deterministic keyword-based fallback with
   the *same* interface, so the prototype still runs end-to-end without
   any credentials. Force this explicitly with `--mock`. It's a stand-in
   for demonstration/offline testing, not a claim that keyword matching is
   an adequate categoriser -- see WRITEUP.md.

## Web demo

```bash
pip install -r requirements.txt
streamlit run scripts/demo_app.py
```

A minimal Streamlit page over the exact same `TriageAgent` and
`client_selection.build_client()` logic the CLI scripts use -- no separate
business logic, no changes to `agent.py`/`llm_client.py`/`routing.py`.
Shows which client is active (Groq/Anthropic/Mock) at the top, takes a
sender name/email and enquiry body, and renders the full structured
`TriageResult` on submit. Same client-selection env vars apply
(`GROQ_API_KEY`/`ANTHROPIC_API_KEY`).

## Layout

```
triage_agent/
  routing.py          routing knowledge base (7 real Leeds services)
  schema.py           structured output schema (dataclasses)
  llm_client.py       AnthropicClient / GroqClient (real) + MockClient (offline)
  client_selection.py picks a client from env vars (see priority above)
  agent.py            TriageAgent: calls the LLM, then enforces hard guardrails
  display.py          shared human-readable rendering (run_tests.py + try_one.py)
guidance/
  disability_evidence.md               sourced excerpt: evidence requirement
  luu_vs_counselling_independence.md   sourced excerpt: internal vs external
  retrieve.py     looks up the right excerpt in code, not via the LLM
data/sample_enquiries.json   the 8 test enquiries (5 from the brief + 3 added
                              for coverage), each with a filled-in expected_*
                              answer key for evaluate.py (7/8 with MockClient,
                              1 intentional mock/live-model divergence)
scripts/run_tests.py         batch: runs all 8, saves outputs/results.json
scripts/try_one.py           interactive: triage one pasted enquiry
scripts/export_table.py      renders results.json as a markdown/CSV table
scripts/evaluate.py          scores actual output against the answer key,
                              saves eval_results.json (full detail) and
                              eval_scorecard.md/.csv (one row per enquiry,
                              expected/actual/PASS-FAIL per field + totals)
scripts/demo_app.py          Streamlit UI wrapper -- streamlit run scripts/demo_app.py
tests/test_guardrails.py     unit tests for _apply_guardrails, stubbed LLM
outputs/                     saved sample output (committed for review)
```

## Design in one paragraph

The LLM does the categorisation (it's the part that genuinely benefits
from language understanding); a thin layer of Python around it enforces
the two constraints that must never depend on a model behaving itself --
`requires_human_review` is always `True`, and a disability-adjustment
reply is never auto-drafted unless evidence is confirmed. The schema has
explicit fields (`needs_human_judgement`, `additional_issues`,
`internal_or_external: "ambiguous"`) for the two hard cases in the brief
(Counselling vs LUU ambiguity, multi-issue emails) instead of forcing a
single category to carry information it can't hold.
