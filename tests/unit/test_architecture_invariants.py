"""
tests/unit/test_architecture_invariants.py

Architectural Invariant Enforcement (PRD §4.1, §9.8, §13.4).

Verifies core architectural constraints via static AST inspection and unit tests:
  1. test_import_graph_candidate_context: Engine modules must NOT import DB repositories directly.
  2. test_no_candidate_data_in_system_prompts: Prompt templates never interpolate facts into SYSTEM.
  3. test_secret_type_safety: Secret cannot be stringified, repr'd, or serialized.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
import pytest

from ajaa.types import Secret

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ENGINE_DIRS = [
    REPO_ROOT / "src" / "ajaa" / "matcher",
    REPO_ROOT / "src" / "ajaa" / "answering",
    REPO_ROOT / "src" / "ajaa" / "browser",
    REPO_ROOT / "src" / "ajaa" / "application" / "connectors",
]


def test_import_graph_candidate_context() -> None:
    """
    PRD §4.1 The Fundamental Rule:
    No engine module imports a fact repository, CV store, ontology loader,
    or policy loader directly. Every engine receives a CandidateContext.
    """
    forbidden_modules = [
        "ajaa.db.repositories",
        "ajaa.cv.store",
    ]

    violations: list[str] = []

    for engine_dir in ENGINE_DIRS:
        if not engine_dir.exists():
            continue
        for py_file in engine_dir.glob("**/*.py"):
            if py_file.name.startswith("__"):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        for forbidden in forbidden_modules:
                            if alias.name.startswith(forbidden):
                                violations.append(f"{py_file.name}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        for forbidden in forbidden_modules:
                            if node.module.startswith(forbidden):
                                violations.append(f"{py_file.name}: imports from {node.module}")

    assert not violations, f"Architectural import boundary violations detected:\n" + "\n".join(violations)


def test_no_candidate_data_in_system_prompts() -> None:
    """
    PRD §9.8 / Invariant I9:
    No prompt template contains an interpolation of candidate facts or personal data into SYSTEM.
    Candidate data belongs exclusively in the CONTEXT channel.
    """
    prompts_dir = REPO_ROOT / "src" / "ajaa" / "llm" / "prompts"
    if not prompts_dir.exists():
        pytest.skip("Prompts directory does not exist")

    forbidden_placeholders = [
        "{candidate_name}",
        "{candidate_facts}",
        "{fact_value}",
        "{cv_text}",
        "{candidate_email}",
        "{candidate_phone}",
    ]

    violations: list[str] = []
    for prompt_file in prompts_dir.glob("**/*.md"):
        content = prompt_file.read_text(encoding="utf-8")
        for ph in forbidden_placeholders:
            if ph in content:
                violations.append(f"{prompt_file.name}: contains forbidden placeholder {ph} in template")

    assert not violations, "Prompt channel separation violations detected:\n" + "\n".join(violations)


def test_secret_type_safety() -> None:
    """
    PRD §9.3: Secret type cannot be stringified, repr'd, or JSON-serialized.
    The raw value is only accessible via explicit .reveal().
    """
    raw = "sk-super-secret-key-12345"
    s = Secret(raw)

    # 1. str() raises TypeError (cannot even be converted to str!)
    with pytest.raises(TypeError):
        str(s)

    # 2. repr() does not leak
    assert repr(s) == "<Secret redacted>"
    assert raw not in repr(s)

    # 3. f-string raises TypeError
    with pytest.raises(TypeError):
        f"{s}"

    # 4. JSON dump fails
    with pytest.raises(TypeError):
        json.dumps({"key": s})

    # 5. Only .reveal() yields raw value
    assert s.reveal() == raw
