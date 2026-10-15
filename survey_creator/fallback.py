"""Safe, offline drafts used only when the model cannot deliver after several tries.

The user never sees an error: a plain but valid question is created from the group topic and the
question type, and is flagged "auto-drafted" so the preview can invite the user to review it.
"""
from __future__ import annotations

from .config import AppConfig, QuestionTypeSpec
from .models import Group, Question, Survey
from .schemas import GroupPlan, SurveyPlan

NOTE_AUTO = "Auto-drafted - please review"

_SCALE_QUALITY = ["Very poor", "Poor", "Neutral", "Good", "Very good"]
_SCALE_AGREE = ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]


def fallback_plan(cfg: AppConfig, request: str, group_count: int) -> SurveyPlan:
    """Minimal plan when the planner fails: title from the request, numbered sections."""
    title = " ".join(request.split())[:70].rstrip(" .,:;") or "Survey"
    pattern = str(cfg.get("survey.fallback_group_name", "Section {index}"))
    return SurveyPlan(
        title=title[:1].upper() + title[1:],
        description=f"Survey based on the request: {' '.join(request.split())[:160]}",
        welcome_text="Thank you for taking part. Your answers help us improve and are kept confidential.",
        end_text="Thank you for your time and feedback.",
        groups=[GroupPlan(name=pattern.format(index=i + 1)) for i in range(group_count)],
    )


def _fit(items: list[str], low: int, high: int) -> list[str]:
    items = items[:high] if high else items
    while len(items) < low:
        items.append(f"Option {len(items) + 1}")
    return items


def apply_fallback(survey: Survey, group: Group, question: Question, spec: QuestionTypeSpec) -> None:
    """Fill ``question`` with a generic but valid draft that fits its type."""
    topic = group.name.strip().rstrip(".") or survey.title or "this topic"
    topic_l = topic[:1].lower() + topic[1:]
    code = spec.code
    answers: list[str] = []
    subs: list[str] = []

    if code == "L":
        text = f"How would you rate your overall experience with {topic_l}?"
        answers = list(_SCALE_QUALITY)
    elif code == "M":
        text = f"Which aspects of {topic_l} matter most to you? Select all that apply."
        subs = ["Quality", "Ease of use", "Communication", "Value", "Reliability"]
    elif code == "S":
        text = f"In a few words, what is your main comment about {topic_l}?"
    elif code == "T":
        text = f"Please describe your experience with {topic_l} in your own words."
    elif code == "Y":
        text = f"Are you satisfied with {topic_l}?"
    elif code == "Q":
        text = f"Please list up to three points you would like to share about {topic_l}."
        subs = ["First point", "Second point", "Third point"]
    elif code == "F":
        text = f"Please rate the following statements about {topic_l}."
        subs = ["Overall quality", "Clarity of information", "Responsiveness"]
        answers = list(_SCALE_AGREE)
    else:  # a type added later in question_types.yaml
        text = f"Please share your feedback about {topic_l}."
        answers = [f"Option {i}" for i in range(1, 4)]

    question.text = text
    question.help = ""
    question.answers = _fit(answers, spec.answers_min, spec.answers_max) if spec.needs_answers else []
    question.subquestions = _fit(subs, spec.subq_min, spec.subq_max) if spec.needs_subquestions else []
    question.status, question.error, question.note = "ok", "", NOTE_AUTO
