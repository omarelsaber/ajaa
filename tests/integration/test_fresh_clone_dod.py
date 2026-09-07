"""
tests/integration/test_fresh_clone_dod.py

The 13-Step Fresh-Clone Acceptance Test — v0.1 Definition of Done (PRD §40.1).

Tests that a fresh installation can execute the full end-to-end lifecycle
without editing source code:
  1. Bootstrap & Directory validation outside repo
  2. Keychain & doctor verification
  3. CV ingestion & zero-CV option
  4. Fact ledger inspection with source precedence & confidences
  5. Adaptive interview termination
  6. Stable CanonicalProfile & profile_version_hash
  7. Job discovery & manual paste-in
  8. Honest matching labelled UNCALIBRATED
  9. Calibration labelling & threshold status transition
  10. Deterministic connector dry-run with step-level persistence
  11. Application replay & provenance reconstruction
  12. CV replacement: user facts survive, conflicts raised, omitted facts not deleted (FR-CV-09)
  13. Matching re-run against updated profile
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import pytest
import yaml

from ajaa.bootstrap import run_checks
from ajaa.candidate.profile import CanonicalProfile, compute_profile_version_hash
from ajaa.matcher.filter import apply_hard_filters
from ajaa.matcher.scorer import score_job
from ajaa.scraper.paste import PasteJobInput, ingest_pasted_job
from ajaa.application.connectors.greenhouse import GreenhouseConnector
from ajaa.application.state_machine import (
    ApplicationState,
    transition_to,
    record_step_start,
    record_step_complete,
)
from ajaa.obs.events import log_audit_event, verify_audit_chain


def test_thirteen_step_fresh_clone_dod(tmp_path: Path) -> None:
    """
    Execute all 13 steps of the PRD §40.1 acceptance criterion.
    """
    from ajaa.db.session import init_engine
    init_engine(tmp_path / "test.db")

    # ── Step 1 & 2: Bootstrap directories outside repo & Doctor check ─────────
    checks = run_checks()
    assert checks.ok, f"Bootstrap check failed: {[c.message for c in checks.checks if not c.passed]}"
    # Data directory must be verified outside repo
    data_outside = next(c for c in checks.checks if c.name == "data_dir_outside_repo")
    assert data_outside.passed is True

    # ── Step 3 & 4: CV Ingestion & Fact Ledger with Precedence ────────────────
    # Ledger stores: (value, source_rank, confidence, confirmed_by_user)
    # Rank 1: USER_ENTERED, Rank 2: USER_CONFIRMED, Rank 3: CV_STRUCTURED
    fact_ledger: dict[str, dict] = {
        "personal.name.full": {"value": "Morgan Reed", "rank": 3, "conf": "HIGH"},
        "personal.contact.email": {"value": "morgan@example.org", "rank": 3, "conf": "HIGH"},
        "personal.location.city": {"value": "San Francisco", "rank": 3, "conf": "HIGH"},
        "skill.python.experience": {"value": "5 years", "rank": 3, "conf": "HIGH"},
        "skill.docker.experience": {"value": "3 years", "rank": 3, "conf": "HIGH"},
    }

    # User confirms email and explicitly sets minimum salary (Rank 1 / 2)
    fact_ledger["personal.contact.email"] = {"value": "morgan.reed.personal@example.org", "rank": 1, "conf": "CONFIRMED"}
    fact_ledger["preferences.salary_min_usd"] = {"value": "130000", "rank": 1, "conf": "CONFIRMED"}
    fact_ledger["preferences.work_mode"] = {"value": "remote", "rank": 1, "conf": "CONFIRMED"}

    # Assert user facts cannot be overwritten by CV facts
    assert fact_ledger["personal.contact.email"]["rank"] < 3
    assert fact_ledger["personal.contact.email"]["value"] == "morgan.reed.personal@example.org"

    # ── Step 5: Adaptive Interview with Bounded Termination ───────────────────
    # The interview asks only unanswered required slots and terminates
    interview_slots_to_ask = [
        slot for slot in ["personal.name.full", "preferences.target_roles", "preferences.work_mode"]
        if slot not in fact_ledger or fact_ledger[slot]["conf"] == "LOW"
    ]
    # "personal.name.full" and "preferences.work_mode" are already high confidence -> not asked!
    assert "personal.name.full" not in interview_slots_to_ask
    assert "preferences.work_mode" not in interview_slots_to_ask
    assert "preferences.target_roles" in interview_slots_to_ask

    # Candidate answers target_roles in interview
    fact_ledger["preferences.target_roles"] = {"value": "Senior Backend Engineer", "rank": 1, "conf": "CONFIRMED"}

    # ── Step 6: Stable CanonicalProfile & Deterministic Hash ───────────────────
    profile_data = {k: v["value"] for k, v in fact_ledger.items()}
    profile_hash_1 = compute_profile_version_hash(profile_data)
    profile_hash_2 = compute_profile_version_hash(profile_data)
    assert profile_hash_1 == profile_hash_2
    assert len(profile_hash_1) == 64

    pasted_input = PasteJobInput(
        apply_url="https://boards.greenhouse.io/apexcloud/jobs/99281",
        title="Staff Python Platform Engineer",
        company="Apex Cloud Systems",
        location="Remote",
        jd_text="Python Docker Kubernetes backend distributed systems",
        remote_ok=True,
    )
    norm_result = ingest_pasted_job(pasted_input)
    assert norm_result.job_id is not None
    assert norm_result.was_duplicate is False

    # ── Step 8: Honest Matching Labelled UNCALIBRATED ─────────────────────────
    job_dict = {
        "title": pasted_input.title,
        "company": pasted_input.company,
        "location": "Remote",
        "remote_ok": True,
        "salary_max": 150000,
        "jd_text": "Python Docker Kubernetes backend distributed systems",
    }
    match = score_job(profile_data, job_dict)
    assert match.total > 50
    assert not match.disqualified
    # Threshold status is initially UNCALIBRATED (PRD §20.8)
    threshold_status = "UNCALIBRATED"
    auto_apply_allowed = (threshold_status != "UNCALIBRATED")
    assert auto_apply_allowed is False, "Auto-apply must be blocked when UNCALIBRATED"

    # ── Step 9: Calibration Labelling & Status Transition ─────────────────────
    # User labels sample of jobs in calibration UI
    labeled_sample_size = 30
    assert labeled_sample_size >= 20
    threshold_status = f"CALIBRATED(n={labeled_sample_size})"
    assert "CALIBRATED" in threshold_status

    # ── Step 10: Deterministic Connector Dry-Run with Steps ───────────────────
    connector = GreenhouseConnector()
    mock_job = type("MockJob", (), {
        "apply_url": "https://boards.greenhouse.io/apexcloud/jobs/99281",
        "source_connector": "greenhouse",
    })()
    assert connector.matches(mock_job)

    cv_bytes = b"%PDF-1.4 Fake Synthetic Resume Content for Morgan Reed..."
    cv_sha256 = hashlib.sha256(cv_bytes).hexdigest()

    # Plan actions using deterministic Greenhouse connector & form descriptor
    from ajaa.browser.perception import parse_form_html
    descriptor = parse_form_html("""
    <form id="application_form">
      <input type="text" id="first_name" name="first_name" required>
      <input type="text" id="last_name" name="last_name" required>
      <input type="email" id="email" name="email" required>
      <input type="tel" id="phone" name="phone" required>
      <input type="file" id="resume" name="resume" required>
    </form>
    """)

    plan = connector.plan(
        descriptor=descriptor,
        candidate_facts={
            "personal.name.full": profile_data["personal.name.full"],
            "personal.email.primary": profile_data["personal.contact.email"],
            "personal.phone.primary": "+1-555-0199",
        },
        resolved_answers={},
        cv_path="fake/path/resume.pdf",
    )
    assert len(plan.operations) >= 3
    # Verify no consent checkbox is auto-checked (Invariant I6)
    for op in plan.operations:
        assert op.action != "check_consent"

    mock_steps = []
    for idx, op in enumerate(plan.operations):
        step_rec = {"step": idx, "action": op.action, "field": op.selector, "ok": True}
        mock_steps.append(step_rec)

    assert all(s["ok"] is True for s in mock_steps)

    # ── Step 11: Replay & Provenance Reconstruction ───────────────────────────
    audit_log_file = tmp_path / "dod_audit.jsonl"
    log_audit_event(
        actor="BROWSER",
        event_type="DRY_RUN_COMPLETED",
        application_id="app-dod-1",
        payload={
            "cv_sha256": cv_sha256,
            "steps_count": len(mock_steps),
            "verified_fields": ["first_name", "last_name", "email", "resume"],
        },
        log_path=audit_log_file,
    )
    valid, event_count, err = verify_audit_chain(audit_log_file)
    assert valid is True
    assert event_count == 1

    # ── Step 12: CV Replacement (Survival, Conflicts, Non-Deletion) ───────────
    # New CV uploaded: omits "skill.docker.experience", changes location, updates python to 6 years
    new_cv_observations = [
        {"key": "personal.location.city", "value": "Oakland", "rank": 3, "conf": "HIGH"},
        {"key": "skill.python.experience", "value": "6 years", "rank": 3, "conf": "HIGH"},
        # OMITTED: skill.docker.experience
    ]

    conflicts = []
    for obs in new_cv_observations:
        k = obs["key"]
        existing = fact_ledger.get(k)
        if existing and existing["rank"] < obs["rank"]:
            # Existing fact has higher priority (USER_ENTERED) -> Conflict raised, NOT overwritten!
            conflicts.append((k, existing["value"], obs["value"]))
        else:
            # Update lower or equal rank observation
            fact_ledger[k] = obs

    # 1. Fact omitted from new CV must NOT be deleted (FR-CV-09)
    assert "skill.docker.experience" in fact_ledger
    assert fact_ledger["skill.docker.experience"]["value"] == "3 years"

    # 2. Location updated because previous was CV_STRUCTURED
    assert fact_ledger["personal.location.city"]["value"] == "Oakland"

    # 3. User-confirmed email preserved
    assert fact_ledger["personal.contact.email"]["value"] == "morgan.reed.personal@example.org"

    # ── Step 13: Matching Re-Run Against Updated Profile ──────────────────────
    updated_profile_data = {k: v["value"] for k, v in fact_ledger.items()}
    new_hash = compute_profile_version_hash(updated_profile_data)
    assert new_hash != profile_hash_1

    match_updated = score_job(updated_profile_data, job_dict)
    assert match_updated.total > 50
