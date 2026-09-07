"""
src/ajaa/llm/injection.py

Prompt injection defense: prefilter patterns & detection (PRD §23.6, §33.6).

Detects injection payloads in untrusted job descriptions, instructions,
or form inputs before they reach LLM channels or matching engines.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Tuple

# PRD §23.6 INJECTION_PATTERNS + extensions for homoglyphs, exfiltration, and multilingual payloads
INJECTION_PATTERNS: list[str] = [
    # Core PRD §23.6 patterns
    r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above)\s+instructions",
    r"disregard\s+.{0,25}(instructions|prompt|rules)",
    r"you\s+are\s+(now\s+|actually\s+)?(a|an|in\s+developer\s+mode)",
    r"system\s*(?:prompt|message|note)?\s*[:=]",
    r"instruction\s*override\s*[:=]",
    r"system\s*override\s*[:=]",
    r"\[\s*system\s*:",
    r"</?(?:system|assistant|user|hidden_instruction|injected_instruction)>",
    r"\bAPI[_ ]?key\b|\bpassword\b|\bcredential",
    r"(?:send|email|post|upload)\s+.{0,40}(?:to|at)\s+https?://",
    r"do\s+not\s+(?:tell|inform|mention\s+to)\s+the\s+(?:user|candidate|human)",
    r"<\|.*?\|>",  # Chat template delimiters
    
    # Exfiltration / PII targeting
    r"data\s+exfiltration",
    r"fill\s+.{0,40}field\s+with\s+.{0,40}(?:email|ssn|social\s+security|password|contact|user\s+data)",
    r"output\s+.{0,40}(?:contact\s+details|pii|password|email).{0,40}field",
    r"add\s+\d+\s+to\s+the\s+candidate",
    r"checkbox\s+.{0,40}checked\s+automatically",
    
    # Multilingual (Arabic) instruction overrides
    r"تجاهل\s+(?:جميع\s+|كل\s+)?التعليمات(?:\s+السابقة|\s+الأولى)?",
    r"(?:أرسل|إرسال|اطبع)\s+.{0,30}(?:بيانات|معلومات)\s+.{0,30}(?:المتقدم|المستخدم)",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def detect_injection(text: str | None) -> Tuple[bool, str | None]:
    """
    Deterministic pre-filter over untrusted text (PRD §23.6 Layer 6).

    Checks for:
      1. Unicode normalization (NFKD) to catch homoglyphs/full-width chars
      2. Hidden HTML comments (<!-- ... -->)
      3. Hidden CSS styling (display:none, visibility:hidden, font-size:0)
      4. Known prompt injection phrases & role override signatures

    Returns:
      (is_suspected, matching_reason)
    """
    if not text:
        return False, None

    # Step 1: Normalize unicode to strip fullwidth/homoglyph obfuscation
    normalized = unicodedata.normalize("NFKD", text)

    # Step 2: Check hidden HTML comments
    html_comments = re.findall(r"<!--(.*?)-->", normalized, re.DOTALL)
    for comment in html_comments:
        for pat in _COMPILED_PATTERNS:
            m = pat.search(comment)
            if m:
                return True, f"Hidden HTML comment matched injection pattern: {m.group(0)}"

    # Step 3: Check hidden CSS elements
    hidden_divs = re.findall(
        r'<[^>]+style=["\'][^"\']*(?:display:\s*none|visibility:\s*hidden|font-size:\s*0)[^"\']*["\'][^>]*>([\s\S]*?)<\/[^>]+>',
        normalized,
        re.IGNORECASE,
    )
    for hidden_content in hidden_divs:
        for pat in _COMPILED_PATTERNS:
            m = pat.search(hidden_content)
            if m:
                return True, f"Hidden CSS text matched injection pattern: {m.group(0)}"

    # Step 4: Scan normalized full text
    for pat in _COMPILED_PATTERNS:
        m = pat.search(normalized)
        if m:
            return True, f"Matched injection pattern: {m.group(0)}"

    return False, None
