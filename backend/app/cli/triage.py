"""Dead-weight triage — classify what looks removable, never remove it.

`python -m app.cli.triage` from `backend/`. Read-only: it opens no file for
writing and shells out to git only for `ls-files` / `check-ignore` / `log`.

**Why this is a report and not a cleaner.** In this repo the mechanical answer
is confidently wrong about the cases that matter most. `app/db/` is unimported
and provisions no database, and is kept deliberately because `/readyz` was
broken in `f265744` by assuming it was live. The model registry looks like
stale artifacts and is what keeps a board's `model_version_id` interpretable.
`BoardSnapshot.dg_baseline` and `dg_fetch_status` are written on every capture
and read by nothing, because A4b is not built — and they are capture-time
writes that cannot be backfilled, so deleting them destroys data no later work
can recover. This repo is structurally full of deliberately-unused-yet code,
because capture always precedes its reader.

So the tool sorts into buckets and cites its reasoning; a human decides.

**`.gitignore` is read as a statement of intent, not as a filter.** A path that
is explicitly ignored and present on disk is neither repo fat nor a mistake —
it is a deliberate local working file. `backend/diagnostics/` (sweep logs from
the closed feature-space program) and `docs/walkthrough-notes.md` are both
ignored by name. A tool reasoning from git cannot see them; one reasoning from
the filesystem would call them debris. Both readings are wrong, so they get
their own bucket and are reported as out of scope.

**The disqualifying test.** If this ever recommends removing something in
`docs/keep-register.toml` without first evaluating that entry's lapse
condition, it is unusable — not miscalibrated. `tests/test_triage.py` pins
that, including the seed test that `app/db/` classifies as
`keep — documented reason` citing ledger §3.4.

Precision over recall, deliberately: missed debris costs disk space, while a
deleted traceability artifact costs the interpretability of the record.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Files worth reference-scanning. Anything else (images, lockfiles, binaries)
# is left alone: this tool is about code and prose that has outlived its use,
# not about disk usage.
_SCANNABLE = frozenset(
    {
        ".py",
        ".md",
        ".toml",
        ".yml",
        ".yaml",
        ".json",
        ".ts",
        ".tsx",
        ".js",
        ".sh",
        ".cfg",
        ".ini",
        ".html",
        ".css",
        ".svg",
        ".txt",
    }
)

# Files their tooling finds by NAME, never by reference. Absence of an inbound
# mention is their normal state, so counting them as dead weight fills the
# report with `.gitignore` and trains you to stop reading it. Dotfiles are
# treated the same way, by the same argument.
_CONVENTION_LOADED = frozenset(
    {
        "makefile",
        "dockerfile",
        "docker-compose.yml",
        "render.yaml",
        "pyproject.toml",
        "uv.lock",
        "alembic.ini",
        "package.json",
        "package-lock.json",
        "tsconfig.json",
        "tsconfig.app.json",
        "tsconfig.node.json",
        "vite.config.ts",
        "vitest.config.ts",
        "eslint.config.js",
        "postcss.config.js",
        "tailwind.config.js",
        "components.json",
        "index.html",
        "license",
        "conftest.py",
    }
)

# Documents and images are *supposed* to be referenced from prose — that is
# what using a document looks like. The prose-only signal below is meaningful
# only for things something is supposed to load or execute.
_DOCUMENT_SUFFIXES = frozenset({".md", ".png", ".jpg", ".jpeg", ".svg", ".gif", ".txt"})

# References from these carry weight — something actually loads or runs the
# file. A reference from a .md is prose: it documents the file, which is not
# the same as using it, and is exactly how `fly.toml` still looks alive.
_CODE_REFERENCE_SUFFIXES = frozenset(
    {".py", ".toml", ".yml", ".yaml", ".json", ".ts", ".tsx", ".js", ".sh", ".cfg", ".ini"}
)

# Import roots for reachability. Everything the running service or a CLI entry
# point can reach transitively is live; the rest is a candidate.
_ENTRY_MODULES = ("app.main",)
_ENTRY_PACKAGES = ("app.cli",)

# Never proposed for removal on a reference count alone — these are load-bearing
# by construction and their absence of inbound references is the normal state.
_NEVER_BY_REFERENCE = (
    "backend/app/",  # covered by the import graph instead
    "frontend/src/",  # covered by the bundler, which this tool does not model
    ".github/workflows/",  # entry points by definition; nothing imports a cron
)

# Regenerable build and tool artefacts. Ignored *and* present, like everything
# in the local-scratch bucket, but listing them is noise: they are not a
# decision anyone has to make, and they reappear on the next command.
_REGENERABLE = frozenset(
    {
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        "__pycache__",
        "node_modules",
        ".venv",
        ".vercel",
        "dist",
        "build",
        ".next",
        "coverage",
        "htmlcov",
        ".DS_Store",
    }
)

# The triage tooling *describes* the repo, so a mention here is documentation,
# not use. Excluded from the reference index because including it is a
# self-fulfilling false negative: naming `fly.toml` in the comment above was
# enough to make `fly.toml` look referenced from code and drop out of the
# report entirely.
_SELF_DESCRIBING = (
    "backend/app/cli/triage.py",
    "backend/tests/test_triage.py",
    "docs/keep-register.toml",
    "docs/plans/02-agent-candidates.md",
)

_MAX_BYTES = 2_000_000  # skip anything larger when reading for references


class Bucket(StrEnum):
    """Where a candidate lands. Only ``REMOVE`` is a recommendation."""

    REMOVE = "remove"
    REVIEW_PROSE_ONLY = "review — described in prose, loaded by nothing"
    KEEP_DOCUMENTED = "keep — documented reason"
    KEEP_READER_PENDING = "keep — reader pending"
    REVIEW = "review — the documented reason may have lapsed"
    LOCAL_SCRATCH = "local scratch — out of scope for repo cleanup"


@dataclass
class Finding:
    path: str
    bucket: Bucket
    why: str
    citation: str | None = None
    check: str | None = None  # the lapse check that was actually run
    refs: list[str] = field(default_factory=list)
    last_touched: str | None = None


# ---------------------------------------------------------------------------
# git, used only as a source of facts
# ---------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout


def repo_root(start: Path | None = None) -> Path:
    here = start or Path(__file__).resolve()
    out = _git(here.parent if here.is_file() else here, "rev-parse", "--show-toplevel").strip()
    if out:
        return Path(out)
    # Fall back to walking up, so the tool still works outside a git checkout.
    for parent in here.parents:
        if (parent / ".git").exists():
            return parent
    raise SystemExit("not inside a git checkout")


def tracked_files(root: Path) -> list[str]:
    return [line for line in _git(root, "ls-files").splitlines() if line]


def ignored_but_present(root: Path) -> list[str]:
    """Paths git is told to ignore that nevertheless exist on disk.

    Deliberate local working files, not debris. Resolved from `.gitignore`
    entries rather than by walking the filesystem, so the report names the
    intent (`backend/.gitignore:1`) and not just the directory.
    """
    found: list[str] = []
    for gitignore in sorted(root.rglob(".gitignore")):
        if "node_modules" in gitignore.parts or ".venv" in gitignore.parts:
            continue
        base = gitignore.parent
        for raw in gitignore.read_text(encoding="utf-8", errors="replace").splitlines():
            entry = raw.strip()
            if not entry or entry.startswith("#") or entry.startswith("!"):
                continue
            if any(ch in entry for ch in "*?["):
                continue  # globs describe classes of file, not specific intent
            target = base / entry.rstrip("/")
            if target.name in _REGENERABLE or not target.exists():
                continue
            found.append(str(target.relative_to(root)))
    return sorted(set(found))


def _human_size(path: Path) -> str:
    total = float(
        path.stat().st_size
        if path.is_file()
        else sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    )
    for unit in ("B", "K", "M", "G"):
        if total < 1024 or unit == "G":
            return f"{total:.0f}{unit}" if unit == "B" else f"{total:.1f}{unit}"
        total /= 1024.0
    return f"{total:.1f}G"


def last_touched(root: Path, path: str) -> str | None:
    out = _git(root, "log", "-1", "--format=%ad", "--date=short", "--", path).strip()
    return out or None


# ---------------------------------------------------------------------------
# Reachability: which backend modules can the running service actually reach?
# ---------------------------------------------------------------------------


def _module_name(root: Path, path: Path) -> str:
    rel = path.relative_to(root / "backend").with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(source: str) -> set[str]:
    """Every ``app.*`` module named by an import anywhere in the file.

    Walks the whole tree rather than just top level, so a deferred import
    inside a function body (the pattern `deps.py` uses for `redis_client`)
    still counts as a real edge.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names if a.name.startswith("app."))
        elif isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app"):
            out.add(node.module)
            # `from app.services import foo` — foo may itself be a module.
            out.update(f"{node.module}.{a.name}" for a in node.names)
    return out


