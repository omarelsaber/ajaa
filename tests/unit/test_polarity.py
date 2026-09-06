"""
tests/unit/test_polarity.py

Test sponsorship polarity matrix across patterns and both candidate states.
CRITICAL SAFETY TEST.
"""
from __future__ import annotations

import pytest
from ajaa.answering.polarity import QuestionPolarity, classify_question, resolve_sponsorship_answer


@pytest.mark.parametrize(
    "question_text",
    [
        "Will you now or in the future require visa sponsorship for employment?",
        "Do you require sponsorship to work in the United States?",
        "Will you need company sponsorship for an H1B visa?",
        "Do you require immigration sponsorship?",
        "Will you require employer sponsorship?",
        "Are you currently on an F-1 OPT or require visa transfer?",
    ],
)
def test_sponsorship_requires_sponsorship_classification(question_text: str):
    res = classify_question(question_text)
    assert res.polarity == QuestionPolarity.REQUIRES_SPONSORSHIP
    assert res.confidence == "HIGH"


@pytest.mark.parametrize(
    "question_text",
    [
        "Are you legally authorized to work in the United States?",
        "Are you eligible to work in the US without sponsorship?",
        "Do you have the legal right to work in this country?",
        "Are you lawfully authorized to work on an ongoing basis?",
        "Do you possess valid work authorization without sponsorship?",
    ],
)
def test_sponsorship_authorized_classification(question_text: str):
    res = classify_question(question_text)
    assert res.polarity == QuestionPolarity.AUTHORIZED_TO_WORK
    assert res.confidence == "HIGH"


def test_unknown_phrasing_yields_needs_user():
    unknown_question = "What is your cosmic astrological alignment regarding office presence?"
    ans, reason = resolve_sponsorship_answer(unknown_question, candidate_requires_sponsorship=False)
    assert ans is None
    assert "NEEDS_USER" in reason


def test_polarity_matrix_resolution():
    # Candidate DOES NOT require sponsorship (e.g. US citizen / green card)
    q_spons = "Will you now or in the future require visa sponsorship?"
    ans, _ = resolve_sponsorship_answer(q_spons, candidate_requires_sponsorship=False)
    assert ans is False  # "No, I do not require sponsorship"

    q_auth = "Are you legally authorized to work in the United States?"
    ans, _ = resolve_sponsorship_answer(q_auth, candidate_requires_sponsorship=False)
    assert ans is True   # "Yes, I am authorized"

    # Candidate REQUIRES sponsorship (e.g. international applicant)
    ans, _ = resolve_sponsorship_answer(q_spons, candidate_requires_sponsorship=True)
    assert ans is True   # "Yes, I will require sponsorship"

    ans, _ = resolve_sponsorship_answer(q_auth, candidate_requires_sponsorship=True)
    assert ans is False  # "No, I am not authorized without sponsorship"