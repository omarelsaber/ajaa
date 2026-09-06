"""
tests/unit/test_matcher.py

Matcher unit tests — scorer, filter, ranker.

Covers:
  - _tokenize extracts lowercase tokens
  - _keyword_overlap (exact, partial, zero)
  - score_job: title/skill/salary/location/authorization components
  - score_job: hard disqualify on salary far below minimum
  - score_job: neutral scoring when profile fields missing
  - apply_hard_filters: stale, blacklist, already-applied
  - rank_jobs: ordering, threshold, pagination
  - rank_jobs: disqualified jobs excluded
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ajaa.db.session import init_engine, reset_engine


@pytest.fixture(autouse=True)
def fresh_db(tmp_path: Path):
    init_engine(tmp_path / "test_matcher.db")
    yield
    reset_engine()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _profile(**kwargs) -> dict:
    defaults = {
        "preferences.target_roles": "Python backend engineer",
        "skills.primary_language": "python",
        "skills.frameworks": "django, fastapi",
        "skills.databases": "postgresql",
        "preferences.remote": "yes",
        "preferences.salary_min_usd": "100000",
        "work_authorization.requires_sponsorship": "no",
        "personal.location.city": "cairo",
        "personal.location.country": "egypt",
    }
    defaults.update(kwargs)
    return defaults


def _job(**kwargs) -> dict:
    defaults = {
        "id": "job-1",
        "title": "Senior Python Backend Engineer",
        "company": "Acme Corp",
        "location": "Remote",
        "remote_ok": True,
        "jd_text": "We use Python, FastAPI, PostgreSQL and Django.",
        "tags_json": "python,django,remote",
        "salary_min": 120_000,
        "salary_max": 160_000,
        "is_stale": False,
        "discovered_at": None,
    }
    defaults.update(kwargs)
    return defaults


# ── Tokenizer ─────────────────────────────────────────────────────────────────

class TestTokenize:
    def test_lowercase(self) -> None:
        from ajaa.matcher.scorer import _tokenize
        assert "python" in _tokenize("Python")

    def test_strips_punctuation(self) -> None:
        from ajaa.matcher.scorer import _tokenize
        tokens = _tokenize("C++, Go, Rust!")
        assert "c++" in tokens
        assert "go" in tokens

    def test_empty_returns_empty_set(self) -> None:
        from ajaa.matcher.scorer import _tokenize
        assert _tokenize("") == set()


# ── Keyword overlap ───────────────────────────────────────────────────────────

class TestKeywordOverlap:
    def test_full_overlap(self) -> None:
        from ajaa.matcher.scorer import _keyword_overlap
        assert _keyword_overlap("python django", "python django fastapi") == 1.0

    def test_no_overlap(self) -> None:
        from ajaa.matcher.scorer import _keyword_overlap
        assert _keyword_overlap("python", "golang rust") == 0.0

    def test_partial_overlap(self) -> None:
        from ajaa.matcher.scorer import _keyword_overlap
        score = _keyword_overlap("python django go", "python fastapi")
        assert 0 < score < 1.0

    def test_empty_source(self) -> None:
        from ajaa.matcher.scorer import _keyword_overlap
        assert _keyword_overlap("", "python django") == 0.0


# ── Scorer ────────────────────────────────────────────────────────────────────

class TestScoreJob:
    def test_perfect_match_high_score(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(_profile(), _job())
        assert s.total >= 70
        assert not s.disqualified

    def test_matched_skills_populated(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(_profile(), _job())
        assert "python" in s.matched_skills or len(s.matched_skills) > 0

    def test_no_skills_in_profile_neutral(self) -> None:
        from ajaa.matcher.scorer import score_job
        p = _profile()
        for k in list(p.keys()):
            if k.startswith("skills."):
                del p[k]
        s = score_job(p, _job())
        assert s.skill_score == 12  # neutral

    def test_salary_below_minimum_hard_disqualify(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(
            _profile(**{"preferences.salary_min_usd": "150000"}),
            _job(salary_min=50_000, salary_max=80_000),
        )
        assert s.disqualified is True
        assert s.total == 0

    def test_salary_meets_minimum_full_points(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(
            _profile(**{"preferences.salary_min_usd": "100000"}),
            _job(salary_min=120_000, salary_max=160_000),
        )
        assert s.salary_score == 20

    def test_no_salary_preference_neutral(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(
            _profile(**{"preferences.salary_min_usd": "0"}),
            _job(salary_min=0, salary_max=0),
        )
        assert s.salary_score == 10

    def test_remote_preference_remote_job_full_points(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(_profile(**{"preferences.remote": "yes"}), _job(remote_ok=True))
        assert s.location_score == 15

    def test_remote_preference_onsite_job_low_points(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(
            _profile(**{"preferences.remote": "yes"}),
            _job(remote_ok=False, location="New York"),
        )
        assert s.location_score <= 5

    def test_sponsorship_us_job_reduced_auth_score(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(
            _profile(**{"work_authorization.requires_sponsorship": "yes"}),
            _job(location="San Francisco, USA", remote_ok=False),
        )
        assert s.authorization_score < 10

    def test_is_qualified_above_threshold(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(_profile(), _job())
        assert s.is_qualified(threshold=50) is True

    def test_total_capped_at_100(self) -> None:
        from ajaa.matcher.scorer import score_job
        s = score_job(_profile(), _job())
        assert s.total <= 100


# ── Hard filters ──────────────────────────────────────────────────────────────

class TestHardFilters:
    def test_stale_job_rejected(self) -> None:
        from ajaa.matcher.filter import apply_hard_filters
        r = apply_hard_filters(_job(is_stale=True), "cand-1")
        assert r.passed is False
        assert "stale" in r.reason

    def test_blacklisted_company_rejected(self) -> None:
        from ajaa.matcher.filter import apply_hard_filters
        r = apply_hard_filters(_job(company="Scam Corp"), "cand-1", ["scam corp"])
        assert r.passed is False
        assert "blacklist" in r.reason

    def test_clean_job_passes(self) -> None:
        from ajaa.matcher.filter import apply_hard_filters
        r = apply_hard_filters(_job(), "cand-1")
        assert r.passed is True

    def test_partial_blacklist_match(self) -> None:
        from ajaa.matcher.filter import apply_hard_filters
        r = apply_hard_filters(_job(company="Evil Recruiting LLC"), "cand-1", ["evil"])
        assert r.passed is False


# ── Ranker ────────────────────────────────────────────────────────────────────

class TestRankJobs:
    def test_sorted_by_score_desc(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        high = _job(id="h", title="Python Backend Engineer", jd_text="python django fastapi postgresql")
        low  = _job(id="l", title="Java Developer", jd_text="java spring enterprise")
        results = rank_jobs(_profile(), [high, low], threshold=0)
        assert results[0].job_id == "h"

    def test_threshold_filters_low_scores(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        bad = _job(id="b", title="PHP Developer", jd_text="php laravel mysql",
                   remote_ok=False, salary_min=30_000, salary_max=40_000)
        results = rank_jobs(
            _profile(**{"preferences.salary_min_usd": "0"}),
            [bad],
            threshold=90,  # very high threshold
        )
        # PHP job with python profile won't reach 90
        assert all(r.score.total >= 90 for r in results)

    def test_disqualified_job_excluded(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        disq = _job(id="d", salary_min=20_000, salary_max=30_000)
        results = rank_jobs(
            _profile(**{"preferences.salary_min_usd": "150000"}),
            [disq],
            threshold=0,
        )
        assert all(r.job_id != "d" for r in results)

    def test_pagination(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        jobs = [_job(id=f"j{i}", title=f"Python Engineer {i}") for i in range(10)]
        p1 = rank_jobs(_profile(), jobs, threshold=0, page=1, page_size=3)
        p2 = rank_jobs(_profile(), jobs, threshold=0, page=2, page_size=3)
        assert len(p1) <= 3
        assert len(p2) <= 3
        ids_p1 = {r.job_id for r in p1}
        ids_p2 = {r.job_id for r in p2}
        assert ids_p1.isdisjoint(ids_p2)

    def test_rank_numbers_start_at_1(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        results = rank_jobs(_profile(), [_job()], threshold=0)
        if results:
            assert results[0].rank == 1

    def test_stale_job_excluded_by_filter(self) -> None:
        from ajaa.matcher.ranker import rank_jobs
        results = rank_jobs(_profile(), [_job(is_stale=True)], threshold=0)
        assert results == []