"""
tests/unit/test_email_application.py

Unit tests for Email Application Pipeline (PRD §27).
"""
from __future__ import annotations

import email
from pathlib import Path
import pytest

from ajaa.candidate.context import CandidateContext
from ajaa.db.models import Job
from ajaa.email.apply import (
    compose_application_email,
    detect_email_application,
    send_email_application,
    verify_email_domain,
)


def test_detect_email_application():
    job_mailto = Job(
        id="j1",
        url_hash="h1",
        apply_url="mailto:careers@linear.app?subject=Application",
        title="Backend Engineer",
        source_connector="email",
    )
    assert detect_email_application(job_mailto) == "careers@linear.app"

    job_text = Job(
        id="j2",
        url_hash="h2",
        apply_url="https://acme.org/jobs/42",
        title="Frontend Engineer",
        jd_text="Interested applicants should send your CV to apply@acme.org for consideration.",
        source_connector="generic",
    )
    assert detect_email_application(job_text) == "apply@acme.org"

    job_web = Job(
        id="j3",
        url_hash="h3",
        apply_url="https://boards.greenhouse.io/stripe/jobs/123",
        title="Security Lead",
        jd_text="Apply through our portal online.",
        source_connector="greenhouse:stripe",
    )
    assert detect_email_application(job_web) is None


def test_verify_email_domain_exfiltration_guard():
    """Verify security check preventing prompt-injection exfiltration (PRD §27.1, T2)."""
    # Plausible employer matches
    assert verify_email_domain("jobs@anthropic.com", "Anthropic", "https://anthropic.com/careers") is True
    assert verify_email_domain("recruiting@spotify.com", "Spotify") is True

    # Known ATS domains
    assert verify_email_domain("applicant123@greenhouse.io", "Random Startup") is True

    # Malicious or mismatched domain -> rejected
    assert verify_email_domain("attacker@pwned.net", "Anthropic", "https://anthropic.com") is False
    assert verify_email_domain("exfiltrate@phishing.ru", "Google") is False


def test_compose_and_dry_run_email(tmp_path: Path, monkeypatch):
    """Verify composition and dry-run .eml saving without network calls."""
    # Point user data dir to tmp_path
    monkeypatch.setattr("ajaa.email.apply.get_user_data_dir", lambda: tmp_path)

    candidate = CandidateContext(
        candidate_id="cand-1",
        display_name="Marie Curie",
        profile={
            "personal.name.full": "Marie Curie",
            "personal.email.primary": "marie@curie.org",
            "skills.languages": "Python, R",
            "skills.science": "Physics, Chemistry",
        },
    )

    # Create dummy CV file
    cv_file = tmp_path / "Marie_Curie_CV.pdf"
    cv_file.write_bytes(b"%PDF-1.4 mock cv binary content")

    job = Job(
        id="job-email-1",
        url_hash="hash_sorbonne",
        apply_url="mailto:hiring@sorbonne.fr",
        company="Sorbonne",
        title="Research Scientist",
        jd_text='Subject line: "Application: Research Scientist - Marie Curie"',
        source_connector="email",
    )

    result = send_email_application(
        application_id="app-test-uuid",
        candidate=candidate,
        job=job,
        cv_path=cv_file,
        dry_run=True,
    )

    assert result["dry_run"] is True
    assert result["to"] == "hiring@sorbonne.fr"
    assert result["status"] == "DRY_RUN_SAVED"

    eml_path = Path(result["eml_path"])
    assert eml_path.exists()

    # Parse written .eml file and assert contents
    with open(eml_path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.default)

    assert msg["To"] == "hiring@sorbonne.fr"
    assert "Marie Curie" in msg["From"]
    assert "marie@curie.org" in msg["From"]
    assert "Research Scientist" in msg["Subject"]

    # Check attachment
    attachments = list(msg.iter_attachments())
    assert len(attachments) == 1
    att = attachments[0]
    assert att.get_filename() == "Marie_Curie_CV.pdf"
    assert att.get_payload(decode=True) == b"%PDF-1.4 mock cv binary content"
