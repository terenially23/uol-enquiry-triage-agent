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
                                       (order doesn't matter; also
                                       insensitive to slug vs. display-name
                                       formatting -- see _canonical_team())
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

Writes outputs/eval_results.json (full detail, as before) plus
outputs/eval_scorecard.md and outputs/eval_scorecard.csv -- a flat table,
one row per enquiry, expected vs. actual vs. pass/fail per field, same
pattern as export_table.py, with a final TOTALS row. For putting straight
into a slide alongside results_table.md/.csv.
"""

from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from triage_agent.agent import TriageAgent
from triage_agent.client_selection import build_client
from triage_agent.llm_client import MockClient
from triage_agent.routing import TEAMS

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "sample_enquiries.json"
OUTPUT_PATH = ROOT / "outputs" / "eval_results.json"
SCORECARD_MD_PATH = ROOT / "outputs" / "eval_scorecard.md"
SCORECARD_CSV_PATH = ROOT / "outputs" / "eval_scorecard.csv"

# Same rationale as run_tests.py: paces real-provider calls under the
# free-tier TPM limit. Skipped for MockClient.
INTER_ENQUIRY_SLEEP_SECONDS = 15

FIELDS = ["category", "team", "flags", "needs_human_judgement"]


def _canonical_team(token: str) -> str:
    """Map a team token -- the canonical slug (e.g.
    "student_information_service") or a display name (e.g. "Student
    Information Service") in any case/whitespace -- to its canonical slug,
    using routing.py's TEAMS as the single source of truth for the
    mapping. A live model sometimes returns the display name instead of
    the slug despite the schema/prompt asking for the slug; that's a
    format difference, not a routing error, so team comparisons need to be
    insensitive to it. Falls back to a lightly normalized version of
    unrecognized tokens rather than crashing, so a genuinely wrong team
    still shows up as a mismatch instead of silently passing."""
    normalized = token.strip().lower()
    for slug, team in TEAMS.items():
        if normalized == slug or normalized == team.name.strip().lower():
            return slug
    return normalized


def _normalize_team_set(tokens) -> set[str]:
    return {_canonical_team(t) for t in tokens}


def score_field(field: str, expected, actual) -> bool | None:
    """Returns True/False if scored, None if this field wasn't filled in."""
    if expected is None:
        return None
    if field == "category":
        return actual.category == expected
    if field == "team":
        return _normalize_team_set(actual.suggested_team) == _normalize_team_set(expected)
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


def _format_cell(value) -> str:
    """Renders a field value (None, bool, str, or list) as a short table
    cell. None means "not scored" (expected_* was null), distinct from an
    empty list [], which is a valid, scored expectation."""
    if value is None:
        return "-"
    if isinstance(value, list):
        return "; ".join(value) if value else "[]"
    return str(value)


SCORECARD_COLUMNS = ["enquiry_id"] + [
    f"{field}_{suffix}" for field in FIELDS for suffix in ("expected", "actual", "result")
]


def build_scorecard_rows(eval_rows: list[dict], scores: dict[str, list[bool]]) -> list[dict]:
    """One row per enquiry (expected/actual/PASS|FAIL per field), plus a
    final TOTALS row with each field's N/M correct count in its `_result`
    column -- same shape export_table.py uses for results.json, so both
    tables read the same way side by side."""
    rows = []
    for row in eval_rows:
        record = {"enquiry_id": row["enquiry_id"]}
        for field in FIELDS:
            cell = row["fields"][field]
            correct = cell["correct"]
            result = "-" if correct is None else ("PASS" if correct else "FAIL")
            record[f"{field}_expected"] = _format_cell(cell["expected"])
            record[f"{field}_actual"] = _format_cell(cell["actual"])
            record[f"{field}_result"] = result
        rows.append(record)

    totals = {"enquiry_id": "TOTALS"}
    for field in FIELDS:
        n = len(scores[field])
        correct = sum(scores[field])
        totals[f"{field}_expected"] = ""
        totals[f"{field}_actual"] = ""
        totals[f"{field}_result"] = f"{correct}/{n}" if n else "-"
    rows.append(totals)

    return rows


def scorecard_to_markdown(rows: list[dict]) -> str:
    header = "| " + " | ".join(SCORECARD_COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in SCORECARD_COLUMNS) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [str(row[col]).replace("|", "\\|") for col in SCORECARD_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    force_mock = "--mock" in sys.argv
    enquiries = json.loads(DATA_PATH.read_text(encoding="utf-8"))
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
    OUTPUT_PATH.write_text(json.dumps({"rows": eval_rows, "mismatches": mismatches}, indent=2), encoding="utf-8")
    print(f"\nSaved full evaluation detail to {OUTPUT_PATH.relative_to(ROOT)}")

    scorecard_rows = build_scorecard_rows(eval_rows, scores)
    SCORECARD_MD_PATH.write_text(scorecard_to_markdown(scorecard_rows) + "\n", encoding="utf-8")
    with SCORECARD_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SCORECARD_COLUMNS)
        writer.writeheader()
        writer.writerows(scorecard_rows)
    print(f"Saved {SCORECARD_MD_PATH.relative_to(ROOT)} and {SCORECARD_CSV_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
