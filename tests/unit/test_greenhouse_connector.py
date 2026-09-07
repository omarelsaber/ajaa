"""
tests/unit/test_greenhouse_connector.py

Unit tests for Greenhouse ATS deterministic connector and perception.
"""
from unittest.mock import MagicMock
import pytest

from ajaa.application.connectors.greenhouse import GreenhouseConnector
from ajaa.browser.perception import parse_form_html
from ajaa.db.models import Job


MOCK_GREENHOUSE_HTML = """
<!DOCTYPE html>
<html>
<body>
  <form id="application_form" action="/jobs/123/apply" method="POST">
    <label for="first_name">First Name *</label>
    <input type="text" id="first_name" name="first_name" required>

    <label for="last_name">Last Name *</label>
    <input type="text" id="last_name" name="last_name" required>

    <label for="email">Email *</label>
    <input type="email" id="email" name="email" required>

    <label for="phone">Phone *</label>
    <input type="tel" id="phone" name="phone" required>

    <label for="resume">Resume/CV *</label>
    <input type="file" id="resume" name="resume" required>

    <label for="job_application_answers_attributes_0_boolean_value">Will you now or in the future require sponsorship? *</label>
    <select id="job_application_answers_attributes_0_boolean_value" name="job_application[answers_attributes][0][boolean_value]">
      <option value="">-- Please Select --</option>
      <option value="0">No</option>
      <option value="1">Yes</option>
    </select>

    <input type="submit" id="submit_app" value="Submit Application">
  </form>
</body>
</html>
"""


def test_greenhouse_matches():
    connector = GreenhouseConnector()
    job1 = Job(source_connector="greenhouse", apply_url="https://boards.greenhouse.io/company/jobs/1")
    job2 = Job(source_connector="manual", apply_url="https://job-boards.greenhouse.io/corp/1")
    job3 = Job(source_connector="lever", apply_url="https://jobs.lever.co/company/1")

    assert connector.matches(job1)
    assert connector.matches(job2)
    assert not connector.matches(job3)


def test_greenhouse_form_perception():
    descriptor = parse_form_html(MOCK_GREENHOUSE_HTML)
    assert descriptor.form_id == "application_form"
    assert len(descriptor.fields) == 6

    f_first = descriptor.get_field_by_name("first_name")
    assert f_first is not None
    assert f_first.label == "First Name *"
    assert f_first.required is True

    f_resume = descriptor.get_field_by_name("resume")
    assert f_resume is not None
    assert f_resume.field_type == "file"


def test_greenhouse_plan_generation():
    connector = GreenhouseConnector()
    descriptor = parse_form_html(MOCK_GREENHOUSE_HTML)

    candidate_facts = {
        "personal.name.full": "Jane Doe",
        "personal.email.primary": "jane@example.com",
        "personal.phone.primary": "+1-555-0199",
        "location.city": "Seattle",
    }
    resolved_answers = {
        "sponsorship": "No",
    }

    plan = connector.plan(
        descriptor=descriptor,
        candidate_facts=candidate_facts,
        resolved_answers=resolved_answers,
        cv_path="/tmp/cv.pdf",
    )

    ops_by_selector = {op.selector: op for op in plan.operations}

    assert "#first_name" in ops_by_selector
    assert ops_by_selector["#first_name"].value == "Jane"

    assert "#last_name" in ops_by_selector
    assert ops_by_selector["#last_name"].value == "Doe"

    assert "#email" in ops_by_selector
    assert ops_by_selector["#email"].value == "jane@example.com"

    assert "#resume" in ops_by_selector
    assert ops_by_selector["#resume"].action == "upload_file"
    assert ops_by_selector["#resume"].value == "/tmp/cv.pdf"


def test_greenhouse_verification_confirmation():
    connector = GreenhouseConnector()
    page = MagicMock()
    page.url = "https://boards.greenhouse.io/company/jobs/123/confirmation"
    page.content.return_value = "<html><body><h1>Thank you for applying!</h1><p>Application #: GH-98765</p></body></html>"

    conf = connector.verify(page)
    assert conf.is_confirmed is True
    assert "confirmation" in conf.confirmation_url
    assert conf.ats_application_id == "GH-98765"
