"""JSON file storage for the survey being edited (replaces keeping it only in memory).

One file per survey: ``<project>/data/surveys/<id>.json``. Saving is atomic (temp file, then
rename) so a crash can never leave a half-written file, and nothing here ever raises into the UI.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import tempfile
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from .models import Group, Question, Survey

log = logging.getLogger("survey_creator.storage")

FORMAT_VERSION = 1
DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "surveys"
_SID = re.compile(r"^[A-Za-z0-9_-]{6,40}$")  # ids come from the URL: never allow path tricks


def new_id() -> str:
    return uuid4().hex[:12]


def valid_id(sid: object) -> bool:
    return isinstance(sid, str) and bool(_SID.match(sid))


def _path(sid: str, base: Path | None = None) -> Path:
    return (base or DATA_DIR) / f"{sid}.json"


# ---------------------------------------------------------------------------- (de)serialisation
def to_json(survey: Survey) -> str:
    """Stable text form of the survey (also used to detect whether anything changed)."""
    return json.dumps({"version": FORMAT_VERSION, "survey": asdict(survey)}, ensure_ascii=False, indent=2)


def _pick(cls: type, data: dict) -> dict:
    """Keep only the fields the dataclass knows (older/newer files stay loadable)."""
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def survey_from_dict(data: dict, known_types: set[str] | None = None) -> Survey:
    groups = []
    for g in data.get("groups", []):
        questions = []
        for q in g.get("questions", []):
            if known_types is not None and q.get("type_key") not in known_types:
                continue  # a question type that no longer exists in question_types.yaml
            questions.append(Question(**_pick(Question, q)))
        groups.append(Group(**_pick(Group, {**g, "questions": questions})))
    return Survey(**_pick(Survey, {**data, "groups": groups}))


# ---------------------------------------------------------------------------- save / load
def save(sid: str, survey: Survey, base: Path | None = None, text: str | None = None) -> bool:
    """Atomically write the survey. Returns False (and logs) instead of raising."""
    if not valid_id(sid):
        return False
    target = _path(sid, base)
    tmp_name = ""
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(text if text is not None else to_json(survey))
            tmp.flush()
            os.fsync(tmp.fileno())
        for attempt in range(3):  # Windows: antivirus/indexers may hold the file for a moment
            try:
                os.replace(tmp_name, target)
                return True
            except PermissionError:
                time.sleep(0.1 * (attempt + 1))
        raise PermissionError(f"could not replace {target}")
    except Exception:
        log.exception("could not save survey %s", sid)
        if tmp_name:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
        return False


def load(sid: str, known_types: set[str] | None = None, base: Path | None = None) -> Survey | None:
    """Read a saved survey; None when it does not exist or cannot be read."""
    if not valid_id(sid):
        return None
    path = _path(sid, base)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return survey_from_dict(payload["survey"], known_types)
    except FileNotFoundError:
        return None
    except Exception:
        log.exception("could not read saved survey %s", sid)
        return None


def cleanup(max_age_days: int = 30, base: Path | None = None) -> None:
    """Delete old survey files and leftover temp files."""
    folder = base or DATA_DIR
    if not folder.exists():
        return
    limit = time.time() - max_age_days * 86400
    for path in folder.glob("*"):
        try:
            if path.suffix in (".json", ".tmp") and path.stat().st_mtime < limit:
                path.unlink()
        except OSError:
            pass