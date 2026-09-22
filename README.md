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
export ANTHROPIC_API_KEY=sk-...        # optional -- see below
python3 scripts/run_tests.py           # batch: all 5 sample enquiries
python3 scripts/try_one.py             # interactive: paste one enquiry
python3 scripts/export_table.py        # markdown + CSV table from results.json
```

`run_tests.py` runs the 5 sample enquiries in `data/sample_enquiries.json`
through the agent, prints a human-readable summary of each (raw enquiry
text next to the agent's own output, deliberately, so a reviewer can
spot-check), and saves full structured output to `outputs/results.json`.
`try_one.py` does the same for a single custom enquiry you paste in,
without touching `outputs/`. `export_table.py` flattens `results.json`
into `outputs/results_table.md` / `.csv` -- one row per enquiry.

- **With `ANTHROPIC_API_KEY` set**: uses the real Claude API for
  categorisation, via a tool-use call that forces valid structured JSON.
- **Without a key**: automatically falls back to a deterministic,
  keyword-based `MockClient` with the *same* interface, so the prototype
  runs end-to-end without any credentials. Force this explicitly with
  `--mock`. This is a stand-in for demonstration/offline testing, not a
  claim that keyword matching is an adequate categoriser -- see
  WRITEUP.md.

## Layout

```
triage_agent/
  routing.py      routing knowledge base (the 6 real Leeds services)
  schema.py       structured output schema (dataclasses)
  llm_client.py   AnthropicClient (real) + MockClient (offline fallback)
  agent.py        TriageAgent: calls the LLM, then enforces hard guardrails
  display.py      shared human-readable rendering (run_tests.py + try_one.py)
guidance/
  disability_evidence.md               sourced excerpt: evidence requirement
  luu_vs_counselling_independence.md   sourced excerpt: internal vs external
  retrieve.py     looks up the right excerpt in code, not via the LLM
data/sample_enquiries.json   the 5 test enquiries from the brief
scripts/run_tests.py         batch: runs all 5, saves outputs/results.json
scripts/try_one.py           interactive: triage one pasted enquiry
scripts/export_table.py      renders results.json as a markdown/CSV table
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
