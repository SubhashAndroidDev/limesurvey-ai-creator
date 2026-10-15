"""LLM access layer: Ollama and Groq clients plus a retry helper.

Design goals (so the end user never sees an LLM error):
  * the JSON schema is always shown to the model, and near-miss answers are repaired in code;
  * rate limits (HTTP 429) are waited out *inside* the client, using the server's own hint and a
    rolling tokens-per-minute budget, and never use up the validation retries;
  * raw exception text is never pasted into a retry prompt;
  * only genuinely fatal problems (bad / missing API key) are raised to the caller.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

import requests

T = TypeVar("T")
log = logging.getLogger("survey_creator.llm")


# ---------------------------------------------------------------------------- results / errors
@dataclass
class LLMResult:
    """Result of one structured LLM call."""

    parsed: Any          # instance of the requested pydantic schema
    tokens: int = 0      # prompt + completion tokens reported by the model server
    ms: int = 0          # wall-clock time of the call


class GenerationError(Exception):
    """Raised when all attempts failed. Carries the usage so far so statistics stay correct."""

    def __init__(self, message: str, tokens: int = 0, ms: int = 0, last_parsed: Any = None):
        super().__init__(message)
        self.tokens = tokens
        self.ms = ms
        self.last_parsed = last_parsed  # last syntactically valid answer (may still be unusable)


class FatalLLMError(Exception):
    """A problem retrying cannot fix (bad/missing API key ...). Message is safe to show to users."""


class OutputError(ValueError):
    """The model answered, but the answer was unusable (empty, not JSON, wrong shape)."""

    def __init__(self, message: str, tokens: int = 0):
        super().__init__(message)
        self.tokens = tokens


class LLMClient(Protocol):
    """Minimal interface the pipeline needs."""

    def generate(self, prompt: str, schema: type[T]) -> LLMResult: ...

    def ping(self) -> tuple[bool, str]: ...


# ---------------------------------------------------------------------------- JSON repair
# Keys small/medium models often use instead of the schema's own field names.
_ALIASES: dict[str, tuple[str, ...]] = {
    "text": ("question", "question_text", "title", "label", "prompt", "name", "q"),
    "help": ("help_text", "hint", "instruction", "instructions"),
    "answers": ("options", "choices", "columns", "scale", "answer_options", "answer_choices"),
    "subquestions": ("sub_questions", "rows", "items", "statements", "text_boxes", "fields", "labels"),
    "title": ("survey_title", "name"),
    "welcome_text": ("welcome", "welcome_message"),
    "end_text": ("end", "end_message", "thank_you"),
    "groups": ("sections", "survey_groups"),
}
_ITEM_KEYS = ("text", "label", "name", "answer", "option", "title", "value", "question")


def _item_to_str(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        for key in _ITEM_KEYS:
            if isinstance(item.get(key), str):
                return item[key]
        for value in item.values():
            if isinstance(value, str):
                return value
        return ""
    return "" if item is None else str(item)


def normalize_payload(schema: type, data: Any) -> Any:
    """Repair common shape mistakes so a valid answer is not thrown away over key names."""
    fields = set(schema.model_fields)
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        data = data[0]
    if not isinstance(data, dict):
        return data
    # Unwrap {"question": {...}} / {"survey": {...}} style envelopes.
    if not (fields & set(data)):
        inner = [v for v in data.values() if isinstance(v, dict)]
        if len(inner) == 1:
            data = inner[0]
    data = dict(data)
    for field_name in fields:
        if field_name not in data:
            for alias in _ALIASES.get(field_name, ()):
                if alias in data and alias not in fields:
                    data[field_name] = data[alias]
                    break
    for field_name, info in schema.model_fields.items():
        if field_name not in data:
            continue
        value = data[field_name]
        annotation = str(info.annotation)
        if "list[str]" in annotation:
            if isinstance(value, str):
                value = [p for p in re.split(r"\n|;", value) if p.strip()]
            data[field_name] = [_item_to_str(v) for v in value] if isinstance(value, list) else []
        elif "list[" in annotation:  # list of nested models, e.g. groups
            data[field_name] = [{"name": v} if isinstance(v, str) else v for v in value] if isinstance(value, list) else []
        elif "str" in annotation:
            if isinstance(value, list):
                value = " ".join(_item_to_str(v) for v in value)
            data[field_name] = "" if value is None else str(value) if not isinstance(value, str) else value
    return data


# def shape_hint(schema: type) -> str:
#     """Short, human-readable description of the JSON object the model must return."""
#     props = schema.model_json_schema().get("properties", {})
#     lines = []
#     for name, meta in props.items():
#         kind = meta.get("type", "string")
#         if kind == "array":
#             item = meta.get("items", {})
#             kind = "array of strings" if item.get("type") == "string" else "array of objects"
#         lines.append(f'  "{name}" ({kind}): {meta.get("description", "")}')
#     example = {name: ("" if m.get("type", "string") == "string" else []) for name, m in props.items()}
#     return ("Return ONLY one JSON object (no Markdown, no extra keys, no commentary) with exactly these keys:\n"
#             + "\n".join(lines) + f"\nShape: {json.dumps(example)}")
def shape_hint(schema: type) -> str:
    """Short, human-readable description of the JSON object the model must return."""
    props = schema.model_json_schema().get("properties", {})
    lines = []
    for name, meta in props.items():
        kind = meta.get("type", "string")
        if kind == "array":
            item = meta.get("items", {})
            kind = "array of strings" if item.get("type") == "string" else "array of objects"
        lines.append(f'  "{name}" ({kind}): {meta.get("description", "")}')

    def _example(meta: dict):
        kind = meta.get("type", "string")
        return "" if kind == "string" else True if kind == "boolean" else []

    example = {name: _example(m) for name, m in props.items()}
    return ("Return ONLY one JSON object (no Markdown, no extra keys, no commentary) with exactly these keys:\n"
            + "\n".join(lines) + f"\nShape: {json.dumps(example)}")

def _extract_json(content: str) -> Any:
    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def _content_to_text(content: Any) -> str:
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("text"):
                parts.append(block["text"])
        return "\n".join(parts)
    return content if isinstance(content, str) else ""


def _is_rate_limit(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return "ratelimit" in text or "429" in text or "rate limit" in text


def _is_fatal(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}".lower()
    return any(s in text for s in ("401", "invalid api key", "authenticationerror", "permission denied", "groq_api_key"))


def _retry_after_seconds(exc: Exception) -> float | None:
    """Read the server's own wait hint, e.g. 'Please try again in 2.76s' or '1m3.5s'."""
    text = str(exc)
    match = re.search(r"try again in\s+(?:(\d+)m)?\s*([\d.]+)s", text, flags=re.I)
    if match:
        return int(match.group(1) or 0) * 60 + float(match.group(2))
    match = re.search(r"try again in\s+([\d.]+)\s*ms", text, flags=re.I)
    return float(match.group(1)) / 1000 if match else None


