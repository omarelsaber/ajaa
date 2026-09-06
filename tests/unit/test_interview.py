"""
tests/unit/test_interview.py

Phase 1 interview engine tests.

Covers:
  - Corpus loading from YAML files
  - Question filtering: by_tier, by_group, all_required
  - Question.is_applicable (depends_on logic)
  - InterviewSession: next_question ordering, phase advancement
  - submit_answer: normal, skip, refuse
  - Validation: email format, required, select options, boolean
  - Progress tracking
  - Profile refresh after answer
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from ajaa.db.session import init_engine, reset_engine
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.interview.corpus import (
    Question, QuestionCorpus, load_corpus, reload_corpus
)
from ajaa.interview.session import (
    InterviewSession, InterviewPhase, AnswerResult
)
from ajaa.types import FactState, FactSource


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_interview.db")
    yield
    reset_engine()


@pytest.fixture
def questions_dir(tmp_path: Path) -> Path:
    """Write minimal YAML corpus for testing."""
    qdir = tmp_path / "questions"
    qdir.mkdir()

    personal = textwrap.dedent("""\
    - key: personal.name.full
      prompt: "What is your full name?"
      required: true
      type: text
      tier: foundation

    - key: personal.email.primary
      prompt: "What is your email?"
      required: true
      type: text
      tier: foundation
      validators: [email]

    - key: personal.phone.primary
      prompt: "What is your phone number?"
      required: false
      type: text
      tier: foundation
    """)

    prefs = textwrap.dedent("""\
    - key: preferences.job_type
      prompt: "What type of job?"
      required: true
      type: select
      options: ["Full-time", "Part-time", "Contract"]
      tier: preferences

    - key: preferences.remote
      prompt: "Remote preference?"
      required: true
      type: select
      options: ["Remote only", "Hybrid", "On-site", "No preference"]
      tier: preferences
    """)

    auth = textwrap.dedent("""\
    - key: work_authorization.requires_sponsorship
      prompt: "Do you require visa sponsorship?"
      required: true
      type: boolean
      tier: safety
    """)

    dependent = textwrap.dedent("""\
    - key: personal.name.preferred
      prompt: "Preferred name?"
      required: false
      type: text
      tier: foundation
      depends_on: [personal.name.full]
    """)

    (qdir / "personal.yaml").write_text(personal + dependent, encoding="utf-8")
    (qdir / "preferences.yaml").write_text(prefs, encoding="utf-8")
    (qdir / "authorization.yaml").write_text(auth, encoding="utf-8")
    return qdir


@pytest.fixture
def corpus(questions_dir: Path) -> QuestionCorpus:
    return load_corpus(questions_dir)


@pytest.fixture
def candidate_id() -> str:
    return candidate_repo.create(display_name="Test Candidate").id


# ── Corpus tests ──────────────────────────────────────────────────────────────

class TestCorpusLoading:

    def test_loads_all_questions(self, corpus: QuestionCorpus) -> None:
        assert len(corpus) == 7

    def test_get_by_key(self, corpus: QuestionCorpus) -> None:
        q = corpus.get("personal.name.full")
        assert q is not None
        assert q.prompt == "What is your full name?"
        assert q.type == "text"
        assert q.tier == "foundation"

    def test_missing_key_returns_none(self, corpus: QuestionCorpus) -> None:
        assert corpus.get("nonexistent.key") is None

    def test_all_required_filter(self, corpus: QuestionCorpus) -> None:
        required = corpus.all_required()
        keys = {q.key for q in required}
        assert "personal.name.full" in keys
        assert "personal.email.primary" in keys
        # phone is required: false
        assert "personal.phone.primary" not in keys

    def test_by_tier(self, corpus: QuestionCorpus) -> None:
        foundation = corpus.by_tier("foundation")
        assert all(q.tier == "foundation" for q in foundation)
        assert len(foundation) >= 2

    def test_by_group(self, corpus: QuestionCorpus) -> None:
        personal = corpus.by_group("personal")
        assert all(q.group == "personal" for q in personal)

    def test_contains(self, corpus: QuestionCorpus) -> None:
        assert "personal.name.full" in corpus
        assert "not.a.key" not in corpus

    def test_empty_dir_returns_empty_corpus(self, tmp_path: Path) -> None:
        empty = load_corpus(tmp_path / "empty_nonexistent")
        assert len(empty) == 0


class TestQuestionApplicability:

    def test_no_depends_always_applicable(self, corpus: QuestionCorpus) -> None:
        q = corpus.get("personal.name.full")
        assert q is not None
        assert q.is_applicable(set()) is True

    def test_depends_on_not_met(self, corpus: QuestionCorpus) -> None:
        q = corpus.get("personal.name.preferred")
        assert q is not None
        assert q.is_applicable(set()) is False

    def test_depends_on_met(self, corpus: QuestionCorpus) -> None:
        q = corpus.get("personal.name.preferred")
        assert q is not None
        assert q.is_applicable({"personal.name.full"}) is True


# ── InterviewSession tests ────────────────────────────────────────────────────

class TestInterviewSession:

    def test_start_returns_session(self, corpus: QuestionCorpus, candidate_id: str) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        assert session.candidate_id == candidate_id
        assert session.phase == InterviewPhase.FOUNDATION

    def test_next_question_returns_unanswered(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        q = session.next_question()
        assert q is not None
        assert q.tier == "foundation"

    def test_submit_answer_accepts_valid(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.name.full", "Alice Smith")
        assert result.accepted is True
        assert result.message == "Saved."

    def test_answer_advances_to_next_question(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.name.full", "Alice Smith")
        # Should get another question (email)
        assert result.next_question is not None
        assert result.next_question.key != "personal.name.full"

    def test_skip_marks_unknown(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        from ajaa.db.repositories import fact as fact_repo
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.name.full", "", skip=True)
        assert result.accepted is True
        assert "skip" in result.message.lower() or "later" in result.message.lower()

        fact = fact_repo.get_canonical(candidate_id, "personal.name.full")
        assert fact is not None
        assert fact.state == FactState.UNKNOWN.value

    def test_refuse_marks_refused(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        from ajaa.db.repositories import fact as fact_repo
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.phone.primary", "", refuse=True)
        assert result.accepted is True

        fact = fact_repo.get_canonical(candidate_id, "personal.phone.primary")
        assert fact is not None
        assert fact.state == FactState.REFUSED_TO_ANSWER.value

    def test_progress_tracking(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        p0 = session.progress()
        assert p0["covered"] == 0
        assert p0["total"] > 0

        session.submit_answer("personal.name.full", "Alice Smith")
        p1 = session.progress()
        assert p1["covered"] == 1

    def test_complete_when_all_required_answered(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)

        answers = {
            "personal.name.full": "Alice Smith",
            "personal.email.primary": "alice@example.com",
            "preferences.job_type": "Full-time",
            "preferences.remote": "Remote only",
            "work_authorization.requires_sponsorship": "No",
        }

        # Drive the session via next_question() loop (correct API)
        max_iterations = 20
        for _ in range(max_iterations):
            q = session.next_question()
            if q is None:
                break
            value = answers.get(q.key, "Yes")
            session.submit_answer(q.key, value)

        assert session.is_complete


# ── Validation tests ──────────────────────────────────────────────────────────

class TestValidation:

    def test_email_validation_rejects_invalid(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.email.primary", "not-an-email")
        assert result.accepted is False
        assert "email" in result.message.lower()

    def test_email_validation_accepts_valid(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("personal.email.primary", "alice@example.com")
        assert result.accepted is True

    def test_select_rejects_invalid_option(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("preferences.job_type", "InvalidOption")
        assert result.accepted is False

    def test_select_accepts_valid_option(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer("preferences.job_type", "Full-time")
        assert result.accepted is True

    def test_boolean_rejects_invalid(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer(
            "work_authorization.requires_sponsorship", "maybe"
        )
        assert result.accepted is False

    def test_boolean_accepts_yes_no(
        self, corpus: QuestionCorpus, candidate_id: str
    ) -> None:
        session = InterviewSession.start(candidate_id, corpus)
        result = session.submit_answer(
            "work_authorization.requires_sponsorship", "No"
        )
        assert result.accepted is True