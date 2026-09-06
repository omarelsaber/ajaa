"""
test_no_personal_strings.py

Guard: no personal identifying strings should appear in source code,
prompt templates, or config templates.

This test runs as a pre-push hook via pre-commit.
It ensures the repository does not inadvertently encode the maintainer's
personal details, making the codebase non-generic.

Add to DENYLIST any string that would identify a real person:
  - Real names
  - Real employers
  - Real email addresses
  - Real phone numbers
  - Real addresses
  - Real institution names specific to one person

Keep this list short and authoritative. It is NOT a spam filter.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

# ── Strings that must NEVER appear in committed source ────────────────────────
# These are intentionally generic placeholders.
# MAINTAINER: do not add your real personal details here — add a pattern instead.
DENYLIST: list[str] = [
    # Add real personal strings here as patterns or literals.
    # Example (do not use real values):
    # "john.doe@example.com",
    # "Acme Corporation",
]

# ── Paths to scan ─────────────────────────────────────────────────────────────
SCAN_PATHS = [
    "src/ajaa",
    "configs",
    "data",
    "tests",
    ".github",
]

# ── Extensions to scan ────────────────────────────────────────────────────────
SCAN_EXTENSIONS = {".py", ".yaml", ".yml", ".md", ".txt", ".toml", ".json"}

# ── Paths to skip ─────────────────────────────────────────────────────────────
SKIP_PATHS = {
    "tests/adversarial",  # adversarial corpus intentionally contains suspicious strings
    "docs",               # docs may quote PRD text
}


def _get_files() -> list[pathlib.Path]:
    repo_root = pathlib.Path(__file__).parent.parent
    files: list[pathlib.Path] = []
    for scan_path in SCAN_PATHS:
        p = repo_root / scan_path
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in SCAN_EXTENSIONS:
                continue
            # Check if any parent is in SKIP_PATHS
            rel = f.relative_to(repo_root)
            skip = any(str(rel).startswith(s) for s in SKIP_PATHS)
            if skip:
                continue
            files.append(f)
    return files


@pytest.mark.parametrize("denied", DENYLIST if DENYLIST else ["__placeholder__"])
def test_no_personal_strings(denied: str) -> None:
    """No personal string from the denylist appears in any source file."""
    if denied == "__placeholder__":
        pytest.skip("Denylist is empty — add real personal strings to enforce this test")
        return

    files = _get_files()
    violations: list[str] = []
    pattern = re.compile(re.escape(denied), re.IGNORECASE)

    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if pattern.search(text):
            violations.append(str(f))

    assert not violations, (
        f"Personal string {denied!r} found in:\n" + "\n".join(violations)
    )
