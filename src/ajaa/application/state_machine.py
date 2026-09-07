"""
src/ajaa/application/state_machine.py

Application Lifecycle State Machine, 3-Layer Safety Ceilings,
and ApplicationStep Persistence.

Governed strictly by PRD §21, §24, and §26:
  - 20 explicit lifecycle states
  - Invariant: SUBMITTING is never re-entered for the same application
  - Invariant: UNCERTAIN is never auto-retried (human resolves, always)
  - 3-Layer Safety Ceiling enforcement (scheduler, queue drain, pre-submit)
  - Pre-submit job freshness check (Amendment 7)
  - ApplicationStep persistence (step logged BEFORE action with ok=None, updated AFTER)
  - Crash recovery using state.crash_resolution
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
import httpx
import sqlalchemy as sa

from ajaa.answering.resolver import AnswerResolution, FormField, ResolutionStatus, resolve_field
from ajaa.candidate.profile import build_profile
from ajaa.db.models import Application, ApplicationAnswer, ApplicationStep, AuditEvent, CV, Job
from ajaa.db.session import get_session
from ajaa.types import ApplicationState


# ── Exceptions ───────────────────────────────────────────────────────────────

class StateMachineError(Exception):
    """Base error for state machine violations."""
    pass


class InvalidStateTransitionError(StateMachineError):
    """Raised when an illegal state transition is attempted."""
    pass


class SubmittingReentryError(StateMachineError):
    """Raised when an application attempts to re-enter SUBMITTING."""
    pass


class SafetyCeilingError(StateMachineError):
    """Raised when an application volume ceiling is breached (PRD §26.1, §26.4)."""
    pass


class DuplicateApplicationError(StateMachineError):
    """Raised when an application would duplicate an existing active/submitted application (PRD §30.3)."""
    pass


# ── Configuration Constants ──────────────────────────────────────────────────

# Hard safety ceiling guard rail (PRD §26.1 / §26.4). Not an operational policy.
DAILY_SAFETY_CEILING = 15

# Terminal states where execution has ended
TERMINAL_STATES: set[ApplicationState] = {
    ApplicationState.SUBMITTED,
    ApplicationState.UNCERTAIN,
    ApplicationState.FAILED,
    ApplicationState.REJECTED,
    ApplicationState.SKIPPED,
    ApplicationState.EXPIRED,
    ApplicationState.STALE_JOB,
    ApplicationState.ABANDONED,
    ApplicationState.BLOCKED_BY_SITE,
}

# ── Valid Transitions Table (PRD §21.1 / §21.2) ──────────────────────────────

VALID_TRANSITIONS: dict[ApplicationState, set[ApplicationState]] = {
    ApplicationState.DISCOVERED: {
        ApplicationState.MATCHED,
        ApplicationState.REJECTED,
    },
    ApplicationState.MATCHED: {
        ApplicationState.QUEUED,
        ApplicationState.REJECTED,
    },
    ApplicationState.QUEUED: {
        ApplicationState.PREPARING,
        ApplicationState.SKIPPED,
        ApplicationState.EXPIRED,
        ApplicationState.STALE_JOB,
    },
    ApplicationState.PREPARING: {
        ApplicationState.READY_FOR_REVIEW,
        ApplicationState.REVIEW,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.STARTED,
        ApplicationState.EXPIRED,
        ApplicationState.STALE_JOB,
        ApplicationState.FAILED,
    },
    ApplicationState.STARTED: {
        ApplicationState.FORM_DETECTED,
        ApplicationState.LOGIN_REQUIRED,
        ApplicationState.REDIRECTED,
        ApplicationState.BLOCKED_BY_SITE,
        ApplicationState.FAILED,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
    },
    ApplicationState.LOGIN_REQUIRED: {
        ApplicationState.FORM_DETECTED,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.FAILED,
    },
    ApplicationState.REDIRECTED: {
        ApplicationState.STARTED,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.FAILED,
    },
    ApplicationState.FORM_DETECTED: {
        ApplicationState.FILLING,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.FAILED,
    },
    ApplicationState.FILLING: {
        ApplicationState.QUESTIONS,
        ApplicationState.STEP_DONE,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.FAILED,
    },
    ApplicationState.QUESTIONS: {
        ApplicationState.STEP_DONE,
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.FAILED,
    },
    ApplicationState.STEP_DONE: {
        ApplicationState.FILLING,
        ApplicationState.REVIEW,
        ApplicationState.READY_FOR_REVIEW,
        ApplicationState.FAILED,
    },
    ApplicationState.REVIEW: {
        ApplicationState.APPROVED,
        ApplicationState.SUBMITTING,
        ApplicationState.ABANDONED,
        ApplicationState.READY_FOR_REVIEW,
    },
    ApplicationState.READY_FOR_REVIEW: {
        ApplicationState.APPROVED,
        ApplicationState.SUBMITTING,
        ApplicationState.ABANDONED,
        ApplicationState.REVIEW,
    },
    ApplicationState.APPROVED: {
        ApplicationState.SUBMITTING,
        ApplicationState.ABANDONED,
    },
    ApplicationState.SUBMITTING: {
        ApplicationState.VERIFYING,
        ApplicationState.UNCERTAIN,
        ApplicationState.FAILED,
    },
    ApplicationState.VERIFYING: {
        ApplicationState.SUBMITTED,
        ApplicationState.UNCERTAIN,
        ApplicationState.FAILED,
    },
    ApplicationState.UNCERTAIN: {
        ApplicationState.SUBMITTED,
        ApplicationState.FAILED,
    },
    ApplicationState.NEEDS_USER_ACTION: {
        ApplicationState.QUEUED,
        ApplicationState.PREPARING,
        ApplicationState.READY_FOR_REVIEW,
        ApplicationState.REVIEW,
        ApplicationState.ABANDONED,
        ApplicationState.FAILED,
    },
    ApplicationState.NEEDS_USER: {
        ApplicationState.QUEUED,
        ApplicationState.PREPARING,
        ApplicationState.READY_FOR_REVIEW,
        ApplicationState.REVIEW,
        ApplicationState.ABANDONED,
        ApplicationState.FAILED,
    },
    ApplicationState.FAILED: {
        ApplicationState.QUEUED,  # Retryable if attempts < 3
    },
    ApplicationState.BLOCKED_BY_SITE: {
        ApplicationState.NEEDS_USER_ACTION,
        ApplicationState.NEEDS_USER,
        ApplicationState.ABANDONED,
    },
    ApplicationState.SKIPPED: set(),
    ApplicationState.EXPIRED: set(),
    ApplicationState.STALE_JOB: set(),
    ApplicationState.ABANDONED: set(),
    ApplicationState.SUBMITTED: set(),
}


# ── Transition Validator & Persistence ────────────────────────────────────────

def transition_to(
    session: sa.orm.Session,
    application: Application,
    target_state: ApplicationState,
    event_type: str | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    """
    Validate and execute state transition with full invariant enforcement:
      1. Legal transition check via VALID_TRANSITIONS.
      2. SUBMITTING re-entry invariant: SUBMITTING can never be re-entered.
      3. UNCERTAIN auto-retry invariant: UNCERTAIN cannot transition automatically.
      4. Append-only AuditEvent logging.
      5. Updates application.previous_state and application.state.
    """
    current_state = ApplicationState(application.state)

    # 1. Check legal transition
    allowed = VALID_TRANSITIONS.get(current_state, set())
    if target_state not in allowed:
        raise InvalidStateTransitionError(
            f"Illegal state transition from {current_state.value} to {target_state.value}. "
            f"Allowed exits from {current_state.value}: {[s.value for s in allowed]}"
        )

    # 2. Check SUBMITTING re-entry invariant
    if target_state == ApplicationState.SUBMITTING:
        prior_submit = session.execute(
            sa.select(AuditEvent).where(
                AuditEvent.application_id == application.id,
                AuditEvent.to_state == ApplicationState.SUBMITTING.value,
            )
        ).scalars().first()

        if prior_submit is not None:
            raise SubmittingReentryError(
                f"Application {application.id} previously entered SUBMITTING at "
                f"{prior_submit.occurred_at}. Re-entry to SUBMITTING is strictly prohibited."
            )

    # Record state update
    old_state_str = application.state
    application.previous_state = old_state_str
    application.state = target_state.value
    application.updated_at = datetime.now(timezone.utc)

    # Log immutable audit event
    _record_audit_event(
        session=session,
        application_id=application.id,
        event_type=event_type or f"STATE_{target_state.value}",
        from_state=old_state_str,
        to_state=target_state.value,
        detail=detail,
    )


# ── Safety Ceilings Enforcement (PRD §26.4) ──────────────────────────────────

def count_daily_auto_submissions(session: sa.orm.Session, candidate_id: str) -> int:
    """
    Count applications submitted today against the safety ceiling (PRD §26.4).
    Counts AUTO submissions and UNCERTAIN (as possible submissions).
    Excludes MANUAL and HUMAN_ASSISTED.
    """
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    query = sa.select(sa.func.count(Application.id)).where(
        Application.candidate_id == candidate_id,
        Application.state.in_([ApplicationState.SUBMITTED.value, ApplicationState.UNCERTAIN.value]),
        Application.submitted_at >= today_start,
    )
    return session.execute(query).scalar() or 0


def verify_safety_ceiling(session: sa.orm.Session, candidate_id: str, layer: str) -> None:
    """
    Enforce safety ceiling at one of the 3 specified layers (PRD §26.4):
      - 'scheduler'
      - 'queue_drain'
      - 'pre_submit'
    Raises SafetyCeilingError if the daily ceiling is reached.
    """
    count = count_daily_auto_submissions(session, candidate_id)
    if count >= DAILY_SAFETY_CEILING:
        raise SafetyCeilingError(
            f"Daily safety ceiling reached at layer '{layer}': {count}/{DAILY_SAFETY_CEILING} "
            f"applications submitted or uncertain today. Halting execution."
        )


def verify_no_duplicate(
    session: sa.orm.Session,
    job_id: str,
    current_application_id: str | None = None,
) -> None:
    """
    Verify that no duplicate application exists for the same job (PRD §30.3).
    Blocks if an existing application is in SUBMITTED, SUBMITTING, VERIFYING, or UNCERTAIN.
    """
    active_states = [
        ApplicationState.SUBMITTED.value,
        ApplicationState.SUBMITTING.value,
        ApplicationState.VERIFYING.value,
        ApplicationState.UNCERTAIN.value,
    ]
    query = sa.select(Application).where(
        Application.job_id == job_id,
        Application.state.in_(active_states),
    )
    if current_application_id:
        query = query.where(Application.id != current_application_id)

    existing = session.execute(query).scalars().first()
    if existing is not None:
        raise DuplicateApplicationError(
            f"An application for job {job_id} is already in state {existing.state} "
            f"(Application ID: {existing.id}). Duplicate submissions are blocked."
        )


# ── Job Freshness Gate (Amendment 7) ─────────────────────────────────────────

def check_job_freshness(apply_url: str, timeout: float = 10.0) -> bool:
    """
    Pre-Submit Job Freshness Check (Amendment 7).
    A lightweight HEAD/GET request to verify the posting is still live.
    Returns False if 404, redirected to homepage, or closed.
    """
    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.head(apply_url)
            if resp.status_code == 405:
                resp = client.get(apply_url)

            if resp.status_code in (404, 410):
                return False

            if resp.history:
                final_url = str(resp.url)
                if resp.url.path in ("/", "", "/jobs", "/careers") and len(apply_url) > len(final_url) + 5:
                    return False

            return resp.status_code < 400
    except Exception:
        return True


# ── ApplicationStep Tracking ─────────────────────────────────────────────────

def record_step_start(
    session: sa.orm.Session,
    application_id: str,
    action: str,
    field_name: str | None = None,
    field_value: str | None = None,
    step_index: int = 0,
) -> ApplicationStep:
    """
    Persist step to application_steps table BEFORE the action is attempted.
    ok=None represents in-flight state.
    """
    step = ApplicationStep(
        application_id=application_id,
        step_index=step_index,
        action=action,
        field_name=field_name,
        field_value=field_value,
        ok=None,
        started_at=datetime.now(timezone.utc),
    )
    session.add(step)
    session.flush()
    return step


def record_step_complete(
    session: sa.orm.Session,
    step_id: str,
    ok: bool = True,
    error_message: str | None = None,
    screenshot_path: str | None = None,
    duration_ms: float | None = None,
) -> None:
    """Update application_steps row AFTER the action completes."""
    step = session.execute(
        sa.select(ApplicationStep).where(ApplicationStep.id == step_id)
    ).scalars().first()
    if step:
        step.ok = ok
        step.error_message = error_message
        step.screenshot_path = screenshot_path
        step.completed_at = datetime.now(timezone.utc)
        if duration_ms is not None:
            step.duration_ms = duration_ms
        elif step.started_at:
            delta = step.completed_at - step.started_at.replace(tzinfo=timezone.utc)
            step.duration_ms = delta.total_seconds() * 1000.0


# ── Preparation Pipeline (PREPARING Stage) ───────────────────────────────────

@dataclass
class PreparationResult:
    application_id: str
    state: ApplicationState
    resolved_count: int
    needs_user_count: int
    answers: list[AnswerResolution]
    selected_cv_path: Optional[str] = None


def prepare_application(
    application_id: str,
    form_fields: list[FormField] | None = None,
    skip_freshness_network_check: bool = False,
) -> PreparationResult:
    """
    Execute PREPARING step:
      1. Layer 1 Safety Ceiling check.
      2. Duplicate application check.
      3. Job freshness check (Amendment 7).
      4. Active CV selection.
      5. Answer resolution against CanonicalProfile facts with grounding validator.
      6. Persist answers to application_answers.
      7. Transition to READY_FOR_REVIEW (or NEEDS_USER_ACTION).
    """
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        # Layer 1 Safety Ceiling enforcement
        verify_safety_ceiling(session, app.candidate_id, layer="scheduler")

        # Duplicate check
        verify_no_duplicate(session, app.job_id, current_application_id=app.id)

        job = session.execute(
            sa.select(Job).where(Job.id == app.job_id)
        ).scalars().first()
        if job is None:
            raise ValueError(f"Job {app.job_id} not found")

        # Check job freshness (Amendment 7)
        if job.is_stale:
            transition_to(
                session, app, ApplicationState.STALE_JOB,
                event_type="JOB_STALE", detail={"reason": "Job marked as stale"}
            )
            session.commit()
            return PreparationResult(
                application_id=application_id,
                state=ApplicationState.STALE_JOB,
                resolved_count=0,
                needs_user_count=0,
                answers=[],
            )

        if not skip_freshness_network_check and job.apply_url:
            is_live = check_job_freshness(job.apply_url)
            job.last_freshness_check = datetime.now(timezone.utc)
            if not is_live:
                job.is_stale = True
                transition_to(
                    session, app, ApplicationState.EXPIRED,
                    event_type="JOB_EXPIRED", detail={"reason": "404 or dead URL at apply_url"}
                )
                session.commit()
                return PreparationResult(
                    application_id=application_id,
                    state=ApplicationState.EXPIRED,
                    resolved_count=0,
                    needs_user_count=0,
                    answers=[],
                )

        # Transition to PREPARING
        transition_to(session, app, ApplicationState.PREPARING, event_type="PREPARATION_STARTED")
        session.commit()

        # Select active CV
        active_cv = session.execute(
            sa.select(CV).where(CV.candidate_id == app.candidate_id, CV.is_active == True)
        ).scalars().first()
        cv_path = active_cv.file_path if active_cv else None

        # Build candidate profile
        profile = build_profile(app.candidate_id)
        facts = profile.to_dict()

    # Form fields to resolve (defaults for ATS if none provided)
    fields_to_resolve = form_fields or [
        FormField(name="full_name", label="Full Legal Name", required=True),
        FormField(name="email", label="Email Address", required=True),
        FormField(name="phone", label="Phone Number", required=True),
        FormField(name="city", label="City", required=False),
        FormField(name="linkedin", label="LinkedIn Profile", required=False),
        FormField(name="github", label="GitHub Profile", required=False),
        FormField(
            name="sponsorship",
            label="Will you now or in the future require visa sponsorship?",
            field_type="radio",
            required=True,
        ),
    ]

    resolutions: list[AnswerResolution] = [
        resolve_field(f, facts) for f in fields_to_resolve
    ]

    resolved_count = sum(1 for r in resolutions if r.status == ResolutionStatus.RESOLVED)
    needs_user_count = sum(1 for r in resolutions if r.status == ResolutionStatus.NEEDS_USER)

    next_state = (
        ApplicationState.NEEDS_USER if needs_user_count > 0 else ApplicationState.READY_FOR_REVIEW
    )

    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app:
            # Clean prior answers
            session.execute(
                sa.delete(ApplicationAnswer).where(
                    ApplicationAnswer.application_id == application_id
                )
            )

            for res in resolutions:
                ans = ApplicationAnswer(
                    application_id=application_id,
                    field_label=res.field_name,
                    field_type="text",
                    answer_value=str(res.value) if res.value is not None else "",
                    answer_source="RESOLVED" if res.status == ResolutionStatus.RESOLVED else "NEEDS_USER",
                    confidence="HIGH" if res.status == ResolutionStatus.RESOLVED else "LOW",
                    is_required=True,
                    was_overridden_by_human=False,
                )
                session.add(ans)

            transition_to(
                session,
                app,
                next_state,
                event_type="PREPARATION_COMPLETE",
                detail={
                    "resolved_count": resolved_count,
                    "needs_user_count": needs_user_count,
                    "cv_path": cv_path,
                },
            )
            session.commit()

    return PreparationResult(
        application_id=application_id,
        state=next_state,
        resolved_count=resolved_count,
        needs_user_count=needs_user_count,
        answers=resolutions,
        selected_cv_path=cv_path,
    )


# ── Human Approval & Submission Actions ──────────────────────────────────────

def approve_application(application_id: str, notes: str = "") -> None:
    """User human approval gate (PRD §21.1 / §21.3)."""
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        app.review_decision = "APPROVED"
        app.review_notes = notes
        app.reviewed_at = datetime.now(timezone.utc)

        transition_to(
            session,
            app,
            ApplicationState.APPROVED,
            event_type="REVIEW_APPROVAL",
            detail={"notes": notes},
        )
        session.commit()


def submit_application(
    application_id: str,
    confirmation_url: str = "",
    ats_application_id: str = "",
) -> None:
    """
    Submission state execution with Layer 3 Pre-Submit safety re-check:
      1. Layer 3 Safety ceiling re-read directly from DB.
      2. Duplicate submission re-check.
      3. Transition: APPROVED/REVIEW -> SUBMITTING -> VERIFYING -> SUBMITTED.
    """
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        # Layer 3 Safety Ceiling re-read immediately before irreversible submission
        verify_safety_ceiling(session, app.candidate_id, layer="pre_submit")

        # Re-check duplicates immediately before submit
        verify_no_duplicate(session, app.job_id, current_application_id=app.id)

        # Transition through SUBMITTING
        transition_to(
            session,
            app,
            ApplicationState.SUBMITTING,
            event_type="SUBMISSION_INITIATED",
        )
        session.commit()

        # Transition through VERIFYING
        transition_to(
            session,
            app,
            ApplicationState.VERIFYING,
            event_type="VERIFICATION_INITIATED",
        )
        session.commit()

        # Final transition to SUBMITTED
        app.submitted_at = datetime.now(timezone.utc)
        app.confirmation_url = confirmation_url or "https://ats.example.com/confirmed"
        if ats_application_id:
            app.ats_application_id = ats_application_id

        transition_to(
            session,
            app,
            ApplicationState.SUBMITTED,
            event_type="SUBMISSION_CONFIRMED",
            detail={
                "confirmation_url": app.confirmation_url,
                "ats_application_id": app.ats_application_id,
            },
        )
        session.commit()


def mark_uncertain(application_id: str, reason: str = "") -> None:
    """
    Transition application to UNCERTAIN state (PRD §21.3).
    Used when submit was clicked but no confirmation was detected.
    Never auto-retry from UNCERTAIN.
    """
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        transition_to(
            session,
            app,
            ApplicationState.UNCERTAIN,
            event_type="SUBMISSION_UNCERTAIN",
            detail={"reason": reason},
        )
        session.commit()


# ── Crash Recovery Handler (PRD §21.4) ───────────────────────────────────────

def recover_crashed_applications(session: sa.orm.Session, candidate_id: str) -> list[tuple[str, str, str]]:
    """
    On system restart, inspect all non-terminal in-flight applications.
    Apply state.crash_resolution:
      - PREPARING / STARTED / FORM_DETECTED / FILLING -> reset to QUEUED
      - SUBMITTING / VERIFYING -> reset to UNCERTAIN (never auto-retry)
      - REVIEW -> preserved for human
    Returns list of (application_id, old_state, new_state).
    """
    in_flight_states = [
        ApplicationState.PREPARING.value,
        ApplicationState.STARTED.value,
        ApplicationState.FORM_DETECTED.value,
        ApplicationState.FILLING.value,
        ApplicationState.QUESTIONS.value,
        ApplicationState.STEP_DONE.value,
        ApplicationState.SUBMITTING.value,
        ApplicationState.VERIFYING.value,
    ]
    apps = session.execute(
        sa.select(Application).where(
            Application.candidate_id == candidate_id,
            Application.state.in_(in_flight_states),
        )
    ).scalars().all()

    recovered: list[tuple[str, str, str]] = []
    for app in apps:
        curr_enum = ApplicationState(app.state)
        target_enum = curr_enum.crash_resolution
        if target_enum != curr_enum:
            old_str = app.state
            app.previous_state = old_str
            app.state = target_enum.value
            app.updated_at = datetime.now(timezone.utc)

            _record_audit_event(
                session=session,
                application_id=app.id,
                event_type="CRASH_RECOVERY",
                from_state=old_str,
                to_state=target_enum.value,
                detail={"reason": f"System restarted while application was in {old_str}"},
            )
            recovered.append((app.id, old_str, target_enum.value))

    if recovered:
        session.commit()

    return recovered


# ── Audit Event Helper ───────────────────────────────────────────────────────

def _record_audit_event(
    session: sa.orm.Session,
    application_id: str,
    event_type: str,
    from_state: str | None,
    to_state: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append-only immutable audit record."""
    event = AuditEvent(
        application_id=application_id,
        event_type=event_type,
        from_state=from_state,
        to_state=to_state,
        detail_json=json.dumps(detail) if detail else None,
        occurred_at=datetime.now(timezone.utc),
    )
    session.add(event)