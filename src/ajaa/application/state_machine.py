"""
src/ajaa/application/state_machine.py

Application Lifecycle State Machine & Orchestrator.

States:
  - QUEUED: application created, awaiting preparation
  - PREPARING: answers being resolved & grounded
  - READY_FOR_REVIEW: all answers ready, waiting for user approval
  - NEEDS_USER: one or more questions cannot be answered deterministically
  - APPROVED: approved by user for submission
  - SUBMITTED: form successfully submitted
  - REJECTED: user discarded the application
  - STALE_JOB: job listing dead or closed
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from ajaa.answering.resolver import AnswerResolution, FormField, ResolutionStatus, resolve_field
from ajaa.candidate.profile import build_profile
from ajaa.db.models import Application, ApplicationAnswer, AuditEvent, Job
from ajaa.db.session import get_session
import sqlalchemy as sa


class ApplicationState(str, Enum):
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    NEEDS_USER = "NEEDS_USER"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    STALE_JOB = "STALE_JOB"


@dataclass
class PreparationResult:
    application_id: str
    state: ApplicationState
    resolved_count: int
    needs_user_count: int
    answers: list[AnswerResolution]


def prepare_application(
    application_id: str,
    form_fields: list[FormField] | None = None,
) -> PreparationResult:
    """
    Execute PREPARING step:
      1. Load application, candidate profile, and job.
      2. Check job staleness gate.
      3. If form_fields not provided, construct standard ATS fields.
      4. Resolve all fields against CanonicalProfile facts.
      5. Save answers to application_answers table.
      6. Transition state to READY_FOR_REVIEW (or NEEDS_USER if required field unresolved).
    """
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()

        if app is None:
            raise ValueError(f"Application {application_id} not found")

        job = session.execute(
            sa.select(Job).where(Job.id == app.job_id)
        ).scalars().first()

        if job is None or job.is_stale:
            app.state = ApplicationState.STALE_JOB.value
            session.commit()
            return PreparationResult(
                application_id=application_id,
                state=ApplicationState.STALE_JOB,
                resolved_count=0,
                needs_user_count=0,
                answers=[],
            )

        candidate_id = app.candidate_id
        profile = build_profile(candidate_id)
        facts = profile.to_dict()

        # Update state to PREPARING
        app.previous_state = app.state
        app.state = ApplicationState.PREPARING.value
        session.commit()

    # Standard ATS form fields if none detected yet
    fields_to_resolve = form_fields or [
        FormField(name="full_name", label="Full Legal Name", required=True),
        FormField(name="email", label="Email Address", required=True),
        FormField(name="phone", label="Phone Number", required=True),
        FormField(name="city", label="City", required=False),
        FormField(name="linkedin", label="LinkedIn Profile", required=False),
        FormField(name="github", label="GitHub Profile", required=False),
        FormField(name="sponsorship", label="Will you now or in the future require visa sponsorship?", field_type="radio", required=True),
    ]

    resolutions: list[AnswerResolution] = [
        resolve_field(f, facts) for f in fields_to_resolve
    ]

    resolved_count = sum(1 for r in resolutions if r.status == ResolutionStatus.RESOLVED)
    needs_user_count = sum(1 for r in resolutions if r.status == ResolutionStatus.NEEDS_USER)

    next_state = (
        ApplicationState.NEEDS_USER if needs_user_count > 0 else ApplicationState.READY_FOR_REVIEW
    )

    # Persist answers into application_answers table
    now = datetime.now(timezone.utc)
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app:
            app.previous_state = app.state
            app.state = next_state.value

            # Clean old answers if any
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

            # Record audit event
            _record_audit_event(
                session=session,
                application_id=application_id,
                event_type="PREPARATION_COMPLETE",
                from_state="PREPARING",
                to_state=next_state.value,
                detail={"resolved_count": resolved_count, "needs_user_count": needs_user_count},
            )

            session.commit()

    return PreparationResult(
        application_id=application_id,
        state=next_state,
        resolved_count=resolved_count,
        needs_user_count=needs_user_count,
        answers=resolutions,
    )


def approve_application(application_id: str, notes: str = "") -> None:
    """User human approval gate."""
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        old_state = app.state
        app.previous_state = old_state
        app.review_decision = "APPROVED"
        app.review_notes = notes
        app.reviewed_at = datetime.now(timezone.utc)
        app.state = ApplicationState.APPROVED.value

        _record_audit_event(
            session=session,
            application_id=application_id,
            event_type="REVIEW_APPROVAL",
            from_state=old_state,
            to_state=ApplicationState.APPROVED.value,
            detail={"notes": notes},
        )
        session.commit()


def submit_application(application_id: str, confirmation_url: str = "") -> None:
    """Mark application as submitted."""
    with get_session() as session:
        app = session.execute(
            sa.select(Application).where(Application.id == application_id)
        ).scalars().first()
        if app is None:
            raise ValueError(f"Application {application_id} not found")

        old_state = app.state
        app.previous_state = old_state
        app.state = ApplicationState.SUBMITTED.value
        app.submitted_at = datetime.now(timezone.utc)
        app.confirmation_url = confirmation_url or "https://ats.example.com/confirmed"

        _record_audit_event(
            session=session,
            application_id=application_id,
            event_type="SUBMISSION_CONFIRMED",
            from_state=old_state,
            to_state=ApplicationState.SUBMITTED.value,
            detail={"confirmation_url": app.confirmation_url},
        )
        session.commit()


def _record_audit_event(
    session,
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