"""The three LLM agents: Survey Planner, Question Generator and Answer Options.

Each function builds a prompt from config/prompts, calls the model with retry, validates the
answer in plain Python and returns an ``AgentOutcome`` with the usage numbers.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .config import AppConfig, QuestionTypeSpec
from .fallback import fallback_plan
from .llm import FatalLLMError, GenerationError, LLMClient, generate_with_retry
from .models import Group, Question, Survey
from .prompts import render_prompt
from .schemas import GroupPlan, OptionsDraft, QuestionDraft, SurveyPlan
from .validation import clean_options, clean_text, options_problems
from .intent import NotSurveyRequest

@dataclass
class AgentOutcome:
    """Value produced by an agent plus its resource usage."""

    value: Any
    tokens: int
    ms: int


# ---------------------------------------------------------------------------- planner
def run_planner(client: LLMClient, cfg: AppConfig, request: str, group_count: int, language_name: str) -> AgentOutcome:
    """Ask the model for title, welcome/end text and exactly ``group_count`` groups."""
    prompt = render_prompt(cfg, "planner", request=request, group_count=group_count, language_name=language_name)

    def check(plan: SurveyPlan) -> list[str]:
        if not plan.is_survey_request:
            return []  # not a survey request: nothing else to validate, it is handled below
        problems = []
        if not clean_text(plan.title):
            problems.append("title is empty")
        if len(plan.groups) != group_count:
            problems.append(f"expected exactly {group_count} groups but got {len(plan.groups)}")
        if any(not clean_text(g.name) for g in plan.groups):
            problems.append("every group needs a name")
        return problems

    tokens = ms = 0
    try:
        outcome = generate_with_retry(client, prompt, SurveyPlan, check, int(cfg.get("llm.max_retries", 2)))
        plan, tokens, ms = outcome.value, outcome.tokens, outcome.ms
    except FatalLLMError:
        raise
    except GenerationError as exc:
        # A plan with a usable title but the wrong group count can still be repaired in code;
        # otherwise fall back to a minimal plan so generation can continue.
        last = exc.last_parsed
        tokens, ms = exc.tokens, exc.ms
        if last is not None and last.is_survey_request is False:
            raise NotSurveyRequest()
        plan = last if last is not None and clean_text(getattr(last, "title", "")) else fallback_plan(cfg, request, group_count)
    except Exception:
        plan = fallback_plan(cfg, request, group_count)

    if not plan.is_survey_request:
        raise NotSurveyRequest()  # the model says this is not a survey request -> friendly message in the UI
    return AgentOutcome(repair_plan(cfg, plan, group_count), tokens, ms)


def repair_plan(cfg: AppConfig, plan: SurveyPlan, group_count: int) -> SurveyPlan:
    """Force the plan to have exactly ``group_count`` groups with non-empty names.

    Extra groups are dropped; missing groups are filled with the fallback name from settings.
    """
    pattern = str(cfg.get("survey.fallback_group_name", "Section {index}"))
    groups = [g for g in plan.groups if clean_text(g.name)][:group_count]
    while len(groups) < group_count:
        groups.append(GroupPlan(name=pattern.format(index=len(groups) + 1), description=""))
    return SurveyPlan(title=clean_text(plan.title), description=plan.description, welcome_text=plan.welcome_text,
                      end_text=plan.end_text, groups=groups)


# ---------------------------------------------------------------------------- question text
def run_question_writer(client: LLMClient, cfg: AppConfig, survey: Survey, group: Group, question: Question,
                        spec: QuestionTypeSpec, examples_text: str) -> AgentOutcome:
    """Generate the text (and optional help text) of one question."""
    limits = cfg.defaults.get("question", {})
    min_chars = int(limits.get("text_min_chars", 1))
    max_chars = int(limits.get("text_max_chars", 10_000))

    # Show the model the most recent finished questions so it does not repeat itself.
    recent = int(cfg.get("survey.recent_questions_in_context", 12))
    earlier = [q.text for _, q in survey.iter_questions() if q is not question and q.exportable][-recent:]
    earlier_text = "\n".join(f"- {t}" for t in earlier) or str(cfg.get("prompts.no_earlier_questions", ""))
    index = [q for _, q in survey.iter_questions()].index(question) + 1

    prompt = render_prompt(
        cfg, "question",
        survey_title=survey.title, request=survey.request, language_name=cfg.language_name(survey.language),
        group_name=group.name, group_description=group.description,
        question_number=index, question_total=survey.question_count,
        type_label=spec.label, type_description=spec.description,
        earlier_questions=earlier_text, examples=examples_text,
    )
    known = {_fingerprint(t) for t in earlier}

    def check(draft: QuestionDraft) -> list[str]:
        text = clean_text(draft.text)
        problems = []
        if len(text) < min_chars:
            problems.append("question text is too short")
        if len(text) > max_chars:
            problems.append(f"question text is longer than {max_chars} characters")
        if _fingerprint(text) in known:
            problems.append("this question already exists in the survey")
        return problems

    outcome = generate_with_retry(client, prompt, QuestionDraft, check, int(cfg.get("llm.max_retries", 2)))
    draft: QuestionDraft = outcome.value
    help_text = clean_text(draft.help)[: int(limits.get("help_max_chars", 200))]
    return AgentOutcome(QuestionDraft(text=clean_text(draft.text), help=help_text), outcome.tokens, outcome.ms)


def _fingerprint(text: str) -> str:
    """Lower-case text without punctuation, used to detect duplicate questions."""
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


# ---------------------------------------------------------------------------- answer options
def run_options_writer(client: LLMClient, cfg: AppConfig, survey: Survey, question: Question, spec: QuestionTypeSpec,
                       group: Group | None = None) -> AgentOutcome:
    """Generate answers/subquestions for a question whose type needs them."""
    lines = []
    if spec.needs_answers:
        lines.append(f'- "answers": between {spec.answers_min} and {spec.answers_max} entries.')
    else:
        lines.append('- "answers": leave as an empty list.')
    if spec.needs_subquestions:
        lines.append(f'- "subquestions": between {spec.subq_min} and {spec.subq_max} entries.')
    else:
        lines.append('- "subquestions": leave as an empty list.')
    if spec.hint:
        lines.append(f"- Guidance: {spec.hint}")

    prompt = render_prompt(
        cfg, "options",
        language_name=cfg.language_name(survey.language), type_label=spec.label, type_description=spec.description,
        question_text=question.text, help_text=question.help or cfg.get("prompts.empty_help", ""),
        survey_title=survey.title, request=survey.request, group_name=group.name if group else "",
        fill_instructions="\n".join(lines),
    )

    def normalise(draft: OptionsDraft) -> tuple[list[str], list[str]]:
        """Clean both lists; lists the type does not use are emptied."""
        answers = clean_options(draft.answers, spec.answers_max) if spec.needs_answers else []
        subs = clean_options(draft.subquestions, spec.subq_max) if spec.needs_subquestions else []
        return answers, subs

    def check(draft: OptionsDraft) -> list[str]:
        return options_problems(spec, *normalise(draft))

    outcome = generate_with_retry(client, prompt, OptionsDraft, check, int(cfg.get("llm.max_retries", 2)))
    answers, subs = normalise(outcome.value)
    return AgentOutcome(OptionsDraft(answers=answers, subquestions=subs), outcome.tokens, outcome.ms)
