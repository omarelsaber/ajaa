"""
src/ajaa/types.py

THE FIRST FILE.

This module defines the foundational types for AJAA. Every other module
in the codebase imports from here. Nothing here imports from anywhere
in src/ajaa/ except standard library and third-party packages.

Design principles:
  - Secret cannot be stringified, logged, or JSON-serialized.
  - Untrusted[T] wraps strings from external (job descriptions, form labels)
    that must never be placed in the SYSTEM or CONTEXT prompt channels.
  - All enums are string-based for readability in logs and the DB.
  - Sentinel types (NOT_SET) distinguish "user has not configured this yet"
    from zero or None.
"""
from __future__ import annotations

import enum
import uuid
from typing import Any, Generic, TypeVar


# ── Secret ────────────────────────────────────────────────────────────────────

class Secret:
    """
    A secret value (API key, password, session cookie, etc.).

    Cannot be stringified, repr'd, logged, or JSON-serialized.
    The only way to access the raw value is via .reveal(), which has
    at most 2 call sites in the entire codebase (browser login helper
    and SMTP client). A lint rule enforces this count.

    Usage:
        key = Secret("sk-...")
        str(key)       # raises TypeError
        repr(key)      # returns "<Secret redacted>"
        f"{key}"       # raises TypeError (calls __str__)
        key.reveal()   # returns the raw string — call sparingly
    """

    __slots__ = ("_v",)

    def __init__(self, value: str) -> None:
        # Use object.__setattr__ because Secret is effectively frozen.
        object.__setattr__(self, "_v", value)

    def __repr__(self) -> str:
        return "<Secret redacted>"

    def __str__(self) -> str:
        raise TypeError(
            "Secret cannot be converted to str. "
            "If you need the raw value, call .reveal() explicitly. "
            "Make sure you are not accidentally logging or serializing a secret."
        )

    def __format__(self, format_spec: str) -> str:
        raise TypeError(
            "Secret cannot be formatted (f-string, .format(), etc.). "
            "Call .reveal() if you need the raw value."
        )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Secret):
            # Constant-time comparison to prevent timing attacks.
            import hmac
            return hmac.compare_digest(self._v, other._v)  # type: ignore[attr-defined]
        return NotImplemented

    def __hash__(self) -> int:
        # Needed for use in sets/dicts; uses the raw value hash.
        return hash(self._v)  # type: ignore[attr-defined]

    def reveal(self) -> str:
        """
        Return the raw secret value.

        CALL SITES: At most 2 in the entire codebase.
        Enforced by: tests/unit/test_secret_call_sites.py
        """
        return self._v  # type: ignore[attr-defined]

    def __reduce__(self) -> tuple[Any, ...]:
        raise TypeError("Secret cannot be pickled.")

    def __copy__(self) -> "Secret":
        return Secret(self._v)  # type: ignore[attr-defined]

    def __deepcopy__(self, memo: dict[Any, Any]) -> "Secret":
        return Secret(self._v)  # type: ignore[attr-defined]


# ── Untrusted ─────────────────────────────────────────────────────────────────

T = TypeVar("T")


class Untrusted(Generic[T]):
    """
    A value from an external, potentially adversarial source.

    Wraps strings (or other values) from:
      - Job descriptions
      - Form labels and placeholder text
      - Employer-provided question text
      - ATS API payloads

    The 3-channel prompt builder REFUSES to place an Untrusted value
    outside the UNTRUSTED block. This is enforced by type checking
    and a runtime assertion in the builder.

    LLM output derived from an Untrusted input inherits this taint:
    the output should also be wrapped in Untrusted before further use.

    Usage:
        raw_job_text = Untrusted("We are hiring...")
        # Pass to builder — it will route to UNTRUSTED block automatically.
        # Do NOT unwrap with .value and pass to SYSTEM or CONTEXT.
    """

    __slots__ = ("_value",)

    def __init__(self, value: T) -> None:
        object.__setattr__(self, "_value", value)

    @property
    def value(self) -> T:
        """The raw untrusted value. Handle with care."""
        return self._value  # type: ignore[attr-defined]

    def __repr__(self) -> str:
        return f"Untrusted({self._value!r})"  # type: ignore[attr-defined]

    def __str__(self) -> str:
        # Allow string conversion for logging; taint is at the type level.
        return str(self._value)  # type: ignore[attr-defined]


UntrustedStr = Untrusted[str]


# ── Sentinel: NOT_SET ─────────────────────────────────────────────────────────

