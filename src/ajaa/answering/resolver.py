"""
src/ajaa/answering/resolver.py

Form Field Resolution Engine.

Maps ATS form fields / screening questions deterministically to candidate facts.
Returns AnswerResolution with status:
  - RESOLVED: answer found and grounded in CanonicalProfile
  - NEEDS_USER: unknown question, ungrounded claim, or ambiguous phrasing
  - SKIPPED: optional field not required
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ajaa.answering.polarity import resolve_sponsorship_answer
from ajaa.answering.validator import validate_grounded_answer


class ResolutionStatus(str, Enum):
    RESOLVED = "RESOLVED"
    NEEDS_USER = "NEEDS_USER"
    SKIPPED = "SKIPPED"


@dataclass
class FormField:
    """Descriptor of a form input field detected in an ATS."""
    name: str                        # input name or id attribute
    label: str                       # visual label or question text
    field_type: str = "text"         # text, email, tel, select, radio, checkbox, textarea
    required: bool = True
    options: list[str] = field(default_factory=list)  # for select/radio


@dataclass
class AnswerResolution:
    field_name: str
    value: Any
    status: ResolutionStatus
    fact_key: str | None = None
    reason: str = ""


# Field name / label patterns to CanonicalProfile keys
_FIELD_MAPPINGS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(full\s*name|legal\s*name|your\s*name)\b", re.I), "personal.name.full"),
    (re.compile(r"\b(first\s*name|given\s*name)\b", re.I), "personal.name.first"),
    (re.compile(r"\b(last\s*name|family\s*name|surname)\b", re.I), "personal.name.last"),
    (re.compile(r"\b(e-?mail|email\s*address)\b", re.I), "personal.email.primary"),
    (re.compile(r"\b(phone|mobile|telephone|contact\s*number)\b", re.I), "personal.phone.primary"),
    (re.compile(r"\b(city|current\s*city)\b", re.I), "personal.location.city"),
    (re.compile(r"\b(country|current\s*country)\b", re.I), "personal.location.country"),
    (re.compile(r"\b(linkedin|linked\s*in)\b", re.I), "personal.linkedin_url"),
    (re.compile(r"\b(github|git\s*hub)\b", re.I), "personal.github_url"),
    (re.compile(r"\b(portfolio|website|personal\s*site)\b", re.I), "personal.portfolio_url"),
    (re.compile(r"\b(years\s*of\s*experience|total\s*experience)\b", re.I), "personal.years_of_experience"),
    (re.compile(r"\b(summary|about\s*you|bio)\b", re.I), "personal.summary"),
    (re.compile(r"\b(expected\s*salary|desired\s*salary|compensation)\b", re.I), "preferences.salary_min_usd"),
]


def resolve_field(
    field: FormField,
    canonical_facts: dict[str, str],
) -> AnswerResolution:
    """
    Resolve a form field using candidate facts and deterministic safety rules.
    """
    label_text = f"{field.label} {field.name}".strip()

    # 1. Check for Work Authorization / Sponsorship (SAFETY CRITICAL)
    if any(k in label_text.lower() for k in ("sponsor", "authorized", "authorization", "visa", "eligib")):
        requires_sponsorship = canonical_facts.get("work_authorization.requires_sponsorship", "").lower() in ("yes", "true", "1")
        resolved_bool, reason = resolve_sponsorship_answer(label_text, requires_sponsorship)
        if resolved_bool is None:
            return AnswerResolution(
                field_name=field.name,
                value=None,
                status=ResolutionStatus.NEEDS_USER,
                reason=reason,
            )

        # Convert boolean to field format
        if field.field_type in ("select", "radio") and field.options:
            val_str = "Yes" if resolved_bool else "No"
            # match case-insensitively with available options
            matched_opt = next((opt for opt in field.options if opt.strip().lower() == val_str.lower()), None)
            if matched_opt:
                return AnswerResolution(
                    field_name=field.name,
                    value=matched_opt,
                    status=ResolutionStatus.RESOLVED,
                    fact_key="work_authorization.requires_sponsorship",
                    reason=reason,
                )
        return AnswerResolution(
            field_name=field.name,
            value="Yes" if resolved_bool else "No",
            status=ResolutionStatus.RESOLVED,
            fact_key="work_authorization.requires_sponsorship",
            reason=reason,
        )

    # 2. Check standard profile field mappings
    for pattern, fact_key in _FIELD_MAPPINGS:
        if pattern.search(label_text):
            if fact_key in canonical_facts and canonical_facts[fact_key]:
                val = canonical_facts[fact_key]
                val_res = validate_grounded_answer(fact_key, val, canonical_facts)
                if val_res.valid:
                    return AnswerResolution(
                        field_name=field.name,
                        value=val,
                        status=ResolutionStatus.RESOLVED,
                        fact_key=fact_key,
                    )

    # 3. If optional and no answer found -> SKIPPED
    if not field.required:
        return AnswerResolution(
            field_name=field.name,
            value="",
            status=ResolutionStatus.SKIPPED,
            reason="Optional field without grounded answer",
        )

    # 4. Mandatory field with no known mapping -> NEEDS_USER
    return AnswerResolution(
        field_name=field.name,
        value=None,
        status=ResolutionStatus.NEEDS_USER,
        reason=f"No grounded fact for required field: {field.label or field.name}",
    )