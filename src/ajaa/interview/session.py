"""
src/ajaa/interview/session.py

InterviewSession — drives the question-answer loop.

State machine per session:
  READY -> ASKING -> ANSWERED -> NEXT -> (ASKING | COMPLETE)

The session reads from CanonicalProfile (what we already know),
determines which questions are uncovered and applicable,
presents them one at a time, and persists answers to the fact ledger.

Session is stateless between calls — all state lives in the DB.
The UI calls next_question() -> show it -> submit_answer() -> repeat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence

from ajaa.candidate.profile import CanonicalProfile, build_profile
from ajaa.db.repositories import fact as fact_repo
from ajaa.interview.corpus import Question, QuestionCorpus
from ajaa.types import Confidence, FactSource, FactState


class InterviewPhase(str, Enum):
    """High-level phase of the interview."""
    FOUNDATION    = "foundation"    # required personal + contact facts
    PROFESSIONAL  = "professional"  # work history, skills, education
    PREFERENCES   = "preferences"   # job type, location, salary expectations
    SAFETY        = "safety"        # sponsorship, auth-to-work
    CALIBRATION   = "calibration"   # verify auto-apply settings
    COMPLETE      = "complete"      # all required facts covered


PHASE_ORDER = [
    InterviewPhase.FOUNDATION,
    InterviewPhase.PROFESSIONAL,
    InterviewPhase.PREFERENCES,
    InterviewPhase.SAFETY,
    InterviewPhase.CALIBRATION,
]


@dataclass
class AnswerResult:
    """Result of submitting an answer."""
    fact_key: str
    accepted: bool
    message: str = ""
    next_question: "Question | None" = None
    phase_complete: bool = False
    interview_complete: bool = False


@dataclass
class InterviewSession:
    """
    Manages one pass through the question corpus for a candidate.

    Usage:
        session = InterviewSession.start(candidate_id, corpus)
        while True:
            q = session.next_question()
            if q is None:
                break  # complete
            answer = get_answer_from_ui(q)
            result = session.submit_answer(q.key, answer)
    """
    candidate_id: str
    corpus: QuestionCorpus
    _profile: CanonicalProfile = field(repr=False)
    _phase: InterviewPhase = InterviewPhase.FOUNDATION
    _asked_this_session: set[str] = field(default_factory=set)
    _skipped_this_session: set[str] = field(default_factory=set)

    @classmethod
    def start(cls, candidate_id: str, corpus: QuestionCorpus) -> "InterviewSession":
        """Create a new session. Loads the current profile from DB."""
        profile = build_profile(candidate_id)
        return cls(
            candidate_id=candidate_id,
            corpus=corpus,
            _profile=profile,
        )

    def refresh_profile(self) -> None:
        """Reload the profile from DB (call after submitting answers)."""
        self._profile = build_profile(self.candidate_id)

    @property
    def phase(self) -> InterviewPhase:
        return self._phase

    @property
    def is_complete(self) -> bool:
        return self._phase == InterviewPhase.COMPLETE

    def progress(self) -> dict[str, int]:
        """Return {covered: int, total: int} for required questions."""
        required = self.corpus.keys_required()
        covered = sum(1 for k in required if self._profile.has(k))
        return {"covered": covered, "total": len(required)}

    def next_question(self) -> Question | None:
        """
        Return the next unanswered, applicable question in the current phase.
        Returns None if the interview is complete.
        """
        if self._phase == InterviewPhase.COMPLETE:
            return None

        known_keys = set(self._profile.to_dict().keys())

        # Try questions in current phase first, then advance
        for phase in self._current_and_later_phases():
            candidates = self.corpus.by_tier(phase.value)
            for q in candidates:
                if q.key in self._asked_this_session:
                    continue
                if q.key in self._skipped_this_session:
                    continue
                if self._profile.has(q.key):
                    continue  # already known
                if not q.is_applicable(known_keys):
                    continue  # depends_on not met yet
                self._phase = phase
                return q

        # Nothing left to ask
        self._phase = InterviewPhase.COMPLETE
        return None

    def _current_and_later_phases(self) -> list[InterviewPhase]:
        """Return phases from current onward (in order)."""
        if self._phase == InterviewPhase.COMPLETE:
            return []
        try:
            idx = PHASE_ORDER.index(self._phase)
        except ValueError:
            idx = 0
        return PHASE_ORDER[idx:]

    def submit_answer(
        self,
        fact_key: str,
        raw_value: str,
        *,
        confidence: Confidence = Confidence.HIGH,
        skip: bool = False,
        refuse: bool = False,
    ) -> AnswerResult:
        """
        Record an answer to the fact ledger and advance the session.

        skip=True  → candidate wants to skip this question (FactState.UNKNOWN)
        refuse=True → candidate explicitly refuses (FactState.REFUSED_TO_ANSWER)
        Otherwise   → write as USER_EXPLICIT, FactState.KNOWN
        """
        self._asked_this_session.add(fact_key)

        if skip:
            self._skipped_this_session.add(fact_key)
            fact_repo.upsert(
                candidate_id=self.candidate_id,
                fact_key=fact_key,
                fact_value="",
                source=FactSource.USER_EXPLICIT,
                confidence=Confidence.LOW,
                state=FactState.UNKNOWN,
            )
            self.refresh_profile()
            return AnswerResult(
                fact_key=fact_key,
                accepted=True,
                message="Skipped. You can answer this later.",
                next_question=self.next_question(),
            )

        if refuse:
            fact_repo.upsert(
                candidate_id=self.candidate_id,
                fact_key=fact_key,
                fact_value="",
                source=FactSource.USER_EXPLICIT,
                confidence=Confidence.CONFIRMED,
                state=FactState.REFUSED_TO_ANSWER,
            )
            self.refresh_profile()
            return AnswerResult(
                fact_key=fact_key,
                accepted=True,
                message="Noted. This field will not be used in applications.",
                next_question=self.next_question(),
            )

        # Normal answer
        validated, message = self._validate(fact_key, raw_value)
        if not validated:
            return AnswerResult(fact_key=fact_key, accepted=False, message=message)

        fact_repo.upsert(
            candidate_id=self.candidate_id,
            fact_key=fact_key,
            fact_value=raw_value.strip(),
            source=FactSource.USER_EXPLICIT,
            confidence=confidence,
            state=FactState.KNOWN,
        )
        self.refresh_profile()

        next_q = self.next_question()
        prog = self.progress()
        phase_done = (next_q is None or next_q.tier != self._phase.value)

        return AnswerResult(
            fact_key=fact_key,
            accepted=True,
            message="Saved.",
            next_question=next_q,
            phase_complete=phase_done,
            interview_complete=(next_q is None),
        )

    def _validate(self, fact_key: str, value: str) -> tuple[bool, str]:
        """Run basic validators. Returns (ok, error_message)."""
        question = self.corpus.get(fact_key)
        if question is None:
            return True, ""  # unknown key — accept as-is

        stripped = value.strip()

        if question.required and not stripped:
            return False, "This field is required. Please provide an answer."

        if question.type == "select" and question.options:
            if stripped not in question.options:
                opts = ", ".join(question.options)
                return False, f"Please choose one of: {opts}"

        if question.type == "boolean":
            if stripped.lower() not in ("yes", "no", "true", "false", "1", "0"):
                return False, "Please answer Yes or No."

        if "email" in fact_key and stripped:
            import re
            if not re.match(r"[^@]+@[^@]+\.[^@]+", stripped):
                return False, "Please enter a valid email address."

        return True, ""