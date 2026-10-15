"""Structural validation of a generated .lss file (the 'LSS Validator' stage)."""
from __future__ import annotations

from lxml import etree

from ..config import AppConfig
from ..validation import CODE_RE, options_problems
from .xmlutil import section_rows


def validate_lss(data: bytes, cfg: AppConfig) -> list[str]:
    """Return a list of problems found in the .lss bytes (empty list = file looks valid)."""
    try:
        root = etree.fromstring(data)
    except etree.XMLSyntaxError as exc:
        return [f"XML is not well-formed: {exc}"]

    issues: list[str] = []
    if (root.findtext("LimeSurveyDocType") or "") != "Survey":
        issues.append("LimeSurveyDocType must be 'Survey'")
    if not (root.findtext("DBVersion") or "").strip().isdigit():
        issues.append("DBVersion is missing or not a number")

    groups = section_rows(root, "groups")
    questions = section_rows(root, "questions")
    subquestions = section_rows(root, "subquestions")
    answers = section_rows(root, "answers")
    gids = {g["gid"] for g in groups}
    l10n_qids = {r["qid"] for r in section_rows(root, "question_l10ns") if r.get("question", "").strip()}
    l10n_aids = {r["aid"] for r in section_rows(root, "answer_l10ns") if r.get("answer", "").strip()}
    group_names = {r["gid"] for r in section_rows(root, "group_l10ns") if r.get("group_name", "").strip()}

    if not groups or not questions:
        issues.append("The survey has no groups or no questions")
    for gid in gids - group_names:
        issues.append(f"Group {gid} has no name")

    specs_by_code = {spec.code: spec for spec in cfg.types.values()}
    seen_codes: set[str] = set()
    for row in questions:
        code = row.get("title", "")
        if not CODE_RE.match(code):
            issues.append(f"Invalid question code '{code}'")
        if code in seen_codes:
            issues.append(f"Duplicate question code '{code}'")
        seen_codes.add(code)
        if row.get("gid") not in gids:
            issues.append(f"Question {code} points to a missing group")
        if row.get("qid") not in l10n_qids:
            issues.append(f"Question {code} has no text")
        spec = specs_by_code.get(row.get("type", ""))
        if spec is None:
            issues.append(f"Question {code} has unknown type '{row.get('type')}'")
            continue
        qid = row.get("qid")
        sub_count = sum(1 for s in subquestions if s.get("parent_qid") == qid and s.get("qid") in l10n_qids)
        ans_count = sum(1 for a in answers if a.get("qid") == qid and a.get("aid") in l10n_aids)
        for problem in options_problems(spec, [""] * ans_count if spec.needs_answers else [],
                                        [""] * sub_count if spec.needs_subquestions else []):
            issues.append(f"Question {code}: {problem}")

    top_qids = {q["qid"] for q in questions}
    for sub in subquestions:
        if sub.get("parent_qid") not in top_qids:
            issues.append(f"Sub-question {sub.get('title')} has no parent question")

    survey_rows = section_rows(root, "surveys")
    lang_rows = section_rows(root, "surveys_languagesettings")
    if not survey_rows or not survey_rows[0].get("sid"):
        issues.append("Survey settings row (sid) is missing")
    if not lang_rows or not lang_rows[0].get("surveyls_title", "").strip():
        issues.append("Survey title is empty")
    return issues
