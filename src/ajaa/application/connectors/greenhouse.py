"""
src/ajaa/application/connectors/greenhouse.py

Deterministic Greenhouse ATS Connector (PRD §10.2).

Handles public Greenhouse job board application forms:
  - Canonical selector mapping for standard fields (first_name, last_name, email, phone, resume)
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
from ajaa.browser.perception import FormDescriptor, parse_form_html
from ajaa.db.models import Job


class GreenhouseConnector:
    """
    Deterministic application connector for Greenhouse.io.
    """

    ats_type: str = "greenhouse"

    def matches(self, job: Job) -> bool:
        """Check if job posting is hosted on or processed by Greenhouse."""
        if job.source_connector and "greenhouse" in job.source_connector.lower():
            return True
        if job.apply_url:
            host = urlparse(job.apply_url).netloc.lower()
            if "greenhouse.io" in host:
                return True
        return False

    def probe(self, page: Any) -> FormDescriptor:
        """Extract form controls from page DOM."""
        html_content = page.content()
        descriptor = parse_form_html(html_content)
        # Greenhouse standard submit button selector
        descriptor.submit_selector = "#submit_app, input[type='submit'][value*='Submit'], button[type='submit']"
        return descriptor

    def plan(
        self,
        descriptor: FormDescriptor,
        candidate_facts: dict[str, Any],
        resolved_answers: dict[str, str],
        cv_path: str | None = None,
    ) -> FillPlan:
        """
        Build deterministic FillPlan mapping candidate facts to Greenhouse form fields.
        """
        ops: list[FillOperation] = []

        # Extract candidate name components
        full_name = str(candidate_facts.get("personal.name.full") or candidate_facts.get("full_name") or "")
        name_parts = full_name.split(None, 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else first_name

        email = str(candidate_facts.get("personal.email.primary") or candidate_facts.get("email") or "")
        phone = str(candidate_facts.get("personal.phone.primary") or candidate_facts.get("phone") or "")
        city = str(candidate_facts.get("location.city") or candidate_facts.get("city") or "")
        linkedin = str(candidate_facts.get("online.linkedin") or candidate_facts.get("linkedin") or "")
        github = str(candidate_facts.get("online.github") or candidate_facts.get("github") or "")

        for f in descriptor.fields:
            name_lower = f.name.lower()
            label_lower = f.label.lower()

            # 1. First Name
            if "first_name" in name_lower or "first name" in label_lower or f.field_id == "first_name":
                if first_name:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=first_name, field_label=f.label, is_required=f.required))

            # 2. Last Name
            elif "last_name" in name_lower or "last name" in label_lower or f.field_id == "last_name":
                if last_name:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=last_name, field_label=f.label, is_required=f.required))

            # 3. Full Name (if Greenhouse uses single name field)
            elif "name" in name_lower and "first" not in name_lower and "last" not in name_lower and ("name" in label_lower or "full" in label_lower):
                if full_name:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=full_name, field_label=f.label, is_required=f.required))

            # 4. Email
            elif "email" in name_lower or "email" in label_lower:
                if email:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=email, field_label=f.label, is_required=f.required))

            # 5. Phone
            elif "phone" in name_lower or "phone" in label_lower or "mobile" in label_lower:
                if phone:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=phone, field_label=f.label, is_required=f.required))

            # 6. Resume / CV File Upload
            elif f.field_type == "file" or "resume" in name_lower or "cv" in name_lower or "resume" in label_lower:
                if cv_path:
                    ops.append(FillOperation(action="upload_file", selector=f.selector, value=cv_path, field_label=f.label, is_required=f.required))

            # 7. LinkedIn
            elif "linkedin" in name_lower or "linkedin" in label_lower:
                if linkedin:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=linkedin, field_label=f.label, is_required=f.required))

            # 8. GitHub / Website / Portfolio
            elif "github" in name_lower or "github" in label_lower:
                if github:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=github, field_label=f.label, is_required=f.required))
            elif "website" in name_lower or "portfolio" in label_lower or "website" in label_lower:
                portfolio = str(candidate_facts.get("online.portfolio") or github or "")
                if portfolio:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=portfolio, field_label=f.label, is_required=f.required))

            # 9. City / Location
            elif "location" in name_lower or "city" in label_lower:
                if city:
                    ops.append(FillOperation(action="fill_text", selector=f.selector, value=city, field_label=f.label, is_required=f.required))

            # 10. Checkboxes / Consent checks (Invariant I6 check)
            elif f.field_type == "checkbox":
                if actions.is_consent_checkbox(f.label):
                    # Flag as requiring user action (refuse auto-checking)
                    ops.append(FillOperation(action="consent_halt", selector=f.selector, value="", field_label=f.label, is_required=f.required))

            # 11. Custom questions mapped via resolved_answers
            else:
                for q_key, ans_val in resolved_answers.items():
                    if q_key.lower() in label_lower or label_lower in q_key.lower():
                        if f.field_type == "select":
                            ops.append(FillOperation(action="select_option", selector=f.selector, value=ans_val, field_label=f.label, is_required=f.required))
                        elif f.field_type in ("text", "textarea"):
                            ops.append(FillOperation(action="fill_text", selector=f.selector, value=ans_val, field_label=f.label, is_required=f.required))
                        break

        return FillPlan(operations=ops)

    def fill(self, page: Any, plan: FillPlan) -> FillReport:
        """Execute FillPlan on the live Greenhouse form."""
        filled = 0
        failed = 0
        errors: list[str] = []

        for op in plan.operations:
            try:
                if op.action == "consent_halt":
                    return FillReport(
                        success=False,
                        filled_count=filled,
                        failed_count=failed,
                        needs_user=True,
                        needs_user_reason=f"Consent checkbox detected: '{op.field_label}' (Invariant I6)",
                    )
                elif op.action == "fill_text":
                    actions.fill_text(page, op.selector, op.value)
                    filled += 1
                elif op.action == "select_option":
                    actions.select_option(page, op.selector, op.value)
                    filled += 1
                elif op.action == "upload_file":
                    actions.upload_file(page, op.selector, op.value)
                    filled += 1
                elif op.action == "set_checkbox":
                    actions.set_checkbox(page, op.selector, checked=True, label_text=op.field_label)
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
        """Click submit button on Greenhouse form."""
        try:
            actions.click_button(page, descriptor.submit_selector)
            return SubmitReport(clicked=True)
        except Exception as e:
            return SubmitReport(clicked=False, error=str(e))

    def verify(self, page: Any) -> Confirmation:
        """Check for Greenhouse confirmation patterns."""
        try:
            # Wait for network idle or URL change
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        current_url = page.url
        raw_content = page.content()
        content = raw_content.lower()

        is_confirmed = False
        confirmation_text = ""

        # Check URL patterns
        if any(w in current_url.lower() for w in ("/confirmation", "/thank_you", "status=submitted")):
            is_confirmed = True
            confirmation_text = f"URL redirected to confirmation: {current_url}"

        # Check page text patterns
        elif any(phrase in content for phrase in (
            "thank you for applying",
            "your application has been submitted",
            "application received",
            "thanks for applying",
        )):
            is_confirmed = True
            confirmation_text = "Confirmation text detected on page"

        # Check for Greenhouse confirmation heading
        elif page.locator("#application_confirmation, .application-confirmation").count() > 0:
            is_confirmed = True
            confirmation_text = "Greenhouse confirmation container detected"

        # Try to extract application ID if present (preserve original case)
        app_id_match = re.search(r"application\s*#?:\s*([a-zA-Z0-9\-_]+)", raw_content, re.IGNORECASE)
        ats_id = app_id_match.group(1) if app_id_match else ""

        return Confirmation(
            is_confirmed=is_confirmed,
            confirmation_text=confirmation_text,
            confirmation_url=current_url,
            ats_application_id=ats_id,
        )
