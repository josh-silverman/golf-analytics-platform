#!/usr/bin/env python3
"""Fail if tracked markdown publishes DataGolf's per-player values (ledger §2.8).

DataGolf's terms are personal use only, no redistribution, and this repo is
public. The *export* path has been defended since it was built; this is the
repo-content path, which had nothing guarding it until 2026-08-25 and
accordingly sat exposed for twenty days.

Deliberately narrow. It matches the shape of a per-player table — a market
column header keyed to DataGolf — rather than trying to recognise a bare
number as DataGolf-derived, which is not decidable from the text. Aggregate
columns about DataGolf's predictions (`DG raw Brier`, `DG skill`) are the point
of the archive and must keep passing, so the market names are matched
explicitly and nothing else is.

This is a backstop against reintroduction, not a classifier. A value pasted
without its header still gets through; ledger §2.8 is the rule, this is the
tripwire.
"""

from __future__ import annotations

import re
import subprocess
import sys

# A table column header naming a DataGolf market: "| DG win |", "| DataGolf
# top-20 |", "| DG make cut |". Anchored to the leading pipe so prose
# discussing a `DG win` column (as ledger §2.8 does) does not trip it.
_DG_MARKET_COLUMN = re.compile(
    r"\|\s*(?:DG|DataGolf)[\s_-]+(?:win|top[\s_-]?\d+|make[\s_-]?cut)\s*\|",
    re.IGNORECASE,
)

# Per-player skill/decomposition and de-vigged price columns.
_OTHER_COLUMNS = re.compile(
    r"\|\s*(?:SG[\s_-]?total|fair[\s_-]?market(?:[\s_-]?win)?|course[\s_-]?fit"
    r"|course[\s_-]?history|driving[\s_-]?dist\w*)\s*\|",
    re.IGNORECASE,
)

_PATTERNS = (
    (_DG_MARKET_COLUMN, "per-player DataGolf market column"),
    (_OTHER_COLUMNS, "per-player skill / decomposition / de-vigged price column"),
)


def tracked_markdown() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout
    return [p for p in out.splitlines() if p]


# A markdown table header is followed by a delimiter row (|---|:--:|---|).
# Requiring one is what separates a data table from prose or a UI mockup's tab
# strip, which is otherwise indistinguishable: "Course Fit" is a column in one
# and a tab label in the other.
_TABLE_DELIMITER = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|[\s:|-]*$")


def _is_table_header(lines: list[str], idx: int) -> bool:
    return idx + 1 < len(lines) and bool(_TABLE_DELIMITER.match(lines[idx + 1]))


def main() -> int:
    violations: list[str] = []
    for rel in tracked_markdown():
        try:
            with open(rel, encoding="utf-8", errors="replace") as fh:
                lines = fh.readlines()
        except OSError:
            continue
        for idx, line in enumerate(lines):
            if not _is_table_header(lines, idx):
                continue
            for pattern, label in _PATTERNS:
                if pattern.search(line):
                    violations.append(
                        f"{rel}:{idx + 1}: {label}\n    {line.strip()[:120]}"
                    )

    if violations:
        print("DataGolf redistribution check FAILED (docs/ledger.md §2.8)\n")
        print(
            "These look like per-player DataGolf values published in a public repo.\n"
            "Keep aggregates, orderings, ratios and this project's own output;\n"
            "hold DataGolf's absolute values privately.\n"
        )
        for v in violations:
            print("  " + v)
        return 1

    print(
        f"ok — {len(tracked_markdown())} tracked markdown files, no per-player DataGolf tables"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
