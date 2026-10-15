"""Build a LimeSurvey .lss (XML) file from a Survey object.

Strategy: load a template .lss (``templates/blank.lss`` or the user's own export), keep its
survey-level settings, remove everything that depends on groups/questions, and write fresh
tables for groups, questions, sub-questions, answers and their texts (l10n tables).
"""
from __future__ import annotations

import html
import random
import re

from lxml import etree

from ..config import AppConfig
from ..models import Group, Question, Survey
from .xmlutil import strip_invalid_xml

# Order in which the generated sections are written into the document.
SECTION_ORDER = ["groups", "group_l10ns", "questions", "subquestions", "answers", "answer_l10ns", "question_l10ns"]

# Column lists per section. Columns that are left out fall back to the database default
# when LimeSurvey imports the file, which keeps the file valid across LimeSurvey versions.
FIELDS = {
    "groups": ["gid", "sid", "group_order", "randomization_group", "grelevance"],
    "group_l10ns": ["gid", "group_name", "description", "language"],
    "questions": ["qid", "parent_qid", "sid", "gid", "type", "title", "preg", "other", "mandatory",
                  "encrypted", "question_order", "scale_id", "same_default", "relevance", "question_theme_name"],
    "subquestions": ["qid", "parent_qid", "sid", "gid", "type", "title", "preg", "other", "mandatory",
                     "encrypted", "question_order", "scale_id", "same_default", "relevance"],
    "answers": ["aid", "qid", "code", "sortorder", "assessment_value", "scale_id"],
    "answer_l10ns": ["aid", "answer", "language"],
    "question_l10ns": ["qid", "question", "help", "script", "language"],
}


def plain_text(value: str) -> str:
    """Plain text for fields LimeSurvey shows as-is (group names, answers).

    Angle brackets are removed because these fields may be rendered as HTML by LimeSurvey.
    """
    return " ".join(strip_invalid_xml(value).replace("<", " ").replace(">", " ").split())


def html_text(value: str) -> str:
    """Convert plain text to the simple HTML LimeSurvey expects for question/help/welcome texts.

    Blank lines separate paragraphs; other line breaks become spaces. The text is HTML-escaped
    exactly once (a double escape would show a literal ``&amp;`` to respondents).
    """
    cleaned = strip_invalid_xml(value).strip()
    if not cleaned:
        return ""
    paragraphs = [p for p in re.split(r"\n\s*\n", cleaned) if p.strip()]
    return "".join(f"<p>{html.escape(' '.join(p.split()), quote=False)}</p>" for p in paragraphs)


