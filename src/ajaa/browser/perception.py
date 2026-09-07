"""
src/ajaa/browser/perception.py

Form Perception & Inspection Layer (PRD §10.2 / §10.3).

Parses DOM and ARIA controls into structured FieldDescriptor and FormDescriptor
models using Python's standard library HTMLParser. Pure, deterministic inspection
with zero external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Optional


@dataclass
class FieldDescriptor:
    """Descriptor for an individual input control on a job application form."""
    field_id: str
    name: str
    label: str
    field_type: str  # text, email, tel, file, select, checkbox, radio, textarea
    required: bool = False
    options: list[str] = field(default_factory=list)
    placeholder: str = ""
    selector: str = ""
    current_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_id": self.field_id,
            "name": self.name,
            "label": self.label,
            "field_type": self.field_type,
            "required": self.required,
            "options": self.options,
            "placeholder": self.placeholder,
            "selector": self.selector,
            "current_value": self.current_value,
        }


@dataclass
class FormDescriptor:
    """Descriptor for the detected application form on the page."""
    form_id: str
    action_url: str
    fields: list[FieldDescriptor]
    submit_selector: str = "button[type='submit'], input[type='submit'], #submit_app"
    raw_snapshot: str = ""

    def get_field_by_name(self, name: str) -> Optional[FieldDescriptor]:
        name_lower = name.lower()
        for f in self.fields:
            if f.name.lower() == name_lower:
                return f
        return None

    def get_field_by_label_contains(self, query: str) -> Optional[FieldDescriptor]:
        q = query.lower()
        for f in self.fields:
            if q in f.label.lower():
                return f
        return None


class _DOMFormParser(HTMLParser):
    """Internal HTML parser extracting form structure, labels, inputs, and options."""

    def __init__(self) -> None:
        super().__init__()
        self.form_id: str = "application_form"
        self.action_url: str = ""
        self.submit_selector: str = "button[type='submit'], input[type='submit'], #submit_app"

        self.labels_by_for: dict[str, str] = {}
        self._current_label_for: str | None = None
        self._current_label_text: list[str] = []

        self._raw_inputs: list[dict[str, Any]] = []
        self._current_select: dict[str, Any] | None = None
        self._current_option_text: list[str] = []
        self._current_option_val: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}

        if tag == "form":
            if "id" in attr_dict:
                self.form_id = attr_dict["id"]
            if "action" in attr_dict:
                self.action_url = attr_dict["action"]

        elif tag == "label":
            self._current_label_for = attr_dict.get("for")
            self._current_label_text = []

        elif tag in ("input", "textarea", "select"):
            field_type = attr_dict.get("type", "text").lower() if tag == "input" else tag
            if field_type in ("submit", "button", "reset") or (tag == "input" and field_type == "submit"):
                btn_id = attr_dict.get("id")
                btn_name = attr_dict.get("name")
                if btn_id:
                    self.submit_selector = f"#{btn_id}"
                elif btn_name:
                    self.submit_selector = f"[name='{btn_name}']"
                return

            if field_type == "hidden":
                return

            elem_id = attr_dict.get("id", "")
            elem_name = attr_dict.get("name", elem_id)
            if not elem_id and not elem_name:
                return

            is_req = "required" in attr_dict or "required" in attr_dict.get("class", "").lower()
            aria_label = attr_dict.get("aria-label", "")
            placeholder = attr_dict.get("placeholder", "")

            input_data: dict[str, Any] = {
                "field_id": elem_id or elem_name,
                "name": elem_name,
                "field_type": field_type,
                "required": is_req,
                "aria_label": aria_label,
                "placeholder": placeholder,
                "options": [],
                "selector": f"#{elem_id}" if elem_id else f"[name='{elem_name}']",
            }

            self._raw_inputs.append(input_data)
            if tag == "select":
                self._current_select = input_data

        elif tag == "option" and self._current_select is not None:
            self._current_option_val = attr_dict.get("value", "")
            self._current_option_text = []

        elif tag == "button":
            btn_type = attr_dict.get("type", "submit").lower()
            if btn_type == "submit" or "submit" in attr_dict.get("id", "").lower():
                if "id" in attr_dict:
                    self.submit_selector = f"#{attr_dict['id']}"

    def handle_endtag(self, tag: str) -> None:
        if tag == "label":
            label_str = "".join(self._current_label_text).strip()
            if self._current_label_for:
                self.labels_by_for[self._current_label_for] = label_str
            self._current_label_for = None
            self._current_label_text = []

        elif tag == "option" and self._current_select is not None:
            opt_str = "".join(self._current_option_text).strip()
            if opt_str and self._current_option_val != "":
                self._current_select["options"].append(opt_str)
            self._current_option_text = []
            self._current_option_val = None

        elif tag == "select":
            self._current_select = None

    def handle_data(self, data: str) -> None:
        if self._current_label_for is not None or self._current_label_text:
            self._current_label_text.append(data)
        if self._current_select is not None and self._current_option_val is not None:
            self._current_option_text.append(data)


def parse_form_html(html_content: str) -> FormDescriptor:
    """
    Deterministically parse HTML string into a FormDescriptor without any external dependencies.
    """
    parser = _DOMFormParser()
    parser.feed(html_content)

    fields: list[FieldDescriptor] = []
    for inp in parser._raw_inputs:
        elem_id = inp["field_id"]
        # Match label from labels_by_for
        label_text = parser.labels_by_for.get(elem_id, "")
        if not label_text and inp.get("aria_label"):
            label_text = inp["aria_label"]
        if not label_text and inp.get("placeholder"):
            label_text = inp["placeholder"]
        if not label_text:
            label_text = inp["name"]

        is_req = inp["required"] or "*" in label_text

        fields.append(
            FieldDescriptor(
                field_id=elem_id,
                name=inp["name"],
                label=label_text,
                field_type=inp["field_type"],
                required=is_req,
                options=inp["options"],
                placeholder=inp["placeholder"],
                selector=inp["selector"],
            )
        )

    return FormDescriptor(
        form_id=parser.form_id,
        action_url=parser.action_url,
        fields=fields,
        submit_selector=parser.submit_selector,
    )
