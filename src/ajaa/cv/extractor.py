"""
src/ajaa/cv/extractor.py

CV extraction engine.

Takes raw CV text (from ingester) and:
  1. Checks extraction_cache (content_hash + extractor_version) — LLM skip if hit
  2. Calls LLM with 3-channel prompt (SYSTEM / CONTEXT / UNTRUSTED)
  3. Parses structured JSON response into fact key-value pairs
  4. Writes facts to fact_ledger with source=CV_EXPLICIT or CV_INFERRED
  5. Records result in extraction_cache

Extractor version controls cache invalidation:
  Bump EXTRACTOR_VERSION when the prompt or output schema changes.
  Old cached extractions become invalid and will be re-extracted.

LLM output schema (JSON):
  {
    "facts": [
      {"key": "personal.name.full", "value": "Alice Smith", "confidence": "HIGH", "inferred": false},
      {"key": "skills.languages", "value": "Python, Go, Rust", "confidence": "MEDIUM", "inferred": true}
    ]
  }

When LLM is unavailable (API not configured / 401):
  Returns an ExtractResult with facts=[] and llm_unavailable=True.
  The CV is still stored — extraction can be retried once LLM is fixed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from ajaa.types import Confidence, FactSource, FactState

EXTRACTOR_VERSION = "v1.0"

# Fact keys the extractor is allowed to populate from a CV
# Keys not in this list are ignored (safety boundary)
ALLOWED_CV_KEYS: frozenset[str] = frozenset({
    "personal.name.full",
    "personal.email.primary",
    "personal.phone.primary",
    "personal.location.city",
    "personal.location.country",
    "personal.linkedin_url",
    "personal.github_url",
    "personal.portfolio_url",
    "personal.years_of_experience",
    "personal.summary",
    "work_authorization.country",
    "work_authorization.requires_sponsorship",
    "work_authorization.status",
    "preferences.target_roles",
    "education.highest_degree",
    "education.field_of_study",
    "education.institution",
    "education.graduation_year",
    "skills.primary_language",
    "skills.languages",
    "skills.frameworks",
    "skills.databases",
    "skills.cloud_platforms",
    "skills.tools",
    "experience.current_title",
    "experience.current_company",
    "experience.total_years",
    "experience.most_recent_start",
})

_SYSTEM_PROMPT = """\
You are a CV data extractor. Extract structured facts from the provided CV text.

Return ONLY valid JSON with this schema:
{
  "facts": [
    {
      "key": "<fact_key>",
      "value": "<string value>",
      "confidence": "HIGH" | "MEDIUM" | "LOW",
      "inferred": true | false
    }
  ]
}

