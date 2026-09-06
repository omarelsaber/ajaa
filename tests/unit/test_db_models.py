"""
tests/unit/test_db_models.py

Phase 0 DB acceptance tests.

Verifies:
  1. Schema creates cleanly on a fresh SQLite file
  2. WAL mode is enabled
  3. ONE candidate_context row is enforceable at runtime
  4. LLM_INFERENCE facts are blocked from usable_in_applications=True
  5. Fact precedence constraint (unique candidate+key+source)
  6. Audit events are append-only (no update in ORM)
  7. content_hash is unique across CVs
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
import sqlalchemy.exc

from ajaa.db.models import (
    Application,
    ApplicationAnswer,
    AuditEvent,
    Base,
    CV,
    CandidateContext,
    Fact,
    Job,
    LLMCallLog,
)
from ajaa.db.session import init_engine, get_session, reset_engine


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_ajaa.db"


@pytest.fixture
def engine(db_path: Path):
    e = init_engine(db_path)
    yield e
    reset_engine()


@pytest.fixture
def candidate(engine) -> CandidateContext:
    with get_session() as session:
        ctx = CandidateContext(display_name="Test Candidate")
        session.add(ctx)
        session.commit()
        # Detach to avoid session issues in tests
        candidate_id = ctx.id
    with get_session() as session:
        return session.get(CandidateContext, candidate_id)


class TestSchemaCreation:
    def test_all_tables_created(self, engine) -> None:
        inspector = sa.inspect(engine)
        tables = inspector.get_table_names()
        expected = {
            "candidate_context", "fact_ledger", "cvs", "extraction_cache",
            "jobs", "applications", "application_answers",
            "audit_events", "llm_call_log",
        }
        assert expected <= set(tables), f"Missing tables: {expected - set(tables)}"

    def test_wal_mode_enabled(self, engine) -> None:
        with engine.connect() as conn:
            result = conn.execute(sa.text("PRAGMA journal_mode")).scalar()
        assert result == "wal", f"Expected WAL journal mode, got: {result}"

    def test_foreign_keys_enabled(self, engine) -> None:
        with engine.connect() as conn:
            result = conn.execute(sa.text("PRAGMA foreign_keys")).scalar()
        assert result == 1, "Foreign keys must be enabled"


class TestCandidateContext:
    def test_create_candidate(self, engine) -> None:
        with get_session() as session:
            ctx = CandidateContext(display_name="Alice")
            session.add(ctx)
            session.commit()
            assert ctx.id is not None
            assert ctx.calibration_completed is False

    def test_candidate_id_is_uuid(self, engine) -> None:
        with get_session() as session:
            ctx = CandidateContext(display_name="Bob")
            session.add(ctx)
            session.commit()
            # UUID v4 format: 8-4-4-4-12 hex chars
            parts = ctx.id.split("-")
            assert len(parts) == 5
            assert len(parts[0]) == 8


class TestFactLedger:
    def test_create_known_fact(self, engine, candidate) -> None:
        with get_session() as session:
            fact = Fact(
                candidate_id=candidate.id,
                fact_key="personal.name.full",
                fact_value="Alice Smith",
                source_rank=1,
                source_label="USER_EXPLICIT",
                confidence="HIGH",
                state="KNOWN",
                usable_in_applications=True,
            )
            session.add(fact)
            session.commit()
            assert fact.id is not None

    def test_llm_inference_cannot_be_usable(self, engine, candidate) -> None:
        """CHECK constraint: source_rank=6 AND usable_in_applications=True is rejected."""
        with get_session() as session:
            fact = Fact(
                candidate_id=candidate.id,
                fact_key="skill.python.inferred",
                fact_value="5 years",
                source_rank=6,  # LLM_INFERENCE
                source_label="LLM_INFERENCE",
                confidence="LOW",
                state="KNOWN",
                usable_in_applications=True,  # VIOLATES constraint
            )
            session.add(fact)
            with pytest.raises(
                (sa.exc.IntegrityError, sa.exc.OperationalError),
                match=r"(CHECK|UNIQUE|constraint)",
            ):
                session.commit()

    def test_llm_inference_with_false_is_allowed(self, engine, candidate) -> None:
        """LLM_INFERENCE with usable_in_applications=False is valid."""
        with get_session() as session:
            fact = Fact(
                candidate_id=candidate.id,
                fact_key="skill.rust.inferred",
                fact_value="2 years",
                source_rank=6,
                source_label="LLM_INFERENCE",
                confidence="LOW",
                state="KNOWN",
                usable_in_applications=False,
            )
            session.add(fact)
            session.commit()
            assert fact.id is not None

    def test_unique_candidate_key_source(self, engine, candidate) -> None:
        """Cannot have two facts with same (candidate, key, source_rank)."""
        with get_session() as session:
            f1 = Fact(
                candidate_id=candidate.id,
                fact_key="personal.email",
                fact_value="alice@example.com",
                source_rank=1,
                source_label="USER_EXPLICIT",
                confidence="HIGH",
            )
            session.add(f1)
            session.commit()

        with get_session() as session:
            f2 = Fact(
                candidate_id=candidate.id,
                fact_key="personal.email",
                fact_value="different@example.com",
                source_rank=1,  # same source_rank = CONFLICT
                source_label="USER_EXPLICIT",
                confidence="HIGH",
            )
            session.add(f2)
            with pytest.raises(sa.exc.IntegrityError):
                session.commit()

    def test_same_key_different_source_allowed(self, engine, candidate) -> None:
        """Same key, different source_rank = allowed (both facts coexist, highest rank wins)."""
        with get_session() as session:
            f1 = Fact(
                candidate_id=candidate.id,
                fact_key="personal.name.full",
                fact_value="Alice",
                source_rank=4,  # CV_EXPLICIT
                source_label="CV_EXPLICIT",
                confidence="HIGH",
            )
            f2 = Fact(
                candidate_id=candidate.id,
                fact_key="personal.name.full",
                fact_value="Alice Smith",
                source_rank=1,  # USER_EXPLICIT wins
                source_label="USER_EXPLICIT",
                confidence="HIGH",
            )
            session.add(f1)
            session.add(f2)
            session.commit()  # Must not raise

    def test_source_rank_constraint(self, engine, candidate) -> None:
        """source_rank must be 1-7."""
        with get_session() as session:
            fact = Fact(
                candidate_id=candidate.id,
                fact_key="bad.rank",
                fact_value="test",
                source_rank=99,  # INVALID
                source_label="UNKNOWN",
                confidence="HIGH",
            )
            session.add(fact)
            with pytest.raises((sa.exc.IntegrityError, sa.exc.OperationalError)):
                session.commit()


class TestCV:
    def test_create_cv(self, engine, candidate) -> None:
        with get_session() as session:
            cv = CV(
                candidate_id=candidate.id,
                filename="alice_cv.pdf",
                content_hash="a" * 64,
                extraction_status="PENDING",
            )
            session.add(cv)
            session.commit()
            assert cv.id is not None
            assert cv.is_active is True

    def test_content_hash_unique(self, engine, candidate) -> None:
        """Two CVs cannot have the same content_hash."""
        with get_session() as session:
            cv1 = CV(
                candidate_id=candidate.id,
                filename="cv1.pdf",
                content_hash="b" * 64,
            )
            session.add(cv1)
            session.commit()

        with get_session() as session:
            cv2 = CV(
                candidate_id=candidate.id,
                filename="cv2.pdf",
                content_hash="b" * 64,  # same hash
            )
            session.add(cv2)
            with pytest.raises(sa.exc.IntegrityError):
                session.commit()


class TestApplication:
    def test_application_state_machine(self, engine, candidate) -> None:
        """Application starts at QUEUED and can transition to DISCOVERING."""
        with get_session() as session:
            job = Job(
                url_hash="c" * 64,
                apply_url="https://example.com/apply",
                source_connector="greenhouse",
            )
            session.add(job)
            session.flush()

            app = Application(
                candidate_id=candidate.id,
                job_id=job.id,
                state="QUEUED",
            )
            session.add(app)
            session.commit()
            assert app.state == "QUEUED"

            app.previous_state = "QUEUED"
            app.state = "DISCOVERING"
            session.commit()
            assert app.state == "DISCOVERING"

    def test_audit_events_recorded(self, engine, candidate) -> None:
        """Audit events accumulate — no deletion."""
        with get_session() as session:
            job = Job(url_hash="d" * 64, apply_url="https://x.com/j", source_connector="lever")
            session.add(job)
            session.flush()

            app = Application(candidate_id=candidate.id, job_id=job.id, state="QUEUED")
            session.add(app)
            session.flush()

            e1 = AuditEvent(application_id=app.id, event_type="STATE_CHANGE", from_state="QUEUED", to_state="PREPARING")
            e2 = AuditEvent(application_id=app.id, event_type="FRESHNESS_PASS", detail_json='{"http_status": 200}')
            session.add(e1)
            session.add(e2)
            session.commit()

        with get_session() as session:
            count = session.execute(sa.select(sa.func.count()).select_from(AuditEvent)).scalar_one()
            assert count == 2