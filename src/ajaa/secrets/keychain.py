"""
src/ajaa/secrets/keychain.py

Keychain wrapper — thin layer over keyring.

Rules:
  - Every read returns a Secret, never a plain str.
  - Every write accepts a Secret or a plain str (convenience).
  - Missing keys raise KeychainError, not return None.
  - This module is the ONLY place keyring is imported in the codebase.
    Enforced by: tests/unit/test_import_graph.py (Phase 1)
"""
from __future__ import annotations

import keyring
import keyring.errors

from ajaa.types import Secret


class KeychainError(Exception):
    """Raised when a required secret is missing from the OS keychain."""


_SERVICE = "ajaa"


def store(key: str, value: str | Secret) -> None:
    """Store a value in the OS keychain under service='ajaa'."""
    raw = value.reveal() if isinstance(value, Secret) else value
    keyring.set_password(_SERVICE, key, raw)


def retrieve(key: str) -> Secret:
    """
    Retrieve a value from the OS keychain.
    Raises KeychainError if the key does not exist.
    """
    raw = keyring.get_password(_SERVICE, key)
    if raw is None:
        raise KeychainError(
            f"Secret '{key}' not found in the OS keychain (service='{_SERVICE}').\n"
            f"Run:  ajaa init --set-api-key\n"
            f"to store the API key securely."
        )
    return Secret(raw)


def retrieve_optional(key: str) -> Secret | None:
    """Retrieve a value, returning None if not found."""
    raw = keyring.get_password(_SERVICE, key)
    return Secret(raw) if raw is not None else None


def delete(key: str) -> None:
    """Delete a key from the keychain. Silent if not found."""
    try:
        keyring.delete_password(_SERVICE, key)
    except keyring.errors.PasswordDeleteError:
        pass


def exists(key: str) -> bool:
    """Return True if the key exists in the keychain."""
    return keyring.get_password(_SERVICE, key) is not None