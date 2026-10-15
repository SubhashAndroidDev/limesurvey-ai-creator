"""High-level API used by the Streamlit app and the command line tool."""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass

from .config import AppConfig
from .examples import load_examples
from .graph import build_graph
from .llm import GroqClient, LLMClient, OllamaClient
from .lss.builder import LssBuilder
from .lss.validator import validate_lss
from .models import AgentStat, Question, Survey
from .pipeline import EventCallback, PipelineContext, fill_question
from .pipeline import EventCallback, PipelineContext, fill_question, plan_survey
from .intent import check_request

@dataclass
class GenerationResult:
    """Everything the UI needs after a generation run."""

    survey: Survey
    lss_bytes: bytes
    issues: list[str]
    stats: list[AgentStat]
    total_tokens: int
    duration_s: float


def build_client(cfg: AppConfig) -> LLMClient:
    """Create a client for the configured provider. Secrets come from the environment only."""
    provider = str(cfg.get("llm.provider", "ollama")).lower()
    temperature = float(cfg.get("llm.temperature", 0.4))
    timeout = int(cfg.get("llm.timeout_seconds", 180))

    if provider == "groq":
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GROQ_API_KEY is missing. Add it to your project-root .env file.")
        return GroqClient(
            model=str(cfg.get("llm.groq.model", "openai/gpt-oss-120b")),
            api_key=api_key,
            temperature=temperature,
            timeout=timeout,
            backoff_seconds=float(cfg.get("llm.retry_backoff_seconds", 5)),
            reasoning_effort=cfg.get("llm.groq.reasoning_effort", "low"),
            tokens_per_minute=int(cfg.get("llm.groq.tokens_per_minute", 8000)),
            min_interval_seconds=float(cfg.get("llm.groq.min_interval_seconds", 0)),
            max_rate_limit_waits=int(cfg.get("llm.groq.max_rate_limit_waits", 8)),
        )

    if provider == "ollama":
        base_url, model = cfg.get("llm.base_url"), cfg.get("llm.model")
        if not base_url or not model:
            raise ValueError("Ollama URL or model is missing. Check settings.yaml.")
        return OllamaClient(base_url=str(base_url), model=str(model), temperature=temperature,
                            num_ctx=int(cfg.get("llm.num_ctx", 4096)), timeout=timeout)

    raise ValueError(f"Unknown LLM provider '{provider}'. Use 'groq' or 'ollama'.")


def generate_survey(
    request: str,
    total_questions: int | None = None,
    *,
    cfg: AppConfig | None = None,
    client: LLMClient | None = None,
    language: str | None = None,
    allowed_types: list[str] | None = None,
    questions_per_group: int | str | None = None,
    on_event: EventCallback | None = None,
) -> GenerationResult:
    """Run the whole pipeline: plan -> questions -> .lss -> validation."""
    cfg = cfg or AppConfig.load()
    if not isinstance(request, str) or not request.strip():
        raise ValueError("Please describe the survey you want to create.")
    check_request(request)  # clearly off-topic (code, poems...) -> friendly NotSurveyRequest, no tokens used
    if total_questions is None:
        total_questions = int(cfg.get("survey.default_questions", 10))
    if allowed_types is not None and not allowed_types:
        allowed_types = None

    client = client or build_client(cfg)
    language = language or str(cfg.get("survey.default_language", "en"))
    ctx = PipelineContext(cfg=cfg, client=client, examples=load_examples(cfg), on_event=on_event)

    graph = build_graph(ctx)
    started = time.perf_counter()
    final = graph.invoke(
        {"request": request.strip(), "total_questions": total_questions, "per_group": questions_per_group,
         "language": language, "allowed_types": allowed_types},
        config={"recursion_limit": total_questions * 2 + 20},
    )
    stats = list(ctx.stats.values())
    return GenerationResult(
        survey=final["survey"], lss_bytes=final["lss_bytes"], issues=final["issues"], stats=stats,
        total_tokens=sum(s.tokens for s in stats), duration_s=time.perf_counter() - started,
    )


