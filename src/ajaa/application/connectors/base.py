"""
src/ajaa/application/connectors/base.py

Connector Protocol & Data Structures (PRD §10.2).

Defines the contract that every ATS connector (Greenhouse, Lever, etc.) must fulfill.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from ajaa.browser.perception import FormDescriptor
from ajaa.db.models import Job


@dataclass
class FillOperation:
    """An individual atomic fill action."""
    action: str  # fill_text, select_option, upload_file, set_checkbox
    selector: str
    value: str
    field_label: str = ""
    is_required: bool = False


@dataclass
class FillPlan:
    """Ordered collection of fill operations to execute."""
    operations: list[FillOperation] = field(default_factory=list)


@dataclass
class FillReport:
    """Result of executing a FillPlan."""
    success: bool
    filled_count: int
    failed_count: int
    errors: list[str] = field(default_factory=list)
    needs_user: bool = False
    needs_user_reason: str = ""


@dataclass
class SubmitReport:
    """Result of submitting the form."""
    clicked: bool
    error: str = ""
    screenshot_path: str = ""


@dataclass
class Confirmation:
    """Outcome of submission verification."""
    is_confirmed: bool
    confirmation_text: str = ""
    confirmation_url: str = ""
    ats_application_id: str = ""


class ApplicationConnector(Protocol):
    """Protocol for an ATS-specific application connector."""

    ats_type: str

    def matches(self, job: Job) -> bool:
        """Return True if this connector handles the given job posting."""
        ...

    def probe(self, page: Any) -> FormDescriptor:
        """Inspect the current page and return a FormDescriptor."""
        ...

    def plan(
        self,
        descriptor: FormDescriptor,
        candidate_facts: dict[str, Any],
        resolved_answers: dict[str, str],
        cv_path: str | None = None,
    ) -> FillPlan:
        """Construct the FillPlan from perceived fields and resolved candidate facts."""
        ...

    def fill(self, page: Any, plan: FillPlan) -> FillReport:
        """Execute the fill plan deterministically on the page."""
        ...

    def submit(self, page: Any, descriptor: FormDescriptor) -> SubmitReport:
        """Click the submit button on the application form."""
        ...

    def verify(self, page: Any) -> Confirmation:
        """Inspect the post-submission page state to confirm application receipt."""
        ...
