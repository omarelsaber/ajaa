"""
tests/unit/test_repositories.py

Phase 1 acceptance tests for candidate + fact repositories and CanonicalProfile.

Covers:
  - candidate repo: create, get, guard against duplicate, update
  - fact repo: upsert, get_canonical (precedence), usable filter,
    LLM_INFERENCE blocked, coverage_summary
  - CanonicalProfile: build, get, has, uncovered, to_dict, precedence
"""
from __future__ import annotations

import pytest
from pathlib import Path

import sqlalchemy as sa

from ajaa.db.session import init_engine, reset_engine
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.db.repositories.candidate import NoCandidateError, CandidateAlreadyExistsError
from ajaa.candidate.profile import build_profile, CanonicalProfile
from ajaa.types import Confidence, FactSource, FactState


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    """Each test gets a fresh isolated SQLite database."""
    init_engine(tmp_path / "test.db")
    yield
    reset_engine()


# ── Candidate Repository ──────────────────────────────────────────────────────

class TestCandidateRepository:

    def test_get_raises_before_init(self) -> None:
        with pytest.raises(NoCandidateError):
            candidate_repo.get()

    def test_get_or_none_returns_none_before_init(self) -> None:
        assert candidate_repo.get_or_none() is None

    def test_create_and_get(self) -> None:
        ctx = candidate_repo.create(display_name="Alice", locale="en-US")
        assert ctx.id is not None
        assert ctx.display_name == "Alice"
        assert ctx.locale == "en-US"
        assert ctx.calibration_completed is False

        fetched = candidate_repo.get()
        assert fetched.id == ctx.id
        assert fetched.display_name == "Alice"

    def test_create_twice_raises(self) -> None:
        candidate_repo.create(display_name="Alice")
        with pytest.raises(CandidateAlreadyExistsError):
            candidate_repo.create(display_name="Bob")

    def test_update_display_name(self) -> None:
        candidate_repo.create(display_name="Alice")
        updated = candidate_repo.update(display_name="Alice Smith")
        assert updated.display_name == "Alice Smith"

    def test_update_calibration_flag(self) -> None:
        candidate_repo.create(display_name="Alice")
        updated = candidate_repo.update(calibration_completed=True)
        assert updated.calibration_completed is True

    def test_update_locale(self) -> None:
        candidate_repo.create(display_name="Alice")
        updated = candidate_repo.update(locale="ar-EG")
        assert updated.locale == "ar-EG"


# ── Fact Repository ───────────────────────────────────────────────────────────

class TestFactRepository:

    @pytest.fixture
    def candidate_id(self) -> str:
        return candidate_repo.create(display_name="Alice").id

    def test_upsert_creates_fact(self, candidate_id: str) -> None:
        fact = fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.name.full",
            fact_value="Alice Smith",
            source=FactSource.USER_EXPLICIT,
            confidence=Confidence.HIGH,
        )
        assert fact.id is not None
        assert fact.fact_value == "Alice Smith"
        assert fact.source_rank == 1
        assert fact.usable_in_applications is True

    def test_upsert_updates_existing(self, candidate_id: str) -> None:
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.email",
            fact_value="alice@old.com",
            source=FactSource.USER_EXPLICIT,
        )
        updated = fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.email",
            fact_value="alice@new.com",
            source=FactSource.USER_EXPLICIT,
        )
        assert updated.fact_value == "alice@new.com"

        # Only one row in DB
        from ajaa.db.session import get_session
        from ajaa.db.models import Fact
        with get_session() as session:
            count = session.execute(
                sa.select(sa.func.count()).select_from(Fact).where(
                    Fact.candidate_id == candidate_id,
                    Fact.fact_key == "personal.email",
                )
            ).scalar_one()
        assert count == 1

    def test_llm_inference_forced_unusable(self, candidate_id: str) -> None:
        fact = fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="skill.python.inferred",
            fact_value="5 years",
            source=FactSource.LLM_INFERENCE,
            confidence=Confidence.LOW,
        )
        assert fact.usable_in_applications is False

    def test_get_canonical_lower_rank_wins(self, candidate_id: str) -> None:
        # CV_EXPLICIT (rank 4) and USER_EXPLICIT (rank 1)
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.name.full",
            fact_value="Alice from CV",
            source=FactSource.CV_EXPLICIT,
        )
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.name.full",
            fact_value="Alice Smith (user said)",
            source=FactSource.USER_EXPLICIT,
        )
        canonical = fact_repo.get_canonical(candidate_id, "personal.name.full")
        assert canonical is not None
        assert canonical.fact_value == "Alice Smith (user said)"
        assert canonical.source_rank == 1

    def test_get_canonical_none_for_missing_key(self, candidate_id: str) -> None:
        result = fact_repo.get_canonical(candidate_id, "nonexistent.key")
        assert result is None

    def test_get_all_usable_excludes_llm_inference(self, candidate_id: str) -> None:
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.name.full",
            fact_value="Alice",
            source=FactSource.USER_EXPLICIT,
        )
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="skill.rust.inferred",
            fact_value="3 years",
            source=FactSource.LLM_INFERENCE,
        )
        usable = fact_repo.get_all_usable(candidate_id)
        keys = {f.fact_key for f in usable}
        assert "personal.name.full" in keys
        assert "skill.rust.inferred" not in keys

    def test_coverage_summary(self, candidate_id: str) -> None:
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.name.full",
            fact_value="Alice",
            source=FactSource.USER_EXPLICIT,
        )
        coverage = fact_repo.coverage_summary(
            candidate_id, ["personal.name.full", "personal.phone"]
        )
        assert coverage["personal.name.full"] is True
        assert coverage["personal.phone"] is False

    def test_mark_stale(self, candidate_id: str) -> None:
        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key="personal.address",
            fact_value="123 Main St",
            source=FactSource.USER_EXPLICIT,
        )
        marked = fact_repo.mark_stale(candidate_id, "personal.address", FactSource.USER_EXPLICIT)
        assert marked is True

        canonical = fact_repo.get_canonical(candidate_id, "personal.address")
        assert canonical is not None
        # mark_stale sets state to UNKNOWN (value is outdated, interview will re-ask)
        assert canonical.state == FactState.UNKNOWN.value


