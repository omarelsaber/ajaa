"""
tests/e2e/test_browser_e2e.py

End-to-End Offline Browser Automation Tests against Local Fake Sites (PRD §34).

Runs 100% offline using a local test server to verify:
  1. GreenhouseConnector E2E (probe -> plan -> fill -> submit -> verify)
  2. LeverConnector E2E (probe -> plan -> fill -> submit -> verify)
  3. AshbyConnector E2E (probe -> plan -> fill -> submit -> verify)
  4. Invariant I6: Live consent checkbox halt in real browser context
"""
from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
import pytest
import uvicorn

from ajaa.application.connectors.ashby import AshbyConnector
from ajaa.application.connectors.greenhouse import GreenhouseConnector
from ajaa.application.connectors.lever import LeverConnector
from ajaa.browser.context import create_browser_session
from ajaa.db.models import Job
from tests.fakesites.app import app as fake_app


@pytest.fixture(scope="session")
def fake_server():
    """Start local fake ATS server in a daemon thread on an ephemeral port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    config = uvicorn.Config(fake_app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    time.sleep(0.8)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


@pytest.fixture
def sample_cv(tmp_path: Path) -> Path:
    cv_file = tmp_path / "Candidate_CV.pdf"
    cv_file.write_bytes(b"%PDF-1.4 mock cv file content for e2e tests")
    return cv_file


@pytest.mark.e2e
def test_greenhouse_e2e_offline(fake_server: str, sample_cv: Path):
    """Verify Greenhouse connector end-to-end against local fake site."""
    apply_url = f"{fake_server}/greenhouse/job"
    job = Job(id="g-1", url_hash="ghash", apply_url=apply_url, source_connector="greenhouse:acme")

    facts = {
        "personal.name.full": "Margaret Hamilton",
        "personal.name.first": "Margaret",
        "personal.name.last": "Hamilton",
        "personal.email.primary": "margaret@apollo.nasa.gov",
        "personal.phone.primary": "+1-555-432-1098",
    }

    with create_browser_session(apply_url, headless=True) as (browser, context, page):
        page.goto(apply_url)

        connector = GreenhouseConnector()
        descriptor = connector.probe(page)
        assert descriptor.fields is not None
        assert len(descriptor.fields) >= 5

        plan = connector.plan(descriptor, facts, {}, cv_path=str(sample_cv))
        assert len(plan.operations) >= 4

        report = connector.fill(page, plan)
        assert report.success is True
        assert report.filled_count >= 4

        submit_report = connector.submit(page, descriptor)
        assert submit_report.clicked is True

        confirmation = connector.verify(page)
        assert confirmation.is_confirmed is True


@pytest.mark.e2e
def test_lever_e2e_offline(fake_server: str, sample_cv: Path):
    """Verify Lever connector end-to-end against local fake site."""
    apply_url = f"{fake_server}/lever/job"
    job = Job(id="l-1", url_hash="lhash", apply_url=apply_url, source_connector="lever:techcorp")

    facts = {
        "personal.name.full": "Katherine Johnson",
        "personal.email.primary": "katherine@nasa.gov",
        "personal.phone.primary": "+1-555-765-4321",
        "experience.company": "NASA Langley",
    }

    with create_browser_session(apply_url, headless=True) as (browser, context, page):
        page.goto(apply_url)

        connector = LeverConnector()
        descriptor = connector.probe(page)
        assert len(descriptor.fields) >= 5

        plan = connector.plan(descriptor, facts, {}, cv_path=str(sample_cv))
        report = connector.fill(page, plan)
        assert report.success is True

        submit_report = connector.submit(page, descriptor)
        assert submit_report.clicked is True

        confirmation = connector.verify(page)
        assert confirmation.is_confirmed is True


@pytest.mark.e2e
def test_ashby_e2e_offline(fake_server: str, sample_cv: Path):
    """Verify Ashby connector end-to-end against local fake site."""
    apply_url = f"{fake_server}/ashby/job"
    job = Job(id="a-1", url_hash="ahash", apply_url=apply_url, source_connector="ashby:futureai")

    facts = {
        "personal.name.full": "Dorothy Vaughan",
        "personal.email.primary": "dorothy@nasa.gov",
        "personal.phone.primary": "+1-555-111-2233",
    }

    with create_browser_session(apply_url, headless=True) as (browser, context, page):
        page.goto(apply_url)

        connector = AshbyConnector()
        descriptor = connector.probe(page)
        assert len(descriptor.fields) >= 4

        plan = connector.plan(descriptor, facts, {}, cv_path=str(sample_cv))
        report = connector.fill(page, plan)
        assert report.success is True

        submit_report = connector.submit(page, descriptor)
        assert submit_report.clicked is True

        confirmation = connector.verify(page)
        assert confirmation.is_confirmed is True


@pytest.mark.e2e
def test_invariant_i6_consent_checkbox_live_halt(fake_server: str):
    """Invariant I6: Live browser verification that consent checkboxes halt execution without being checked."""
    apply_url = f"{fake_server}/consent/job"
    job = Job(id="c-1", url_hash="chash", apply_url=apply_url, source_connector="ashby:test")

    facts = {"personal.name.full": "Alan Turing"}

    with create_browser_session(apply_url, headless=True) as (browser, context, page):
        page.goto(apply_url)

        connector = AshbyConnector()
        descriptor = connector.probe(page)
        plan = connector.plan(descriptor, facts, {})

        # Execute fill
        report = connector.fill(page, plan)

        # Automation MUST halt safely under Invariant I6
        assert report.success is False
        assert report.needs_user is True
        assert "Invariant I6" in report.needs_user_reason

        # The checkbox element MUST still be unchecked
        is_checked = page.is_checked("#consent_cb")
        assert is_checked is False
