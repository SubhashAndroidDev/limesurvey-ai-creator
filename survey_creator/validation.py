"""Validation and clean-up of generated question content."""
from __future__ import annotations

import re

from .config import AppConfig, QuestionTypeSpec
from .models import Question

# LimeSurvey question codes: start with a letter, then letters/digits only, max 20 characters.
CODE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]{0,19}$")
# Leading list markers a model sometimes adds: "1.", "2)", "- ", "* ", "a)".
_LEADING_MARKER_RE = re.compile(r"^\s*(?:\d+[.)]|[a-zA-Z][.)]|[-*\u2022])\s+")
_PLACEHOLDER_RE = re.compile(
    r"^(?:option|item|row|choice|answer|question|statement|category|label)\s*(?:\d+|[a-z])$",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    """Collapse whitespace and strip surrounding spaces."""
    return " ".join(str(value or "").split())


def clean_options(items: list[str], max_count: int) -> list[str]:
    """Clean a list of options: remove markers, empties and duplicates, cut to max_count."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items or []:
        text = clean_text(_LEADING_MARKER_RE.sub("", str(item or "")))
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result[:max_count] if max_count > 0 else []


def options_problems(spec: QuestionTypeSpec, answers: list[str], subquestions: list[str]) -> list[str]:
    """Validate both list sizes and content, rejecting generic model placeholders."""
    problems: list[str] = []
    if spec.needs_answers and not (spec.answers_min <= len(answers) <= spec.answers_max):
        problems.append(f"'answers' needs {spec.answers_min}-{spec.answers_max} entries, got {len(answers)}")
    if spec.needs_subquestions and not (spec.subq_min <= len(subquestions) <= spec.subq_max):
        problems.append(f"'subquestions' needs {spec.subq_min}-{spec.subq_max} entries, got {len(subquestions)}")
    for field_name, items in (("answers", answers), ("subquestions", subquestions)):
        for item in items:
            text = clean_text(item)
            if _PLACEHOLDER_RE.fullmatch(text):
                problems.append(f"{field_name} contains a generic placeholder: {text}")
    return problems


def question_problems(cfg: AppConfig, question: Question) -> list[str]:
    """Full validation of one question (used after the UI edit form and before export)."""
    problems: list[str] = []
    spec = cfg.types.get(question.type_key)
    if spec is None:
        return [f"Unknown question type '{question.type_key}'"]
    limits = cfg.defaults.get("question", {})
    text = clean_text(question.text)
    if len(text) < int(limits.get("text_min_chars", 1)):
        problems.append("Question text is too short")
    if len(text) > int(limits.get("text_max_chars", 10_000)):
        problems.append("Question text is too long")
    if not CODE_RE.match(question.code):
        problems.append(f"Invalid question code '{question.code}'")
    problems += options_problems(spec, question.answers if spec.needs_answers else [],
                                 question.subquestions if spec.needs_subquestions else [])
    return problems
