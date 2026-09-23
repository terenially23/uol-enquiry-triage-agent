#!/usr/bin/env python3
"""Score the agent's output against a hand-written answer key.

Deliberately a deterministic, exact-match evaluation against a small
labelled set (data/sample_enquiries.json's expected_* fields) -- not an
LLM-graded/fuzzy eval. With 8 enquiries the whole answer key fits on a
screen and every number this script prints should be defensible by hand:
open the JSON, read the expected value, read the actual output, done.

Each enquiry's expected_category / expected_team / expected_flags /
expected_needs_human_judgement starts as `null` (unfilled). A `null` field
is skipped for scoring -- not counted as wrong -- so this script is safe
to run before the answer key is finished; it'll just report fewer scored
fields until you fill them in. Fill in a field, re-run, the denominator
for that field goes up by one.

Field semantics:
  expected_category                -> exact string match against category
  expected_team                    -> set match against suggested_team
                                       (order doesn't matter)
  expected_flags                   -> set match against flags (order
                                       doesn't matter; [] is a valid,
                                       fillable expectation, not "unfilled"
                                       -- only `null` means unfilled)
  expected_needs_human_judgement   -> exact bool match (false is a valid,
                                       fillable expectation; only `null`
                                       means unfilled)

Usage:
    python3 scripts/evaluate.py            # same client selection as
                                              # run_tests.py / try_one.py
    python3 scripts/evaluate.py --mock     # force the mock client
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.client_selection import build_client
from triage_agent.llm_client import MockClient

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "sample_enquiries.json"
OUTPUT_PATH = ROOT / "outputs" / "eval_results.json"

# Same rationale as run_tests.py: paces real-provider calls under the
# free-tier TPM limit. Skipped for MockClient.
INTER_ENQUIRY_SLEEP_SECONDS = 15

FIELDS = ["category", "team", "flags", "needs_human_judgement"]


def score_field(field: str, expected, actual) -> bool | None:
    """Returns True/False if scored, None if this field wasn't filled in."""
    if expected is None:
        return None
    if field == "category":
        return actual.category == expected
    if field == "team":
        return set(actual.suggested_team) == set(expected)
    if field == "flags":
        return set(actual.flags) == set(expected)
    if field == "needs_human_judgement":
        return actual.needs_human_judgement == expected
    raise ValueError(field)


def actual_value(field: str, actual):
    if field == "category":
        return actual.category
    if field == "team":
        return actual.suggested_team
    if field == "flags":
        return actual.flags
    if field == "needs_human_judgement":
        return actual.needs_human_judgement
    raise ValueError(field)


def main() -> None:
    force_mock = "--mock" in sys.argv
    enquiries = json.loads(DATA_PATH.read_text())
    client = build_client(force_mock)
    agent = TriageAgent(client)
    pace_batch = not isinstance(client, MockClient)

    # scores[field] = [True, False, True, ...] for every enquiry where that
    # field's expected value was filled in (None entries are skipped, not
    # appended, so len(scores[field]) is the denominator for that field).
    scores: dict[str, list[bool]] = {f: [] for f in FIELDS}
    mismatches: list[str] = []
    eval_rows = []

    for i, enquiry in enumerate(enquiries):
        if pace_batch and i > 0:
            print(f"[info] Pacing batch under the free-tier rate limit -- waiting {INTER_ENQUIRY_SLEEP_SECONDS}s.\n")
            time.sleep(INTER_ENQUIRY_SLEEP_SECONDS)

        actual = agent.triage(
            sender_name=enquiry["sender_name"],
            sender_email=enquiry["sender_email"],
            body=enquiry["body"],
            enquiry_id=enquiry["enquiry_id"],
        )

        row = {"enquiry_id": enquiry["enquiry_id"], "fields": {}}
        for field in FIELDS:
            expected = enquiry.get(f"expected_{field}")
            correct = score_field(field, expected, actual)
            row["fields"][field] = {"expected": expected, "actual": actual_value(field, actual), "correct": correct}
            if correct is None:
                continue
            scores[field].append(correct)
            if not correct:
                mismatches.append(
                    f"{enquiry['enquiry_id']} [{field}]: expected {expected!r}, got {actual_value(field, actual)!r}"
                )
        eval_rows.append(row)

    print("=" * 88)
    print("EVALUATION SCORECARD")
    print("=" * 88)
    any_scored = False
    for field in FIELDS:
        n = len(scores[field])
        if n == 0:
            print(f"{field:24s}: no enquiries scored yet (expected_{field} not filled in)")
            continue
        any_scored = True
        correct = sum(scores[field])
        print(f"{field:24s}: {correct}/{n} correct  ({n} of {len(enquiries)} enquiries have this field filled in)")

    print()
    if not any_scored:
        print("Nothing scored yet -- fill in expected_* fields in data/sample_enquiries.json and re-run.")
    elif mismatches:
        print(f"Mismatches ({len(mismatches)}):")
        for m in mismatches:
            print(f"  - {m}")
    else:
        print("No mismatches on any scored field.")

    print("=" * 88)

    OUTPUT_PATH.parent.mkdir(exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps({"rows": eval_rows, "mismatches": mismatches}, indent=2))
    print(f"\nSaved full evaluation detail to {OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