Rules:
- Use ONLY the allowed fact keys listed in the CONTEXT section.
- "inferred": true means you deduced the value (not explicitly stated).
- "inferred": false means it was explicitly written in the CV.
- confidence HIGH = directly stated, MEDIUM = mostly clear, LOW = uncertain.
- Do NOT add keys that are not in the allowed list.
- Do NOT include personally identifying info beyond the allowed keys.
- If a field is not present in the CV, omit it entirely — do not guess.
- Return an empty facts array if nothing can be extracted.
"""


@dataclass
class ExtractedFact:
    key: str
    value: str
    confidence: Confidence
    inferred: bool


@dataclass
class ExtractResult:
    cv_id: str
    candidate_id: str
    facts_written: int = 0
    facts_skipped: int = 0        # keys not in ALLOWED_CV_KEYS
    llm_unavailable: bool = False
    cache_hit: bool = False
    extractor_version: str = EXTRACTOR_VERSION
    facts: list[ExtractedFact] = field(default_factory=list)
    error: str | None = None


def extract_cv_facts(
    candidate_id: str,
    cv_id: str,
    raw_text: str,
    content_hash: str,
) -> ExtractResult:
    """
    Extract facts from CV text and write them to the fact ledger.

    Checks extraction cache first (same hash + version = skip LLM).
    Falls back gracefully if LLM is unavailable.
    """
    from ajaa.db.session import get_session
    from ajaa.db.models import ExtractionCache
    from ajaa.db.repositories import fact as fact_repo
    import sqlalchemy as sa

    result = ExtractResult(cv_id=cv_id, candidate_id=candidate_id)

    # ── 1. Cache check ───────────────────────────────────────────────────────
    with get_session() as session:
        cached = session.execute(
            sa.select(ExtractionCache).where(
                ExtractionCache.content_hash == content_hash,
                ExtractionCache.extractor_version == EXTRACTOR_VERSION,
            )
        ).scalars().first()

        if cached is not None:
            result.cache_hit = True
            cached_facts = json.loads(cached.extracted_json or "[]")
            _write_facts(candidate_id, cv_id, cached_facts, fact_repo, result)
            return result

    # ── 2. LLM call ──────────────────────────────────────────────────────────
    context_block = f"Allowed fact keys:\n{chr(10).join(sorted(ALLOWED_CV_KEYS))}"
    untrusted_block = _truncate_cv_text(raw_text)

    try:
        from ajaa.llm.gateway import call_llm
        from ajaa.types import LLMTask, Tier

        response_text = call_llm(
            task=LLMTask.CV_EXTRACTION,
            system_prompt=_SYSTEM_PROMPT,
            context_block=context_block,
            untrusted_block=untrusted_block,
            tier=Tier.MID,
        )
    except Exception as exc:
        err = str(exc)
        result.llm_unavailable = True
        result.error = f"LLM unavailable: {err[:200]}"
        return result

    # ── 3. Parse response ────────────────────────────────────────────────────
    raw_facts = _parse_llm_response(response_text)
    if raw_facts is None:
        result.error = "LLM returned unparseable JSON"
        return result

    # ── 4. Store in cache ────────────────────────────────────────────────────
    now = datetime.now(timezone.utc)
    with get_session() as session:
        cache_row = ExtractionCache(
            content_hash=content_hash,
            extractor_version=EXTRACTOR_VERSION,
            extracted_json=json.dumps(raw_facts),
            cv_id=cv_id,
            created_at=now,
            updated_at=now,
        )
        session.add(cache_row)
        session.commit()

    # ── 5. Write facts to ledger ─────────────────────────────────────────────
    _write_facts(candidate_id, cv_id, raw_facts, fact_repo, result)
    return result


def _write_facts(
    candidate_id: str,
    cv_id: str,
    raw_facts: list[dict],
    fact_repo,
    result: ExtractResult,
) -> None:
    """Write parsed facts to the fact ledger (CV_EXPLICIT or CV_INFERRED)."""
    for raw in raw_facts:
        key = str(raw.get("key", "")).strip()
        value = str(raw.get("value", "")).strip()
        inferred = bool(raw.get("inferred", False))
        conf_str = str(raw.get("confidence", "MEDIUM")).upper()

        if key not in ALLOWED_CV_KEYS:
            result.facts_skipped += 1
            continue
        if not value:
            result.facts_skipped += 1
            continue

        try:
            confidence = Confidence[conf_str]
        except KeyError:
            confidence = Confidence.MEDIUM

        source = FactSource.CV_INFERRED if inferred else FactSource.CV_EXPLICIT

        fact_repo.upsert(
            candidate_id=candidate_id,
            fact_key=key,
            fact_value=value,
            source=source,
            confidence=confidence,
            state=FactState.KNOWN,
            source_ref=cv_id,
        )
        result.facts.append(ExtractedFact(
            key=key, value=value, confidence=confidence, inferred=inferred
        ))
        result.facts_written += 1


def _parse_llm_response(text: str) -> list[dict] | None:
    """Extract JSON from LLM response, handling markdown code fences."""
    # Strip ```json ... ``` fences if present
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1)

    # Find first { and last }
    start = text.find("{")
    end = text.rfind("}") + 1
    if start == -1 or end == 0:
        return None

    try:
        data = json.loads(text[start:end])
        return data.get("facts", [])
    except json.JSONDecodeError:
        return None


def _truncate_cv_text(text: str, max_chars: int = 12_000) -> str:
    """Truncate CV text to fit in LLM context window."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n[... CV truncated for extraction ...]"