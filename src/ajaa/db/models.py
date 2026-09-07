"""
src/ajaa/db/models.py

SQLAlchemy ORM models — canonical schema for AJAA.

Design constraints:
  1. ONE candidate_context row per installation (enforced at runtime by ajaa init).
  2. Fact precedence is FactSource rank: lower number = wins. Stored as INTEGER.
  3. LLM_INFERENCE facts: usable_in_applications=False enforced by CHECK constraint.
  4. ApplicationState transitions validated in the application layer, not here.
  5. All text fields that may contain PII are marked with info="pii" metadata.
  6. Passwords / API keys are NEVER stored in the DB — keychain only.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

import sqlalchemy as sa
import sqlalchemy.orm as orm

# ── Base ──────────────────────────────────────────────────────────────────────

class Base(orm.DeclarativeBase):
    pass


def _new_uuid() -> str:
    return str(uuid.uuid4())


# ── candidate_context ─────────────────────────────────────────────────────────

class CandidateContext(Base):
    """
    One row per installation.

    Represents the owner of this AJAA instance. ajaa init creates
    this row once and refuses to create a second one.
    """
    __tablename__ = "candidate_context"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    display_name: orm.Mapped[str] = orm.mapped_column(
        sa.String(200), info={"pii": True}
    )
    locale: orm.Mapped[str] = orm.mapped_column(sa.String(10), default="en-US")
    calibration_completed: orm.Mapped[bool] = orm.mapped_column(
        sa.Boolean, default=False
    )
    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    facts: orm.Mapped[list["Fact"]] = orm.relationship(
        "Fact", back_populates="candidate", cascade="all, delete-orphan"
    )
    cvs: orm.Mapped[list["CV"]] = orm.relationship(
        "CV", back_populates="candidate", cascade="all, delete-orphan"
    )
    applications: orm.Mapped[list["Application"]] = orm.relationship(
        "Application", back_populates="candidate", cascade="all, delete-orphan"
    )
    cover_letters: orm.Mapped[list["CoverLetter"]] = orm.relationship(
        "CoverLetter", back_populates="candidate", cascade="all, delete-orphan"
    )


# ── fact_ledger ───────────────────────────────────────────────────────────────

class Fact(Base):
    """
    The fact ledger. One row per fact per source.

    Precedence: lower source_rank wins (FactSource.rank).
    When two facts have the same key, the one with lower source_rank is canonical.
    Equal ranks: latest updated_at wins.

    LLM_INFERENCE constraint: usable_in_applications must be False (source_rank=6).
    """
    __tablename__ = "fact_ledger"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    candidate_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("candidate_context.id", ondelete="CASCADE"),
        index=True,
    )

    # The fact identifier (e.g. "personal.name.full", "skill.python.years")
    fact_key: orm.Mapped[str] = orm.mapped_column(sa.String(300), index=True)
    fact_value: orm.Mapped[str] = orm.mapped_column(
        sa.Text, info={"pii": True}
    )

    # Source provenance
    source_rank: orm.Mapped[int] = orm.mapped_column(
        sa.Integer,
        sa.CheckConstraint("source_rank BETWEEN 1 AND 7", name="ck_fact_source_rank"),
    )
    source_label: orm.Mapped[str] = orm.mapped_column(sa.String(50))
    source_ref: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(300), nullable=True
    )  # CV ID, application ID, or None

    # Confidence — must match types.Confidence enum exactly
    confidence: orm.Mapped[str] = orm.mapped_column(
        sa.String(20),
        sa.CheckConstraint(
            "confidence IN ('LOW', 'MEDIUM', 'HIGH', 'CONFIRMED')",
            name="ck_fact_confidence",
        ),
        default="MEDIUM",
    )

    # State — must match types.FactState enum exactly
    state: orm.Mapped[str] = orm.mapped_column(
        sa.String(30),
        sa.CheckConstraint(
            "state IN ('KNOWN', 'UNKNOWN', 'REFUSED_TO_ANSWER', 'NOT_APPLICABLE')",
            name="ck_fact_state",
        ),
        default="KNOWN",
    )

    # HARD RULE: LLM_INFERENCE facts (source_rank=6) cannot be used in applications
    usable_in_applications: orm.Mapped[bool] = orm.mapped_column(
        sa.Boolean,
        sa.CheckConstraint(
            "NOT (source_rank = 6 AND usable_in_applications = 1)",
            name="ck_llm_inference_not_usable",
        ),
        default=True,
    )

    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    # Unique: one (candidate, fact_key, source_rank) per DB
    __table_args__ = (
        sa.UniqueConstraint(
            "candidate_id", "fact_key", "source_rank",
            name="uq_fact_candidate_key_source",
        ),
    )

    candidate: orm.Mapped["CandidateContext"] = orm.relationship(
        "CandidateContext", back_populates="facts"
    )


# ── cv ────────────────────────────────────────────────────────────────────────

class CV(Base):
    """
    Stores CV file metadata and extraction status.
    The actual file lives in data_dir/cvs/<id>.<ext>.
    """
    __tablename__ = "cvs"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    candidate_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("candidate_context.id", ondelete="CASCADE"),
        index=True,
    )

    filename: orm.Mapped[str] = orm.mapped_column(sa.String(500), info={"pii": True})
    label: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(200), nullable=True
    )  # User-facing label, e.g. "My CV 2025"
    file_path: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(1000), nullable=True
    )  # Absolute path to saved PDF on disk
    content_hash: orm.Mapped[str] = orm.mapped_column(
        sa.String(64), index=True
    )  # SHA-256 hex. Same hash = same file = cache hit.

    # Extracted text (stored for re-extraction without re-upload)
    raw_text: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    page_count: orm.Mapped[int] = orm.mapped_column(sa.Integer, default=0)
    char_count: orm.Mapped[int] = orm.mapped_column(sa.Integer, default=0)

    extraction_status: orm.Mapped[str] = orm.mapped_column(
        sa.String(20),
        sa.CheckConstraint(
            "extraction_status IN ('PENDING', 'EXTRACTING', 'DONE', 'FAILED')",
            name="ck_cv_extraction_status",
        ),
        default="PENDING",
    )
    extraction_version: orm.Mapped[Optional[int]] = orm.mapped_column(
        sa.Integer, nullable=True
    )  # Increment when re-extracted (model version change)

    is_active: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=True)

    uploaded_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    extracted_at: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )
    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        sa.UniqueConstraint("candidate_id", "content_hash", name="uq_cv_candidate_hash"),
    )

    candidate: orm.Mapped["CandidateContext"] = orm.relationship(
        "CandidateContext", back_populates="cvs"
    )
    extraction_cache: orm.Mapped[list["ExtractionCache"]] = orm.relationship(
        "ExtractionCache", back_populates="cv", cascade="all, delete-orphan"
    )


# ── extraction_cache ──────────────────────────────────────────────────────────

class ExtractionCache(Base):
    """
    Content-addressed extraction cache.
    Same content_hash + extractor_version = cache hit, no LLM call.
    """
    __tablename__ = "extraction_cache"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    cv_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("cvs.id", ondelete="CASCADE"), index=True
    )
    content_hash: orm.Mapped[str] = orm.mapped_column(sa.String(64), index=True)
    extractor_version: orm.Mapped[str] = orm.mapped_column(
        sa.String(20), default="v1.0"
    )  # String like "v1.0" — bump to invalidate old cache entries
    extracted_json: orm.Mapped[str] = orm.mapped_column(sa.Text)  # JSON array of facts
    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        sa.UniqueConstraint(
            "content_hash", "extractor_version",
            name="uq_extraction_hash_version",
        ),
    )

    cv: orm.Mapped["CV"] = orm.relationship("CV", back_populates="extraction_cache")


# ── job ───────────────────────────────────────────────────────────────────────

class Job(Base):
    """
    A discovered job listing.
    One row per unique apply_url (deduplicated by URL + hash).
    """
    __tablename__ = "jobs"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )

    # Dedup key: SHA-256 of normalized(apply_url)
    url_hash: orm.Mapped[str] = orm.mapped_column(
        sa.String(64), index=True, unique=True
    )
    apply_url: orm.Mapped[str] = orm.mapped_column(sa.String(2000))
    source_connector: orm.Mapped[str] = orm.mapped_column(sa.String(50))  # "greenhouse", "lever", "ashby"

    title: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(500), nullable=True)
    company: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(200), nullable=True)
    location: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(200), nullable=True)
    remote_ok: orm.Mapped[Optional[bool]] = orm.mapped_column(sa.Boolean, nullable=True)

    # Freshness gate result
    last_freshness_check: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )
    is_stale: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)

    # Match score (populated after matching engine runs)
    match_score: orm.Mapped[Optional[float]] = orm.mapped_column(
        sa.Float, nullable=True,
    )

    discovered_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    jd_scraped_at: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )
    jd_text: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    jd_content_hash: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(64), nullable=True
    )

    # Injection defense & quarantine (PRD §23.6, §33.6)
    injection_suspected: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)
    quarantined: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)
    quarantine_reason: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(500), nullable=True
    )

    __table_args__ = (
        sa.CheckConstraint(
            "match_score IS NULL OR (match_score >= 0.0 AND match_score <= 1.0)",
            name="ck_job_match_score_range",
        ),
    )

    applications: orm.Mapped[list["Application"]] = orm.relationship(
        "Application", back_populates="job"
    )


# ── application ───────────────────────────────────────────────────────────────

class Application(Base):
    """
    One row per application attempt.
    Tracks the full state machine (ApplicationState enum).
    """
    __tablename__ = "applications"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    candidate_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("candidate_context.id", ondelete="CASCADE"),
        index=True,
    )
    job_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("jobs.id", ondelete="RESTRICT"), index=True
    )

    state: orm.Mapped[str] = orm.mapped_column(
        sa.String(30), index=True, default="QUEUED"
    )
    previous_state: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(30), nullable=True
    )

    # Safety gate results (stored as JSON strings for flexibility)
    safety_block_reasons: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.Text, nullable=True
    )  # JSON array of block reason strings

    # Review decision
    review_decision: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(20),
        sa.CheckConstraint(
            "review_decision IS NULL OR review_decision IN ('APPROVED', 'REJECTED', 'EDITED')",
            name="ck_app_review_decision",
        ),
        nullable=True,
    )
    review_notes: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    reviewed_at: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )

    # Submission result
    ats_application_id: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(200), nullable=True
    )
    submitted_at: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )
    confirmation_url: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(2000), nullable=True
    )

    # Audit
    error_message: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    retry_count: orm.Mapped[int] = orm.mapped_column(sa.Integer, default=0)

    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    candidate: orm.Mapped["CandidateContext"] = orm.relationship(
        "CandidateContext", back_populates="applications"
    )
    job: orm.Mapped["Job"] = orm.relationship("Job", back_populates="applications")
    answers: orm.Mapped[list["ApplicationAnswer"]] = orm.relationship(
        "ApplicationAnswer", back_populates="application", cascade="all, delete-orphan"
    )
    audit_events: orm.Mapped[list["AuditEvent"]] = orm.relationship(
        "AuditEvent", back_populates="application", cascade="all, delete-orphan"
    )
    steps: orm.Mapped[list["ApplicationStep"]] = orm.relationship(
        "ApplicationStep", back_populates="application", cascade="all, delete-orphan",
        order_by="ApplicationStep.step_index",
    )
    cover_letter: orm.Mapped[Optional["CoverLetter"]] = orm.relationship(
        "CoverLetter", back_populates="application", uselist=False, cascade="all, delete-orphan"
    )


# ── application_step ──────────────────────────────────────────────────────────

class ApplicationStep(Base):
    """
    Persisted browser automation steps.
    Every step is written to the DB before action with ok=None,
    and updated after with outcome, duration, and error if any.
    """
    __tablename__ = "application_steps"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    application_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )

    step_index: orm.Mapped[int] = orm.mapped_column(sa.Integer, default=0)
    action: orm.Mapped[str] = orm.mapped_column(sa.String(50))
    field_name: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(200), nullable=True)
    field_value: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True, info={"pii": True})

    ok: orm.Mapped[Optional[bool]] = orm.mapped_column(sa.Boolean, nullable=True, default=None)
    error_message: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    screenshot_path: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(1000), nullable=True)
    duration_ms: orm.Mapped[Optional[float]] = orm.mapped_column(sa.Float, nullable=True)

    started_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    completed_at: orm.Mapped[Optional[datetime]] = orm.mapped_column(
        sa.DateTime, nullable=True
    )

    application: orm.Mapped["Application"] = orm.relationship(
        "Application", back_populates="steps"
    )


# ── application_answer ────────────────────────────────────────────────────────

class ApplicationAnswer(Base):
    """
    One row per form field answer per application.
    Stores what AJAA filled in (or planned to fill).
    """
    __tablename__ = "application_answers"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    application_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )

    field_label: orm.Mapped[str] = orm.mapped_column(sa.String(500))
    field_type: orm.Mapped[str] = orm.mapped_column(sa.String(50))  # text, select, checkbox, etc.
    answer_value: orm.Mapped[str] = orm.mapped_column(sa.Text, info={"pii": True})
    answer_source: orm.Mapped[str] = orm.mapped_column(sa.String(50))  # FactSource label
    confidence: orm.Mapped[str] = orm.mapped_column(sa.String(20), default="MEDIUM")

    is_required: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)
    was_overridden_by_human: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)

    application: orm.Mapped["Application"] = orm.relationship(
        "Application", back_populates="answers"
    )


# ── audit_event ───────────────────────────────────────────────────────────────

class AuditEvent(Base):
    """
    Immutable append-only audit log.
    Every state transition and significant action is recorded here.
    Rows are NEVER updated or deleted (soft-append only).
    """
    __tablename__ = "audit_events"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    application_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )

    event_type: orm.Mapped[str] = orm.mapped_column(sa.String(100), index=True)
    from_state: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(30), nullable=True)
    to_state: orm.Mapped[Optional[str]] = orm.mapped_column(sa.String(30), nullable=True)
    detail_json: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)

    occurred_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )

    application: orm.Mapped["Application"] = orm.relationship(
        "Application", back_populates="audit_events"
    )


# ── llm_call_log ──────────────────────────────────────────────────────────────

class LLMCallLog(Base):
    """
    Persisted LLM call log (Phase 1+).
    Phase 0 uses in-memory log in llm/gateway.py.
    """
    __tablename__ = "llm_call_log"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    run_id: orm.Mapped[str] = orm.mapped_column(sa.String(8), index=True)
    task: orm.Mapped[str] = orm.mapped_column(sa.String(100))
    tier: orm.Mapped[str] = orm.mapped_column(sa.String(20))
    model: orm.Mapped[str] = orm.mapped_column(sa.String(100))
    prompt_tokens: orm.Mapped[int] = orm.mapped_column(sa.Integer)
    completion_tokens: orm.Mapped[int] = orm.mapped_column(sa.Integer)
    cost_usd: orm.Mapped[float] = orm.mapped_column(sa.Float)
    duration_ms: orm.Mapped[float] = orm.mapped_column(sa.Float)
    cached: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)
    error: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)
    occurred_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), index=True
    )


# ── cover_letters ─────────────────────────────────────────────────────────────

class CoverLetter(Base):
    """
    Persisted cover letter generated for an application or candidate (PRD §14).
    Enforces Invariant I1: grounded_fact_ids records every fact cited.
    Tracks manual user edits for candidate voice adaptation (PRD §14.4).
    """
    __tablename__ = "cover_letters"

    id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    application_id: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("applications.id", ondelete="CASCADE"), nullable=True, index=True
    )
    candidate_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("candidate_context.id", ondelete="CASCADE"), index=True
    )
    job_id: orm.Mapped[Optional[str]] = orm.mapped_column(
        sa.String(36), sa.ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    opening_text: orm.Mapped[str] = orm.mapped_column(sa.Text, default="")
    fit_paragraph: orm.Mapped[str] = orm.mapped_column(sa.Text, default="")
    evidence_blurbs: orm.Mapped[str] = orm.mapped_column(sa.Text, default="")
    closing_text: orm.Mapped[str] = orm.mapped_column(sa.Text, default="")
    full_text: orm.Mapped[str] = orm.mapped_column(sa.Text, default="")

    grounded_fact_ids: orm.Mapped[str] = orm.mapped_column(sa.Text, default="[]")
    was_edited: orm.Mapped[bool] = orm.mapped_column(sa.Boolean, default=False)
    edited_text: orm.Mapped[Optional[str]] = orm.mapped_column(sa.Text, nullable=True)

    created_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: orm.Mapped[datetime] = orm.mapped_column(
        sa.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )

    candidate: orm.Mapped["CandidateContext"] = orm.relationship(
        "CandidateContext", back_populates="cover_letters"
    )
    application: orm.Mapped[Optional["Application"]] = orm.relationship(
        "Application", back_populates="cover_letter"
    )