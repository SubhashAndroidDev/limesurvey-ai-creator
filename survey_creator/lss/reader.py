"""Read questions out of an existing .lss file (used for few-shot examples and tests)."""
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from lxml import etree

from .xmlutil import section_rows

_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class ExampleQuestion:
    """A question read from an .lss file."""

    type_code: str
    text: str
    help: str = ""
    answers: list[str] = field(default_factory=list)
    subquestions: list[str] = field(default_factory=list)


def _plain(value: str) -> str:
    """Convert the HTML stored in .lss files to plain text."""
    return " ".join(html.unescape(_TAG_RE.sub(" ", value or "")).split())


def _order(row: dict[str, str], key: str) -> int:
    """Sort key helper: numeric order column or 0."""
    try:
        return int(row.get(key, "0") or 0)
    except ValueError:
        return 0


def read_questions(data: bytes) -> list[ExampleQuestion]:
    """Parse .lss bytes and return the top-level questions with their answers/subquestions.

    Newer files (DBVersion >= 400) keep texts in ``*_l10ns`` tables, older files keep them in
    the ``question`` / ``answer`` columns; both layouts are supported.
    """
    root = etree.fromstring(data)
    questions = section_rows(root, "questions")
    subquestions = section_rows(root, "subquestions")
    answers = section_rows(root, "answers")

    # Texts per question id (first language found wins).
    q_text: dict[str, tuple[str, str]] = {}
    for row in section_rows(root, "question_l10ns"):
        q_text.setdefault(row.get("qid", ""), (_plain(row.get("question", "")), _plain(row.get("help", ""))))
    # Texts per answer id.
    a_text: dict[str, str] = {}
    for row in section_rows(root, "answer_l10ns"):
        a_text.setdefault(row.get("aid", ""), _plain(row.get("answer", "")))

    def text_of(row: dict[str, str]) -> tuple[str, str]:
        found = q_text.get(row.get("qid", ""))
        if found:
            return found
        return _plain(row.get("question", "")), _plain(row.get("help", ""))  # old layout

    # question_order restarts inside every group, so sort by (group order, question order).
    group_order = {g.get("gid", ""): _order(g, "group_order") for g in section_rows(root, "groups")}

    def position(row: dict[str, str]) -> tuple[int, int]:
        return group_order.get(row.get("gid", ""), 0), _order(row, "question_order")

    result: list[ExampleQuestion] = []
    for row in sorted((r for r in questions if r.get("parent_qid", "0") in ("", "0")), key=position):
        qid = row.get("qid", "")
        text, help_text = text_of(row)
        subs = sorted((r for r in subquestions + questions if r.get("parent_qid", "") == qid and qid), key=lambda r: _order(r, "question_order"))
        ans = sorted((r for r in answers if r.get("qid", "") == qid), key=lambda r: _order(r, "sortorder"))
        result.append(
            ExampleQuestion(
                type_code=row.get("type", ""),
                text=text,
                help=help_text,
                answers=[a_text.get(r.get("aid", ""), "") or _plain(r.get("answer", "")) for r in ans],
                subquestions=[text_of(r)[0] for r in subs],
            )
        )
    return result
