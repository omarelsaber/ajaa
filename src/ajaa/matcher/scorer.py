"""
src/ajaa/matcher/scorer.py

CanonicalProfile x Job -> MatchScore (0-100).

Scoring is RULES-BASED (no LLM) so it works without API connectivity.

Score components:
  - Title relevance     30 pts  keyword overlap between profile target_roles and job title
  - Skill relevance     25 pts  profile skills found in job description/tags
  - Salary fit          20 pts  job salary vs profile minimum expectation
  - Location fit        15 pts  remote preference vs job remote_ok
  - Authorization fit   10 pts  work authorization vs job location

Total: 100 pts. Threshold for application: configurable (default 50).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MatchScore:
    total: int                    # 0-100
    title_score: int = 0          # 0-30
    skill_score: int = 0          # 0-25
    salary_score: int = 0         # 0-20
    location_score: int = 0       # 0-15
    authorization_score: int = 0  # 0-10
    matched_skills: list[str] = field(default_factory=list)
    disqualified: bool = False
    disqualify_reason: str = ""

    def is_qualified(self, threshold: int = 50) -> bool:
        return not self.disqualified and self.total >= threshold


def _tokenize(text: str) -> set[str]:
    """Lowercase words, strip punctuation."""
    return set(re.findall(r"[a-z0-9#+]+", text.lower()))


def _keyword_overlap(source: str, target: str) -> float:
    """Fraction of source tokens found in target. Returns 0.0-1.0."""
    src_tokens = _tokenize(source)
    if not src_tokens:
        return 0.0
    tgt_tokens = _tokenize(target)
    matched = src_tokens & tgt_tokens
    return len(matched) / len(src_tokens)


def score_job(profile: dict, job: dict) -> MatchScore:
    """
    Score a job against a candidate profile.

    profile: output of CanonicalProfile.to_dict() or dict with same keys
    job: dict with keys: title, company, location, remote_ok,
         jd_text, tags_json (comma-sep string), salary_min, salary_max

    Returns MatchScore.
    """
    result = MatchScore(total=0)

    title = job.get("title", "") or ""
    jd_text = job.get("jd_text", "") or ""
    tags_raw = job.get("tags_json") or job.get("tags", "") or ""
    tags = [t.strip() for t in tags_raw.split(",") if t.strip()] if isinstance(tags_raw, str) else tags_raw
    job_text = f"{title} {jd_text} {' '.join(tags)}"
    job_remote = bool(job.get("remote_ok", False))

    # ── 1. Title relevance (30 pts) ───────────────────────────────────────────
    target_roles = profile.get("preferences.target_roles", "")
    if target_roles:
        overlap = _keyword_overlap(target_roles, title + " " + jd_text)
        result.title_score = round(overlap * 30)
    else:
        result.title_score = 15  # neutral if no preference set

    # ── 2. Skill relevance (25 pts) ───────────────────────────────────────────
    skill_keys = [
        "skills.primary_language",
        "skills.languages",
        "skills.frameworks",
        "skills.databases",
        "skills.cloud_platforms",
        "skills.tools",
    ]
    all_skills: list[str] = []
    for k in skill_keys:
        val = profile.get(k, "")
        if val:
            all_skills.extend(re.split(r"[,;/]", val.lower()))

    matched: list[str] = []
    job_tokens = _tokenize(job_text)
    for skill in all_skills:
        skill = skill.strip()
        if skill and skill in job_tokens:
            matched.append(skill)

    unique_matched = list(dict.fromkeys(matched))  # dedup, preserve order
    result.matched_skills = unique_matched[:10]
    if all_skills:
        ratio = min(len(unique_matched) / max(len(all_skills), 1), 1.0)
        result.skill_score = round(ratio * 25)
    else:
        result.skill_score = 12  # neutral

    # ── 3. Salary fit (20 pts) ────────────────────────────────────────────────
    try:
        min_salary = int(profile.get("preferences.salary_min_usd", 0) or 0)
    except (ValueError, TypeError):
        min_salary = 0

    job_salary_min = job.get("salary_min") or 0
    job_salary_max = job.get("salary_max") or 0

    if min_salary == 0:
        result.salary_score = 10  # neutral — no preference set
    elif job_salary_min == 0 and job_salary_max == 0:
        result.salary_score = 10  # salary not disclosed — neutral
    elif job_salary_max >= min_salary:
        result.salary_score = 20  # full points — salary meets requirement
    elif job_salary_max >= min_salary * 0.9:
        result.salary_score = 12  # within 10% — partial
    else:
        # Hard disqualify if salary is more than 20% below minimum
        if min_salary > 0 and job_salary_max > 0 and job_salary_max < min_salary * 0.8:
            result.disqualified = True
            result.disqualify_reason = (
                f"Salary ${job_salary_max:,} is below minimum ${min_salary:,}"
            )
            result.total = 0
            return result
        result.salary_score = 5

    # ── 4. Location fit (15 pts) ──────────────────────────────────────────────
    wants_remote = str(profile.get("preferences.remote", "")).lower() in (
        "yes", "remote only", "remote", "true", "1"
    )
    if wants_remote and job_remote:
        result.location_score = 15
    elif wants_remote and not job_remote:
        result.location_score = 3  # prefers remote but job is not remote
    elif not wants_remote:
        job_location = (job.get("location", "") or "").lower()
        profile_city = (profile.get("personal.location.city", "") or "").lower()
        profile_country = (profile.get("personal.location.country", "") or "").lower()
        if profile_city and profile_city in job_location:
            result.location_score = 15
        elif profile_country and profile_country in job_location:
            result.location_score = 10
        else:
            result.location_score = 7  # unknown location fit
    else:
        result.location_score = 7

    # ── 5. Authorization (10 pts) ─────────────────────────────────────────────
    requires_sponsorship = str(
        profile.get("work_authorization.requires_sponsorship", "")
    ).lower() in ("yes", "true", "1")

    job_location_str = (job.get("location", "") or "").lower()
    # Simple heuristic: if job is US-based and candidate needs sponsorship = partial
    us_job = any(kw in job_location_str for kw in ("united states", "usa", "us only", "new york", "san francisco", "seattle", "austin"))

    if requires_sponsorship and us_job:
        result.authorization_score = 3  # might need sponsorship for US job
    else:
        result.authorization_score = 10  # assume authorized

    # ── Total ─────────────────────────────────────────────────────────────────
    result.total = min(
        result.title_score
        + result.skill_score
        + result.salary_score
        + result.location_score
        + result.authorization_score,
        100,
    )
    return result