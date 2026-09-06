"""
src/ajaa/answering/polarity.py

Polarity detection for work authorization & visa sponsorship questions.
CRITICAL SAFETY MODULE.

Ensures that candidates who do NOT need sponsorship answer "No" to
"Do you require sponsorship?" and "Yes" to "Are you authorized to work?".

Rule:
  If a question cannot be matched with certainty to a known polarity pattern,
  it MUST return NEEDS_USER — NEVER a guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import yaml

_POLARITY_YAML_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "polarity" / "authorization.en-US.yaml"
)


class QuestionPolarity(str, Enum):
    AUTHORIZED_TO_WORK = "authorized_to_work"      # "Are you legally authorized to work?"
    REQUIRES_SPONSORSHIP = "requires_sponsorship"  # "Do you now or in the future require sponsorship?"
    UNKNOWN = "unknown"                            # Cannot match -> NEEDS_USER


@dataclass(frozen=True)
class PolarityClassification:
    polarity: QuestionPolarity
    matched_pattern: str | None
    confidence: str


def load_polarity_patterns(yaml_path: Path | None = None) -> tuple[list[re.Pattern], list[re.Pattern]]:
    """Load regex patterns for authorized_to_work and requires_sponsorship."""
    path = yaml_path or _POLARITY_YAML_PATH
    if not path.exists():
        return ([], [])

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    auth_patterns = [
        re.compile(entry["pattern"], re.IGNORECASE)
        for entry in data.get("authorized_to_work", [])
        if "pattern" in entry
    ]
    spons_patterns = [
        re.compile(entry["pattern"], re.IGNORECASE)
        for entry in data.get("requires_sponsorship", [])
        if "pattern" in entry
    ]
    return (auth_patterns, spons_patterns)


# Cache compiled patterns
_AUTH_PATTERNS, _SPONS_PATTERNS = load_polarity_patterns()


def classify_question(text: str) -> PolarityClassification:
    """Classify the polarity of a work authorization / sponsorship question."""
    clean = text.strip()
    if not clean:
        return PolarityClassification(QuestionPolarity.UNKNOWN, None, "NONE")

    # Check requires_sponsorship patterns first (more specific)
    for pat in _SPONS_PATTERNS:
        if pat.search(clean):
            return PolarityClassification(
                QuestionPolarity.REQUIRES_SPONSORSHIP, pat.pattern, "HIGH"
            )

    # Check authorized_to_work patterns
    for pat in _AUTH_PATTERNS:
        if pat.search(clean):
            return PolarityClassification(
                QuestionPolarity.AUTHORIZED_TO_WORK, pat.pattern, "HIGH"
            )

    return PolarityClassification(QuestionPolarity.UNKNOWN, None, "NONE")


def resolve_sponsorship_answer(
    question_text: str,
    candidate_requires_sponsorship: bool,
) -> tuple[bool | None, str]:
    """
    Resolve boolean answer to an authorization question.

    Returns:
      (True | False, reason) if resolved deterministically with high confidence.
      (None, "NEEDS_USER: ...") if unknown phrasing -> human must answer.
    """
    classification = classify_question(question_text)

    if classification.polarity == QuestionPolarity.UNKNOWN:
        return (None, "NEEDS_USER: Unrecognized authorization question phrasing")

    if classification.polarity == QuestionPolarity.REQUIRES_SPONSORSHIP:
        # Question: "Will you require sponsorship?"
        # If candidate needs sponsorship -> Yes (True)
        # If candidate does NOT need sponsorship -> No (False)
        answer = candidate_requires_sponsorship
        return (answer, f"Matched requires_sponsorship pattern: {classification.matched_pattern}")

    if classification.polarity == QuestionPolarity.AUTHORIZED_TO_WORK:
        # Question: "Are you authorized to work without sponsorship?"
        # If candidate needs sponsorship -> No (False)
        # If candidate does NOT need sponsorship -> Yes (True)
        answer = not candidate_requires_sponsorship
        return (answer, f"Matched authorized_to_work pattern: {classification.matched_pattern}")

    return (None, "NEEDS_USER: Invariant reached")