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
plus a list of mismatches -- see WRITEUP.md's "Evaluation" section for the
field semantics and why the answer key ships unfilled (`null`) by design.

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
                              for coverage), each with expected_* answer-key
                              fields for evaluate.py (unfilled by default)
scripts/run_tests.py         batch: runs all 8, saves outputs/results.json
scripts/try_one.py           interactive: triage one pasted enquiry
scripts/export_table.py      renders results.json as a markdown/CSV table
scripts/evaluate.py          scores actual output against the answer key
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
