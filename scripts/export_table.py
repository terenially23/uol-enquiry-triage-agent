#!/usr/bin/env python3
"""Render outputs/results.json as a flat table (markdown + CSV) -- one row
per enquiry, every field in the record, for putting in a slide. The brief
requires results shown "in a list, table, or another structured format";
results.json on its own is structured but not a table, so this is that
view.

Usage:
    python3 scripts/run_tests.py        # generates outputs/results.json first
    python3 scripts/export_table.py

Writes outputs/results_table.md and outputs/results_table.csv, and prints
the markdown table to stdout.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RESULTS_PATH = ROOT / "outputs" / "results.json"
MD_OUTPUT_PATH = ROOT / "outputs" / "results_table.md"
CSV_OUTPUT_PATH = ROOT / "outputs" / "results_table.csv"

# Every field currently in a results.json record, in the order it appears
# there (enquiry fields first, then the TriageResult fields) -- kept in
# sync by hand, not derived from the dataclass, so a schema change here is
# a deliberate edit, not a silent drop.
COLUMNS = [
    "enquiry_id",
    "sender_name",
    "sender_email",
    "body",
    "category",
    "confidence",
    "summary",
    "suggested_team",
    "internal_or_external",
    "missing_info",
    "suggested_response_draft",
    "requires_human_review",
    "urgency",
    "needs_human_judgement",
    "internal_note",
    "flags",
    "additional_issues",
    "source_citation",
]


def _format_list(values: list[str]) -> str:
    return "; ".join(values) if values else "-"


def _format_missing_info(missing_info: dict | None) -> str:
    if not missing_info:
        return "-"
    return f"evidence_attached={missing_info['evidence_attached']} ({missing_info.get('details') or '-'})"


def _format_additional_issues(issues: list[dict]) -> str:
    if not issues:
        return "-"
    parts = [
        f"{issue['category']} (team={_format_list(issue['suggested_team'])}, "
        f"urgency={issue['urgency']}): {issue['summary']}"
        for issue in issues
    ]
    return " | ".join(parts)


def flatten(row: dict) -> dict:
    # row is already a flat record (run_tests.py merges the enquiry's own
    # fields -- sender_name/sender_email/body -- directly into the same
    # dict as the triage result); this just formats each value for a
    # single table cell. Multi-line fields (body, suggested_response_draft,
    # internal_note) keep real newlines here -- fine for CSV, which quotes
    # them correctly; to_markdown() below escapes them separately for
    # display, since a raw newline breaks a markdown table row.
    return {
        "enquiry_id": row["enquiry_id"],
        "sender_name": row["sender_name"],
        "sender_email": row["sender_email"],
        "body": row["body"],
        "category": row["category"],
        "confidence": f"{row['confidence']:.2f}",
        "summary": row["summary"],
        "suggested_team": _format_list(row["suggested_team"]),
        "internal_or_external": row["internal_or_external"],
        "missing_info": _format_missing_info(row.get("missing_info")),
        "suggested_response_draft": row["suggested_response_draft"] or "-- deferred to human --",
        "requires_human_review": row["requires_human_review"],
        "urgency": row["urgency"],
        "needs_human_judgement": row["needs_human_judgement"],
        "internal_note": row["internal_note"] or "-",
        "flags": _format_list(row["flags"]),
        "additional_issues": _format_additional_issues(row["additional_issues"]),
        "source_citation": row["source_citation"] or "-",
    }


def to_markdown(rows: list[dict]) -> str:
    header = "| " + " | ".join(COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in COLUMNS) + " |"
    lines = [header, sep]
    for row in rows:
        # "|" would split a cell into extra columns; a raw newline would
        # end the row early -- both escaped for markdown display only
        # (the CSV keeps the real characters).
        cells = [str(row[col]).replace("|", "\\|").replace("\n", "<br>") for col in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    if not RESULTS_PATH.exists():
        print(f"[error] {RESULTS_PATH.relative_to(ROOT)} not found -- run scripts/run_tests.py first.")
        sys.exit(1)

    raw_rows = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    rows = [flatten(r) for r in raw_rows]

    md = to_markdown(rows)
    MD_OUTPUT_PATH.write_text(md + "\n", encoding="utf-8")

    with CSV_OUTPUT_PATH.open("w", newline="", encoding="utf-8") as f:
        # QUOTE_ALL, not the csv module's QUOTE_MINIMAL default: several
        # columns (body, suggested_response_draft, internal_note,
        # additional_issues) routinely contain commas, quotes and embedded
        # newlines, and this makes every field's quoting explicit rather
        # than relying on the reader trusting minimal-quoting heuristics.
        writer = csv.DictWriter(f, fieldnames=COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)

    print(md)
    print(f"\nSaved {MD_OUTPUT_PATH.relative_to(ROOT)} and {CSV_OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