# ---------------------------------------------------------------------------- Ollama
class OllamaClient:
    """Structured-output client for a local Ollama server (via langchain-ollama)."""

    def __init__(self, base_url: str, model: str, temperature: float = 0.4, num_ctx: int = 4096, timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.num_ctx = num_ctx
        self.timeout = timeout
        self._chat: Any = None

    def _get_chat(self) -> Any:
        if self._chat is None:
            from langchain_ollama import ChatOllama

            self._chat = ChatOllama(model=self.model, base_url=self.base_url, temperature=self.temperature,
                                    num_ctx=self.num_ctx, client_kwargs={"timeout": self.timeout})
        return self._chat

    def generate(self, prompt: str, schema: type[T]) -> LLMResult:
        started = time.perf_counter()
        structured = self._get_chat().with_structured_output(schema, method="json_schema", include_raw=True)
        output = structured.invoke(prompt)
        parsed = output.get("parsed")
        tokens = _count_tokens(output.get("raw"))
        if parsed is None:
            raise OutputError(f"Model returned invalid JSON: {output.get('parsing_error')}", tokens)
        return LLMResult(parsed=parsed, tokens=tokens, ms=int((time.perf_counter() - started) * 1000))

    def ping(self) -> tuple[bool, str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
        except Exception as exc:
            return False, f"Cannot reach Ollama at {self.base_url}: {exc}"
        names = {m.get("name", "") for m in response.json().get("models", [])}
        if names & {self.model, f"{self.model}:latest"}:
            return True, f"Connected. Model '{self.model}' is available."
        return False, f"Ollama is running but model '{self.model}' is missing. Run: ollama pull {self.model}"


# ---------------------------------------------------------------------------- Groq
class GroqClient:
    """Structured-output client for the Groq cloud API (JSON mode + schema in the prompt)."""

    API_URL = "https://api.groq.com/openai/v1"

    def __init__(
        self,
        model: str,
        api_key: str | None = None,
        temperature: float = 0.4,
        timeout: int = 60,
        backoff_seconds: float = 5,
        reasoning_effort: str | None = "low",
        tokens_per_minute: int = 8000,
        min_interval_seconds: float = 0.0,
        max_rate_limit_waits: int = 8,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.temperature = temperature
        self.timeout = timeout
        self.backoff_seconds = backoff_seconds
        self.reasoning_effort = reasoning_effort
        self.tokens_per_minute = tokens_per_minute
        self.min_interval_seconds = min_interval_seconds
        self.max_rate_limit_waits = max_rate_limit_waits
        self._sleep = sleep
        self._chat: Any = None
        self._window: deque[tuple[float, int]] = deque()  # (timestamp, tokens) of the last minute
        self._last_call = 0.0

    def _get_chat(self) -> Any:
        if not self.api_key:
            raise FatalLLMError("The AI service key (GROQ_API_KEY) is not configured.")
        if self._chat is None:
            from langchain_groq import ChatGroq

            kwargs: dict[str, Any] = dict(model=self.model, api_key=self.api_key, temperature=self.temperature,
                                          timeout=self.timeout, max_retries=0)
            if self.reasoning_effort:
                kwargs["reasoning_effort"] = self.reasoning_effort  # fewer hidden tokens -> fewer 429s
            self._chat = ChatGroq(**kwargs)
        return self._chat

    # -- pacing ---------------------------------------------------------------------------
    def _throttle(self, estimate: int) -> None:
        """Wait until the next call fits into the rolling tokens-per-minute budget."""
        if self.min_interval_seconds > 0:
            gap = self.min_interval_seconds - (time.monotonic() - self._last_call)
            if gap > 0:
                self._sleep(gap)
        budget = int(self.tokens_per_minute * 0.85)
        for _ in range(12):  # bounded: pacing must never be able to hang a run
            now = time.monotonic()
            while self._window and now - self._window[0][0] >= 60:
                self._window.popleft()
            used = sum(t for _, t in self._window)
            if not self._window or used + estimate <= budget:
                return
            self._sleep(min(max(self._window[0][0] + 60 - now + 0.5, 0.5), 60))

    def _record(self, tokens: int) -> None:
        self._window.append((time.monotonic(), tokens))
        self._last_call = time.monotonic()

    # -- main call ------------------------------------------------------------------------
    def generate(self, prompt: str, schema: type[T]) -> LLMResult:
        started = time.perf_counter()
        full_prompt = f"{prompt}\n\n{shape_hint(schema)}"
        self._throttle(estimate=len(full_prompt) // 3 + 700)

        response = None
        for wait_no in range(self.max_rate_limit_waits + 1):
            try:
                response = self._get_chat().invoke(full_prompt, response_format={"type": "json_object"})
                break
            except FatalLLMError:
                raise
            except Exception as exc:
                if _is_fatal(exc):
                    raise FatalLLMError("The AI service rejected the API key. Please check GROQ_API_KEY.") from exc
                if not _is_rate_limit(exc) or wait_no >= self.max_rate_limit_waits:
                    raise
                hint = _retry_after_seconds(exc)
                delay = min(max((hint or 0) + 1.0, self.backoff_seconds), 60.0)
                log.info("Rate limited; waiting %.1fs (%d/%d)", delay, wait_no + 1, self.max_rate_limit_waits)
                self._sleep(delay)

        tokens = _count_tokens(response)
        self._record(tokens or len(full_prompt) // 3 + 700)
        content = _content_to_text(response.content)
        if not content.strip():
            raise OutputError("The model returned an empty answer.", tokens)
        try:
            data = _extract_json(content)
        except json.JSONDecodeError as exc:
            raise OutputError(f"The answer was not valid JSON ({exc.msg}).", tokens) from exc

        from pydantic import ValidationError

        try:
            parsed = schema.model_validate(normalize_payload(schema, data))
        except ValidationError as exc:
            missing = [".".join(map(str, e["loc"])) for e in exc.errors()]
            raise OutputError(f"The JSON did not match the required keys (problem with: {', '.join(missing)}).", tokens) from exc
        return LLMResult(parsed=parsed, tokens=tokens, ms=int((time.perf_counter() - started) * 1000))

    def ping(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "GROQ_API_KEY is not set. Add it to the project-root .env file."
        try:
            response = requests.get(f"{self.API_URL}/models", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=10)
        except Exception as exc:
            return False, f"Cannot reach Groq: {exc}"
        if response.status_code == 401:
            return False, "Groq rejected the API key (401). Check your .env."
        if not response.ok:
            return False, f"Groq returned HTTP {response.status_code}."
        try:
            ids = {m.get("id") for m in response.json().get("data", [])}
        except (ValueError, AttributeError):
            return False, "Groq returned an invalid model list."
        if self.model in ids:
            return True, f"Connected to Groq. Model '{self.model}' is available."
        return False, f"Model '{self.model}' was not found in the models available to your Groq API key."


def _count_tokens(message: Any) -> int:
    """Read the token usage from a LangChain message."""
    if message is None:
        return 0
    usage = getattr(message, "usage_metadata", None) or {}
    if usage.get("total_tokens"):
        return int(usage["total_tokens"])
    meta = getattr(message, "response_metadata", None) or {}
    return int(meta.get("prompt_eval_count", 0) or 0) + int(meta.get("eval_count", 0) or 0)


# ---------------------------------------------------------------------------- retry helper
@dataclass
class Outcome:
    """Successful result of ``generate_with_retry``."""

    value: Any
    tokens: int
    ms: int
    attempts: int


def generate_with_retry(
    client: LLMClient,
    prompt: str,
    schema: type[T],
    check: Callable[[Any], list[str]] | None = None,
    max_retries: int = 2,
) -> Outcome:
    """Call the model until its answer passes ``check`` or the retries are used up.

    Only *content* problems (bad shape, failed ``check``) are fed back to the model. Technical
    errors (timeouts, 5xx, connection) are retried with the original prompt, never with the raw
    exception text. Fatal errors (bad API key) are raised immediately.
    """
    tokens = 0
    started = time.perf_counter()
    problem = ""
    last_parsed: Any = None
    for attempt in range(1, max_retries + 2):
        full_prompt = prompt
        if problem:
            full_prompt += f"\n\nYour previous answer was rejected: {problem}\nReturn a corrected JSON answer."
        try:
            result = client.generate(full_prompt, schema)
        except FatalLLMError:
            raise
        except OutputError as exc:
            tokens += exc.tokens
            problem = str(exc)[:300]
            continue
        except Exception as exc:  # timeout, connection, 5xx ... retry with the clean prompt
            log.warning("LLM call failed (attempt %d): %s: %s", attempt, type(exc).__name__, str(exc)[:200])
            problem = ""
            time.sleep(min(2.0 * attempt, 6.0))
            continue
        tokens += result.tokens
        last_parsed = result.parsed
        issues = check(result.parsed) if check else []
        if not issues:
            return Outcome(result.parsed, tokens, int((time.perf_counter() - started) * 1000), attempt)
        problem = "; ".join(issues)
    raise GenerationError(problem or "The model could not produce a usable answer.", tokens,
                          int((time.perf_counter() - started) * 1000), last_parsed)
