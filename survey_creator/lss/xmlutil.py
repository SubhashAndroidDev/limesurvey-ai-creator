"""Small helpers for the table-like XML layout used by .lss files."""
from __future__ import annotations

import re
from lxml import etree

# Characters that are illegal in XML 1.0 (control chars except tab, newline, carriage return).
_INVALID_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]")


def section_rows(root: etree._Element, name: str) -> list[dict[str, str]]:
    """Return the rows of a section (``<name><rows><row>...``) as a list of dicts.

    The values are read by tag name, so the optional ``<fields>`` list is not needed and files
    from different LimeSurvey versions (different columns) are handled the same way.
    """
    section = root.find(name)
    if section is None:
        return []
    rows = section.find("rows")
    if rows is None:
        return []
    return [{child.tag: (child.text or "") for child in row} for row in rows.findall("row")]


def strip_invalid_xml(text: str) -> str:
    """Remove characters that would make the XML document invalid."""
    return _INVALID_XML_CHARS.sub("", str(text))
