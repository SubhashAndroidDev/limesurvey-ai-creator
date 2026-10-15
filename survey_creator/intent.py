"""Quick check that a request is really about creating a survey (this tool does nothing else).

Two layers keep it cheap and safe:
  1. ``check_request`` - instant, no tokens: catches obvious non-survey tasks such as
     "write a program for adding two numbers" or "write me a poem".
  2. the planner prompt also returns ``is_survey_request``; when it is false the pipeline raises
     ``NotSurveyRequest`` too.
Both raise the same friendly, user-facing message. Borderline requests that merely *mention* code or
programs as a survey topic ("survey about programming courses") are allowed through.
"""
from __future__ import annotations

import re

FRIENDLY_MESSAGE = (
    "This tool only creates surveys, so I can't help with that request. "
    "Please describe the survey you need, for example: "
    "\u201cCustomer feedback survey for a gym covering trainers, cleanliness and pricing.\u201d"
)


class NotSurveyRequest(ValueError):
    """The request is not about creating a survey. ``str(exc)`` is safe to show to the user."""

    def __init__(self, message: str = FRIENDLY_MESSAGE):
        super().__init__(message)


# Words that show the user really wants a survey / form / questions.
_SURVEY_WORDS = re.compile(
    r"\b(surveys?|questionnaires?|polls?|feedback|opinions?|satisfaction|evaluations?|census|quiz|forms?|questions?)\b",
    re.I,
)
_VERBS = (r"(?:write|create|make|generate|give|build|code|develop|draft|compose|solve|explain|translate|debug|fix|"
          r"calculate|tell|show|teach|implement)")
_THINGS = (r"(?:program|programme|code|script|function|algorithm|software|website|web\s?page|poem|poetry|song|lyrics|"
          r"story|essay|recipe|joke|email|letter|python|java|javascript|typescript|sql|html|css|math|equation|"
          r"homework|assignment|summary|article|blog)")
_TASK = re.compile(rf"\b{_VERBS}\b[^.?!\n]{{0,50}}\b{_THINGS}\b", re.I)
_INJECTION = re.compile(r"\bignore\b[^.\n]{0,30}\b(instructions?|rules?|prompts?)\b", re.I)


def check_request(text: str) -> None:
    """Raise ``NotSurveyRequest`` for clearly off-topic requests; return silently otherwise."""
    if not isinstance(text, str):
        return
    if _SURVEY_WORDS.search(text):
        return  # the user mentions a survey/form/questions: let the planner decide the rest
    if _TASK.search(text) or _INJECTION.search(text):
        raise NotSurveyRequest()