"""
src/ajaa/db/repositories/fact.py

Fact Ledger repository.

Precedence rule (immutable):
  source_rank 1 (USER_EXPLICIT) > 2 > ... > 7 (DEFAULT)
  Lower rank number = higher precedence = wins.

  get_canonical(fact_key) returns the fact with the lowest source_rank.
  If two facts have the same source_rank, the most recently updated wins.

Write rules:
  - upsert() inserts or replaces (candidate_id, fact_key, source_rank).
  - Writing LLM_INFERENCE (rank=6) automatically sets usable_in_applications=False.
  - Writing USER_EXPLICIT (rank=1) promotes FactState to KNOWN and clears STALE.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

import sqlalchemy as sa

from ajaa.db.models import Fact
from ajaa.db.session import get_session
from ajaa.types import FactSource, FactState, Confidence


def upsert(
    candidate_id: str,
    fact_key: str,
    fact_value: str,
    source: FactSource,
    confidence: Confidence = Confidence.MEDIUM,
    state: FactState = FactState.KNOWN,
    source_ref: str | None = None,
) -> Fact:
    """
    Insert or update a fact for (candidate_id, fact_key, source_rank).

    If a row with the same (candidate_id, fact_key, source_rank) exists,
    it is updated in-place. Otherwise, a new row is inserted.

    LLM_INFERENCE facts: usable_in_applications forced to False.
    """
    usable = not (source == FactSource.LLM_INFERENCE)

    with get_session() as session:
        existing = session.execute(
            sa.select(Fact).where(
                Fact.candidate_id == candidate_id,
                Fact.fact_key == fact_key,
                Fact.source_rank == source.rank,
            )
        ).scalars().first()

        now = datetime.now(timezone.utc)

        if existing is not None:
            existing.fact_value = fact_value
            existing.confidence = confidence.value
            existing.state = state.value
            existing.source_ref = source_ref
            existing.usable_in_applications = usable
            existing.updated_at = now
            session.commit()
            session.expunge(existing)
            return existing
        else:
            fact = Fact(
                candidate_id=candidate_id,
                fact_key=fact_key,
                fact_value=fact_value,
                source_rank=source.rank,
                source_label=source.value,
                source_ref=source_ref,
                confidence=confidence.value,
                state=state.value,
                usable_in_applications=usable,
                created_at=now,
                updated_at=now,
            )
            session.add(fact)
            session.commit()
            session.expunge(fact)
            return fact


def get_canonical(candidate_id: str, fact_key: str) -> Fact | None:
    """
    Return the highest-precedence fact for this key.
    Lowest source_rank wins; ties broken by updated_at (latest wins).
    Returns None if no fact exists.
    """
    with get_session() as session:
        facts = session.execute(
            sa.select(Fact).where(
                Fact.candidate_id == candidate_id,
                Fact.fact_key == fact_key,
            ).order_by(Fact.source_rank.asc(), Fact.updated_at.desc())
        ).scalars().all()

        if not facts:
            return None
        result = facts[0]
        session.expunge(result)
        return result


def get_all_for_key(candidate_id: str, fact_key: str) -> list[Fact]:
    """Return all fact rows for this key (all sources), ordered by rank."""
    with get_session() as session:
        facts = session.execute(
            sa.select(Fact).where(
                Fact.candidate_id == candidate_id,
                Fact.fact_key == fact_key,
            ).order_by(Fact.source_rank.asc())
        ).scalars().all()
        for f in facts:
            session.expunge(f)
        return list(facts)


def get_all_usable(candidate_id: str) -> list[Fact]:
    """
    Return all facts usable in applications, deduplicated by fact_key.
    For each key, only the canonical (lowest rank) fact is returned.
    """
    with get_session() as session:
        # Subquery: min source_rank per key for this candidate
        subq = (
            sa.select(Fact.fact_key, sa.func.min(Fact.source_rank).label("min_rank"))
            .where(
                Fact.candidate_id == candidate_id,
                Fact.usable_in_applications == True,
                Fact.state == FactState.KNOWN.value,
            )
            .group_by(Fact.fact_key)
            .subquery()
        )

        facts = session.execute(
            sa.select(Fact)
            .join(
                subq,
                sa.and_(
                    Fact.fact_key == subq.c.fact_key,
                    Fact.source_rank == subq.c.min_rank,
                ),
            )
            .where(Fact.candidate_id == candidate_id)
            .order_by(Fact.fact_key)
        ).scalars().all()

        for f in facts:
            session.expunge(f)
        return list(facts)


def list_by_prefix(candidate_id: str, prefix: str) -> list[Fact]:
    """Return canonical facts whose key starts with the given prefix."""
    with get_session() as session:
        facts = session.execute(
            sa.select(Fact).where(
                Fact.candidate_id == candidate_id,
                Fact.fact_key.startswith(prefix),
            ).order_by(Fact.fact_key, Fact.source_rank)
        ).scalars().all()
        for f in facts:
            session.expunge(f)
        return list(facts)


def mark_stale(candidate_id: str, fact_key: str, source: FactSource) -> bool:
    """
    Mark a fact as UNKNOWN (its value may be outdated).
    Returns True if the fact was found and updated.

    'Stale' facts become UNKNOWN — the value is still stored but we
    no longer consider it reliable. The interview engine will re-ask.
    """
    with get_session() as session:
        row = session.execute(
            sa.select(Fact).where(
                Fact.candidate_id == candidate_id,
                Fact.fact_key == fact_key,
                Fact.source_rank == source.rank,
            )
        ).scalars().first()
        if row is None:
            return False
        row.state = FactState.UNKNOWN.value
        row.updated_at = datetime.now(timezone.utc)
        session.commit()
        return True


def coverage_summary(candidate_id: str, required_keys: Sequence[str]) -> dict[str, bool]:
    """
    Return {fact_key: is_covered} for each required key.
    A key is covered if a KNOWN, usable fact exists at any rank.
    """
    with get_session() as session:
        known_keys: set[str] = set(
            session.execute(
                sa.select(Fact.fact_key).where(
                    Fact.candidate_id == candidate_id,
                    Fact.state == FactState.KNOWN.value,
                    Fact.usable_in_applications == True,
                )
            ).scalars().all()
        )
    return {k: (k in known_keys) for k in required_keys}