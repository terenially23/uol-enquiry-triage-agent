#!/usr/bin/env python3
"""Render outputs/results.json as a flat table (markdown + CSV) -- one row
per enquiry, for putting in a slide. The brief requires results shown "in
a list, table, or another structured format"; results.json on its own is
structured but not a table, so this is that view.

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

COLUMNS = [
    "enquiry_id",
    "sender",
    "category",
    "confidence",
    "suggested_team",
    "internal_or_external",
    "urgency",
    "needs_human_judgement",
    "missing_info",
    "flags",
    "has_draft",
    "summary",
]


def flatten(row: dict) -> dict:
    enquiry = row["enquiry"]
    result = row["triage_result"]
    missing_info = result.get("missing_info")
    return {
        "enquiry_id": result["enquiry_id"],
        "sender": f"{enquiry['sender_name']} <{enquiry['sender_email']}>",
        "category": result["category"],
        "confidence": f"{result['confidence']:.2f}",
        "suggested_team": "; ".join(result["suggested_team"]),
        "internal_or_external": result["internal_or_external"],
        "urgency": result["urgency"],
        "needs_human_judgement": result["needs_human_judgement"],
        "missing_info": missing_info["evidence_attached"] if missing_info else "-",
        "flags": "; ".join(result["flags"]) or "-",
        "has_draft": bool(result["suggested_response_draft"]),
        "summary": result["summary"],
    }


def to_markdown(rows: list[dict]) -> str:
    header = "| " + " | ".join(COLUMNS) + " |"
    sep = "| " + " | ".join("---" for _ in COLUMNS) + " |"
    lines = [header, sep]
    for row in rows:
        cells = [str(row[col]).replace("|", "\\|") for col in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> None:
    if not RESULTS_PATH.exists():
        print(f"[error] {RESULTS_PATH.relative_to(ROOT)} not found -- run scripts/run_tests.py first.")
        sys.exit(1)

    raw_rows = json.loads(RESULTS_PATH.read_text())
    rows = [flatten(r) for r in raw_rows]

    md = to_markdown(rows)
    MD_OUTPUT_PATH.write_text(md + "\n")

    with CSV_OUTPUT_PATH.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(md)
    print(f"\nSaved {MD_OUTPUT_PATH.relative_to(ROOT)} and {CSV_OUTPUT_PATH.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
