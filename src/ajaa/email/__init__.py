"""
src/ajaa/email/__init__.py

Email application pipeline module (PRD §27).
"""
from __future__ import annotations

from ajaa.email.apply import (
    compose_application_email,
    detect_email_application,
    send_email_application,
    verify_email_domain,
)

__all__ = [
    "compose_application_email",
    "detect_email_application",
    "send_email_application",
    "verify_email_domain",
]
