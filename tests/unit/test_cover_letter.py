"""
tests/unit/test_cover_letter.py

Unit tests for Grounded Cover Letter Generation (PRD §14, Invariants I1 & I4).
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ajaa.candidate.context import CandidateContext
from ajaa.db.models import Base, CandidateContext as DBCandidate, CoverLetter, Job
from ajaa.letters.generator import (
    generate_cover_letter,
    record_user_edit,
    save_or_update_cover_letter,
)


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    session = session_factory()
    yield session
    session.close()


def test_cover_letter_grounded_generation_structure():
    """Verify 4-part structure and Invariant I1 fact citations."""
    candidate_ctx = CandidateContext(
        candidate_id="cand-1",
        display_name="Elena Rostova",
        profile={
            "personal.name.full": "Elena Rostova",
            "personal.email.primary": "elena@example.com",
            "personal.phone.primary": "+1-555-987-6543",
            "skills.languages": "Python, Rust, Go",
            "skills.frameworks": "PyTorch, FastAPI, Docker",
            "experience.current.title": "Senior AI Systems Engineer",
            "experience.highlight.1": "Architected distributed inference pipeline reducing latency by 40%.",
        },
    )

    job = Job(
        id="job-1",
        url_hash="hash_anthropic_1",
        apply_url="https://jobs.ashbyhq.com/anthropic/job-1",
        title="Staff ML Engineer",
        company="Anthropic",
        jd_text="Looking for an ML engineer with PyTorch and Python experience to build scalable inference systems.",
    )

    result = generate_cover_letter(candidate_ctx, job)

    # 1. Opening mentions role and employer
    assert "Staff ML Engineer" in result.opening_text
    assert "Anthropic" in result.opening_text

    # 2. Fit paragraph cites relevant skills (PyTorch / Python)
    assert "Python" in result.fit_paragraph or "PyTorch" in result.fit_paragraph
    assert "Anthropic" in result.fit_paragraph

    # 3. Evidence contains candidate's own verbatim accomplishment
    assert "Architected distributed inference pipeline" in result.evidence_blurbs

    # 4. Closing contains contact info
    assert "elena@example.com" in result.closing_text

    # 5. Invariant I1: Every claim cites facts
    assert len(result.grounded_fact_ids) > 0
    assert any("skill" in fid or "experience" in fid for fid in result.grounded_fact_ids)

    # 6. Full text contains all 4 parts
    assert result.opening_text in result.full_text
    assert result.fit_paragraph in result.full_text
    assert result.evidence_blurbs in result.full_text
    assert result.closing_text in result.full_text


def test_cover_letter_db_persistence_and_user_edit(memory_db: Session):
    """Test saving cover letter and recording user edits (PRD §14.4)."""
    cand = DBCandidate(id="cand-test", display_name="Test User")
    job = Job(id="job-test", url_hash="hash_acme_1", apply_url="https://acme.com/job", source_connector="generic", title="Software Engineer", company="Acme Inc")
    memory_db.add_all([cand, job])
    memory_db.commit()

    candidate_ctx = CandidateContext(
        candidate_id=cand.id,
        display_name=cand.display_name,
        profile={
            "personal.email.primary": "test@example.com",
            "skills.languages": "Python",
        },
    )

    result = generate_cover_letter(candidate_ctx, job)
    record = save_or_update_cover_letter(
        session=memory_db,
        candidate_id=cand.id,
        job_id=job.id,
        application_id=None,
        letter_result=result,
    )
    memory_db.commit()

    assert record.id is not None
    assert record.candidate_id == cand.id
    assert record.job_id == job.id
    assert record.was_edited is False
    assert "Software Engineer" in record.opening_text

    # User manual edit
    custom_text = "Dear Hiring Manager,\nI am writing to apply with custom tailored words."
    updated = record_user_edit(memory_db, record.id, custom_text)
    memory_db.commit()

    assert updated is not None
    assert updated.was_edited is True
    assert updated.edited_text == custom_text
    assert updated.full_text == custom_text
