"""
Configuration loading.

Everything that can change between deployments (model, question types,
defaults, prompts) lives in files under config/. Python code only reads
them through this module, so nothing about a specific survey type or
question type is hard-coded in the logic.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import yaml


PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class QuestionTypeSpec:
    """Description of one LimeSurvey question type."""

    key: str
    label: str
    code: str
    theme: str
    description: str
    weight: float
    enabled: bool
    hint: str = ""
    answers_min: int = 0
    answers_max: int = 0
    subq_min: int = 0
    subq_max: int = 0

    @property
    def needs_answers(self) -> bool:
        """Whether this type requires answer choices."""
        return self.answers_max > 0

    @property
    def needs_subquestions(self) -> bool:
        """Whether this type requires subquestions."""
        return self.subq_max > 0

    @property
    def needs_options(self) -> bool:
        """Whether an extra Answer Options LLM step is required."""
        return self.needs_answers or self.needs_subquestions


@dataclass
class AppConfig:
    """All application configuration in one object."""

    root: Path
    config_dir: Path
    settings: dict[str, Any]
    types: dict[str, QuestionTypeSpec]
    defaults: dict[str, Any]
    _prompt_cache: dict[str, str] = field(
        default_factory=dict,
        repr=False,
    )

    # ---------------------------------------------------------------
    # Loading
    # ---------------------------------------------------------------
    @classmethod
    def load(
        cls,
        config_dir: str | Path | None = None,
    ) -> "AppConfig":
        """Read YAML files and apply environment-variable overrides."""

        directory = Path(
            config_dir
            or os.environ.get("SURVEY_CONFIG_DIR")
            or PROJECT_ROOT / "config"
        )

        settings = _read_yaml(directory / "settings.yaml")
        defaults = _read_yaml(directory / "defaults.yaml")
        raw_types = _read_yaml(
            directory / "question_types.yaml"
        ).get("types", {})

        # Get the LLM configuration AFTER loading settings.yaml.
        llm = settings.setdefault("llm", {})

        # LLM provider: ollama or groq, depending on your application.
        llm["provider"] = os.environ.get(
            "LLM_PROVIDER",
            llm.get("provider", "ollama"),
        )

        # Ollama configuration.
        llm["base_url"] = os.environ.get(
            "OLLAMA_BASE_URL",
            llm.get("base_url"),
        )
        llm["model"] = os.environ.get(
            "OLLAMA_MODEL",
            llm.get("model"),
        )

        # Groq configuration.
        groq = llm.setdefault("groq", {})
        groq["model"] = os.environ.get(
            "GROQ_MODEL",
            groq.get("model"),
        )

        # Parse question types from YAML.
        types = {
            key: _parse_type(key, body)
            for key, body in raw_types.items()
        }

        return cls(
            root=PROJECT_ROOT,
            config_dir=directory,
            settings=settings,
            types=types,
            defaults=defaults,
        )

    # ---------------------------------------------------------------
    # Accessors
    # ---------------------------------------------------------------
    def get(
        self,
        dotted_key: str,
        default: Any = None,
    ) -> Any:
        """Read a nested setting using a dotted path."""

        node: Any = self.settings

        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]

        return node

    def prompt(self, name: str) -> str:
        """Return the text of config/prompts/<name>.txt (cached)."""

        if name not in self._prompt_cache:
            path = self.config_dir / "prompts" / f"{name}.txt"
            self._prompt_cache[name] = path.read_text(
                encoding="utf-8"
            )

        return self._prompt_cache[name]

    def resolve(self, relative_path: str | Path) -> Path:
        """Resolve a path relative to the project root."""

        path = Path(relative_path)
        return path if path.is_absolute() else self.root / path

    def language_name(self, code: str) -> str:
        """Return a human-readable language name."""

        return str(self.get("languages", {}).get(code, code))

    def enabled_types(
        self,
        allowed_keys: list[str] | None = None,
    ) -> list[QuestionTypeSpec]:
        """Return enabled question types, optionally filtered by key."""

        specs = [
            spec
            for spec in self.types.values()
            if spec.enabled
        ]

        if allowed_keys is not None:
            specs = [
                spec
                for spec in specs
                if spec.key in allowed_keys
            ]

        return specs

    def type_by_code(
        self,
        code: str,
    ) -> QuestionTypeSpec | None:
        """Find a question type by its LimeSurvey code."""

        for spec in self.types.values():
            if spec.code == code:
                return spec

        return None

    def mandatory_for(self, type_key: str) -> str:
        """Return the default mandatory flag (Y/N/S) for a type."""

        block = self.defaults.get("mandatory", {})

        return str(
            block.get("by_type", {}).get(
                type_key,
                block.get("default", "N"),
            )
        )


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file and always return a dictionary."""

    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _parse_type(
    key: str,
    body: dict[str, Any],
) -> QuestionTypeSpec:
    """Convert one YAML block into a QuestionTypeSpec."""

    answers = body.get("answers") or {}
    subs = body.get("subquestions") or {}

    return QuestionTypeSpec(
        key=key,
        label=str(body.get("label", key)),
        code=str(body["code"]),
        theme=str(body.get("theme", "")),
        description=str(body.get("description", "")),
        weight=float(body.get("weight", 1)),
        enabled=bool(body.get("enabled", True)),
        hint=str(body.get("hint", "")),
        answers_min=int(answers.get("min", 0)),
        answers_max=int(answers.get("max", 0)),
        subq_min=int(subs.get("min", 0)),
        subq_max=int(subs.get("max", 0)),
    )



# """Configuration loading.

# Everything that can change between deployments (model, question types, defaults, prompts) lives
# in files under ``config/``. Python code only reads them through this module, so nothing about a
# specific survey type or question type is hard-coded in the logic.
# """
# from __future__ import annotations

