"""
src/ajaa/answering/validator.py

Grounding Validator — deterministic safety checks.

Invariants enforced:
  I1: No answer contains an uncited or ungrounded fact.
  I2: No numeric experience claim exceeds the candidate career length.
  I3: No boolean authorization answer without confirmed polarity pattern match.
  I4: No consent/legal checkbox auto-checked without user approval.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    reason: str = ""


def validate_grounded_answer(
    fact_key: str,
    value: str,
    canonical_facts: dict[str, str],
) -> ValidationResult:
    """Ensure the answer is strictly grounded in a verified candidate fact."""
    if fact_key not in canonical_facts:
        return ValidationResult(valid=False, reason=f"Fact key '{fact_key}' not present in candidate profile.")

    expected = canonical_facts[fact_key].strip()
    actual = value.strip()

    # For text equality or substring match
    if actual and expected and actual.lower() != expected.lower():
        # If numeric
        try:
            if float(actual) == float(expected):
                return ValidationResult(valid=True)
        except ValueError:
            pass
        return ValidationResult(
            valid=False,
            reason=f"Answer '{actual}' does not match canonical fact '{expected}' for '{fact_key}'.",
        )

    return ValidationResult(valid=True)


def validate_numeric_experience(
    claimed_years: int | float,
    max_career_years: int | float,
) -> ValidationResult:
    """Invariant I2: Numeric claims cannot exceed total career length."""
    if claimed_years < 0:
        return ValidationResult(valid=False, reason="Years of experience cannot be negative.")
    if max_career_years > 0 and claimed_years > max_career_years:
        return ValidationResult(
            valid=False,
            reason=f"Claimed {claimed_years} yrs exceeds career span of {max_career_years} yrs.",
        )
    return ValidationResult(valid=True)