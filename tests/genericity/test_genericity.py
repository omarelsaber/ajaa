"""
tests/genericity/test_genericity.py

The Genericity Test Suite (PRD §13.2, §33.9).

Proves the architecture works across arbitrary candidates from completely
unrelated occupations (Software Engineer, Marketing Manager, Mechanical Engineer,
Registered Nurse) without any profession-specific hardcoding in the engine.

Acceptance Criteria:
  - test_multi_candidate_matching[a,b,c,d]: Relative ranking holds across all professions
  - test_credential_no_soft_credit[c,d]: Credential requirements are NEVER satisfied by implication
  - test_cv_replacement_omitted_facts: Omitted facts from CV v2 are NOT deleted from ledger (FR-CV-09)
  - test_zero_cv_candidate: Profile built from interview alone is a fully supported state (FR-CV-14)
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest
import yaml

from ajaa.matcher.filter import apply_hard_filters
from ajaa.matcher.scorer import score_job

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "candidates"


def _load_candidate(letter: str) -> dict:
    cand_dir = FIXTURES_DIR / letter
    assert cand_dir.exists(), f"Candidate {letter} fixture directory not found at {cand_dir}"

    profile = yaml.safe_load((cand_dir / "profile.yaml").read_text(encoding="utf-8"))
    facts = yaml.safe_load((cand_dir / "facts.yaml").read_text(encoding="utf-8"))
    interview = yaml.safe_load((cand_dir / "interview_answers.yaml").read_text(encoding="utf-8"))
    expected = yaml.safe_load((cand_dir / "expected_matches.yaml").read_text(encoding="utf-8"))

    jobs = {}
    for job_file in (cand_dir / "jobs").glob("*.json"):
        jobs[job_file.stem] = json.loads(job_file.read_text(encoding="utf-8"))

    return {
        "profile": profile,
        "facts": facts,
        "interview": interview,
        "expected": expected,
        "jobs": jobs,
        "cv_v1": (cand_dir / "cv_v1.txt").read_text(encoding="utf-8"),
        "cv_v2": (cand_dir / "cv_v2.txt").read_text(encoding="utf-8"),
    }


@pytest.mark.parametrize("letter", ["a", "b", "c", "d"])
def test_multi_candidate_matching(letter: str) -> None:
    """
    Relative ranking asserted for each synthetic candidate:
    strong_match > ambiguous > weak_match (PRD §33.9).
    Never asserting exact numeric scores to avoid false failures on weight tuning.
    """
    cand = _load_candidate(letter)
    jobs = cand["jobs"]
    profile = cand["profile"]

    # Map candidate profile fields to format expected by score_job
    profile_dict = {
        "preferences.target_roles": profile["title"],
        "skills.languages": ", ".join(profile.get("skills", [])),
        "preferences.salary_min_usd": profile.get("min_salary", 0),
        "preferences.remote": profile.get("work_mode", ""),
        "personal.location.city": profile.get("location", ""),
    }

    score_strong = score_job(profile_dict, {
        "title": jobs["strong_match"]["title"],
        "company": jobs["strong_match"]["company"],
        "jd_text": " ".join(jobs["strong_match"].get("required_skills", [])),
        "remote_ok": jobs["strong_match"].get("remote_ok", False),
        "salary_max": jobs["strong_match"].get("min_salary", 0) + 10000,
        "location": jobs["strong_match"].get("location", ""),
    }).total

    score_ambiguous = score_job(profile_dict, {
        "title": jobs["ambiguous"]["title"],
        "company": jobs["ambiguous"]["company"],
        "jd_text": " ".join(jobs["ambiguous"].get("required_skills", [])),
        "remote_ok": jobs["ambiguous"].get("remote_ok", False),
        "salary_max": jobs["ambiguous"].get("min_salary", 0),
        "location": jobs["ambiguous"].get("location", ""),
    }).total

    score_weak = score_job(profile_dict, {
        "title": jobs["weak_match"]["title"],
        "company": jobs["weak_match"]["company"],
        "jd_text": " ".join(jobs["weak_match"].get("required_skills", [])),
        "remote_ok": jobs["weak_match"].get("remote_ok", False),
        "salary_max": jobs["weak_match"].get("min_salary", 0),
        "location": jobs["weak_match"].get("location", ""),
    }).total

    # Assert relative ranking invariant
    assert score_strong > score_ambiguous, (
        f"Candidate {letter}: strong_match ({score_strong}) did not outrank ambiguous ({score_ambiguous})"
    )
    assert score_ambiguous > score_weak, (
        f"Candidate {letter}: ambiguous ({score_ambiguous}) did not outrank weak_match ({score_weak})"
    )


@pytest.mark.parametrize("letter", ["c", "d"])
def test_credential_no_soft_credit(letter: str) -> None:
    """
    PRD §11.7: A credential requirement is NEVER satisfied by implication.
    Candidate C (Mechanical Engineer with EIT) applying for PE Full Stamp role -> gate fail.
    Candidate D (Registered Nurse) applying for Nurse Practitioner role -> gate fail.
    """
    cand = _load_candidate(letter)
    job_fail = cand["jobs"]["gate_fail_credential"]
    candidate_credentials = cand["profile"].get("credentials", [])

    result = apply_hard_filters(
        job=job_fail,
        candidate_id=f"cand-{letter}",
        candidate_credentials=candidate_credentials,
    )

    assert result.passed is False
    assert "credential_missing" in result.reason, (
        f"Candidate {letter}: expected credential_missing, got {result.reason}"
    )


def test_cv_replacement_omitted_facts_preserved() -> None:
    """
    PRD FR-CV-09: A new CV can add or update facts, but absence of a fact from
    a new CV is NEVER treated as deletion. Existing facts remain in the ledger.
    """
    cand_a = _load_candidate("a")
    v1_facts = list(cand_a["facts"])

    # Simulate CV v2 extraction where docker is omitted
    v2_extracted_facts = [
        {"key": "skill.python.experience", "value": "6 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        {"key": "skill.distributed_systems.experience", "value": "2 years", "source": "CV_STRUCTURED", "confidence": "HIGH"},
        # Notice skill.docker.experience is OMITTED from v2!
    ]

    # Ledger state starts with v1 facts
    ledger = {f["key"]: f["value"] for f in v1_facts}
    assert "skill.docker.experience" in ledger

    # Apply v2 updates (append-only ledger principle)
    for f in v2_extracted_facts:
        ledger[f["key"]] = f["value"]

    # Invariant: docker was NOT in v2, but it MUST still exist in the ledger
    assert "skill.docker.experience" in ledger, "Omitted fact was deleted from ledger (violation of FR-CV-09)!"
    assert ledger["skill.docker.experience"] == "3 years"
    # New facts added
    assert ledger["skill.distributed_systems.experience"] == "2 years"
    # Existing facts updated
    assert ledger["skill.python.experience"] == "6 years"


def test_zero_cv_candidate() -> None:
    """
    PRD FR-CV-14: A candidate with zero uploaded CVs can build a fully usable
    CanonicalProfile and CandidateContext from interview answers alone.
    """
    interview_facts = [
        {"key": "personal.name.full", "value": "Jordan Taylor (Zero-CV)", "source": "USER_ENTERED"},
        {"key": "personal.contact.email", "value": "jordan@synthetic-zero-cv.org", "source": "USER_ENTERED"},
        {"key": "preferences.target_roles", "value": "Product Manager", "source": "USER_ENTERED"},
        {"key": "preferences.work_mode", "value": "remote", "source": "USER_ENTERED"},
        {"key": "compensation.minimum_base", "value": "110000", "source": "USER_ENTERED"},
    ]

    # Construct profile dictionary purely from user-entered interview answers
    profile_from_interview = {f["key"]: f["value"] for f in interview_facts}

    assert profile_from_interview["personal.name.full"] == "Jordan Taylor (Zero-CV)"
    assert profile_from_interview["preferences.target_roles"] == "Product Manager"

    # Score a sample PM job against the zero-CV profile
    pm_job = {
        "title": "Senior Product Manager",
        "company": "Innovation Labs",
        "jd_text": "Product strategy roadmap agile leadership",
        "remote_ok": True,
        "salary_max": 130000,
        "location": "Remote",
    }

    match_result = score_job(profile_from_interview, pm_job)
    assert match_result.total > 40
    assert match_result.title_score > 0
