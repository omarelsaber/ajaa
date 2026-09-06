"""
tests/unit/test_answering.py

Unit tests for form field resolution and grounding validation.
"""
from __future__ import annotations

import pytest
from ajaa.answering.resolver import FormField, ResolutionStatus, resolve_field
from ajaa.answering.validator import validate_grounded_answer, validate_numeric_experience


@pytest.fixture
def canonical_facts() -> dict[str, str]:
    return {
        "personal.name.full": "Alice Dev",
        "personal.email.primary": "alice@example.com",
        "personal.phone.primary": "+1-555-0199",
        "personal.location.city": "Seattle",
        "personal.years_of_experience": "6",
        "work_authorization.requires_sponsorship": "No",
    }


class TestResolver:
    def test_resolve_standard_field(self, canonical_facts: dict[str, str]):
        f = FormField(name="email", label="Email Address", required=True)
        res = resolve_field(f, canonical_facts)
        assert res.status == ResolutionStatus.RESOLVED
        assert res.value == "alice@example.com"

    def test_resolve_sponsorship_field_with_polarity(self, canonical_facts: dict[str, str]):
        f = FormField(
            name="spons",
            label="Do you require sponsorship to work in the United States?",
            field_type="radio",
            required=True,
            options=["Yes", "No"],
        )
        res = resolve_field(f, canonical_facts)
        assert res.status == ResolutionStatus.RESOLVED
        assert res.value == "No"

    def test_resolve_optional_unmapped_field(self, canonical_facts: dict[str, str]):
        f = FormField(name="favorite_hobby", label="What is your favorite hobby?", required=False)
        res = resolve_field(f, canonical_facts)
        assert res.status == ResolutionStatus.SKIPPED

    def test_resolve_required_unknown_field_yields_needs_user(self, canonical_facts: dict[str, str]):
        f = FormField(name="security_clearance", label="Do you hold TS/SCI security clearance?", required=True)
        res = resolve_field(f, canonical_facts)
        assert res.status == ResolutionStatus.NEEDS_USER


class TestValidator:
    def test_validate_grounded_answer(self, canonical_facts: dict[str, str]):
        res = validate_grounded_answer("personal.email.primary", "alice@example.com", canonical_facts)
        assert res.valid

        bad_res = validate_grounded_answer("personal.email.primary", "hacker@evil.com", canonical_facts)
        assert not bad_res.valid

    def test_validate_numeric_experience(self):
        # 5 yrs claimed within 10 yrs career
        assert validate_numeric_experience(5, 10).valid

        # 15 yrs claimed exceeding 5 yrs career -> reject
        assert not validate_numeric_experience(15, 5).valid