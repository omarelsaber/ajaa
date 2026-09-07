"""
tests/fakesites/app.py

Lightweight Fake ATS Server for Offline E2E Browser Testing (PRD §34).

Serves structurally accurate forms for Greenhouse, Lever, Ashby,
consent halts, and captcha detection without external network dependencies.
"""
from __future__ import annotations

from typing import Any
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

app = FastAPI(title="Fake ATS Test Server")

# In-memory recorded submissions for test assertions
recorded_submissions: list[dict[str, Any]] = []


@app.get("/greenhouse/job", response_class=HTMLResponse)
async def greenhouse_job():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Staff Engineer - Acme Corp</title></head>
    <body>
      <h1>Staff Engineer at Acme Corp</h1>
      <form id="application_form" action="/submit" method="POST" enctype="multipart/form-data">
        <label for="first_name">First Name *</label>
        <input id="first_name" name="first_name" type="text" required />

        <label for="last_name">Last Name *</label>
        <input id="last_name" name="last_name" type="text" required />

        <label for="email">Email *</label>
        <input id="email" name="email" type="email" required />

        <label for="phone">Phone</label>
        <input id="phone" name="phone" type="tel" />

        <label for="resume">Resume/CV *</label>
        <input id="resume" name="resume" type="file" required />

        <button id="submit_app" type="submit">Submit Application</button>
      </form>
    </body>
    </html>
    """


@app.get("/lever/job", response_class=HTMLResponse)
async def lever_job():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Senior AI Engineer - TechCorp</title></head>
    <body>
      <h1>Senior AI Engineer at TechCorp</h1>
      <form id="application-form" action="/submit" method="POST" enctype="multipart/form-data">
        <label>Full Name <span>✱</span></label>
        <input name="name" type="text" required />

        <label>Email <span>✱</span></label>
        <input name="email" type="email" required />

        <label>Phone</label>
        <input name="phone" type="tel" />

        <label>Current company</label>
        <input name="org" type="text" />

        <label>Resume/CV <span>✱</span></label>
        <input name="resume" type="file" required />

        <button type="submit" data-qa="btn-submit">Submit application</button>
      </form>
    </body>
    </html>
    """


@app.get("/ashby/job", response_class=HTMLResponse)
async def ashby_job():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Lead Infrastructure Engineer - FutureAI</title></head>
    <body>
      <h1>Lead Infrastructure Engineer at FutureAI</h1>
      <form id="ashby-apply-form" action="/submit" method="POST" enctype="multipart/form-data">
        <label for="field_name">Full Name *</label>
        <input id="field_name" name="name" type="text" required />

        <label for="field_email">Email *</label>
        <input id="field_email" name="email" type="email" required />

        <label for="field_phone">Phone Number</label>
        <input id="field_phone" name="phoneNumber" type="tel" />

        <label for="field_resume">Resume / CV *</label>
        <input id="field_resume" name="resume" type="file" required />

        <button type="submit">Submit Application</button>
      </form>
    </body>
    </html>
    """


@app.get("/consent/job", response_class=HTMLResponse)
async def consent_job():
    """Form with mandatory privacy/consent checkbox to verify Invariant I6."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Consent Guard Job</title></head>
    <body>
      <form id="consent-form" action="/submit" method="POST">
        <label for="cand_name">Full Name</label>
        <input id="cand_name" name="name" type="text" value="" />

        <label for="consent_cb">
          <input id="consent_cb" name="consent" type="checkbox" />
          I agree to the privacy policy and consent to data processing (GDPR)
        </label>

        <button id="submit_app" type="submit">Submit Application</button>
      </form>
    </body>
    </html>
    """


@app.get("/captcha/job", response_class=HTMLResponse)
async def captcha_job():
    """Form with CAPTCHA challenge widget to test BLOCKED_BY_SITE detection."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Captcha Challenge Job</title></head>
    <body>
      <form id="captcha-form" action="/submit" method="POST">
        <input id="cand_name" name="name" type="text" />
        <div class="g-recaptcha" data-sitekey="fake-key-test"></div>
        <iframe src="about:blank" title="reCAPTCHA"></iframe>
        <button type="submit">Submit</button>
      </form>
    </body>
    </html>
    """


@app.post("/submit", response_class=HTMLResponse)
async def submit_form(request: Request):
    """Handle form submission, record payload, and return confirmation."""
    form_data = await request.form()
    payload = {key: str(val) for key, val in form_data.items()}
    recorded_submissions.append(payload)

    return """
    <!DOCTYPE html>
    <html>
    <head><title>Application Submitted</title></head>
    <body>
      <div id="application_confirmation">
        <h1>Thank you for applying</h1>
        <p>Your application has been submitted successfully.</p>
        <p>Application #: APP-987654</p>
      </div>
    </body>
    </html>
    """


@app.get("/confirmation", response_class=HTMLResponse)
async def confirmation_page():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Application Submitted</title></head>
    <body>
      <h1>Thank you for applying</h1>
      <p>We've received your application.</p>
    </body>
    </html>
    """