# import os
# from dataclasses import dataclass, field
# from pathlib import Path
# from typing import Any

# import yaml

# PROJECT_ROOT = Path(__file__).resolve().parent.parent


# @dataclass(frozen=True)
# class QuestionTypeSpec:
#     """Description of one LimeSurvey question type, loaded from question_types.yaml."""

#     key: str
#     label: str
#     code: str                 # LimeSurvey type code (L, M, S, T, Y, Q, F, ...)
#     theme: str                # LimeSurvey question theme name
#     description: str
#     weight: float
#     enabled: bool
#     hint: str = ""
#     answers_min: int = 0
#     answers_max: int = 0
#     subq_min: int = 0
#     subq_max: int = 0

#     @property
#     def needs_answers(self) -> bool:
#         """True when the type stores 'answers' (radio choices, matrix columns)."""
#         return self.answers_max > 0

#     @property
#     def needs_subquestions(self) -> bool:
#         """True when the type stores 'subquestions' (checkbox options, matrix rows)."""
#         return self.subq_max > 0

#     @property
#     def needs_options(self) -> bool:
#         """True when an extra 'Answer Options' LLM step is required for this type."""
#         return self.needs_answers or self.needs_subquestions


# @dataclass
# class AppConfig:
#     """All configuration of the application in one object."""

#     root: Path
#     config_dir: Path
#     settings: dict[str, Any]
#     types: dict[str, QuestionTypeSpec]
#     defaults: dict[str, Any]
#     _prompt_cache: dict[str, str] = field(default_factory=dict, repr=False)

#     # ------------------------------------------------------------------ loading
#     @classmethod
#     def load(cls, config_dir: str | Path | None = None) -> "AppConfig":
#         """Read all YAML files and apply environment-variable overrides."""
#         directory = Path(config_dir or os.environ.get("SURVEY_CONFIG_DIR") or PROJECT_ROOT / "config")
#         settings = _read_yaml(directory / "settings.yaml")
#         defaults = _read_yaml(directory / "defaults.yaml")
#         raw_types = _read_yaml(directory / "question_types.yaml").get("types", {})

#         # Environment variables win over the file so Docker can point the app at another Ollama.
#         llm = settings.setdefault("llm", {})
#         llm["base_url"] = os.environ.get("OLLAMA_BASE_URL", llm.get("base_url"))
#         llm["model"] = os.environ.get("OLLAMA_MODEL", llm.get("model"))

#         types = {key: _parse_type(key, body) for key, body in raw_types.items()}
#         return cls(root=PROJECT_ROOT, config_dir=directory, settings=settings, types=types, defaults=defaults)

#     # ------------------------------------------------------------------ accessors
#     def get(self, dotted_key: str, default: Any = None) -> Any:
#         """Read a nested setting using a dotted path, e.g. ``get("llm.model")``."""
#         node: Any = self.settings
#         for part in dotted_key.split("."):
#             if not isinstance(node, dict) or part not in node:
#                 return default
#             node = node[part]
#         return node

#     def prompt(self, name: str) -> str:
#         """Return the text of ``config/prompts/<name>.txt`` (cached)."""
#         if name not in self._prompt_cache:
#             path = self.config_dir / "prompts" / f"{name}.txt"
#             self._prompt_cache[name] = path.read_text(encoding="utf-8")
#         return self._prompt_cache[name]

#     def resolve(self, relative_path: str | Path) -> Path:
#         """Resolve a path from settings relative to the project root."""
#         path = Path(relative_path)
#         return path if path.is_absolute() else self.root / path

#     def language_name(self, code: str) -> str:
#         """Human readable language name used in prompts (falls back to the code itself)."""
#         return str(self.get("languages", {}).get(code, code))

#     def enabled_types(self, allowed_keys: list[str] | None = None) -> list[QuestionTypeSpec]:
#         """Enabled question types, optionally restricted to the keys chosen by the user."""
#         specs = [s for s in self.types.values() if s.enabled]
#         if allowed_keys is not None:
#             specs = [s for s in specs if s.key in allowed_keys]
#         return specs

#     def type_by_code(self, code: str) -> QuestionTypeSpec | None:
#         """Find a question type by its LimeSurvey code (used when reading .lss files)."""
#         for spec in self.types.values():
#             if spec.code == code:
#                 return spec
#         return None

#     def mandatory_for(self, type_key: str) -> str:
#         """Default mandatory flag (Y/N/S) for a type."""
#         block = self.defaults.get("mandatory", {})
#         return str(block.get("by_type", {}).get(type_key, block.get("default", "N")))


# def _read_yaml(path: Path) -> dict[str, Any]:
#     """Load a YAML file and always return a dict."""
#     with path.open("r", encoding="utf-8") as handle:
#         return yaml.safe_load(handle) or {}


# def _parse_type(key: str, body: dict[str, Any]) -> QuestionTypeSpec:
#     """Convert one YAML block into a QuestionTypeSpec."""
#     answers = body.get("answers") or {}
#     subs = body.get("subquestions") or {}
#     return QuestionTypeSpec(
#         key=key,
#         label=str(body.get("label", key)),
#         code=str(body["code"]),
#         theme=str(body.get("theme", "")),
#         description=str(body.get("description", "")),
#         weight=float(body.get("weight", 1)),
#         enabled=bool(body.get("enabled", True)),
#         hint=str(body.get("hint", "")),
#         answers_min=int(answers.get("min", 0)),
#         answers_max=int(answers.get("max", 0)),
#         subq_min=int(subs.get("min", 0)),
#         subq_max=int(subs.get("max", 0)),
#     )
