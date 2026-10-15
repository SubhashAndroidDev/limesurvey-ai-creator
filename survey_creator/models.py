"""Plain data objects shared by the pipeline, the .lss builder and the UI.

They are intentionally simple dataclasses (not tied to any LLM library) so the survey can be
edited in the UI, validated, and exported without touching the model again.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator
from dataclasses import dataclass, field
from typing import Iterator
from uuid import uuid4
# Question statuses that are allowed into the exported .lss file.
EXPORTABLE_STATUSES = ("ok", "edited")


@dataclass
class Question:
    """One survey question inside a group."""

    code: str                      # LimeSurvey question code, e.g. "Q001"
    type_key: str                  # key from config/question_types.yaml, e.g. "single_choice"
    text: str = ""
    help: str = ""
    mandatory: str = "N"           # "Y", "N" or "S" (soft)
    answers: list[str] = field(default_factory=list)       # radio choices / array columns
    subquestions: list[str] = field(default_factory=list)  # checkbox options / array rows
    status: str = "pending"        # pending | ok | edited | failed
    error: str = ""                # human readable reason when status == "failed"
    note: str = ""                 # soft hint for the UI, e.g. "Auto-drafted - please review"

    @property
    def exportable(self) -> bool:
        """True when the question may be written to the .lss file."""
        return self.status in EXPORTABLE_STATUSES and bool(self.text.strip())


# @dataclass
# class Group:
#     """A question group (section). Every question lives inside exactly one group."""

#     name: str
#     description: str = ""
#     questions: list[Question] = field(default_factory=list)

@dataclass
class Group:
    """A question group (section). Every question lives inside exactly one group."""

    name: str
    description: str = ""
    questions: list[Question] = field(default_factory=list)
    uid: str = field(default_factory=lambda: uuid4().hex[:8])  # stable id for UI widget keys

@dataclass
class Survey:
    """The whole generated survey."""

    title: str
    description: str = ""
    welcome_text: str = ""
    end_text: str = ""
    language: str = "en"
    request: str = ""              # the original user prompt (used when regenerating a question)
    groups: list[Group] = field(default_factory=list)

    def iter_questions(self) -> Iterator[tuple[Group, Question]]:
        """Yield (group, question) pairs in survey order."""
        for group in self.groups:
            for question in group.questions:
                yield group, question

    def find_question(self, code: str) -> tuple[Group, Question] | None:
        """Return the (group, question) pair with the given code, or None."""
        for group, question in self.iter_questions():
            if question.code == code:
                return group, question
        return None

    @property
    def question_count(self) -> int:
        return sum(len(g.questions) for g in self.groups)


@dataclass
class AgentStat:
    """Progress/usage numbers shown in the 'Agent progress' panel for one pipeline stage."""

    name: str
    status: str = "pending"        # pending | running | done | warning | error
    tokens: int = 0
    ms: int = 0
    calls: int = 0
    failures: int = 0
    message: str = ""
