"""Pipeline steps (framework independent). graph.py wires them into a LangGraph flow.

Stages shown in the progress panel:
  Survey Planner -> Question Generator -> Answer Options -> LSS Formatter -> LSS Validator
The first three call the LLM; the last two are plain Python (0 tokens).
"""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Callable

from .agents import run_options_writer, run_planner, run_question_writer
from .config import AppConfig
from .examples import format_examples
from .fallback import apply_fallback
from .llm import FatalLLMError, GenerationError, LLMClient
from .lss.builder import LssBuilder
from .lss.reader import ExampleQuestion
from .lss.validator import validate_lss
from .models import AgentStat, Group, Question, Survey
from .planning import build_skeleton, group_sizes, parse_per_group
from .question_types import assign_types
from .validation import question_problems

STAGE_PLANNER = "Survey Planner"
STAGE_QUESTIONS = "Question Generator"
STAGE_OPTIONS = "Answer Options"
STAGE_FORMATTER = "LSS Formatter"
STAGE_VALIDATOR = "LSS Validator"
STAGES = [STAGE_PLANNER, STAGE_QUESTIONS, STAGE_OPTIONS, STAGE_FORMATTER, STAGE_VALIDATOR]
LLM_STAGES = (STAGE_PLANNER, STAGE_QUESTIONS, STAGE_OPTIONS)

EventCallback = Callable[[list[AgentStat], str], None]


@dataclass
class PipelineContext:
    """Everything the pipeline steps share: config, model client, statistics and callbacks."""

    cfg: AppConfig
    client: LLMClient
    examples: dict[str, list[ExampleQuestion]] = field(default_factory=dict)
    on_event: EventCallback | None = None
    stats: dict[str, AgentStat] = field(default_factory=lambda: {name: AgentStat(name) for name in STAGES})
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep  # replaced in tests so they do not wait

    def update(self, stage: str, *, status: str | None = None, tokens: int = 0, ms: int = 0,
               calls: int = 0, failures: int = 0, message: str = "") -> None:
        """Add usage to a stage, optionally change its status, and notify the UI."""
        stat = self.stats[stage]
        stat.tokens += tokens
        stat.ms += ms
        stat.calls += calls
        stat.failures += failures
        if status:
            stat.status = status
        if message:
            stat.message = message
        if self.on_event:
            self.on_event(list(self.stats.values()), message)


# ---------------------------------------------------------------------------- step 1: plan
def plan_survey(ctx: PipelineContext, request: str, total: int, per_group: int | str | None,
                language: str, allowed_types: list[str] | None) -> Survey:
    """Run the planner and create the survey skeleton with typed, still empty questions."""
    cfg = ctx.cfg
    limits = (int(cfg.get("survey.min_questions", 1)), int(cfg.get("survey.max_questions", 60)))
    if not request.strip():
        raise ValueError("Please describe the survey you want.")
    if not limits[0] <= total <= limits[1]:
        raise ValueError(f"Number of questions must be between {limits[0]} and {limits[1]}.")
    specs = cfg.enabled_types(allowed_types)
    if not specs:
        raise ValueError("Select at least one question type.")

    sizes = group_sizes(total, parse_per_group(per_group, cfg), int(cfg.get("survey.auto_group_size", 4)))
    # The type of every question is decided here (code), not by the LLM.
    type_keys = assign_types(total, specs, cfg.get("survey.type_seed"), float(cfg.get("survey.type_jitter", 0.35)))

    ctx.update(STAGE_PLANNER, status="running", message="Planning groups...")
    try:
        outcome = run_planner(ctx.client, cfg, request, len(sizes), cfg.language_name(language))
    except FatalLLMError as exc:
        ctx.update(STAGE_PLANNER, status="error", calls=1, failures=1, message=str(exc))
        raise RuntimeError(str(exc)) from exc
    ctx.update(STAGE_PLANNER, status="done", tokens=outcome.tokens, ms=outcome.ms, calls=1, message="Plan ready")
    return build_skeleton(cfg, outcome.value, sizes, type_keys, language, request)


