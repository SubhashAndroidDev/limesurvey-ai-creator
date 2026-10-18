#!/usr/bin/env python3
"""Sanity-check a LimeSurvey .lss file. Standard library only.

Usage: python check_lss.py survey.lss [--expected N]
Exit code 0 = no errors, 1 = errors found.
"""
import re
import sys
import xml.etree.ElementTree as ET

PLACEHOLDER = re.compile(
    r"^\s*(option|item|row|choice|answer|opsi|opcion)\s*[a-z0-9]{1,3}\s*$", re.I
)
CHOICE_TYPES = {"L", "M", "F", "!", "O", "P", "Q"}  # types that need answers or subquestions
NEEDS_ANSWERS = {"L", "F", "!"}
NEEDS_SUBQ = {"M", "Q", "F"}


def rows(root, section):
    out = []
    for row in root.findall(f"{section}/rows/row"):
        out.append({c.tag: (c.text or "").strip() for c in row})
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    expected = None
    if "--expected" in sys.argv:
        expected = int(sys.argv[sys.argv.index("--expected") + 1])
        args = [a for a in args if a != str(expected)]
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: not well-formed XML: {exc}")
        return 1

    groups = rows(root, "groups")
    questions = [q for q in rows(root, "questions") if q.get("parent_qid", "0") in ("0", "")]
    subq = rows(root, "subquestions")
    answers = rows(root, "answers")
    q_l10n = rows(root, "question_l10ns")
    a_l10n = rows(root, "answer_l10ns")

    text_by_qid = {r.get("qid"): r.get("question", "") for r in q_l10n}
    answers_by_qid = {}
    for a in answers:
        answers_by_qid.setdefault(a.get("qid"), []).append(a)
    subq_by_parent = {}
    for s in subq:
        subq_by_parent.setdefault(s.get("parent_qid"), []).append(s)

    errors, warns = [], []
    print(f"groups: {len(groups)} | questions: {len(questions)} | "
          f"subquestions: {len(subq)} | answers: {len(answers)}")

    if not questions:
        errors.append("no questions found")
    if expected is not None and len(questions) < expected:
        warns.append(f"requested {expected} questions, file has {len(questions)}")

    seen = {}
    for q in questions:
        qid, code, qtype = q.get("qid"), q.get("title", "?"), q.get("type", "?")
        text = re.sub(r"<[^>]+>", "", text_by_qid.get(qid, "")).strip()
        if not text:
            errors.append(f"{code}: empty question text")
        key = text.lower()
        if key and key in seen:
            warns.append(f"{code}: same text as {seen[key]}")
        seen[key] = code
        if qtype in NEEDS_ANSWERS and len(answers_by_qid.get(qid, [])) < 2 and qtype != "F":
            errors.append(f"{code} (type {qtype}): fewer than 2 answers")
        if qtype in {"M", "Q", "F"} and len(subq_by_parent.get(qid, [])) < 2:
            errors.append(f"{code} (type {qtype}): fewer than 2 subquestions")

    for a in a_l10n:
        if PLACEHOLDER.match(a.get("answer", "")):
            warns.append(f"placeholder answer text: {a.get('answer')!r}")
    for s in q_l10n:
        if PLACEHOLDER.match(re.sub(r"<[^>]+>", "", s.get("question", ""))):
            warns.append(f"placeholder question/label: {s.get('question')!r}")

    for w in warns:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:", e)
    print("RESULT:", "FAIL" if errors else "OK")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
