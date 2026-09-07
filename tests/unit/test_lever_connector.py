"""
tests/unit/test_lever_connector.py

Unit tests for Lever ATS deterministic connector and perception.
"""
from unittest.mock import MagicMock
import pytest

from ajaa.application.connectors.lever import LeverConnector
from ajaa.browser.perception import parse_form_html
from ajaa.db.models import Job


MOCK_LEVER_HTML = """
<!DOCTYPE html>
<html>
<body>
  <form id="application-form" action="/palantir/123/apply" method="POST">
    <div class="application-field">
      <label for="resume-upload-input">Resume/CV <span>✱</span></label>
      <input type="file" id="resume-upload-input" name="resume" required>
    </div>

    <div class="application-field">
      <label for="name">Full name <span>✱</span></label>
      <input type="text" id="name" name="name" required>
    </div>

    <div class="application-field">
      <label for="email">Email <span>✱</span></label>
      <input type="email" id="email" name="email" required>
    </div>

    <div class="application-field">
      <label for="phone">Phone <span>✱</span></label>
      <input type="text" id="phone" name="phone" required>
    </div>

    <div class="application-field">
      <label for="org">Current company</label>
      <input type="text" id="org" name="org">
    </div>

    <div class="application-field">
      <label for="location-input">Current location</label>
      <input type="text" id="location-input" name="location">
    </div>

    <div class="application-field">
      <label for="linkedin">LinkedIn URL</label>
      <input type="text" id="linkedin" name="urls[LinkedIn]">
    </div>

    <div class="application-field">
      <label for="github">GitHub URL</label>
      <input type="text" id="github" name="urls[GitHub]">
    </div>

    <div class="application-field">
      <label for="portfolio">Portfolio URL</label>
      <input type="text" id="portfolio" name="urls[Portfolio]">
    </div>

    <div class="application-field">
      <label for="consent_checkbox">I agree to the privacy policy and processing of my personal data</label>
      <input type="checkbox" id="consent_checkbox" name="consent">
    </div>

    <button id="btn-submit" type="button" class="postings-btn template-btn-submit" data-qa="btn-submit">Submit application</button>
  </form>
</body>
</html>
"""


def test_lever_matches():
    connector = LeverConnector()
    job1 = Job(source_connector="lever:palantir", apply_url="https://jobs.lever.co/palantir/1/apply")
    job2 = Job(source_connector="manual", apply_url="https://jobs.lever.co/stripe/2")
    job3 = Job(source_connector="greenhouse", apply_url="https://boards.greenhouse.io/corp/1")

    assert connector.matches(job1)
    assert connector.matches(job2)
    assert not connector.matches(job3)


def test_lever_form_perception():
    descriptor = parse_form_html(MOCK_LEVER_HTML)
    assert descriptor.form_id == "application-form"
    assert len(descriptor.fields) == 10

    f_name = descriptor.get_field_by_name("name")
    assert f_name is not None
    assert f_name.required is True

    f_resume = descriptor.get_field_by_name("resume")
    assert f_resume is not None
    assert f_resume.field_type == "file"


def test_lever_plan_generation():
    connector = LeverConnector()
    descriptor = parse_form_html(MOCK_LEVER_HTML)

    candidate_facts = {
        "personal.name.full": "Alex Vance",
        "personal.email.primary": "alex@blackmesa.org",
        "personal.phone.primary": "+1-555-0142",
        "location.city": "Boston",
        "experience.current_company": "Black Mesa",
        "online.linkedin": "https://linkedin.com/in/alexvance",
        "online.github": "https://github.com/alexvance",
        "online.portfolio": "https://alexvance.dev",
    }
    resolved_answers = {}

    plan = connector.plan(
        descriptor=descriptor,
        candidate_facts=candidate_facts,
        resolved_answers=resolved_answers,
        cv_path="/tmp/alex_cv.pdf",
    )

    ops_by_selector = {op.selector: op for op in plan.operations}

    # Verify standard fields mapped accurately
    assert "#name" in ops_by_selector
    assert ops_by_selector["#name"].value == "Alex Vance"

    assert "#email" in ops_by_selector
    assert ops_by_selector["#email"].value == "alex@blackmesa.org"

    assert "#phone" in ops_by_selector
    assert ops_by_selector["#phone"].value == "+1-555-0142"

    assert "#org" in ops_by_selector
    assert ops_by_selector["#org"].value == "Black Mesa"

    assert "#location-input" in ops_by_selector
    assert ops_by_selector["#location-input"].value == "Boston"

    assert "#linkedin" in ops_by_selector
    assert ops_by_selector["#linkedin"].value == "https://linkedin.com/in/alexvance"

    assert "#github" in ops_by_selector
    assert ops_by_selector["#github"].value == "https://github.com/alexvance"

    assert "#resume-upload-input" in ops_by_selector
    assert ops_by_selector["#resume-upload-input"].action == "upload_file"
    assert ops_by_selector["#resume-upload-input"].value == "/tmp/alex_cv.pdf"

    # Invariant I6: Consent checkbox must halt
    assert "#consent_checkbox" in ops_by_selector
    assert ops_by_selector["#consent_checkbox"].action == "consent_halt"


def test_lever_verification():
    connector = LeverConnector()
    page = MagicMock()
    page.url = "https://jobs.lever.co/palantir/123/thanks"
    page.content.return_value = "<html><body>Thank you for applying to Palantir! Application #: PAL-9921</body></html>"
    page.locator.return_value.count.return_value = 1

    conf = connector.verify(page)
    assert conf.is_confirmed is True
    assert conf.ats_application_id == "PAL-9921"
