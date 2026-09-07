"""
src/ajaa/application/connectors/generic.py

Generic ATS / Career Page Heuristic Connector (PRD §10.2).

Handles standard public career pages using universal DOM heuristics:
  - Common field names and types (name, first_name, last_name, email, phone, resume)
  - Invariant I6: Consent checkboxes are never auto-checked
  - Standard submit button detection
"""
from __future__ import annotations

import re
from typing import Any

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


class GenericConnector:
    """
    Fallback heuristic application connector for arbitrary web forms.
    """

    ats_type: str = "generic"

    def matches(self, job: Job) -> bool:
        """Fallback connector matches any job posting with an apply_url."""
        return bool(job.apply_url)

    def probe(self, page: Any) -> FormDescriptor:
        """Extract form controls from page DOM."""
        html_content = page.content()
        descriptor = parse_form_html(html_content)
        return descriptor

    def plan(
        self,
        descriptor: FormDescriptor,
        candidate_facts: dict[str, Any],
        resolved_answers: dict[str, str],
        cv_path: str | None = None,
    ) -> FillPlan:
        """
        Build heuristic FillPlan mapping candidate facts to standard form fields.
        """
        ops: list[FillOperation] = []

        full_name = str(
            candidate_facts.get("personal.name.full")
            or candidate_facts.get("full_name")
            or ""
        )
        name_parts = full_name.split(None, 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else first_name

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

        for f in descriptor.fields:
            name_lower = f.name.lower()
            label_lower = f.label.lower()

            if f.field_type == "file" or "resume" in name_lower or "cv" in name_lower or "resume" in label_lower:
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
            elif "first_name" in name_lower or "first name" in label_lower:
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
            elif "last_name" in name_lower or "last name" in label_lower:
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
            elif name_lower == "name" or "full name" in label_lower or ("name" in label_lower and "first" not in label_lower and "last" not in label_lower):
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
            elif "email" in name_lower or "email" in label_lower:
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
            elif "phone" in name_lower or "phone" in label_lower or "tel" in name_lower:
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
            elif "city" in name_lower or "city" in label_lower or "location" in name_lower:
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
                        break

        return FillPlan(operations=ops)

    def fill(self, page: Any, plan: FillPlan) -> FillReport:
        """Execute FillPlan on the live generic form."""
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
        """Click submit button on form."""
        try:
            actions.click_button(page, descriptor.submit_selector)
            return SubmitReport(clicked=True)
        except Exception as e:
            return SubmitReport(clicked=False, error=str(e))

    def verify(self, page: Any) -> Confirmation:
        """Check for confirmation indicators."""
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        current_url = page.url
        raw_content = page.content()
        content = raw_content.lower()

        is_confirmed = False
        confirmation_text = ""

        if any(w in current_url.lower() for w in ("/thanks", "/thank-you", "/confirmation", "status=submitted", "success")):
            is_confirmed = True
            confirmation_text = f"URL redirected to confirmation: {current_url}"
        elif any(
            phrase in content
            for phrase in (
                "thank you for applying",
                "your application has been received",
                "application submitted",
                "thanks for applying",
                "successfully submitted",
            )
        ):
            is_confirmed = True
            confirmation_text = "Confirmation text detected on page"

        app_id_match = re.search(r"application\s*#?:\s*([a-zA-Z0-9\-_]+)", raw_content, re.IGNORECASE)
        ats_id = app_id_match.group(1) if app_id_match else ""

        return Confirmation(
            is_confirmed=is_confirmed,
            confirmation_text=confirmation_text,
            confirmation_url=current_url,
            ats_application_id=ats_id,
        )
