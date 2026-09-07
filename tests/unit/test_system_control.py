"""
tests/unit/test_system_control.py

Unit tests for SystemController and Control Routes (PRD §6.10, §26.5, §28.4).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient

from ajaa.application.state_machine import ApplicationState
from ajaa.db.models import Application, AuditEvent, Base, CandidateContext, Job
from ajaa.orchestration.control import ExecutionStatus, SystemController
from ajaa.web.app import app


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_pause_and_resume():
    ctrl = SystemController()
    status = ctrl.get_status()
    assert status.status == ExecutionStatus.RUNNING
    assert status.is_paused is False

    # Pause
    paused = ctrl.pause()
    assert paused.status == ExecutionStatus.PAUSED
    assert paused.is_paused is True

    # Resume
    resumed = ctrl.resume()
    assert resumed.status == ExecutionStatus.RUNNING
    assert resumed.is_paused is False


def test_emergency_panic_transitions_in_flight_to_uncertain(memory_db: Session):
    """PRD §26.5 & §21.3: Panic must move SUBMITTING/VERIFYING to UNCERTAIN."""
    cand = CandidateContext(id="cand-panic", display_name="Panic Tester")
    job1 = Job(id="job-p1", url_hash="h1", apply_url="https://a.com", source_connector="g")
    job2 = Job(id="job-p2", url_hash="h2", apply_url="https://b.com", source_connector="g")
    job3 = Job(id="job-p3", url_hash="h3", apply_url="https://c.com", source_connector="g")
    memory_db.add_all([cand, job1, job2, job3])

    app_submitting = Application(id="app-1", candidate_id=cand.id, job_id=job1.id, state=ApplicationState.SUBMITTING.value)
    app_verifying = Application(id="app-2", candidate_id=cand.id, job_id=job2.id, state=ApplicationState.VERIFYING.value)
    app_started = Application(id="app-3", candidate_id=cand.id, job_id=job3.id, state=ApplicationState.STARTED.value)
    memory_db.add_all([app_submitting, app_verifying, app_started])
    memory_db.commit()

    ctrl = SystemController()
    status = ctrl.panic(session=memory_db)

    assert status.status == ExecutionStatus.PANIC
    assert status.panic_tripped is True

    # Refresh DB objects
    memory_db.refresh(app_submitting)
    memory_db.refresh(app_verifying)
    memory_db.refresh(app_started)

    # In-flight submissions converted to UNCERTAIN to prevent duplicate submissions
    assert app_submitting.state == ApplicationState.UNCERTAIN.value
    assert "PANIC_INTERRUPTED" in app_submitting.error_message

    assert app_verifying.state == ApplicationState.UNCERTAIN.value
    assert "PANIC_INTERRUPTED" in app_verifying.error_message

    # Pre-submission step aborted
    assert app_started.state == ApplicationState.FAILED.value


def test_stale_lock_reaper(memory_db: Session):
    """PRD §28.4: Reaps claims older than 15 minutes."""
    cand = CandidateContext(id="cand-reap", display_name="Reaper Tester")
    job1 = Job(id="job-r1", url_hash="hr1", apply_url="https://r1.com", source_connector="g")
    job2 = Job(id="job-r2", url_hash="hr2", apply_url="https://r2.com", source_connector="g")
    memory_db.add_all([cand, job1, job2])

    stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    fresh_time = datetime.now(timezone.utc) - timedelta(minutes=5)

    stale_app = Application(
        id="app-stale",
        candidate_id=cand.id,
        job_id=job1.id,
        state=ApplicationState.STARTED.value,
        updated_at=stale_time,
    )
    fresh_app = Application(
        id="app-fresh",
        candidate_id=cand.id,
        job_id=job2.id,
        state=ApplicationState.STARTED.value,
        updated_at=fresh_time,
    )
    memory_db.add_all([stale_app, fresh_app])
    memory_db.commit()

    ctrl = SystemController()
    reaped_count = ctrl.reap_stale_locks(session=memory_db, timeout_minutes=15)

    assert reaped_count == 1
    memory_db.refresh(stale_app)
    memory_db.refresh(fresh_app)

    assert stale_app.state == ApplicationState.FAILED.value
    assert "STALE_LOCK_REAPED" in stale_app.error_message
    assert fresh_app.state == ApplicationState.STARTED.value


def test_control_web_routes():
    """Verify HTTP endpoints for pause, resume, and panic."""
    client = TestClient(app)

    # 1. GET /control/status
    res = client.get("/control/status")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "is_paused" in data

    # 2. POST /control/pause
    res = client.post("/control/pause", follow_redirects=False)
    assert res.status_code == 303
    assert "paused" in res.headers["location"]

    # 3. POST /control/resume
    res = client.post("/control/resume", follow_redirects=False)
    assert res.status_code == 303
    assert "resumed" in res.headers["location"]

    # 4. POST /control/panic
    res = client.post("/control/panic", follow_redirects=False)
    assert res.status_code == 303
    assert "PANIC" in res.headers["location"]
