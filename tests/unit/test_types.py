"""
tests/unit/test_types.py

Tests for src/ajaa/types.py — the foundational types.

These tests are ACCEPTANCE-CRITERION level. They must pass before
Phase 0 is complete. They are not optional.
"""
from __future__ import annotations

import json
import pickle
from uuid import UUID

import pytest

from ajaa.types import (
    NOT_SET,
    ApplicationState,
    Confidence,
    FactSource,
    FactState,
    LLMTask,
    Secret,
    Tier,
    Untrusted,
    UntrustedStr,
    _NotSetType,
)


# ── Secret ────────────────────────────────────────────────────────────────────

class TestSecret:
    def test_repr_is_redacted(self) -> None:
        s = Secret("sk-12345")
        assert repr(s) == "<Secret redacted>"

    def test_str_raises(self) -> None:
        s = Secret("sk-12345")
        with pytest.raises(TypeError, match="cannot be converted to str"):
            str(s)

    def test_fstring_raises(self) -> None:
        s = Secret("sk-12345")
        with pytest.raises(TypeError):
            _ = f"{s}"

    def test_format_raises(self) -> None:
        s = Secret("sk-12345")
        with pytest.raises(TypeError):
            "{}".format(s)  # noqa: UP032

    def test_reveal_returns_value(self) -> None:
        s = Secret("sk-12345")
        assert s.reveal() == "sk-12345"

    def test_json_serialize_raises(self) -> None:
        s = Secret("sk-12345")
        with pytest.raises(TypeError):
            json.dumps({"key": s})

    def test_pickle_raises(self) -> None:
        s = Secret("sk-12345")
        with pytest.raises(TypeError):
            pickle.dumps(s)

    def test_equality(self) -> None:
        assert Secret("abc") == Secret("abc")
        assert Secret("abc") != Secret("xyz")
        assert Secret("abc") != "abc"

    def test_hash(self) -> None:
        s1, s2 = Secret("abc"), Secret("abc")
        assert hash(s1) == hash(s2)

    def test_copy_does_not_leak(self) -> None:
        import copy
        s = Secret("abc")
        s2 = copy.copy(s)
        assert s2.reveal() == "abc"
        assert s2 is not s

    def test_deepcopy_does_not_leak(self) -> None:
        import copy
        s = Secret("abc")
        s2 = copy.deepcopy(s)
        assert s2.reveal() == "abc"


# ── Untrusted ─────────────────────────────────────────────────────────────────

class TestUntrusted:
    def test_value_accessible(self) -> None:
        u: UntrustedStr = Untrusted("job text")
        assert u.value == "job text"

    def test_repr_shows_type(self) -> None:
        u: UntrustedStr = Untrusted("something")
        assert "Untrusted" in repr(u)

    def test_str_returns_inner(self) -> None:
        u: UntrustedStr = Untrusted("something")
        assert str(u) == "something"

    def test_type_distinction(self) -> None:
        u: UntrustedStr = Untrusted("text")
        # Must be Untrusted, not a plain str
        assert isinstance(u, Untrusted)
        assert not isinstance(u, str)


# ── NOT_SET sentinel ──────────────────────────────────────────────────────────

class TestNotSet:
    def test_singleton(self) -> None:
        a = _NotSetType()
        b = _NotSetType()
        assert a is b
        assert NOT_SET is a

    def test_falsy(self) -> None:
        assert not NOT_SET

    def test_repr(self) -> None:
        assert repr(NOT_SET) == "NOT_SET"

    def test_equality(self) -> None:
        assert NOT_SET == _NotSetType()

    def test_distinct_from_none(self) -> None:
        assert NOT_SET is not None
        assert NOT_SET != None  # noqa: E711

    def test_distinct_from_zero(self) -> None:
        assert NOT_SET != 0


# ── FactSource ────────────────────────────────────────────────────────────────

