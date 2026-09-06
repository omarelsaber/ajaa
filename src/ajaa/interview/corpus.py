"""
src/ajaa/interview/corpus.py

Question corpus loader.

The corpus is a collection of YAML files under data/questions/.
Each file defines a group of questions — e.g. personal.yaml, skills.yaml.

Question structure:
  key:          fact_key this question covers (e.g. "personal.name.full")
  prompt:       what the UI shows to the candidate
  required:     whether this must be answered before auto-apply is enabled
  type:         text | select | multiselect | boolean | date | number
  options:      list of valid options (for select/multiselect)
  validators:   optional list of validator names
  depends_on:   list of fact_keys that must be known first
  tier:         foundation | professional | preferences | safety
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


# ── Question model ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Question:
    key: str                         # fact_key this covers
    prompt: str                      # shown to candidate
    required: bool = True
    type: str = "text"               # text | select | multiselect | boolean | date | number
    options: tuple[str, ...] = ()    # for select/multiselect
    validators: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    tier: str = "foundation"         # foundation | professional | preferences | safety
    group: str = ""                  # from filename (e.g. "personal")
    hint: str = ""                   # optional hint shown below prompt

    def is_applicable(self, known_keys: set[str]) -> bool:
        """Return True if all depends_on keys are already known."""
        return all(dep in known_keys for dep in self.depends_on)


# ── Corpus ────────────────────────────────────────────────────────────────────

@dataclass
class QuestionCorpus:
    """
    Immutable collection of all questions, indexed by fact_key.

    Built once at startup from the data/questions/ directory.
    Multiple questions may share the same key (different phrasings for
    different locales — future), but for now 1 key = 1 question.
    """
    _questions: dict[str, Question] = field(default_factory=dict)

    def get(self, key: str) -> Question | None:
        return self._questions.get(key)

    def all_required(self) -> list[Question]:
        return [q for q in self._questions.values() if q.required]

    def by_tier(self, tier: str) -> list[Question]:
        return [q for q in self._questions.values() if q.tier == tier]

    def by_group(self, group: str) -> list[Question]:
        return [q for q in self._questions.values() if q.group == group]

    def keys_required(self) -> list[str]:
        return [q.key for q in self._questions.values() if q.required]

    def __len__(self) -> int:
        return len(self._questions)

    def __contains__(self, key: str) -> bool:
        return key in self._questions


def _parse_question(raw: dict[str, Any], group: str) -> Question:
    return Question(
        key=raw["key"],
        prompt=raw["prompt"],
        required=bool(raw.get("required", True)),
        type=str(raw.get("type", "text")),
        options=tuple(raw.get("options", [])),
        validators=tuple(raw.get("validators", [])),
        depends_on=tuple(raw.get("depends_on", [])),
        tier=str(raw.get("tier", "foundation")),
        group=group,
        hint=str(raw.get("hint", "")),
    )


def load_corpus(questions_dir: Path) -> QuestionCorpus:
    """
    Load all YAML files from questions_dir into a QuestionCorpus.

    Each YAML file is a list of question dicts.
    The group name is the filename stem (e.g. personal.yaml -> "personal").
    """
    corpus = QuestionCorpus()

    if not questions_dir.exists():
        return corpus  # empty corpus — bootstrapped lazily

    yaml_files = sorted(questions_dir.glob("*.yaml"))
    for yaml_file in yaml_files:
        group = yaml_file.stem
        with yaml_file.open(encoding="utf-8") as f:
            raw_list = yaml.safe_load(f) or []
        if not isinstance(raw_list, list):
            continue
        for raw in raw_list:
            if not isinstance(raw, dict) or "key" not in raw or "prompt" not in raw:
                continue
            q = _parse_question(raw, group=group)
            corpus._questions[q.key] = q

    return corpus


_corpus_cache: QuestionCorpus | None = None


def get_corpus(questions_dir: Path | None = None) -> QuestionCorpus:
    """Return the cached corpus singleton. Pass questions_dir to force reload."""
    global _corpus_cache
    if _corpus_cache is None or questions_dir is not None:
        if questions_dir is None:
            # Default: data/questions/ relative to project root
            questions_dir = Path(__file__).parent.parent.parent.parent / "data" / "questions"
        _corpus_cache = load_corpus(questions_dir)
    return _corpus_cache


def reload_corpus(questions_dir: Path) -> QuestionCorpus:
    """Force reload. Used in tests and after corpus updates."""
    global _corpus_cache
    _corpus_cache = load_corpus(questions_dir)
    return _corpus_cache