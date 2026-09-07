"""
src/ajaa/application/connectors/ashby.py

Deterministic Ashby ATS Connector (PRD §10.2, §18.3).

Handles public Ashby job board application forms (jobs.ashbyhq.com):
  - Canonical selector mapping for standard fields (name, email, phone, resume, URLs)
  - Custom screening questions mapping using resolved candidate facts
  - Invariant I6: Consent checkboxes are never auto-checked
  - Zero LLM calls on standard fields
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ajaa.application.connectors.base import (
    Confirmation,
    FillOperation,
    FillPlan,
    FillReport,
    SubmitReport,
)
from ajaa.browser import actions
from ajaa.browser.perception import FieldDescriptor, FormDescriptor, parse_form_html
from ajaa.db.models import Job


class AshbyConnector:
    """
    Deterministic application connector for Ashby (jobs.ashbyhq.com).
    """

    ats_type: str = "ashby"

    def matches(self, job: Job) -> bool:
        """Check if job posting is hosted on or processed by Ashby."""
        if job.source_connector and "ashby" in job.source_connector.lower():
            return True
        if job.apply_url:
            host = urlparse(job.apply_url).netloc.lower()
            if "ashbyhq.com" in host:
                return True
        return False

    def probe(self, page: Any) -> FormDescriptor:
        """Extract form controls from page DOM."""
        html_content = page.content()
        descriptor = parse_form_html(html_content)
        # Ashby standard submit button selectors
        descriptor.submit_selector = (
            "button[type='submit'], "
            "button:has-text('Submit Application'), "
            "button:has-text('Submit application'), "
            "button:has-text('Submit'), "
            "input[type='submit']"
        )
        return descriptor

    def plan(
        self,
        descriptor: FormDescriptor,
        candidate_facts: dict[str, Any],
        resolved_answers: dict[str, str],
        cv_path: str | None = None,
    ) -> FillPlan:
        """
        Build deterministic FillPlan mapping candidate facts to Ashby form fields.
        """
        ops: list[FillOperation] = []

        full_name = str(
            candidate_facts.get("personal.name.full")
            or candidate_facts.get("full_name")
            or ""
        )
        first_name = str(
            candidate_facts.get("personal.name.first")
            or (full_name.split()[0] if full_name else "")
        )
        last_name = str(
            candidate_facts.get("personal.name.last")
            or (" ".join(full_name.split()[1:]) if full_name and len(full_name.split()) > 1 else "")
        )
        email = str(
            candidate_facts.get("personal.email.primary")
            or candidate_facts.get("email")
            or ""
        )
        phone = str(
            candidate_facts.get("personal.phone.primary")
            or candidate_facts.get("phone")
            or ""
        )
        linkedin = str(
            candidate_facts.get("online.linkedin")
            or candidate_facts.get("linkedin")
            or ""
        )
        github = str(
            candidate_facts.get("online.github")
            or candidate_facts.get("github")
            or ""
        )
        website = str(
            candidate_facts.get("online.portfolio")
            or candidate_facts.get("online.website")
            or ""
        )

        for f in descriptor.fields:
            name_lower = (f.name or "").lower()
            field_id_lower = (f.field_id or "").lower()
            label_lower = (f.label or "").lower()
            field_type = f.field_type.lower()

            # 1. Resume / File Upload
            if field_type == "file" or "resume" in name_lower or "resume" in field_id_lower or "cv" in name_lower:
                if cv_path:
                    ops.append(
                        FillOperation(
                            action="upload_file",
                            selector=f.selector,
                            value=cv_path,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 2. Name field(s)
            if name_lower == "name" or field_id_lower == "name" or label_lower == "name" or "full name" in label_lower:
                if full_name:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=full_name,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue
            elif "first" in name_lower or "first_name" in field_id_lower or "first name" in label_lower:
                if first_name:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=first_name,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue
            elif "last" in name_lower or "last_name" in field_id_lower or "last name" in label_lower:
                if last_name:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=last_name,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 3. Email
            if field_type == "email" or name_lower == "email" or field_id_lower == "email" or "email" in label_lower:
                if email:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=email,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 4. Phone
            if field_type == "tel" or "phone" in name_lower or "phonenumber" in field_id_lower or "phone" in label_lower:
                if phone:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=phone,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 5. Social / Portfolio Links
            if "linkedin" in name_lower or "linkedin" in label_lower:
                if linkedin:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=linkedin,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            if "github" in name_lower or "github" in label_lower:
                if github:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=github,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            if "website" in name_lower or "portfolio" in name_lower or "website" in label_lower or "portfolio" in label_lower:
                if website:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=website,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 6. Checkboxes / Consent checks (Invariant I6: NEVER AUTO-CHECK)
            if field_type == "checkbox":
                if actions.is_consent_checkbox(f.label) or actions.is_consent_checkbox(f.name):
                    ops.append(
                        FillOperation(
                            action="consent_halt",
                            selector=f.selector,
                            value="",
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )
                continue

            # 7. Check resolved answers
            matched_key = None
            for r_key in resolved_answers:
                if r_key.lower() in label_lower or r_key.lower() in name_lower:
                    matched_key = r_key
                    break

            if matched_key:
                val = resolved_answers[matched_key]
                action_type = "select_option" if field_type == "select" else "set_checkbox" if field_type == "checkbox" else "fill_text"
                ops.append(
                    FillOperation(
                        action=action_type,
                        selector=f.selector,
                        value=val,
                        field_label=f.label,
                        is_required=f.required,
                    )
                )

        return FillPlan(operations=ops)

    def fill(self, page: Any, plan: FillPlan) -> FillReport:
        """
        Execute FillPlan with Playwright.
        Enforces Invariant I6: halts immediately upon reaching consent checkboxes.
        """
        filled = 0
        failed = 0
        errors: list[str] = []

        for op in plan.operations:
            # INVARIANT I6: Never auto-check consent checkboxes
            if op.action == "consent_halt":
                return FillReport(
                    success=False,
                    filled_count=filled,
                    failed_count=failed,
                    needs_user=True,
                    needs_user_reason=f"Consent checkbox detected ({op.field_label}). Halting under Invariant I6.",
                )

            try:
                if op.action == "fill_text":
                    actions.fill_text(page, op.selector, op.value)
                    filled += 1
                elif op.action == "select_option":
                    actions.select_option(page, op.selector, op.value)
                    filled += 1
                elif op.action == "upload_file":
                    actions.upload_file(page, op.selector, op.value)
                    filled += 1
                elif op.action == "set_checkbox":
                    actions.set_checkbox(
                        page,
                        op.selector,
                        checked=(op.value.lower() in ("true", "1", "yes", "on")),
                        label_text=op.field_label,
                    )
                    filled += 1
            except actions.ConsentCheckboxHaltError as cce:
                return FillReport(
                    success=False,
                    filled_count=filled,
                    failed_count=failed,
                    needs_user=True,
                    needs_user_reason=str(cce),
                )
            except Exception as e:
                failed += 1
                errors.append(f"Failed {op.action} on {op.selector}: {e}")

        return FillReport(
            success=(failed == 0),
            filled_count=filled,
            failed_count=failed,
            errors=errors,
        )

    def submit(self, page: Any, descriptor: FormDescriptor) -> SubmitReport:
        """Click submit button on Ashby form."""
        try:
            actions.click_button(page, descriptor.submit_selector)
            return SubmitReport(clicked=True)
        except Exception as e:
            return SubmitReport(clicked=False, error=str(e))

    def verify(self, page: Any) -> Confirmation:
        """Verify post-submission confirmation."""
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        current_url = page.url
        raw_content = page.content()
        content = raw_content.lower()

        is_confirmed = False
        confirmation_text = ""

        # Success patterns
        if any(w in current_url.lower() for w in ("/thank", "/submitted", "/success", "status=submitted", "application-submitted")):
            is_confirmed = True
            confirmation_text = f"URL redirected to confirmation: {current_url}"
        elif any(phrase in content for phrase in (
            "thank you for applying",
            "your application has been submitted",
            "we've received your application",
            "we have received your application",
            "thanks for applying",
            "application submitted",
        )):
            is_confirmed = True
            confirmation_text = "Confirmation text detected on page"
        elif page.locator("div:has-text('Application Submitted'), div:has-text('Thank you for applying')").count() > 0:
            is_confirmed = True
            confirmation_text = "Ashby confirmation element detected"

        app_id_match = re.search(r"application\s*#?:\s*([a-zA-Z0-9\-_]+)", raw_content, re.IGNORECASE)
        ats_id = app_id_match.group(1) if app_id_match else ""

        return Confirmation(
            is_confirmed=is_confirmed,
            confirmation_text=confirmation_text,
            confirmation_url=current_url,
            ats_application_id=ats_id,
        )