# ── CanonicalProfile ──────────────────────────────────────────────────────────

class TestCanonicalProfile:

    @pytest.fixture
    def profile_with_facts(self) -> CanonicalProfile:
        ctx = candidate_repo.create(display_name="Alice Smith")
        cid = ctx.id
        fact_repo.upsert(cid, "personal.name.full", "Alice Smith", FactSource.USER_EXPLICIT, Confidence.HIGH)
        fact_repo.upsert(cid, "personal.email", "alice@example.com", FactSource.USER_EXPLICIT, Confidence.HIGH)
        fact_repo.upsert(cid, "personal.name.full", "Alice from CV", FactSource.CV_EXPLICIT)
        fact_repo.upsert(cid, "skill.python.years", "5", FactSource.CV_EXPLICIT, Confidence.MEDIUM)
        fact_repo.upsert(cid, "skill.rust.inferred", "2", FactSource.LLM_INFERENCE, Confidence.LOW)
        return build_profile()

    def test_build_profile(self, profile_with_facts: CanonicalProfile) -> None:
        assert profile_with_facts.display_name == "Alice Smith"
        assert profile_with_facts.calibration_completed is False

    def test_get_canonical_value(self, profile_with_facts: CanonicalProfile) -> None:
        # USER_EXPLICIT wins over CV_EXPLICIT for same key
        assert profile_with_facts.get("personal.name.full") == "Alice Smith"

    def test_get_missing_key_returns_none(self, profile_with_facts: CanonicalProfile) -> None:
        assert profile_with_facts.get("nonexistent.key") is None

    def test_llm_inference_not_in_get(self, profile_with_facts: CanonicalProfile) -> None:
        # LLM_INFERENCE is in the fact ledger but get() must return None
        assert profile_with_facts.get("skill.rust.inferred") is None

    def test_has(self, profile_with_facts: CanonicalProfile) -> None:
        assert profile_with_facts.has("personal.email") is True
        assert profile_with_facts.has("personal.phone") is False

    def test_uncovered(self, profile_with_facts: CanonicalProfile) -> None:
        missing = profile_with_facts.uncovered(["personal.email", "personal.phone", "personal.name.full"])
        assert missing == ["personal.phone"]

    def test_to_dict_excludes_llm_inference(self, profile_with_facts: CanonicalProfile) -> None:
        d = profile_with_facts.to_dict()
        assert "personal.name.full" in d
        assert "personal.email" in d
        assert "skill.rust.inferred" not in d  # LLM_INFERENCE blocked

    def test_keys_by_prefix(self, profile_with_facts: CanonicalProfile) -> None:
        keys = profile_with_facts.keys_by_prefix("skill.")
        assert "skill.python.years" in keys
        assert "skill.rust.inferred" not in keys

    def test_get_with_source(self, profile_with_facts: CanonicalProfile) -> None:
        result = profile_with_facts.get_with_source("personal.name.full")
        assert result is not None
        value, source = result
        assert value == "Alice Smith"
        assert source == FactSource.USER_EXPLICIT

    def test_profile_is_frozen(self, profile_with_facts: CanonicalProfile) -> None:
        with pytest.raises((AttributeError, TypeError)):
            profile_with_facts.display_name = "Hacked"  # type: ignore[misc]

    def test_repr_contains_fact_count(self, profile_with_facts: CanonicalProfile) -> None:
        r = repr(profile_with_facts)
        assert "CanonicalProfile" in r
        assert "facts_covered" in r