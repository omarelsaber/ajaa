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
            from ajaa.db.models import AuditEvent
            app = session.execute(sa.select(Application).where(Application.id == app_id)).scalars().first()
            assert app.state == ApplicationState.SUBMITTED.value
            assert app.submitted_at is not None
            assert app.confirmation_url == "https://company.example.com/thanks"

            events = session.execute(
                sa.select(AuditEvent).where(AuditEvent.application_id == app_id).order_by(AuditEvent.occurred_at.asc())
            ).scalars().all()
            assert len(events) == 6
            event_types = [e.event_type for e in events]
            assert event_types == [
                "PREPARATION_STARTED",
                "PREPARATION_COMPLETE",
                "REVIEW_APPROVAL",
                "SUBMISSION_INITIATED",
                "VERIFICATION_INITIATED",
                "SUBMISSION_CONFIRMED",
            ]

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

    def test_submitting_never_reentered(self, candidate_with_facts: str, test_job: str):
        """Invariant: SUBMITTING can NEVER be re-entered for the same application."""
        from ajaa.application.state_machine import SubmittingReentryError, transition_to

        with get_session() as session:
            app = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app)
            session.commit()
            app_id = app.id

        prepare_application(app_id)
        approve_application(app_id)
        submit_application(app_id)

        # Now attempt to transition back to SUBMITTING on the same application
        with get_session() as session:
            import sqlalchemy as sa
            app = session.execute(sa.select(Application).where(Application.id == app_id)).scalars().first()
            app.state = ApplicationState.APPROVED.value  # Pretend someone tried to reset to approved

            with pytest.raises(SubmittingReentryError):
                transition_to(session, app, ApplicationState.SUBMITTING)

    def test_illegal_state_transitions_raise(self, candidate_with_facts: str, test_job: str):
        """Invalid transitions outside the legal state graph must raise InvalidStateTransitionError."""
        from ajaa.application.state_machine import InvalidStateTransitionError, transition_to

        with get_session() as session:
            app = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app)
            session.commit()

            # QUEUED cannot jump straight to SUBMITTED
            with pytest.raises(InvalidStateTransitionError):
                transition_to(session, app, ApplicationState.SUBMITTED)

            # QUEUED cannot jump straight to FILLING
            with pytest.raises(InvalidStateTransitionError):
                transition_to(session, app, ApplicationState.FILLING)

    def test_safety_ceiling_enforcement(self, candidate_with_facts: str, test_job: str):
        """PRD §26.4: Reaching daily safety ceiling (15) must halt with SafetyCeilingError."""
        from ajaa.application.state_machine import DAILY_SAFETY_CEILING, SafetyCeilingError, verify_safety_ceiling
        from datetime import datetime, timezone

        with get_session() as session:
            # Seed 15 submitted applications today
            now = datetime.now(timezone.utc)
            for i in range(DAILY_SAFETY_CEILING):
                # Create separate jobs
                raw = RawJob(source="manual", apply_url=f"https://company.example.com/job-{i}", title=f"Job {i}")
                job_res = ingest_job(raw)
                app = Application(
                    candidate_id=candidate_with_facts,
                    job_id=job_res.job_id,
                    state=ApplicationState.SUBMITTED.value,
                    submitted_at=now,
                )
                session.add(app)
            session.commit()

            # Layer 1, 2, and 3 must all raise SafetyCeilingError
            for layer in ("scheduler", "queue_drain", "pre_submit"):
                with pytest.raises(SafetyCeilingError):
                    verify_safety_ceiling(session, candidate_with_facts, layer=layer)

    def test_duplicate_application_blocked(self, candidate_with_facts: str, test_job: str):
        """PRD §30.3: Duplicate application for the same job must raise DuplicateApplicationError."""
        from ajaa.application.state_machine import DuplicateApplicationError

        with get_session() as session:
            app1 = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app1)
            session.commit()
            app1_id = app1.id

        prepare_application(app1_id)
        approve_application(app1_id)
        submit_application(app1_id)

        # Create second application for same job
        with get_session() as session:
            app2 = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app2)
            session.commit()
            app2_id = app2.id

        with pytest.raises(DuplicateApplicationError):
            prepare_application(app2_id)

    def test_crash_recovery(self, candidate_with_facts: str, test_job: str):
        """PRD §21.4: In-flight applications recover to QUEUED or UNCERTAIN on restart."""
        from ajaa.application.state_machine import recover_crashed_applications

        with get_session() as session:
            # app in FILLING -> should recover to QUEUED
            app1 = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.FILLING.value,
            )
            # app in SUBMITTING -> should recover to UNCERTAIN (danger zone)
            raw2 = RawJob(source="manual", apply_url="https://company.example.com/job-danger", title="Job Danger")
            job2 = ingest_job(raw2)
            app2 = Application(
                candidate_id=candidate_with_facts,
                job_id=job2.job_id,
                state=ApplicationState.SUBMITTING.value,
            )
            session.add_all([app1, app2])
            session.commit()

            recovered = recover_crashed_applications(session, candidate_with_facts)
            recovered_map = {r[0]: (r[1], r[2]) for r in recovered}

            assert recovered_map[app1.id] == ("FILLING", "QUEUED")
            assert recovered_map[app2.id] == ("SUBMITTING", "UNCERTAIN")

    def test_application_step_persistence(self, candidate_with_facts: str, test_job: str):
        """ApplicationStep must be logged before action with ok=None and updated after."""
        from ajaa.application.state_machine import record_step_complete, record_step_start
        from ajaa.db.models import ApplicationStep

        with get_session() as session:
            app = Application(
                candidate_id=candidate_with_facts,
                job_id=test_job,
                state=ApplicationState.QUEUED.value,
            )
            session.add(app)
            session.commit()
            app_id = app.id

            step = record_step_start(session, app_id, action="NAVIGATE", field_name="url", field_value="https://test.com")
            session.commit()
            step_id = step.id

        with get_session() as session:
            import sqlalchemy as sa
            s = session.execute(sa.select(ApplicationStep).where(ApplicationStep.id == step_id)).scalars().first()
            assert s.action == "NAVIGATE"
            assert s.ok is None  # In-flight

            record_step_complete(session, step_id, ok=True, screenshot_path="/tmp/shot.png", duration_ms=120.0)
            session.commit()

        with get_session() as session:
            import sqlalchemy as sa
            s = session.execute(sa.select(ApplicationStep).where(ApplicationStep.id == step_id)).scalars().first()
            assert s.ok is True
            assert s.screenshot_path == "/tmp/shot.png"
            assert s.duration_ms == 120.0