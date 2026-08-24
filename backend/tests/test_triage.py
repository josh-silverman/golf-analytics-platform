"""Seed tests for the dead-weight triage report.

The disqualifying condition is the one that matters and it is pinned first:
the tool must never recommend removing something the keep register protects,
and it must show the lapse check it actually ran. A cleanup tool that is
merely usually right about `app/db/` is not usable, because the one time it
is wrong the loss is irreversible.

The rest pin the classification rules the report depends on to stay readable:
convention-loaded configs and package markers are not dead weight, a document
referenced from prose is a document in use, and an explicitly ignored path is
a deliberate local file rather than debris.
"""

from __future__ import annotations

import pytest

from app.cli import triage
from app.cli.triage import Bucket

# Deliberately NOT marked slow: it runs in about a second, and the
# disqualifying condition below is only worth having if CI enforces it.


@pytest.fixture(scope="module")
def findings() -> list[triage.Finding]:
    return triage.classify(triage.repo_root())


def _for(findings: list[triage.Finding], needle: str) -> triage.Finding | None:
    return next((f for f in findings if needle in f.path), None)


# ---------------------------------------------------------------------------
# The disqualifying condition
# ---------------------------------------------------------------------------


def test_never_recommends_removing_anything_the_register_protects(findings) -> None:
    """The single test that decides whether this tool may be used at all."""
    register = triage.load_register(triage.repo_root())
    removals = [f for f in findings if f.bucket is Bucket.REMOVE]
    for finding in removals:
        for entry in register:
            assert not entry.covers(finding.path), (
                f"recommended removing {finding.path}, protected by register "
                f"entry {entry.id!r} ({entry.citation})"
            )


def test_vestigial_db_is_kept_with_its_citation(findings) -> None:
    """The seed test named in docs/plans/02-agent-candidates.md.

    `app/db/` is unimported and render.yaml provisions no Postgres, so every
    static measure calls it dead. It is kept because /readyz was broken in
    f265744 by assuming it was live.
    """
    found = _for(findings, "backend/app/db")
    assert found is not None
    assert found.bucket is Bucket.KEEP_DOCUMENTED
    assert found.citation == "docs/ledger.md §3.4"


def test_every_register_entry_reports_the_check_that_ran(findings) -> None:
    """A keep decision without a visible check is indistinguishable from the
    tool simply not looking, which is the failure this design exists to
    prevent."""
    kept = [
        f
        for f in findings
        if f.bucket in (Bucket.KEEP_DOCUMENTED, Bucket.KEEP_READER_PENDING, Bucket.REVIEW)
    ]
    assert kept, "the register produced no findings at all"
    for finding in kept:
        assert finding.check, f"{finding.path} was kept without reporting a check"


def test_capture_time_fields_are_kept_while_their_reader_is_unbuilt(findings) -> None:
    """Written every capture, read by nothing until A4b. Deleting them
    destroys data no later work can recover."""
    found = _for(findings, "dg_fetch_status")
    assert found is not None
    assert found.bucket is Bucket.KEEP_READER_PENDING
    assert "A4b" in found.check


def test_an_unverifiable_reason_never_becomes_a_removal(findings) -> None:
    """The model registry cannot be checked from a local checkout, so the
    honest answer is the question, not a guess."""
    found = _for(findings, "backend/models")
    assert found is not None
    assert found.bucket is Bucket.KEEP_DOCUMENTED
    assert found.check.startswith("manual")


# ---------------------------------------------------------------------------
# Lapse checks actually evaluate
# ---------------------------------------------------------------------------


def test_lapse_check_fires_when_the_reason_stops_holding(tmp_path) -> None:
    """A register entry is a claim with an expiry, not a permanent exemption."""
    root = triage.repo_root()
    entry = next(e for e in triage.load_register(root) if e.id == "capture-time-fields")

    lapsed, check = triage.evaluate_lapse(root, entry)
    assert lapsed is False  # A4b is not built today
    assert "not found" in check

    # Simulate the roadmap marking A4b built.
    fake = tmp_path / "docs" / "plans"
    fake.mkdir(parents=True)
    (fake / "01-roadmap.md").write_text("### A4b. Named baselines ✅ (built)\n")
    lapsed, check = triage.evaluate_lapse(tmp_path, entry)
    assert lapsed is True
    assert "found" in check


# ---------------------------------------------------------------------------
# Noise control — a report nobody reads catches nothing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        ".gitignore",
        "backend/pyproject.toml",
        "frontend/package.json",
        "frontend/tsconfig.json",
        "render.yaml",
        "Makefile",
    ],
)
def test_convention_loaded_configs_are_not_dead_weight(findings, path) -> None:
    """Their tooling finds them by name, so no inbound reference is normal."""
    assert _for(findings, path) is None


def test_package_markers_are_not_reported(findings) -> None:
    """An `__init__.py` exists so the package imports; an unreferenced one
    says nothing about whether the package is used."""
    assert not [f for f in findings if f.path.endswith("__init__.py")]


def test_a_document_referenced_from_prose_counts_as_used(findings) -> None:
    """Being cited by another document is what using a document looks like.
    Treating prose references as non-references flags the entire docs tree."""
    for name in ("CLAUDE.md", "docs/ledger.md", "docs/plans/01-roadmap.md"):
        assert _for(findings, name) is None


def test_ignored_and_present_is_scratch_rather_than_debris(tmp_path) -> None:
    """`.gitignore` read as intent: these are deliberate local files. A
    git-based tool cannot see them; a filesystem-based one calls them debris.
    Both are wrong.

    Built from a temporary tree rather than asserted against this checkout:
    the real examples (`backend/diagnostics`, `docs/walkthrough-notes.md`) are
    gitignored, so they exist on a working machine and not in a fresh clone.
    A test that only passes where the developer happens to have run a sweep
    is testing the machine, not the rule — which is how this first went red
    in CI.
    """
    (tmp_path / ".gitignore").write_text("diagnostics/\nnotes.md\n.mypy_cache\nabsent/\n")
    (tmp_path / "diagnostics").mkdir()
    (tmp_path / "diagnostics" / "sweep.log").write_text("x")
    (tmp_path / "notes.md").write_text("y")
    (tmp_path / ".mypy_cache").mkdir()

    found = triage.ignored_but_present(tmp_path)
    assert "diagnostics" in found  # a directory of local working files
    assert "notes.md" in found  # a single ignored-by-name document
    assert ".mypy_cache" not in found  # regenerable: not a decision
    assert "absent" not in found  # ignored but not present is nothing at all


def test_regenerable_caches_are_never_reported(findings) -> None:
    """They are ignored and present, but they are not a decision anyone makes."""
    for cache in (".mypy_cache", ".ruff_cache", "node_modules", "__pycache__"):
        assert _for(findings, cache) is None


def test_report_renders_and_marks_only_removals_as_recommendations(findings) -> None:
    text = triage.render(findings)
    assert "Classification only" in text
    assert "KEEP — DOCUMENTED REASON" in text
    assert "docs/ledger.md §3.4" in text
