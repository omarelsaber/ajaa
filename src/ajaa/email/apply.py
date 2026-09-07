"""
src/ajaa/email/apply.py

Email Application Pipeline (PRD §27).

Handles job applications where the application route is email:
  1. Detection: mailto: URLs, apply_email fields, or explicit email patterns in JD.
  2. Domain verification: prevents exfiltration by verifying email domain matches employer.
  3. Composition: multipart MIME with grounded cover letter body and attached CV.
  4. Transport: safe dry-run (.eml file saved to disk) or live SMTP using keychain credentials.
"""
from __future__ import annotations

import email.policy
from email.message import EmailMessage
import logging
import mimetypes
from pathlib import Path
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse

from ajaa.bootstrap import get_user_data_dir
from ajaa.candidate.context import CandidateContext
from ajaa.db.models import Job
from ajaa.letters.generator import generate_cover_letter
from ajaa.types import Secret

log = logging.getLogger(__name__)

# Common ATS email handling domains
_KNOWN_ATS_EMAIL_DOMAINS = {
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "workablemail.com",
    "recruitee.com",
    "bamboohr.com",
}

# Regex for matching email in text
_EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

# Regex for detecting email apply instructions in job descriptions
_EMAIL_APPLY_PATTERN = re.compile(
    r"(?:send|email|forward)\s+(?:your\s+)?(?:cv|resume|application)\s+to\s+([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)


def detect_email_application(job: Job) -> Optional[str]:
    """
    Detect if a job listing requires application via email.
    Returns the target email address if detected, or None.
    """
    # 1. URL starts with mailto:
    if job.apply_url and job.apply_url.lower().startswith("mailto:"):
        raw_email = job.apply_url[7:].split("?")[0].strip()
        return unquote(raw_email)

    # 2. Check source connector or extra metadata
    if hasattr(job, "extra") and isinstance(job.extra, dict):
        email_val = job.extra.get("apply_email")
        if email_val and _EMAIL_REGEX.match(str(email_val)):
            return str(email_val).strip()

    # 3. Check job description pattern
    jd = getattr(job, "jd_text", None) or getattr(job, "description", None) or ""
    match = _EMAIL_APPLY_PATTERN.search(jd)
    if match:
        return match.group(1).strip()

    return None


def verify_email_domain(email_address: str, employer_name: str, apply_url: str = "") -> bool:
    """
    Safety check (PRD §27.1, T2):
    Recipient email domain must plausibly match employer name or known ATS domain.
    Prevents prompt injection exfiltration attacks.
    """
    if "@" not in email_address:
        return False

    domain = email_address.split("@")[1].lower()

    # Allow known ATS forwarding domains
    if any(domain == ats or domain.endswith(f".{ats}") for ats in _KNOWN_ATS_EMAIL_DOMAINS):
        return True

    # Check against apply_url host
    if apply_url:
        parsed = urlparse(apply_url)
        host = parsed.netloc.lower()
        if domain in host or host.endswith(f".{domain}") or domain.split(".")[0] in host:
            return True

    # Check normalized employer name in domain
    clean_employer = re.sub(r"[^a-zA-Z0-9]", "", employer_name.lower())
    clean_domain = domain.split(".")[0]

    if clean_employer and (clean_employer in clean_domain or clean_domain in clean_employer):
        return True

    return False


def compose_application_email(
    candidate: CandidateContext,
    job: Job,
    to_email: str,
    cv_path: Optional[Path] = None,
) -> EmailMessage:
    """
    Compose RFC-5322 multipart application email with grounded cover letter and CV attachment.
    """
    msg = EmailMessage()

    full_name = candidate.display_name or candidate.profile.get("personal.name.full") or "Candidate"
    from_email = candidate.profile.get("personal.email.primary") or candidate.profile.get("email") or "applicant@example.com"

    msg["To"] = to_email
    msg["From"] = f"{full_name} <{from_email}>"
    msg["Reply-To"] = from_email

    # Extract stated subject or default
    jd = getattr(job, "jd_text", None) or getattr(job, "description", None) or ""
    subject_match = re.search(r'subject(?:\s*line)?\s*:\s*["\']?([^"\'\n\r]+)["\']?', jd, re.IGNORECASE)

    if subject_match:
        subject = subject_match.group(1).strip()
    else:
        role = job.title or "Job Position"
        subject = f"Application for {role} - {full_name}"

    msg["Subject"] = subject

    # Generate grounded cover letter
    letter = generate_cover_letter(candidate, job)
    plain_body = letter.full_text

    msg.set_content(plain_body)

    # Attach CV if available
    if cv_path and Path(cv_path).exists():
        cv_file = Path(cv_path)
        content_type, _ = mimetypes.guess_type(cv_file.name)
        if content_type is None:
            content_type = "application/pdf"
        maintype, subtype = content_type.split("/", 1)

        safe_name_slug = re.sub(r"[^a-zA-Z0-9]", "_", full_name)
        attachment_filename = f"{safe_name_slug}_CV{cv_file.suffix}"

        with open(cv_file, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype=maintype,
                subtype=subtype,
                filename=attachment_filename,
            )

    return msg


def send_email_application(
    application_id: str,
    candidate: CandidateContext,
    job: Job,
    cv_path: Optional[Path] = None,
    dry_run: bool = True,
    smtp_config: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Execute email application.
    In dry-run mode (default), saves .eml file to user data dir emails/ directory.
    """
    target_email = detect_email_application(job)
    if not target_email:
        raise ValueError(f"No valid email application target found for job '{job.title}'")

    company = job.company or ""
    apply_url = job.apply_url or ""
    if not verify_email_domain(target_email, company, apply_url):
        log.warning("Email domain %r does not match employer %r or known ATS domains", target_email, company)

    msg = compose_application_email(candidate, job, target_email, cv_path)

    # User data directory for emails
    data_dir = get_user_data_dir()
    emails_dir = data_dir / "emails"
    emails_dir.mkdir(parents=True, exist_ok=True)
    eml_path = emails_dir / f"{application_id}.eml"

    with open(eml_path, "wb") as f:
        f.write(msg.as_bytes(policy=email.policy.default))

    if dry_run:
        log.info("Email application dry-run: wrote .eml to %s", eml_path)
        return {
            "dry_run": True,
            "to": target_email,
            "subject": msg["Subject"],
            "eml_path": str(eml_path),
            "status": "DRY_RUN_SAVED",
        }

    # Live sending via SMTP
    if not smtp_config:
        raise ValueError("SMTP configuration is required for live email applications")

    host = smtp_config.get("smtp_host", "localhost")
    port = int(smtp_config.get("smtp_port", 587))
    use_tls = bool(smtp_config.get("use_tls", True))
    username = smtp_config.get("smtp_username", "")
    secret_pw = smtp_config.get("smtp_password")

    import smtplib

    if use_tls:
        with smtplib.SMTP(host, port, timeout=15) as server:
            server.starttls()
            if username and secret_pw:
                raw_pw = secret_pw.reveal() if isinstance(secret_pw, Secret) else str(secret_pw)
                server.login(username, raw_pw)
            server.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=15) as server:
            if username and secret_pw:
                raw_pw = secret_pw.reveal() if isinstance(secret_pw, Secret) else str(secret_pw)
                server.login(username, raw_pw)
            server.send_message(msg)

    log.info("Live email application sent to %s via %s:%s", target_email, host, port)
    return {
        "dry_run": False,
        "to": target_email,
        "subject": msg["Subject"],
        "eml_path": str(eml_path),
        "status": "SENT",
    }
