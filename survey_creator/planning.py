"""Pure planning logic: how many groups, how many questions per group, skeleton creation."""
from __future__ import annotations

import math

from .config import AppConfig
from .models import Group, Question, Survey
from .schemas import SurveyPlan


def parse_per_group(value: int | str | None, cfg: AppConfig) -> int | str:
    """Normalise the 'questions per group' setting to a positive int or the string 'auto'."""
    if value is None:
        value = cfg.get("survey.questions_per_group", 1)
    if isinstance(value, str):
        value = value.strip().lower()
        if value == "auto":
            return "auto"
        value = int(value)
    if int(value) < 1:
        raise ValueError("questions_per_group must be 1 or higher, or 'auto'.")
    return int(value)


def group_sizes(total: int, per_group: int | str, auto_size: int = 4) -> list[int]:
    """Split ``total`` questions into groups and return the number of questions of each group.

    * integer k -> ceil(total / k) groups
    * "auto"    -> round(total / auto_size) groups (at least one)
    The questions are spread as evenly as possible (e.g. 10 questions in 3 groups -> 4, 3, 3).
    """
    if total < 1:
        raise ValueError("The survey needs at least one question.")
    if per_group == "auto":
        groups = max(1, round(total / max(auto_size, 1)))
    else:
        groups = math.ceil(total / int(per_group))
    groups = min(groups, total)
    base, extra = divmod(total, groups)
    return [base + 1 if i < extra else base for i in range(groups)]


def build_skeleton(cfg: AppConfig, plan: SurveyPlan, sizes: list[int], type_keys: list[str], language: str, request: str) -> Survey:
    """Create the Survey object with empty, typed questions from the plan and the type assignment."""
    code_pattern = str(cfg.get("survey.question_code_pattern", "Q{index:03d}"))
    survey = Survey(
        title=plan.title.strip(),
        description=plan.description.strip(),
        welcome_text=plan.welcome_text.strip(),
        end_text=plan.end_text.strip(),
        language=language,
        request=request,
    )
    cursor = 0
    for group_plan, size in zip(plan.groups, sizes):
        group = Group(name=group_plan.name.strip(), description=group_plan.description.strip())
        for _ in range(size):
            type_key = type_keys[cursor]
            group.questions.append(
                Question(
                    code=code_pattern.format(index=cursor + 1),
                    type_key=type_key,
                    mandatory=cfg.mandatory_for(type_key),
                )
            )
            cursor += 1
        survey.groups.append(group)
    return survey