class _NotSetType:
    """
    Sentinel for configuration values that the user has not yet set.

    Distinct from None (which means "no value") and 0 (which is a value).

    Used for operational policy fields like max_applications_per_day and
    min_match_score, which ship as NOT_SET until the user calibrates.
    """

    _instance: "_NotSetType | None" = None

    def __new__(cls) -> "_NotSetType":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "NOT_SET"

    def __bool__(self) -> bool:
        return False

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _NotSetType)

    def __hash__(self) -> int:
        return hash("__NOT_SET__")


NOT_SET = _NotSetType()


# ── FactSource ────────────────────────────────────────────────────────────────

class FactSource(str, enum.Enum):
    """
    Source of a fact in the fact ledger.

    Rank (highest wins):
      1. USER_EXPLICIT           — typed by the user in the interview or profile editor
      2. USER_CONFIRMED_SUGGESTION — user confirmed an LLM or CV suggestion
      3. APPLICATION_ANSWER      — answer given in a real application form
      4. CV_EXPLICIT             — explicitly stated in the CV text
      5. CV_INFERRED             — inferred from CV context (e.g. tenure from dates)
      6. LLM_INFERENCE           — generated by the model without citation
      7. DEFAULT                 — system default when no other source exists

    IMPORTANT: LLM_INFERENCE facts have usable_in_applications=False forced
    at write time (enforced by DB CHECK constraint and application code).
    """

    USER_EXPLICIT = "USER_EXPLICIT"
    USER_CONFIRMED_SUGGESTION = "USER_CONFIRMED_SUGGESTION"
    APPLICATION_ANSWER = "APPLICATION_ANSWER"
    CV_EXPLICIT = "CV_EXPLICIT"
    CV_INFERRED = "CV_INFERRED"
    LLM_INFERENCE = "LLM_INFERENCE"
    DEFAULT = "DEFAULT"

    @property
    def rank(self) -> int:
        """Lower number = higher precedence."""
        return {
            "USER_EXPLICIT": 1,
            "USER_CONFIRMED_SUGGESTION": 2,
            "APPLICATION_ANSWER": 3,
            "CV_EXPLICIT": 4,
            "CV_INFERRED": 5,
            "LLM_INFERENCE": 6,
            "DEFAULT": 7,
        }[self.value]

    def outranks(self, other: "FactSource") -> bool:
        """Return True if this source has higher precedence than other."""
        return self.rank < other.rank

    @property
    def is_user_controlled(self) -> bool:
        return self in (FactSource.USER_EXPLICIT, FactSource.USER_CONFIRMED_SUGGESTION)


# ── Confidence ────────────────────────────────────────────────────────────────

