"""Few-shot examples: read real .lss files and show a few of their questions to the model."""
from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from .config import AppConfig
from .lss.reader import ExampleQuestion, read_questions


def load_examples(cfg: AppConfig) -> dict[str, list[ExampleQuestion]]:
    """Read every ``*.lss`` file of the examples folder and group the questions by type key."""
    folder = cfg.resolve(cfg.get("examples.dir", "examples"))
    by_type: dict[str, list[ExampleQuestion]] = defaultdict(list)
    if not folder.is_dir():
        return by_type
    for path in sorted(Path(folder).glob("*.lss")):
        try:
            questions = read_questions(path.read_bytes())
        except Exception:  # a broken example file must never stop the app
            continue
        for question in questions:
            spec = cfg.type_by_code(question.type_code)
            if spec is not None and question.text:
                by_type[spec.key].append(question)
    return by_type


def format_examples(cfg: AppConfig, examples: dict[str, list[ExampleQuestion]], type_key: str, rng: random.Random | None = None) -> str:
    """Return a few example questions of ``type_key`` formatted for the prompt."""
    pool = examples.get(type_key, [])
    limit = int(cfg.get("examples.max_per_type", 2))
    if not pool or limit <= 0:
        return str(cfg.get("prompts.no_examples", ""))
    chosen = (rng or random).sample(pool, min(limit, len(pool)))
    lines: list[str] = []
    for item in chosen:
        lines.append(f"- Question: {item.text}")
        options = item.answers + item.subquestions
        if options:
            lines.append("  Options: " + " | ".join(options[:8]))
    return "\n".join(lines)
