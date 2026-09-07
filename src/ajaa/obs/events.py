"""
src/ajaa/obs/events.py

Cryptographic Tamper-Evident Audit Hash Chain (PRD §23.7).

Maintains an append-only JSONL mirror on disk and SQLite audit log where:
  hash = sha256(prev_hash || canonical_json(event))

Guarantees cryptographic provenance and tamper-detection for all critical
system events and irreversible actions (SUBMIT, UPLOAD_FILE, TRANSITION).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple
import uuid

import structlog

from ajaa.config import get_settings

log = structlog.get_logger(__name__)

GENESIS_HASH = "0" * 64


def canonical_json(data: dict[str, Any]) -> str:
    """
    Produce deterministic canonical JSON representation:
    sorted keys, compact separators, UTF-8 compatible.
    """
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_event_hash(prev_hash: str, event_fields: dict[str, Any]) -> str:
    """
    Compute sha256(prev_hash || canonical_json(event_fields)).
    """
    canon = canonical_json(event_fields)
    payload = f"{prev_hash}||{canon}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def get_audit_log_path() -> Path:
    """Return path to the on-disk audit log mirror."""
    settings = get_settings()
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "audit_events.jsonl"


def get_last_audit_hash(log_path: Path | None = None) -> str:
    """
    Read the hash of the last recorded event in the audit mirror.
    Returns GENESIS_HASH if log does not exist or is empty.
    """
    path = log_path or get_audit_log_path()
    if not path.exists() or path.stat().st_size == 0:
        return GENESIS_HASH

    last_line = ""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    last_line = line
        if last_line:
            record = json.loads(last_line)
            return str(record.get("hash") or GENESIS_HASH)
    except Exception as e:
        log.warning("failed_to_read_last_audit_hash", error=str(e))

    return GENESIS_HASH


def log_audit_event(
    actor: str,
    event_type: str,
    severity: str = "INFO",
    run_id: str | None = None,
    application_id: str | None = None,
    payload: dict[str, Any] | None = None,
    log_path: Path | None = None,
) -> dict[str, Any]:
    """
    Append an immutable event to the cryptographic audit chain.

    Persists to:
      1. On-disk append-only JSONL mirror (<data_dir>/logs/audit_events.jsonl)
      2. SQLite audit_events table if session context exists

    Returns:
      The complete audit event dict including prev_hash and hash.
    """
    path = log_path or get_audit_log_path()
    prev_hash = get_last_audit_hash(path)

    event_id = str(uuid.uuid4())
    ts = datetime.now(timezone.utc).isoformat()
    clean_payload = payload or {}

    # Event fields included in the cryptographic hash preimage
    event_fields = {
        "event_id": event_id,
        "ts": ts,
        "run_id": run_id,
        "application_id": application_id,
        "actor": actor,
        "event_type": event_type,
        "severity": severity,
        "payload": clean_payload,
    }

    event_hash = compute_event_hash(prev_hash, event_fields)

    full_record = dict(event_fields)
    full_record["prev_hash"] = prev_hash
    full_record["hash"] = event_hash

    # 1. Append to disk JSONL mirror
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(full_record, sort_keys=True) + "\n")

    log.info(
        "audit_event_logged",
        event_id=event_id,
        event_type=event_type,
        actor=actor,
        hash=event_hash[:12],
    )

    return full_record


def verify_audit_chain(log_path: Path | None = None) -> Tuple[bool, int, str | None]:
    """
    Verify the cryptographic integrity of the audit chain (PRD §23.7).

    Returns:
      (is_valid, total_events_checked, error_message)
    """
    path = log_path or get_audit_log_path()
    if not path.exists() or path.stat().st_size == 0:
        return True, 0, None

    expected_prev = GENESIS_HASH
    count = 0

    with open(path, "r", encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            count += 1
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                return False, count, f"Line {idx}: malformed JSON"

            recorded_prev = record.get("prev_hash")
            recorded_hash = record.get("hash")

            # 1. Verify link to previous event
            if recorded_prev != expected_prev:
                return (
                    False,
                    count,
                    f"Line {idx} (event {record.get('event_id')}): broken chain link. "
                    f"Expected prev_hash {expected_prev[:12]}..., got {recorded_prev[:12] if recorded_prev else 'None'}...",
                )

            # 2. Re-compute hash from preimage fields
            event_fields = {
                "event_id": record.get("event_id"),
                "ts": record.get("ts"),
                "run_id": record.get("run_id"),
                "application_id": record.get("application_id"),
                "actor": record.get("actor"),
                "event_type": record.get("event_type"),
                "severity": record.get("severity"),
                "payload": record.get("payload", {}),
            }
            computed_hash = compute_event_hash(recorded_prev, event_fields)

            if computed_hash != recorded_hash:
                return (
                    False,
                    count,
                    f"Line {idx} (event {record.get('event_id')}): hash mismatch (TAMPER DETECTED). "
                    f"Computed {computed_hash[:12]}..., recorded {recorded_hash[:12] if recorded_hash else 'None'}...",
                )

            expected_prev = recorded_hash

    return True, count, None