def unreachable_modules(root: Path) -> tuple[list[str], set[str]]:
    """Backend modules no entry point can reach, plus those only tests import."""
    app_dir = root / "backend" / "app"
    graph: dict[str, set[str]] = {}
    for path in sorted(app_dir.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        graph[_module_name(root, path)] = _imports(
            path.read_text(encoding="utf-8", errors="replace")
        )

    roots = [m for m in graph if m in _ENTRY_MODULES or m.startswith(_ENTRY_PACKAGES)]
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for target in graph.get(current, ()):  # unknown targets are stdlib/3rd-party
            if target in graph and target not in seen:
                stack.append(target)

    test_dir = root / "backend" / "tests"
    test_imports: set[str] = set()
    for path in sorted(test_dir.rglob("*.py")) if test_dir.exists() else []:
        test_imports |= _imports(path.read_text(encoding="utf-8", errors="replace"))

    return sorted(set(graph) - seen), test_imports


# ---------------------------------------------------------------------------
# Reference scan for everything that is not a Python module
# ---------------------------------------------------------------------------


def build_reference_index(root: Path, tracked: list[str]) -> dict[str, str]:
    index: dict[str, str] = {}
    for rel in tracked:
        path = root / rel
        if path.suffix not in _SCANNABLE or not path.exists():
            continue
        if rel in _SELF_DESCRIBING:
            continue
        try:
            if path.stat().st_size > _MAX_BYTES:
                continue
            index[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return index


def references_to(rel: str, index: dict[str, str]) -> list[str]:
    """Files mentioning ``rel`` by path or basename, excluding itself."""
    name = Path(rel).name
    hits: list[str] = []
    for source, text in index.items():
        if source == rel:
            continue
        if rel in text or name in text:
            hits.append(source)
    return sorted(hits)


# ---------------------------------------------------------------------------
# The keep register, and its lapse checks
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KeepEntry:
    id: str
    paths: tuple[str, ...]
    bucket: str
    citation: str
    reason: str
    lapse: dict[str, str]

    def covers(self, rel: str) -> bool:
        """Does this entry protect ``rel``? Directory entries cover their tree."""
        for raw in self.paths:
            target = raw.split("::", 1)[0]
            if rel == target or rel.startswith(target.rstrip("/") + "/"):
                return True
        return False


def load_register(root: Path) -> list[KeepEntry]:
    path = root / "docs" / "keep-register.toml"
    if not path.exists():
        raise SystemExit(f"keep register missing: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return [
        KeepEntry(
            id=raw["id"],
            paths=tuple(raw["paths"]),
            bucket=raw["bucket"],
            citation=raw["citation"],
            reason=" ".join(raw["reason"].split()),
            lapse=raw.get("lapse", {"kind": "manual", "question": "(none recorded)"}),
        )
        for raw in data.get("keep", [])
    ]


def evaluate_lapse(root: Path, entry: KeepEntry) -> tuple[bool, str]:
    """``(has_lapsed, description_of_the_check_that_ran)``.

    A `manual` check never lapses automatically. That is the honest answer
    when a checkout cannot see the evidence — reporting the question beats
    guessing, and guessing here means proposing an irreversible deletion.
    """
    kind = entry.lapse.get("kind", "manual")
    if kind == "manual":
        return False, "manual — " + " ".join(entry.lapse.get("question", "").split())

    target = root / entry.lapse["path"]
    pattern = entry.lapse["pattern"]
    text = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
    present = bool(re.search(pattern, text))
    lapsed = present if kind == "file_contains" else not present
    verb = "found" if present else "not found"
    return lapsed, f"{kind}: /{pattern}/ {verb} in {entry.lapse['path']}"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_BUCKET_BY_REGISTER = {
    "documented": Bucket.KEEP_DOCUMENTED,
    "reader_pending": Bucket.KEEP_READER_PENDING,
}


def classify(root: Path) -> list[Finding]:
    register = load_register(root)
    tracked = tracked_files(root)
    index = build_reference_index(root, tracked)
    findings: list[Finding] = []

    # 1. Register entries first, so nothing protected can reach the reference
    #    or reachability paths and be proposed for removal by them.
    for entry in register:
        lapsed, check = evaluate_lapse(root, entry)
        findings.append(
            Finding(
                path=", ".join(entry.paths),
                bucket=Bucket.REVIEW if lapsed else _BUCKET_BY_REGISTER[entry.bucket],
                why=(
                    entry.lapse.get("means", "").strip().replace("\n", " ")
                    if lapsed
                    else entry.reason
                ),
                citation=entry.citation,
                check=check,
            )
        )

    def is_protected(rel: str) -> bool:
        return any(e.covers(rel) for e in register)

    # 2. Backend modules nothing can reach.
    unreachable, test_imports = unreachable_modules(root)
    for module in unreachable:
        rel = "backend/" + module.replace(".", "/")
        candidate = rel + ".py"
        if not (root / candidate).exists():
            # A bare package. Its `__init__.py` is a marker that exists so the
            # package imports at all, so an unreferenced one says nothing.
            continue
        if is_protected(candidate) or is_protected(rel):
            continue
        only_tests = module in test_imports
        findings.append(
            Finding(
                path=candidate,
                bucket=Bucket.REMOVE,
                why=(
                    "No entry point reaches this module; only tests import it."
                    if only_tests
                    else "No entry point reaches this module and no test imports it."
                ),
                last_touched=last_touched(root, candidate),
            )
        )

    # 3. Tracked non-Python files nothing references, and the subtler case:
    #    referenced only from prose. A config that only documentation mentions
    #    is not in use — it just looks alive, which is how a dead deploy target
    #    survives three README mentions.
    for rel in tracked:
        name = Path(rel).name.lower()
        if rel.endswith(".py") or rel.startswith(_NEVER_BY_REFERENCE):
            continue
        if is_protected(rel) or name.startswith("readme"):
            continue
        if name.startswith(".") or name in _CONVENTION_LOADED:
            continue  # found by name by its own tooling
        refs = references_to(rel, index)
        if not refs:
            findings.append(
                Finding(
                    path=rel,
                    bucket=Bucket.REMOVE,
                    why="Nothing in the repo references this file.",
                    last_touched=last_touched(root, rel),
                )
            )
            continue
        if Path(rel).suffix.lower() in _DOCUMENT_SUFFIXES:
            continue  # a document referenced from prose is a document in use
        if not [r for r in refs if Path(r).suffix in _CODE_REFERENCE_SUFFIXES]:
            findings.append(
                Finding(
                    path=rel,
                    bucket=Bucket.REVIEW_PROSE_ONLY,
                    why=(
                        "Documentation describes it, but no code, config or workflow "
                        "loads it. Either it is a manual tool whose instructions are "
                        "its invocation, or it is dead and the prose is keeping it "
                        "looking alive. That distinction is yours, not the tool's."
                    ),
                    refs=refs,
                    last_touched=last_touched(root, rel),
                )
            )

    # 4. Explicitly ignored and present: deliberate local files.
    for rel in ignored_but_present(root):
        findings.append(
            Finding(
                path=f"{rel}  ({_human_size(root / rel)})",
                bucket=Bucket.LOCAL_SCRATCH,
                why=(
                    "Explicitly listed in a .gitignore and present on disk: a deliberate "
                    "local working file, not repo fat. Yours to delete or keep; nothing "
                    "in the repo depends on it either way."
                ),
            )
        )

    order = list(Bucket)
    findings.sort(key=lambda f: (order.index(f.bucket), f.path))
    return findings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def render(findings: list[Finding]) -> str:
    lines = [
        "Dead-weight triage report",
        "=" * 72,
        "",
        "Classification only. Nothing here has been changed, and only the",
        "'remove' buckets are recommendations. Register entries are reported",
        "with the lapse check that was actually run against them.",
        "",
    ]
    for bucket in Bucket:
        group = [f for f in findings if f.bucket is bucket]
        if not group:
            continue
        lines.append(f"{bucket.value.upper()}  ({len(group)})")
        lines.append("-" * 72)
        for finding in group:
            stamp = f"  [last touched {finding.last_touched}]" if finding.last_touched else ""
            lines.append(f"  {finding.path}{stamp}")
            lines.append(f"      {finding.why}")
            if finding.citation:
                lines.append(f"      cited: {finding.citation}")
            if finding.check:
                lines.append(f"      checked: {finding.check}")
            if finding.refs:
                shown = ", ".join(finding.refs[:6])
                extra = f" (+{len(finding.refs) - 6} more)" if len(finding.refs) > 6 else ""
                lines.append(f"      referenced by: {shown}{extra}")
            lines.append("")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli.triage",
        description="Classify repo dead weight. Reports; never deletes.",
    )
    parser.add_argument(
        "--bucket",
        action="append",
        choices=[b.name.lower() for b in Bucket],
        help="Limit output to one or more buckets (repeatable).",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    findings = classify(root)
    if args.bucket:
        wanted = {Bucket[name.upper()] for name in args.bucket}
        findings = [f for f in findings if f.bucket in wanted]
    sys.stdout.write(render(findings))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
