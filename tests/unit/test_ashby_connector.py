"""
tests/unit/test_ashby_connector.py

Unit tests for AshbyConnector (PRD §10.2, §18.3, Invariant I6).
"""
from __future__ import annotations

from unittest.mock import MagicMock
import pytest

from ajaa.application.connectors.ashby import AshbyConnector
from ajaa.browser.perception import FieldDescriptor, FormDescriptor
from ajaa.db.models import Job


def test_ashby_connector_matches() -> None:
    connector = AshbyConnector()

    job1 = Job(id="1", apply_url="https://jobs.ashbyhq.com/openai/635f1111", source_connector="ashby:openai")
    assert connector.matches(job1) is True

    job2 = Job(id="2", apply_url="https://jobs.ashbyhq.com/linear/eng-lead", source_connector=None)
    assert connector.matches(job2) is True

    job3 = Job(id="3", apply_url="https://boards.greenhouse.io/stripe/jobs/123", source_connector="greenhouse:stripe")
    assert connector.matches(job3) is False

    job4 = Job(id="4", apply_url="https://jobs.lever.co/spotify/abc", source_connector="lever:spotify")
    assert connector.matches(job4) is False


def test_ashby_connector_plan_standard_fields() -> None:
    connector = AshbyConnector()

    descriptor = FormDescriptor(
        form_id="ashby_form",
        action_url="https://jobs.ashbyhq.com/api/apply",
        fields=[
            FieldDescriptor(field_id="field_name", name="name", field_type="text", label="Full Name", required=True, selector="input#field_name"),
            FieldDescriptor(field_id="field_email", name="email", field_type="email", label="Email", required=True, selector="input#field_email"),
            FieldDescriptor(field_id="field_phone", name="phoneNumber", field_type="tel", label="Phone Number", required=False, selector="input#field_phone"),
            FieldDescriptor(field_id="field_resume", name="resume", field_type="file", label="Resume / CV", required=True, selector="input#field_resume"),
            FieldDescriptor(field_id="field_linkedin", name="linkedin", field_type="text", label="LinkedIn URL", required=False, selector="input#field_linkedin"),
            FieldDescriptor(field_id="field_github", name="github", field_type="text", label="GitHub URL", required=False, selector="input#field_github"),
        ],
    )

    facts = {
        "personal.name.full": "Ada Lovelace",
        "personal.email.primary": "ada@example.com",
        "personal.phone.primary": "+15551234567",
        "online.linkedin": "https://linkedin.com/in/adalovelace",
        "online.github": "https://github.com/adalovelace",
    }

    plan = connector.plan(descriptor, facts, {}, cv_path="/tmp/cv.pdf")

    assert len(plan.operations) == 6
    ops_dict = {op.field_label: op for op in plan.operations}

    assert ops_dict["Full Name"].value == "Ada Lovelace"
    assert ops_dict["Full Name"].action == "fill_text"

    assert ops_dict["Email"].value == "ada@example.com"
    assert ops_dict["Email"].action == "fill_text"

    assert ops_dict["Phone Number"].value == "+15551234567"
    assert ops_dict["Phone Number"].action == "fill_text"

    assert ops_dict["Resume / CV"].value == "/tmp/cv.pdf"
    assert ops_dict["Resume / CV"].action == "upload_file"

    assert ops_dict["LinkedIn URL"].value == "https://linkedin.com/in/adalovelace"
    assert ops_dict["GitHub URL"].value == "https://github.com/adalovelace"


def test_ashby_connector_invariant_i6_consent_halt() -> None:
    """Invariant I6: Consent checkboxes are never auto-checked."""
    connector = AshbyConnector()

    descriptor = FormDescriptor(
        form_id="ashby_form",
        action_url="https://jobs.ashbyhq.com/api/apply",
        fields=[
            FieldDescriptor(field_id="name", name="name", field_type="text", label="Full Name", selector="input#name"),
            FieldDescriptor(field_id="gdpr_consent", name="consent", field_type="checkbox", label="I agree to the privacy policy", selector="input#gdpr_consent"),
        ],
    )

    facts = {"personal.name.full": "Grace Hopper"}
    plan = connector.plan(descriptor, facts, {})

    consent_ops = [op for op in plan.operations if op.action == "consent_halt"]
    assert len(consent_ops) == 1

    # Fill execution must halt
    mock_page = MagicMock()
    report = connector.fill(mock_page, plan)

    assert report.success is False
    assert report.needs_user is True
    assert "Invariant I6" in report.needs_user_reason
    assert report.filled_count == 1
    mock_page.check.assert_not_called()


def test_ashby_connector_verify() -> None:
    connector = AshbyConnector()

    page_success = MagicMock()
    page_success.url = "https://jobs.ashbyhq.com/openai/application-submitted"
    page_success.content.return_value = "<html>Thank you for applying to OpenAI!</html>"
    page_success.locator.return_value.count.return_value = 0

    confirmation_success = connector.verify(page_success)
    assert confirmation_success.is_confirmed is True

    page_uncertain = MagicMock()
    page_uncertain.url = "https://jobs.ashbyhq.com/openai/job"
    page_uncertain.content.return_value = "<html>Still on form</html>"
    page_uncertain.locator.return_value.count.return_value = 0

    confirmation_uncertain = connector.verify(page_uncertain)
    assert confirmation_uncertain.is_confirmed is False