class TestFactSource:
    def test_rank_ordering(self) -> None:
        """USER_EXPLICIT must outrank everything else."""
        for other in FactSource:
            if other == FactSource.USER_EXPLICIT:
                continue
            assert FactSource.USER_EXPLICIT.outranks(other), (
                f"USER_EXPLICIT should outrank {other}"
            )

    def test_llm_inference_outranked_by_cv(self) -> None:
        assert FactSource.CV_EXPLICIT.outranks(FactSource.LLM_INFERENCE)
        assert FactSource.CV_INFERRED.outranks(FactSource.LLM_INFERENCE)

    def test_user_controlled(self) -> None:
        assert FactSource.USER_EXPLICIT.is_user_controlled
        assert FactSource.USER_CONFIRMED_SUGGESTION.is_user_controlled
        assert not FactSource.CV_EXPLICIT.is_user_controlled
        assert not FactSource.LLM_INFERENCE.is_user_controlled

    def test_all_sources_have_rank(self) -> None:
        for source in FactSource:
            assert isinstance(source.rank, int)
            assert source.rank > 0

    def test_ranks_are_unique(self) -> None:
        ranks = [s.rank for s in FactSource]
        assert len(ranks) == len(set(ranks)), "Duplicate ranks found"

    @pytest.mark.parametrize("higher,lower", [
        (FactSource.USER_EXPLICIT, FactSource.USER_CONFIRMED_SUGGESTION),
        (FactSource.USER_CONFIRMED_SUGGESTION, FactSource.APPLICATION_ANSWER),
        (FactSource.APPLICATION_ANSWER, FactSource.CV_EXPLICIT),
        (FactSource.CV_EXPLICIT, FactSource.CV_INFERRED),
        (FactSource.CV_INFERRED, FactSource.LLM_INFERENCE),
        (FactSource.LLM_INFERENCE, FactSource.DEFAULT),
    ])
    def test_precedence_chain(self, higher: FactSource, lower: FactSource) -> None:
        assert higher.outranks(lower)
        assert not lower.outranks(higher)


# ── FactState ─────────────────────────────────────────────────────────────────

class TestFactState:
    def test_known_counts_as_covered(self) -> None:
        assert FactState.KNOWN.counts_as_covered

    def test_refused_counts_as_covered(self) -> None:
        assert FactState.REFUSED_TO_ANSWER.counts_as_covered

    def test_not_applicable_counts_as_covered(self) -> None:
        assert FactState.NOT_APPLICABLE.counts_as_covered

    def test_unknown_does_not_count_as_covered(self) -> None:
        assert not FactState.UNKNOWN.counts_as_covered

    def test_refused_blocks_reask(self) -> None:
        assert FactState.REFUSED_TO_ANSWER.blocks_reask

    def test_not_applicable_blocks_reask(self) -> None:
        assert FactState.NOT_APPLICABLE.blocks_reask

    def test_known_does_not_block_reask(self) -> None:
        # KNOWN can be updated; it doesn't block asking for an update
        assert not FactState.KNOWN.blocks_reask

    def test_unknown_does_not_block_reask(self) -> None:
        assert not FactState.UNKNOWN.blocks_reask

    def test_all_four_states_exist(self) -> None:
        states = {s.value for s in FactState}
        assert states == {"KNOWN", "UNKNOWN", "REFUSED_TO_ANSWER", "NOT_APPLICABLE"}


# ── ApplicationState ──────────────────────────────────────────────────────────

class TestApplicationState:
    def test_submitting_crash_yields_uncertain(self) -> None:
        assert ApplicationState.SUBMITTING.crash_resolution == ApplicationState.UNCERTAIN

    def test_verifying_crash_yields_uncertain(self) -> None:
        assert ApplicationState.VERIFYING.crash_resolution == ApplicationState.UNCERTAIN

    def test_queued_crash_yields_queued(self) -> None:
        assert ApplicationState.QUEUED.crash_resolution == ApplicationState.QUEUED

    def test_preparing_crash_yields_queued(self) -> None:
        assert ApplicationState.PREPARING.crash_resolution == ApplicationState.QUEUED

    def test_submitted_is_terminal(self) -> None:
        assert ApplicationState.SUBMITTED.is_terminal

    def test_uncertain_is_terminal(self) -> None:
        assert ApplicationState.UNCERTAIN.is_terminal

    def test_failed_is_terminal(self) -> None:
        assert ApplicationState.FAILED.is_terminal

    def test_queued_is_not_terminal(self) -> None:
        assert not ApplicationState.QUEUED.is_terminal

    def test_submitting_is_not_terminal(self) -> None:
        # SUBMITTING is in-progress, not terminal
        assert not ApplicationState.SUBMITTING.is_terminal

    def test_queued_is_pre_browser(self) -> None:
        assert ApplicationState.QUEUED.is_pre_browser

    def test_preparing_is_pre_browser(self) -> None:
        assert ApplicationState.PREPARING.is_pre_browser

    def test_started_is_not_pre_browser(self) -> None:
        assert not ApplicationState.STARTED.is_pre_browser


# ── Confidence ────────────────────────────────────────────────────────────────

class TestConfidence:
    def test_confirmed_is_highest(self) -> None:
        assert Confidence.CONFIRMED.numeric == 1.0

    def test_low_is_lowest(self) -> None:
        assert Confidence.LOW.numeric < Confidence.MEDIUM.numeric

    def test_ordering(self) -> None:
        nums = [c.numeric for c in [Confidence.LOW, Confidence.MEDIUM, Confidence.HIGH, Confidence.CONFIRMED]]
        assert nums == sorted(nums)