def render_lss(survey: Survey, cfg: AppConfig) -> tuple[bytes, list[str]]:
    """Rebuild and validate the .lss after the user edited the survey in the UI."""
    data = LssBuilder(cfg).build(survey)
    return data, validate_lss(data, cfg)


def regenerate_question(survey: Survey, code: str, *, cfg: AppConfig, client: LLMClient | None = None) -> None:
    """Ask the model again for one question (keeps its group, type and code)."""
    found = survey.find_question(code)
    if found is None:
        raise KeyError(f"Unknown question code {code}")
    ctx = PipelineContext(cfg=cfg, client=client or build_client(cfg), examples=load_examples(cfg))
    fill_question(ctx, survey, *found)


# ---------------------------------------------------------------------------- editing helpers
def next_code(survey: Survey, cfg: AppConfig) -> str:
    """Return an unused question code that follows the configured pattern (default Q001...)."""
    pattern = str(cfg.get("survey.question_code_pattern", "Q{index:03d}"))
    used = {q.code for _, q in survey.iter_questions()}
    numbers = [int(m.group()) for c in used if (m := re.search(r"\d+$", c))]
    index = max(numbers, default=0) + 1
    while pattern.format(index=index) in used:
        index += 1
    return pattern.format(index=index)


def add_question(survey: Survey, group_index: int, type_key: str, *, cfg: AppConfig,
                 client: LLMClient | None = None, use_ai: bool = False) -> Question:
    """Append a new question to a group; optionally let the model draft it (never raises on LLM trouble)."""
    group = survey.groups[group_index]
    question = Question(code=next_code(survey, cfg), type_key=type_key, mandatory=cfg.mandatory_for(type_key))
    group.questions.append(question)
    if use_ai:
        ctx = PipelineContext(cfg=cfg, client=client or build_client(cfg), examples=load_examples(cfg))
        fill_question(ctx, survey, group, question)
    else:
        question.status = "edited"  # blank on purpose; becomes exportable once the user types a text
    return question


def delete_question(survey: Survey, code: str) -> bool:
    """Remove a question by code. Returns True when something was removed."""
    for group in survey.groups:
        for question in group.questions:
            if question.code == code:
                group.questions.remove(question)
                return True
    return False


# ---------------------------------------------------------------------------- step-by-step generation
def start_generation(
    request: str,
    total_questions: int,
    *,
    cfg: AppConfig,
    client: LLMClient,
    language: str | None = None,
    allowed_types: list[str] | None = None,
    questions_per_group: int | str | None = None,
) -> tuple[Survey, PipelineContext]:
    """Plan the survey only: groups (name + description), question count per group and the type of
    every question. All questions stay 'pending'; call ``fill_next_question`` to write them one by one."""
    if not isinstance(request, str) or not request.strip():
        raise ValueError("Please describe the survey you want to create.")
    if allowed_types is not None and not allowed_types:
        allowed_types = None
    language = language or str(cfg.get("survey.default_language", "en"))
    ctx = PipelineContext(cfg=cfg, client=client, examples=load_examples(cfg))
    survey = plan_survey(ctx, request.strip(), int(total_questions), questions_per_group, language, allowed_types)
    return survey, ctx


def fill_next_question(survey: Survey, ctx: PipelineContext) -> Question | None:
    """Write the first still-pending question (text + options) and return it; None when all are done."""
    for group, question in survey.iter_questions():
        if question.status == "pending":
            fill_question(ctx, survey, group, question)
            return question
    return None




def make_context(cfg: AppConfig, client: LLMClient | None = None) -> PipelineContext:
    """Fresh pipeline context (used to continue writing questions after a saved survey is restored)."""
    return PipelineContext(cfg=cfg, client=client or build_client(cfg), examples=load_examples(cfg))