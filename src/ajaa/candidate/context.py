"""
src/ajaa/candidate/context.py

CandidateContext immutable handle (PRD §4.1, §11.1).

The Fundamental Architectural Rule:
No engine module imports a fact repository, CV store, ontology loader,
or policy loader directly. Every engine receives a CandidateContext.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class CandidateContext:
    """
    Immutable representation of the candidate context passed to engine modules.
    """
    candidate_id: str
    display_name: str
    locale: str = "en-US"
    calibration_completed: bool = False
    profile: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str, default: Any = None) -> Any:
        return self.profile.get(key, default)

    @classmethod
    def from_profile(cls, canonical_profile: Any) -> "CandidateContext":
        """Construct from a CanonicalProfile."""
        return cls(
            candidate_id=canonical_profile.candidate_id,
            display_name=canonical_profile.display_name,
            locale=canonical_profile.locale,
            calibration_completed=canonical_profile.calibration_completed,
            profile=canonical_profile.to_dict(),
        )
