"""Prompt rendering helpers."""
from __future__ import annotations

from string import Template
from typing import Any

from .config import AppConfig


def render_prompt(cfg: AppConfig, name: str, **values: Any) -> str:
    """Fill ``${placeholders}`` of ``config/prompts/<name>.txt``.

    ``string.Template`` is used on purpose: prompts may contain curly braces (JSON examples) and
    ``safe_substitute`` leaves unknown placeholders untouched instead of raising.
    """
    template = Template(cfg.prompt(name))
    return template.safe_substitute({key: str(value) for key, value in values.items()})
