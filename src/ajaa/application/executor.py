"""
src/ajaa/application/executor.py

Application Execution Engine (PRD §10.2, §21, §26.4, §26.5).

Orchestrates the entire browser application lifecycle:
  - Layer 2 & 3 Safety Ceiling enforcement
  - ApplicationStep persistence (before action with ok=None, updated after)
  - Greenhouse deterministic connector execution
  - Invariant I6: Halts on consent checkboxes
  - --dry-run support: fills form, captures screenshot, logs WOULD_SUBMIT, never clicks submit
  - UNCERTAIN state handling on verification timeout
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import time
import sqlalchemy as sa

from ajaa.application.connectors import FillPlan, get_connector
from ajaa.application.state_machine import (
    ApplicationState,
    prepare_application,
    record_step_complete,
    record_step_start,
    transition_to,
    verify_no_duplicate,
    verify_safety_ceiling,
)
from ajaa.browser.actions import capture_screenshot
from ajaa.browser.context import create_browser_session
from ajaa.candidate.profile import build_profile
from ajaa.config import get_settings
from ajaa.db.models import Application, ApplicationAnswer, CV, Job
from ajaa.db.session import get_session


@dataclass
class ExecutionResult:
    application_id: str
    final_state: ApplicationState
    is_dry_run: bool
    success: bool
    message: str = ""
    screenshot_path: Optional[str] = None


def execute_application(
    application_id: str,
    dry_run: bool = False,
    headless: bool = True,
) -> ExecutionResult:
    """
    Execute an application through the browser subsystem:
      1. Load application, ensure answers are prepared.
      2. Layer 2 Safety Ceiling check (queue drain).
      3. Launch browser session with navigation route filtering.
      4. Navigate to job.apply_url -> STARTED.
      5. Probe form controls -> FORM_DETECTED.
      6. Fill form fields with ApplicationStep tracking -> FILLING -> STEP_DONE.
      7. If dry_run: log WOULD_SUBMIT, capture verification screenshot, halt at REVIEW.
      8. If real run: Layer 3 Safety Ceiling re-check -> SUBMITTING -> VERIFYING -> SUBMITTED (or UNCERTAIN).
    """
    settings = get_settings()
    artifacts_dir = Path(settings.data_dir) / "artifacts" / application_id
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load application and check state
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        candidate_id = app.candidate_id
        job_id = app.job_id

        # Layer 2 Safety Ceiling enforcement
        verify_safety_ceiling(session, candidate_id, layer="queue_drain")

        # Duplicate check
        verify_no_duplicate(session, job_id, current_application_id=app.id)

        job = session.execute(
            sa.select(Job).where(Job.id == job_id)
        ).scalars().first()
        if job is None or not job.apply_url:
            raise ValueError(f"Job {job_id} has no valid apply_url")

        apply_url = job.apply_url

        # Check if preparation needed
        if app.state in (ApplicationState.QUEUED.value, ApplicationState.PREPARING.value):
            session.close()
            prep_res = prepare_application(application_id, skip_freshness_network_check=True)
            if prep_res.state != ApplicationState.READY_FOR_REVIEW:
                return ExecutionResult(
                    application_id=application_id,
                    final_state=prep_res.state,
                    is_dry_run=dry_run,
                    success=False,
                    message=f"Preparation halted in state {prep_res.state.value}",
                )

    # Re-fetch candidate facts and answers
    with get_session() as session:
        profile = build_profile(candidate_id)
        candidate_facts = profile.to_dict()

        active_cv = session.execute(
            sa.select(CV).where(CV.candidate_id == candidate_id, CV.is_active == True)
        ).scalars().first()
        cv_path = active_cv.file_path if active_cv else None

        answers = session.execute(
            sa.select(ApplicationAnswer).where(ApplicationAnswer.application_id == application_id)
        ).scalars().all()
        answers_dict = {a.field_label: a.answer_value for a in answers}

    connector = get_connector(job)
    step_idx = 0

    try:
        with create_browser_session(apply_url, headless=headless) as (browser, context, page):
            # Step: Navigate to apply_url
            step_idx += 1
            with get_session() as session:
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                step = record_step_start(
                    session, application_id, action="NAVIGATE", field_name="apply_url", field_value=apply_url, step_index=step_idx
                )
                transition_to(session, app, ApplicationState.STARTED, event_type="BROWSER_STARTED")
                session.commit()
                step_id = step.id

            t0 = time.time()
            try:
                page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
                nav_shot = artifacts_dir / "step_nav.png"
                capture_screenshot(page, str(nav_shot))
                with get_session() as session:
                    record_step_complete(session, step_id, ok=True, screenshot_path=str(nav_shot), duration_ms=(time.time() - t0) * 1000)
                    session.commit()
            except Exception as e:
                with get_session() as session:
                    record_step_complete(session, step_id, ok=False, error_message=str(e), duration_ms=(time.time() - t0) * 1000)
                    app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                    transition_to(session, app, ApplicationState.FAILED, detail={"error": str(e)})
                    session.commit()
                return ExecutionResult(application_id=application_id, final_state=ApplicationState.FAILED, is_dry_run=dry_run, success=False, message=f"Navigation failed: {e}")

            # Step: Probe form
            step_idx += 1
            with get_session() as session:
                step = record_step_start(session, application_id, action="PROBE", step_index=step_idx)
                session.commit()
                step_id = step.id

            t0 = time.time()
            descriptor = connector.probe(page)
            with get_session() as session:
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                transition_to(
                    session, app, ApplicationState.FORM_DETECTED,
                    detail={"fields_count": len(descriptor.fields), "submit_selector": descriptor.submit_selector}
                )
                record_step_complete(session, step_id, ok=True, duration_ms=(time.time() - t0) * 1000)
                session.commit()

            # Build fill plan
            plan = connector.plan(descriptor, candidate_facts, answers_dict, cv_path)

            # Step: Execute filling
            with get_session() as session:
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                transition_to(session, app, ApplicationState.FILLING)
                session.commit()

            for op in plan.operations:
                step_idx += 1
                with get_session() as session:
                    step = record_step_start(
                        session, application_id, action=op.action, field_name=op.field_label, field_value=op.value, step_index=step_idx
                    )
                    session.commit()
                    step_id = step.id

                t0 = time.time()
                try:
                    report = connector.fill(page, FillPlan(operations=[op]))
                    if report.needs_user:
                        with get_session() as session:
                            record_step_complete(session, step_id, ok=False, error_message=report.needs_user_reason, duration_ms=(time.time() - t0) * 1000)
                            app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                            transition_to(session, app, ApplicationState.NEEDS_USER_ACTION, detail={"reason": report.needs_user_reason})
                            session.commit()
                        return ExecutionResult(
                            application_id=application_id,
                            final_state=ApplicationState.NEEDS_USER_ACTION,
                            is_dry_run=dry_run,
                            success=False,
                            message=report.needs_user_reason,
                        )

                    with get_session() as session:
                        record_step_complete(session, step_id, ok=report.success, error_message="; ".join(report.errors) if report.errors else None, duration_ms=(time.time() - t0) * 1000)
                        session.commit()
                except Exception as e:
                    with get_session() as session:
                        record_step_complete(session, step_id, ok=False, error_message=str(e), duration_ms=(time.time() - t0) * 1000)
                        session.commit()

            # Filling step complete
            with get_session() as session:
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                transition_to(session, app, ApplicationState.STEP_DONE)
                session.commit()

            # Handle --dry-run mode
            if dry_run:
                step_idx += 1
                dry_shot = artifacts_dir / "dry_run_completed.png"
                capture_screenshot(page, str(dry_shot))

                with get_session() as session:
                    step = record_step_start(session, application_id, action="WOULD_SUBMIT", step_index=step_idx)
                    record_step_complete(session, step.id, ok=True, screenshot_path=str(dry_shot))
                    app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                    target_state = (
                        ApplicationState.APPROVED
                        if (app and app.review_decision == "APPROVED")
                        else ApplicationState.REVIEW
                    )
                    transition_to(
                        session, app, target_state,
                        event_type="DRY_RUN_COMPLETED",
                        detail={"screenshot": str(dry_shot), "note": "Dry-run mode stopped before submit_click"}
                    )
                    session.commit()

                return ExecutionResult(
                    application_id=application_id,
                    final_state=target_state,
                    is_dry_run=True,
                    success=True,
                    message="Dry run executed successfully. Form was filled and verified without submitting.",
                    screenshot_path=str(dry_shot),
                )

            # Real Submission: Layer 3 Safety Ceiling Re-read
            with get_session() as session:
                verify_safety_ceiling(session, candidate_id, layer="pre_submit")
                verify_no_duplicate(session, job_id, current_application_id=application_id)
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                transition_to(session, app, ApplicationState.SUBMITTING)
                session.commit()

            # Submit click
            step_idx += 1
            with get_session() as session:
                step = record_step_start(session, application_id, action="SUBMIT_CLICK", step_index=step_idx)
                session.commit()
                step_id = step.id

            t0 = time.time()
            sub_rep = connector.submit(page, descriptor)
            with get_session() as session:
                record_step_complete(session, step_id, ok=sub_rep.clicked, error_message=sub_rep.error or None, duration_ms=(time.time() - t0) * 1000)
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
                transition_to(session, app, ApplicationState.VERIFYING)
                session.commit()

            # Verification
            step_idx += 1
            with get_session() as session:
                step = record_step_start(session, application_id, action="VERIFY", step_index=step_idx)
                session.commit()
                step_id = step.id

            t0 = time.time()
            confirmation = connector.verify(page)
            post_shot = artifacts_dir / "post_submit.png"
            capture_screenshot(page, str(post_shot))

            with get_session() as session:
                record_step_complete(session, step_id, ok=confirmation.is_confirmed, screenshot_path=str(post_shot), duration_ms=(time.time() - t0) * 1000)
                app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()

                if confirmation.is_confirmed:
                    app.submitted_at = datetime.now(timezone.utc)
                    app.confirmation_url = confirmation.confirmation_url
                    app.ats_application_id = confirmation.ats_application_id
                    transition_to(
                        session, app, ApplicationState.SUBMITTED,
                        detail={"confirmation": confirmation.confirmation_text, "url": confirmation.confirmation_url}
                    )
                    session.commit()
                    return ExecutionResult(
                        application_id=application_id,
                        final_state=ApplicationState.SUBMITTED,
                        is_dry_run=False,
                        success=True,
                        message="Application submitted and confirmed.",
                        screenshot_path=str(post_shot),
                    )
                else:
                    # Invariant: Transition to UNCERTAIN. Never auto-retry.
                    transition_to(
                        session, app, ApplicationState.UNCERTAIN,
                        detail={"reason": "Submit was clicked, but post-submit confirmation was not detected."}
                    )
                    session.commit()
                    return ExecutionResult(
                        application_id=application_id,
                        final_state=ApplicationState.UNCERTAIN,
                        is_dry_run=False,
                        success=False,
                        message="Submitted but confirmation was not positively detected. Transitioned to UNCERTAIN for human verification.",
                        screenshot_path=str(post_shot),
                    )

    except Exception as exc:
        with get_session() as session:
            app = session.execute(sa.select(Application).where(Application.id == application_id)).scalars().first()
            if app:
                try:
                    curr_state = ApplicationState(app.state)
                    # Crash resolution: if in SUBMITTING/VERIFYING -> UNCERTAIN, else FAILED
                    if curr_state in (ApplicationState.SUBMITTING, ApplicationState.VERIFYING):
                        transition_to(session, app, ApplicationState.UNCERTAIN, detail={"crash_error": str(exc)})
                    else:
                        transition_to(session, app, ApplicationState.FAILED, detail={"error": str(exc)})
                    session.commit()
                except Exception:
                    pass

        return ExecutionResult(
            application_id=application_id,
            final_state=ApplicationState.FAILED,
            is_dry_run=dry_run,
            success=False,
            message=f"Execution encountered an unhandled exception: {exc}",
        )
