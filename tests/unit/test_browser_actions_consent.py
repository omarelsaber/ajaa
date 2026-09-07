"""
tests/unit/test_browser_actions_consent.py

Unit tests for browser action safety and Invariant I6 (no consent auto-checking).
"""
import pytest
from unittest.mock import MagicMock
from ajaa.browser.actions import (
    ConsentCheckboxHaltError,
    is_consent_checkbox,
    set_checkbox,
)


def test_is_consent_checkbox_detection():
    # True positives (consent / terms / GDPR)
    assert is_consent_checkbox("I agree to the Terms of Service and Privacy Policy")
    assert is_consent_checkbox("I consent to the processing of my personal data under GDPR")
    assert is_consent_checkbox("Do you agree with the data processing agreement?")
    assert is_consent_checkbox("I acknowledge that all information is truthful")
    assert is_consent_checkbox("Consent for background check")

    # True negatives (regular checkboxes)
    assert not is_consent_checkbox("Notify me about future job opportunities")
    assert not is_consent_checkbox("Are you open to remote work?")
    assert not is_consent_checkbox("Over 18 years of age")


def test_set_checkbox_halts_on_consent_checkbox():
    """Invariant I6: Consent checkboxes MUST raise ConsentCheckboxHaltError and never be auto-checked."""
    mock_page = MagicMock()

    with pytest.raises(ConsentCheckboxHaltError):
        set_checkbox(
            page=mock_page,
            selector="#gdpr_consent",
            checked=True,
            label_text="I agree to the processing of my personal data under GDPR",
        )

    # Verify Playwright check() was never called
    assert mock_page.locator.call_count == 0


def test_set_checkbox_allows_non_consent():
    mock_page = MagicMock()
    mock_locator = MagicMock()
    mock_page.locator.return_value.first = mock_locator

    set_checkbox(
        page=mock_page,
        selector="#remote_pref",
        checked=True,
        label_text="Open to remote work",
    )
    mock_locator.check.assert_called_once()
