"""
tests/unit/test_audit_chain.py

Cryptographic Tamper-Evident Audit Hash Chain Tests (PRD §23.7).

Verifies that:
  1. Sequential events link prev_hash -> hash via SHA-256.
  2. Genesis event uses 64 zeros as prev_hash.
  3. verify_audit_chain passes for untampered logs.
  4. Tampering with any payload field or hash breaks the chain and is detected.
"""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from ajaa.obs.events import (
    GENESIS_HASH,
    compute_event_hash,
    log_audit_event,
    verify_audit_chain,
)


def test_audit_hash_chain_sequential_integrity(tmp_path: Path) -> None:
    """Sequential events link properly and verify cleanly."""
    log_file = tmp_path / "audit_events.jsonl"

    # Log 3 events
    e1 = log_audit_event(
        actor="SYSTEM",
        event_type="BOOTSTRAP",
        severity="INFO",
        payload={"message": "System initialized"},
        log_path=log_file,
    )
    assert e1["prev_hash"] == GENESIS_HASH
    assert len(e1["hash"]) == 64

    e2 = log_audit_event(
        actor="USER",
        event_type="CV_UPLOADED",
        severity="INFO",
        application_id="app-1",
        payload={"filename": "resume.pdf", "hash": "abc1234"},
        log_path=log_file,
    )
    assert e2["prev_hash"] == e1["hash"]

    e3 = log_audit_event(
        actor="BROWSER",
        event_type="SUBMIT_ATTEMPTED",
        severity="WARNING",
        application_id="app-1",
        payload={"url": "https://boards.greenhouse.io/test/jobs/1"},
        log_path=log_file,
    )
    assert e3["prev_hash"] == e2["hash"]

    # Verify chain
    valid, count, error = verify_audit_chain(log_file)
    assert valid is True
    assert count == 3
    assert error is None


def test_audit_hash_chain_tamper_detection(tmp_path: Path) -> None:
    """Tampering with an event payload breaks the cryptographic chain."""
    log_file = tmp_path / "audit_events.jsonl"

    # Log 2 events
    log_audit_event(
        actor="SYSTEM",
        event_type="STATE_CHANGE",
        payload={"from": "QUEUED", "to": "PREPARING"},
        log_path=log_file,
    )
    log_audit_event(
        actor="BROWSER",
        event_type="FORM_SUBMITTED",
        payload={"status": "OK"},
        log_path=log_file,
    )

    # Read events
    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    record0 = json.loads(lines[0])

    # Tamper with record0 payload (e.g. attacker tries to change the logged state)
    record0["payload"]["to"] = "SUBMITTED"
    lines[0] = json.dumps(record0, sort_keys=True)
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Verification must fail with tamper detection
    valid, count, error = verify_audit_chain(log_file)
    assert valid is False
    assert "TAMPER DETECTED" in str(error)


def test_audit_hash_chain_tamper_break_link(tmp_path: Path) -> None:
    """Tampering with a prev_hash pointer is caught as a broken chain link."""
    log_file = tmp_path / "audit_events.jsonl"

    log_audit_event(actor="USER", event_type="LOGIN", log_path=log_file)
    log_audit_event(actor="USER", event_type="LOGOUT", log_path=log_file)

    lines = log_file.read_text(encoding="utf-8").strip().split("\n")
    record1 = json.loads(lines[1])
    # Tamper with prev_hash
    record1["prev_hash"] = "f" * 64
    lines[1] = json.dumps(record1, sort_keys=True)
    log_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    valid, count, error = verify_audit_chain(log_file)
    assert valid is False
    assert "broken chain link" in str(error)