class Confidence(str, enum.Enum):
    """
    Confidence level of a fact.

    CONFIRMED is the highest: the user has explicitly verified the value.
    LOW facts from LLM_INFERENCE are never used in applications.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CONFIRMED = "CONFIRMED"

    @property
    def numeric(self) -> float:
        return {"LOW": 0.25, "MEDIUM": 0.5, "HIGH": 0.75, "CONFIRMED": 1.0}[self.value]


# ── FactState ─────────────────────────────────────────────────────────────────

class FactState(str, enum.Enum):
    """
    The epistemic state of a fact slot.

    CRITICAL: Absence of a state is NOT one of these values.
    All four states are distinct and have different downstream effects.

      KNOWN               — we have a value for this slot
      UNKNOWN             — we know we don't know (asked; no answer yet)
      REFUSED_TO_ANSWER   — user explicitly declined to answer
      NOT_APPLICABLE      — this slot does not apply to this candidate

    NOT_APPLICABLE slots score ZERO in coverage and are never re-asked.
    REFUSED_TO_ANSWER prevents re-asking the same question.
    UNKNOWN allows re-asking (the slot is open).
    """

    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    REFUSED_TO_ANSWER = "REFUSED_TO_ANSWER"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @property
    def counts_as_covered(self) -> bool:
        """Whether this state counts as coverage for the slot."""
        return self in (FactState.KNOWN, FactState.REFUSED_TO_ANSWER, FactState.NOT_APPLICABLE)

    @property
    def blocks_reask(self) -> bool:
        """Whether this state prevents the interview from re-asking this slot."""
        return self in (FactState.REFUSED_TO_ANSWER, FactState.NOT_APPLICABLE)


# ── ApplicationState ──────────────────────────────────────────────────────────

class ApplicationState(str, enum.Enum):
    """
    States of the application state machine.

    IMPORTANT: UNCERTAIN is never auto-retried. A human always resolves it.
    SUBMITTING is never re-entered for the same application.

    Pre-SUBMITTING states are safe to restart from QUEUED after a crash.
    SUBMITTING/VERIFYING crashes -> UNCERTAIN (human resolves).
    """

    # ── Discovery & matching pipeline ────────────────────────
    DISCOVERED = "DISCOVERED"
    MATCHED = "MATCHED"

    # ── Application lifecycle ─────────────────────────────────
    QUEUED = "QUEUED"
    PREPARING = "PREPARING"    # CV selection, answers, freshness check — before browser
    STARTED = "STARTED"
    FORM_DETECTED = "FORM_DETECTED"
    FILLING = "FILLING"
    QUESTIONS = "QUESTIONS"
    STEP_DONE = "STEP_DONE"
    REVIEW = "REVIEW"          # human reviews before submit; always in v0.1
    READY_FOR_REVIEW = "READY_FOR_REVIEW"  # synonym for REVIEW
    APPROVED = "APPROVED"      # human approved for submission
    SUBMITTING = "SUBMITTING"  # NEVER re-entered for the same application
    VERIFYING = "VERIFYING"

    # ── Terminal states ───────────────────────────────────────
    SUBMITTED = "SUBMITTED"
    UNCERTAIN = "UNCERTAIN"    # submit clicked; no confirmation; NEVER auto-retry
    FAILED = "FAILED"

    # ── Blocked / paused states ───────────────────────────────
    REJECTED = "REJECTED"          # hard gate rejected
    SKIPPED = "SKIPPED"            # user skipped
    EXPIRED = "EXPIRED"            # job no longer live (freshness gate)
    STALE_JOB = "STALE_JOB"        # synonym for EXPIRED
    ABANDONED = "ABANDONED"        # user abandoned
    NEEDS_USER_ACTION = "NEEDS_USER_ACTION"
    NEEDS_USER = "NEEDS_USER"      # synonym for NEEDS_USER_ACTION
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    REDIRECTED = "REDIRECTED"
    BLOCKED_BY_SITE = "BLOCKED_BY_SITE"    # CAPTCHA, bot check, etc.

    @property
    def is_terminal(self) -> bool:
        return self in {
            ApplicationState.SUBMITTED,
            ApplicationState.UNCERTAIN,
            ApplicationState.FAILED,
            ApplicationState.REJECTED,
            ApplicationState.SKIPPED,
            ApplicationState.EXPIRED,
            ApplicationState.ABANDONED,
            ApplicationState.BLOCKED_BY_SITE,
        }

    @property
    def is_pre_browser(self) -> bool:
        """States before the browser has been opened — safe to re-queue on crash."""
        return self in {
            ApplicationState.QUEUED,
            ApplicationState.PREPARING,
        }

    @property
    def crash_resolution(self) -> "ApplicationState":
        """What state to assign if the process crashes while in this state."""
        if self in (ApplicationState.SUBMITTING, ApplicationState.VERIFYING):
            return ApplicationState.UNCERTAIN
        if self.is_pre_browser or self in (
            ApplicationState.STARTED,
            ApplicationState.FORM_DETECTED,
            ApplicationState.FILLING,
            ApplicationState.QUESTIONS,
            ApplicationState.STEP_DONE,
            ApplicationState.REVIEW,
        ):
            return ApplicationState.QUEUED
        return self


# ── Tier ─────────────────────────────────────────────────────────────────────

class Tier(str, enum.Enum):
    """LLM task tiers, mapped to model IDs in providers.yaml."""
    CHEAP = "cheap"
    MID = "mid"
    STRONG = "strong"
    VISION = "vision"


# ── LLM Task keys ─────────────────────────────────────────────────────────────

class LLMTask(str, enum.Enum):
    """
    Known LLM task types. Defined here so task keys are type-safe.
    Each maps to a tier in tasks.yaml and a Pydantic schema in llm/schemas.py.
    """
    CV_EXTRACTION = "cv_extraction"
    JOB_REQUIREMENT_EXTRACTION = "job_requirement_extraction"
    FIELD_CLASSIFICATION = "field_classification"
    QUESTION_TYPE_CLASSIFICATION = "question_type_classification"
    MATCH_ADJUDICATION = "match_adjudication"
    OPEN_ENDED_GENERATION = "open_ended_generation"
    RECOVERY_REASONING = "recovery_reasoning"
    VISION_SCREENSHOT = "vision_screenshot"


# ── ID type aliases ───────────────────────────────────────────────────────────

FactID = uuid.UUID
ApplicationID = uuid.UUID
JobID = uuid.UUID
RunID = uuid.UUID
CVID = uuid.UUID
CVVersionID = uuid.UUID


# ── Module exports ────────────────────────────────────────────────────────────

__all__ = [
    "Secret",
    "Untrusted",
    "UntrustedStr",
    "NOT_SET",
    "_NotSetType",
    "FactSource",
    "Confidence",
    "FactState",
    "ApplicationState",
    "Tier",
    "LLMTask",
    "FactID",
    "ApplicationID",
    "JobID",
    "RunID",
    "CVID",
    "CVVersionID",
]
