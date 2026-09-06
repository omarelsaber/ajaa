"""
tests/unit/test_application_state_machine.py

Unit tests for application state transitions and approval gates.
"""
from __future__ import annotations

from pathlib import Path
import pytest

from ajaa.application.state_machine import (
    ApplicationState,
    approve_application,
    prepare_application,
    submit_application,
)
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.db.session import get_session, init_engine, reset_engine
from ajaa.db.models import Application, Job
from ajaa.types import Confidence, FactSource, FactState
from ajaa.scraper.base import RawJob
from ajaa.scraper.normalizer import ingest_job


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_app_sm.db")
    yield
    reset_engine()


@pytest.fixture
def candidate_with_facts() -> str:
    cand = candidate_repo.create(display_name="Tester")
    cid = cand.id
    fact_repo.upsert(cid, "personal.name.full", "Test User", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "personal.email.primary", "user@test.com", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "personal.phone.primary", "+1-555-9999", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    fact_repo.upsert(cid, "work_authorization.requires_sponsorship", "No", FactSource.USER_EXPLICIT, Confidence.CONFIRMED, FactState.KNOWN)
    return cid


@pytest.fixture
def test_job() -> str:
    raw = RawJob(
        source="manual",
        apply_url="https://company.example.com/jobs/eng-1",
        title="Software Engineer",
        company="Example Corp",
    )
    res = ingest_job(raw)
    return res.job_id


class TestStateMachine:
    def test_full_lifecycle(self, candidate_with_facts: str, test_job: str):
        # 1. Create Application in QUEUED state
        with get_session() as session:
            app = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app)
            session.commit()
            app_id = app.id

        # 2. Prepare
        prep_res = prepare_application(app_id)
        assert prep_res.state == ApplicationState.READY_FOR_REVIEW
        assert prep_res.resolved_count >= 4
        assert prep_res.needs_user_count == 0

        # 3. Approve
        approve_application(app_id, notes="Looks great")
        with get_session() as session:
            import sqlalchemy as sa
            app = session.execute(sa.select(Application).where(Application.id == app_id)).scalars().first()
            assert app.state == ApplicationState.APPROVED.value
            assert app.review_decision == "APPROVED"

        # 4. Submit
        submit_application(app_id, confirmation_url="https://company.example.com/thanks")
        with get_session() as session:
            import sqlalchemy as sa
            app = session.execute(sa.select(Application).where(Application.id == app_id)).scalars().first()
            assert app.state == ApplicationState.SUBMITTED.value
            assert app.submitted_at is not None
            assert app.confirmation_url == "https://company.example.com/thanks"

    def test_stale_job_blocks_preparation(self, candidate_with_facts: str, test_job: str):
        # Mark job as stale
        with get_session() as session:
            import sqlalchemy as sa
            job = session.execute(sa.select(Job).where(Job.id == test_job)).scalars().first()
            job.is_stale = True
            app = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app)
            session.commit()
            app_id = app.id

        prep_res = prepare_application(app_id)
        assert prep_res.state == ApplicationState.STALE_JOB