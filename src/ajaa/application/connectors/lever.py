"""
src/ajaa/application/connectors/lever.py

Deterministic Lever ATS Connector (PRD §10.2).

Handles public Lever job board application forms:
  - Canonical selector mapping for standard fields (name, email, phone, org, resume, location, URLs)
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


class LeverConnector:
    """
    Deterministic application connector for Lever.co.
    """

    ats_type: str = "lever"

    def matches(self, job: Job) -> bool:
        """Check if job posting is hosted on or processed by Lever."""
        if job.source_connector and "lever" in job.source_connector.lower():
            return True
        if job.apply_url:
            host = urlparse(job.apply_url).netloc.lower()
            if "lever.co" in host:
                return True
        return False

    def probe(self, page: Any) -> FormDescriptor:
        """Extract form controls from page DOM."""
        html_content = page.content()
        descriptor = parse_form_html(html_content)
        # Lever standard submit button selectors
        descriptor.submit_selector = (
            "#btn-submit, button[data-qa='btn-submit'], .template-btn-submit, button[type='submit']"
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
        Build deterministic FillPlan mapping candidate facts to Lever form fields.
        """
        ops: list[FillOperation] = []

        full_name = str(
            candidate_facts.get("personal.name.full")
            or candidate_facts.get("full_name")
            or ""
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
        city = str(
            candidate_facts.get("location.city")
            or candidate_facts.get("city")
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
        portfolio = str(
            candidate_facts.get("online.portfolio")
            or candidate_facts.get("portfolio")
            or github
            or ""
        )

        org = str(
            candidate_facts.get("experience.current_company")
            or candidate_facts.get("employer")
            or ""
        )
        if not org and isinstance(candidate_facts.get("experience"), list):
            exps = candidate_facts.get("experience")
            if exps and isinstance(exps[0], dict):
                org = exps[0].get("employer") or ""

        for f in descriptor.fields:
            name_lower = f.name.lower()
            label_lower = f.label.lower()

            # 1. Resume / CV File Upload
            if f.field_type == "file" or name_lower == "resume" or "resume" in label_lower:
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

            # 2. Full Name
            elif name_lower == "name" or f.field_id == "name" or "full name" in label_lower:
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

            # 3. Email
            elif name_lower == "email" or "email" in label_lower:
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

            # 4. Phone
            elif name_lower == "phone" or "phone" in label_lower or "mobile" in label_lower:
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

            # 5. Current Company / Org
            elif name_lower == "org" or "current company" in label_lower or "organization" in label_lower:
                if org:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=org,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )

            # 6. Location
            elif name_lower == "location" or f.field_id == "location-input" or "location" in label_lower:
                if city:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=city,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )

            # 7. LinkedIn
            elif "linkedin" in name_lower or "linkedin" in label_lower:
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

            # 8. GitHub
            elif "github" in name_lower or "github" in label_lower:
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

            # 9. Portfolio / Website / Other URL
            elif "portfolio" in name_lower or "portfolio" in label_lower or "website" in name_lower or "other" in name_lower:
                if portfolio:
                    ops.append(
                        FillOperation(
                            action="fill_text",
                            selector=f.selector,
                            value=portfolio,
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )

            # 10. Checkboxes / Consent checks (Invariant I6)
            elif f.field_type == "checkbox":
                if actions.is_consent_checkbox(f.label):
                    ops.append(
                        FillOperation(
                            action="consent_halt",
                            selector=f.selector,
                            value="",
                            field_label=f.label,
                            is_required=f.required,
                        )
                    )

            # 11. Custom questions mapped via resolved_answers
            else:
                for q_key, ans_val in resolved_answers.items():
                    if q_key.lower() in label_lower or label_lower in q_key.lower():
                        if f.field_type == "select":
                            ops.append(
                                FillOperation(
                                    action="select_option",
                                    selector=f.selector,
                                    value=ans_val,
                                    field_label=f.label,
                                    is_required=f.required,
                                )
                            )
                        elif f.field_type in ("text", "textarea"):
                            ops.append(
                                FillOperation(
                                    action="fill_text",
                                    selector=f.selector,
                                    value=ans_val,
                                    field_label=f.label,
                                    is_required=f.required,
                                )
                            )
                        elif f.field_type == "checkbox":
                            ops.append(
                                FillOperation(
                                    action="set_checkbox",
                                    selector=f.selector,
                                    value=ans_val,
                                    field_label=f.label,
                                    is_required=f.required,
                                )
                            )
                        break

        return FillPlan(operations=ops)

    def fill(self, page: Any, plan: FillPlan) -> FillReport:
        """Execute FillPlan on the live Lever form."""
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
        """Click submit button on Lever form."""
        try:
            actions.click_button(page, descriptor.submit_selector)
            return SubmitReport(clicked=True)
        except Exception as e:
            return SubmitReport(clicked=False, error=str(e))

    def verify(self, page: Any) -> Confirmation:
        """Check for Lever confirmation patterns."""
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        current_url = page.url
        raw_content = page.content()
        content = raw_content.lower()

        is_confirmed = False
        confirmation_text = ""

        # Check URL patterns
        if any(w in current_url.lower() for w in ("/thanks", "/thank-you", "/confirmation", "status=submitted")):
            is_confirmed = True
            confirmation_text = f"URL redirected to confirmation: {current_url}"

        # Check page text patterns
        elif any(
            phrase in content
            for phrase in (
                "thank you for applying",
                "your application has been received",
                "application submitted",
                "thanks for applying",
                "we have received your application",
            )
        ):
            is_confirmed = True
            confirmation_text = "Confirmation text detected on page"

        # Check for Lever confirmation element
        elif page.locator(".application-confirmation, .thank-you-page, [data-qa='thank-you']").count() > 0:
            is_confirmed = True
            confirmation_text = "Lever confirmation container detected"

        app_id_match = re.search(r"application\s*#?:\s*([a-zA-Z0-9\-_]+)", raw_content, re.IGNORECASE)
        ats_id = app_id_match.group(1) if app_id_match else ""

        return Confirmation(
            is_confirmed=is_confirmed,
            confirmation_text=confirmation_text,
            confirmation_url=current_url,
            ats_application_id=ats_id,
        )
