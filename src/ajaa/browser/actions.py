"""
src/ajaa/browser/actions.py

Deterministic Browser Automation Actions & Safety Guardrails.

Governed by PRD §10.2, §24.2, and §24.4:
  - Invariant I6: Consent checkboxes are NEVER auto-checked in v0.1.
    If a consent/GDPR checkbox is encountered, execution halts to NEEDS_USER_ACTION.
  - Safe, predictable field operations (fill, select, upload, click).
  - LLMs NEVER execute actions directly.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import re


class BrowserActionError(Exception):
    """Base error for browser action failures."""
    pass


class ConsentCheckboxHaltError(BrowserActionError):
    """Raised when a consent/terms checkbox is encountered (Invariant I6)."""
    pass


# Regular expression matching consent, GDPR, privacy, and terms acknowledgment
CONSENT_PATTERN = re.compile(
    r"\b(consent|agree|agreed|agreement|privacy\s*policy|gdpr|terms\s*of|terms\s*and\s*conditions|"
    r"processing\s*(of\s*my)?\s*personal\s*data|acknowledge|authoriz(e|ation))\b",
    re.IGNORECASE,
)


def is_consent_checkbox(label_or_text: str) -> bool:
    """Return True if the text represents a consent, GDPR, or legal agreement checkbox."""
    if not label_or_text:
        return False
    return bool(CONSENT_PATTERN.search(label_or_text))


def fill_text(page: Any, selector: str, value: str, timeout: float = 5000) -> bool:
    """
    Safely fill a text, email, or telephone input.
    Clears existing content first and inputs value with human-like keystroke rhythm.
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        locator.fill("")
        locator.fill(value)
        return True
    except Exception as e:
        raise BrowserActionError(f"Failed to fill text in selector '{selector}': {e}") from e


def select_option(page: Any, selector: str, option_text_or_value: str, timeout: float = 5000) -> bool:
    """
    Select an option in a <select> dropdown by label or value.
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        try:
            locator.select_option(label=option_text_or_value)
        except Exception:
            locator.select_option(value=option_text_or_value)
        return True
    except Exception as e:
        raise BrowserActionError(f"Failed to select '{option_text_or_value}' in '{selector}': {e}") from e


def set_checkbox(
    page: Any,
    selector: str,
    checked: bool = True,
    label_text: str = "",
    timeout: float = 5000,
) -> bool:
    """
    Check or uncheck a checkbox input.
    CRITICAL: Enforces Invariant I6. If the checkbox is a consent/terms checkbox,
    raises ConsentCheckboxHaltError and halts execution.
    """
    if is_consent_checkbox(label_text):
        raise ConsentCheckboxHaltError(
            f"Consent checkbox encountered (Invariant I6): '{label_text}'. "
            f"AJAA v0.1 refuses to auto-check consent checkboxes. Halting to NEEDS_USER_ACTION."
        )

    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        if checked:
            locator.check()
        else:
            locator.uncheck()
        return True
    except Exception as e:
        raise BrowserActionError(f"Failed to set checkbox '{selector}': {e}") from e


def upload_file(page: Any, selector: str, file_path: str, timeout: float = 5000) -> bool:
    """
    Attach a file (such as a CV PDF) to an input[type='file'].
    """
    path_obj = Path(file_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"CV file not found on disk at '{file_path}'")

    try:
        locator = page.locator(selector).first
        locator.set_input_files(str(path_obj.resolve()), timeout=timeout)
        return True
    except Exception as e:
        raise BrowserActionError(f"Failed to upload file '{file_path}' to '{selector}': {e}") from e


def click_button(page: Any, selector: str, timeout: float = 5000) -> bool:
    """
    Click a button, link, or submit element.
    """
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=timeout)
        locator.click()
        return True
    except Exception as e:
        raise BrowserActionError(f"Failed to click selector '{selector}': {e}") from e


def capture_screenshot(page: Any, output_path: str) -> str:
    """
    Capture a screenshot of the current page state and write to output_path.
    Creates parent directories if necessary.
    """
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        page.screenshot(path=str(out.resolve()), full_page=True)
        return str(out.resolve())
    except Exception as e:
        # Non-fatal if screenshot fails
        return ""