class LssBuilder:
    """Creates .lss bytes from a Survey."""

    def __init__(self, cfg: AppConfig):
        self.cfg = cfg
        self.template_path = cfg.resolve(cfg.get("template.file", "templates/blank.lss"))
        if not self.template_path.is_file():
            raise FileNotFoundError(f"Template .lss not found: {self.template_path}")

    # ------------------------------------------------------------------ public API
    def build(self, survey: Survey, sid: int | None = None) -> bytes:
        """Return the complete .lss document as UTF-8 bytes."""
        groups = self._exportable_groups(survey)
        if not groups:
            raise ValueError("The survey has no valid question to export.")
        sid = sid or random.randint(100_000, 999_999)

        tree = etree.parse(str(self.template_path), etree.XMLParser(remove_blank_text=True))
        root = tree.getroot()
        self._purge_old_sections(root)

        tables = self._build_tables(survey, groups, sid)
        self._insert_sections(root, tables)
        self._update_template_rows(root, survey, sid)
        return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)

    # ------------------------------------------------------------------ table construction
    @staticmethod
    def _exportable_groups(survey: Survey) -> list[tuple[Group, list[Question]]]:
        """Keep only questions that are exportable and drop groups that end up empty."""
        result = []
        for group in survey.groups:
            questions = [q for q in group.questions if q.exportable]
            if questions:
                result.append((group, questions))
        return result

    def _build_tables(self, survey: Survey, groups: list[tuple[Group, list[Question]]], sid: int) -> dict[str, list[dict]]:
        """Create the row dictionaries for every generated section."""
        lang = survey.language
        sub_pattern = str(self.cfg.get("survey.subquestion_code_pattern", "SQ{index:03d}"))
        ans_pattern = str(self.cfg.get("survey.answer_code_pattern", "A{index:02d}"))
        relevance = str(self.cfg.defaults.get("question", {}).get("relevance", "1"))
        tables: dict[str, list[dict]] = {name: [] for name in SECTION_ORDER}

        # LimeSurvey replaces all ids on import, but they must be unique and consistent in the file.
        gid = qid = aid = 0
        for group_order, (group, questions) in enumerate(groups):
            gid += 1
            tables["groups"].append({"gid": gid, "sid": sid, "group_order": group_order, "randomization_group": "", "grelevance": ""})
            tables["group_l10ns"].append({"gid": gid, "group_name": plain_text(group.name), "description": html_text(group.description), "language": lang})

            for question_order, question in enumerate(questions):
                spec = self.cfg.types[question.type_key]
                qid += 1
                parent_qid = qid
                tables["questions"].append({
                    "qid": parent_qid, "parent_qid": 0, "sid": sid, "gid": gid, "type": spec.code,
                    "title": question.code, "preg": "", "other": "N", "mandatory": question.mandatory,
                    "encrypted": "N", "question_order": question_order, "scale_id": 0, "same_default": 0,
                    "relevance": relevance, "question_theme_name": spec.theme,
                })
                tables["question_l10ns"].append({"qid": parent_qid, "question": html_text(question.text),
                                                 "help": html_text(question.help), "script": "", "language": lang})

                if spec.needs_subquestions:
                    for index, text in enumerate(question.subquestions, start=1):
                        qid += 1
                        # Sub-questions are stored as questions that point to their parent.
                        tables["subquestions"].append({
                            "qid": qid, "parent_qid": parent_qid, "sid": sid, "gid": gid, "type": "T",
                            "title": sub_pattern.format(index=index), "preg": "", "other": "N", "mandatory": "",
                            "encrypted": "N", "question_order": index - 1, "scale_id": 0, "same_default": 0,
                            "relevance": relevance,
                        })
                        tables["question_l10ns"].append({"qid": qid, "question": plain_text(text), "help": "", "script": "", "language": lang})

                if spec.needs_answers:
                    for index, text in enumerate(question.answers, start=1):
                        aid += 1
                        tables["answers"].append({"aid": aid, "qid": parent_qid, "code": ans_pattern.format(index=index),
                                                  "sortorder": index, "assessment_value": 0, "scale_id": 0})
                        tables["answer_l10ns"].append({"aid": aid, "answer": plain_text(text), "language": lang})
        return tables

    # ------------------------------------------------------------------ XML manipulation
    def _purge_old_sections(self, root: etree._Element) -> None:
        """Remove template sections that would reference questions/groups which no longer exist."""
        for name in self.cfg.get("template.purge_sections", []):
            for element in root.findall(name):
                root.remove(element)

    @staticmethod
    def _insert_sections(root: etree._Element, tables: dict[str, list[dict]]) -> None:
        """Insert the generated sections right before ``<surveys>`` (or at the end)."""
        anchor = root.find("surveys")
        position = list(root).index(anchor) if anchor is not None else len(root)
        for name in SECTION_ORDER:
            rows = tables[name]
            if not rows:  # sections without data are simply left out, like LimeSurvey exports do
                continue
            section = etree.Element(name)
            fields = FIELDS[name]
            fields_el = etree.SubElement(section, "fields")
            for field_name in fields:
                etree.SubElement(fields_el, "fieldname").text = field_name
            rows_el = etree.SubElement(section, "rows")
            for row in rows:
                row_el = etree.SubElement(rows_el, "row")
                for field_name in fields:
                    cell = etree.SubElement(row_el, field_name)
                    # CDATA keeps characters like & and < intact without extra escaping.
                    cell.text = etree.CDATA(_cdata_safe(row.get(field_name, "")))
            root.insert(position, section)
            position += 1

    def _update_template_rows(self, root: etree._Element, survey: Survey, sid: int) -> None:
        """Write the survey id, language, title and texts into the template's own rows."""
        db_version = self.cfg.get("template.db_version")
        if db_version:
            version_el = root.find("DBVersion")
            if version_el is not None:
                version_el.text = str(db_version)

        languages = root.find("languages")
        if languages is not None:
            for child in list(languages):
                languages.remove(child)
            etree.SubElement(languages, "language").text = survey.language

        _set_row_values(root, "surveys", {"sid": sid, "language": survey.language, "additional_languages": ""})
        _set_row_values(root, "surveys_languagesettings", {
            "surveyls_survey_id": sid,
            "surveyls_language": survey.language,
            "surveyls_title": plain_text(survey.title),
            "surveyls_description": html_text(survey.description),
            "surveyls_welcometext": html_text(survey.welcome_text),
            "surveyls_endtext": html_text(survey.end_text),
        })


def _cdata_safe(value: object) -> str:
    """Make a value safe for a CDATA block (a CDATA section cannot contain ``]]>``)."""
    return strip_invalid_xml(str(value)).replace("]]>", "]] >")


def _set_row_values(root: etree._Element, section_name: str, values: dict[str, object]) -> None:
    """Set columns of the first row of a template section, adding missing columns when needed."""
    section = root.find(section_name)
    row = section.find("rows/row") if section is not None else None
    if section is None or row is None:
        raise ValueError(f"Template is missing a <{section_name}> row.")
    fields_el = section.find("fields")
    for name, value in values.items():
        cell = row.find(name)
        if cell is None:
            cell = etree.SubElement(row, name)
            if fields_el is not None:
                etree.SubElement(fields_el, "fieldname").text = name
        cell.text = etree.CDATA(_cdata_safe(value))
