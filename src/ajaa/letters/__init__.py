"""
src/ajaa/letters/__init__.py

Cover letter generation and management module (PRD §14).
"""
from __future__ import annotations

from ajaa.letters.generator import (
    CoverLetterResult,
    generate_cover_letter,
    record_user_edit,
    save_or_update_cover_letter,
)

__all__ = [
    "CoverLetterResult",
    "generate_cover_letter",
    "record_user_edit",
    "save_or_update_cover_letter",
]