# ---------------------------------------------------------------------------- step 2: questions
def fill_question(ctx: PipelineContext, survey: Survey, group: Group, question: Question) -> None:
    """Generate text and options for one question - this function never fails.

    Self-healing order: normal attempt -> (cool down, try again) x ``llm.heal_attempts`` -> a safe
    offline draft (flagged "auto-drafted"). Only a fatal configuration error (bad API key) is
    raised, because no amount of retrying can fix it.
    """
    cfg = ctx.cfg
    spec = cfg.types[question.type_key]
    heal = int(cfg.get("llm.heal_attempts", 2))
    cooldown = float(cfg.get("llm.heal_cooldown_seconds", 8))
    for attempt in range(heal + 1):
        if attempt:
            ctx.update(STAGE_QUESTIONS, status="running", message=f"Refining {question.code}...")
            ctx.sleep(cooldown * attempt)
        if _fill_once(ctx, survey, group, question):
            return
    apply_fallback(survey, group, question, spec)
    ctx.update(STAGE_QUESTIONS, failures=1, message=f"{question.code} drafted with a safe default")


def _fill_once(ctx: PipelineContext, survey: Survey, group: Group, question: Question) -> bool:
    """One full attempt (text + options). Returns True when the question is complete and valid."""
    cfg = ctx.cfg
    spec = cfg.types[question.type_key]
    question.status, question.error, question.note = "pending", "", ""

    ctx.update(STAGE_QUESTIONS, status="running", message=f"Writing {question.code}...")
    examples_text = format_examples(cfg, ctx.examples, question.type_key, ctx.rng)
    try:
        written = run_question_writer(ctx.client, cfg, survey, group, question, spec, examples_text)
    except FatalLLMError:
        raise
    except GenerationError as exc:
        ctx.update(STAGE_QUESTIONS, tokens=exc.tokens, ms=exc.ms, calls=1)
        return False
    except Exception:
        return False
    question.text, question.help = written.value.text, written.value.help
    ctx.update(STAGE_QUESTIONS, tokens=written.tokens, ms=written.ms, calls=1)

    question.answers, question.subquestions = [], []
    if spec.needs_options:
        ctx.update(STAGE_OPTIONS, status="running", message=f"Options for {question.code}...")
        try:
            options = run_options_writer(ctx.client, cfg, survey, question, spec, group)
        except FatalLLMError:
            raise
        except GenerationError as exc:
            ctx.update(STAGE_OPTIONS, tokens=exc.tokens, ms=exc.ms, calls=1)
            return False
        except Exception:
            return False
        question.answers = options.value.answers
        question.subquestions = options.value.subquestions
        ctx.update(STAGE_OPTIONS, tokens=options.tokens, ms=options.ms, calls=1)

    if question_problems(cfg, question):
        return False
    question.status = "ok"
    return True


def finish_llm_stages(ctx: PipelineContext) -> None:
    """Mark LLM stages as done, or 'warning' when some of their calls failed."""
    for name in LLM_STAGES:
        stat = ctx.stats[name]
        if stat.status in ("running", "pending"):
            ctx.update(name, status="warning" if stat.failures else "done")
        elif stat.status == "done" and stat.failures:
            stat.status = "warning"
    if ctx.on_event:
        ctx.on_event(list(ctx.stats.values()), "Questions finished")


# ---------------------------------------------------------------------------- steps 3+4: lss
def format_survey(ctx: PipelineContext, survey: Survey) -> bytes:
    """Build the .lss file (no LLM involved)."""
    ctx.update(STAGE_FORMATTER, status="running", message="Building .lss ...")
    started = time.perf_counter()
    try:
        data = LssBuilder(ctx.cfg).build(survey)
    except Exception as exc:
        ctx.update(STAGE_FORMATTER, status="error", message=str(exc))
        raise
    ctx.update(STAGE_FORMATTER, status="done", ms=int((time.perf_counter() - started) * 1000), calls=1, message=".lss built")
    return data


def validate_output(ctx: PipelineContext, data: bytes) -> list[str]:
    """Validate the generated file (no LLM involved)."""
    ctx.update(STAGE_VALIDATOR, status="running", message="Validating .lss ...")
    started = time.perf_counter()
    issues = validate_lss(data, ctx.cfg)
    ctx.update(STAGE_VALIDATOR, status="warning" if issues else "done",
               ms=int((time.perf_counter() - started) * 1000), calls=1,
               failures=len(issues), message="; ".join(issues) or "Valid")
    return issues
