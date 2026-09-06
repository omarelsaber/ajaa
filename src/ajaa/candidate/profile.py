"""
src/ajaa/candidate/profile.py

CandidateContext read layer — the canonical view of the candidate.

This is what ALL engines receive instead of direct DB access.
No engine should import from ajaa.db directly — they get a CanonicalProfile.

Design:
  - CanonicalProfile is a frozen dataclass (read-only snapshot)
  - Built from the fact ledger at query time
  - Cached per-request; never mutated
  - Exposes get(key) → str | None using precedence rules
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ajaa.db.models import CandidateContext, Fact
from ajaa.db.repositories import candidate as candidate_repo
from ajaa.db.repositories import fact as fact_repo
from ajaa.types import FactSource, FactState


@dataclass(frozen=True)
class CanonicalProfile:
    """
    A frozen, precedence-resolved snapshot of all candidate facts.

    Built once per request. All engines work from this snapshot.
    Never mutated — if facts change, rebuild the profile.

    Attributes:
        candidate_id: The installation's UUID.
        display_name: Human display name (from CandidateContext).
        locale: e.g. "en-US".
        calibration_completed: Whether interview calibration is done.
        _facts: Internal mapping of fact_key → canonical Fact (lowest rank wins).
    """
    candidate_id: str
    display_name: str
    locale: str
    calibration_completed: bool
    _facts: dict[str, Fact] = field(default_factory=dict, compare=False, hash=False)

    def get(self, key: str) -> str | None:
        """
        Return the canonical value for a fact key.
        Returns None if not known or not usable in applications.
        """
        fact = self._facts.get(key)
        if fact is None:
            return None
        if not fact.usable_in_applications:
            return None
        if fact.state != FactState.KNOWN.value:
            return None
        return fact.fact_value

    def get_with_source(self, key: str) -> tuple[str, FactSource] | None:
        """
        Return (value, source) or None.
        Useful for answering engines that need to cite provenance.
        """
        fact = self._facts.get(key)
        if fact is None or not fact.usable_in_applications:
            return None
        if fact.state != FactState.KNOWN.value:
            return None
        source = FactSource(fact.source_label)
        return (fact.fact_value, source)

    def has(self, key: str) -> bool:
        """Return True if the key is known and usable."""
        return self.get(key) is not None

    def coverage(self, required_keys: Sequence[str]) -> dict[str, bool]:
        """Return {key: is_covered} for the given required keys."""
        return {k: self.has(k) for k in required_keys}

    def uncovered(self, required_keys: Sequence[str]) -> list[str]:
        """Return keys that are NOT covered (missing or unusable)."""
        return [k for k in required_keys if not self.has(k)]

    def keys_by_prefix(self, prefix: str) -> list[str]:
        """Return all known fact keys starting with prefix."""
        return [k for k in self._facts if k.startswith(prefix) and self.get(k) is not None]

    def to_dict(self) -> dict[str, str]:
        """Return all usable facts as {key: value}."""
        return {
            k: f.fact_value
            for k, f in self._facts.items()
            if f.usable_in_applications and f.state == FactState.KNOWN.value
        }

    def __repr__(self) -> str:
        covered = sum(1 for f in self._facts.values()
                      if f.usable_in_applications and f.state == FactState.KNOWN.value)
        return (
            f"CanonicalProfile("
            f"candidate_id={self.candidate_id!r}, "
            f"display_name={self.display_name!r}, "
            f"facts_covered={covered}"
            f")"
        )


def build_profile(candidate_id: str | None = None) -> CanonicalProfile:
    """
    Build a CanonicalProfile from the current state of the fact ledger.

    If candidate_id is None, loads the single installation candidate.
    Applies precedence: for each fact_key, keeps the fact with the lowest
    source_rank. Ties broken by updated_at (latest wins).

    This is the ONLY function that reads the fact ledger for the profile.
    """
    # Load candidate context
    if candidate_id is not None:
        import sqlalchemy as sa
        from ajaa.db.session import get_session
        with get_session() as session:
            ctx = session.get(CandidateContext, candidate_id)
            if ctx is None:
                raise ValueError(f"No candidate with id={candidate_id!r}")
            session.expunge(ctx)
    else:
        ctx = candidate_repo.get()

    # Load all facts for this candidate
    import sqlalchemy as sa
    from ajaa.db.models import Fact
    from ajaa.db.session import get_session

    with get_session() as session:
        all_facts: list[Fact] = session.execute(
            sa.select(Fact)
            .where(Fact.candidate_id == ctx.id)
            .order_by(Fact.fact_key, Fact.source_rank.asc(), Fact.updated_at.desc())
        ).scalars().all()
        for f in all_facts:
            session.expunge(f)

    # Apply precedence: for each key, keep the lowest-rank fact
    canonical: dict[str, Fact] = {}
    for fact in all_facts:
        existing = canonical.get(fact.fact_key)
        if existing is None:
            canonical[fact.fact_key] = fact
        elif fact.source_rank < existing.source_rank:
            canonical[fact.fact_key] = fact
        # Equal rank: already handled by ORDER BY updated_at DESC (first wins)

    return CanonicalProfile(
        candidate_id=ctx.id,
        display_name=ctx.display_name,
        locale=ctx.locale,
        calibration_completed=ctx.calibration_completed,
        _facts=canonical,
    )