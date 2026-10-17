# LimeSurvey Survey Creator skill

Reusable `SKILL.md` package for Codex and Claude Code. It improves the survey workflow while keeping generation tied to the question types, schemas, validator, and LSS builder that actually exist in the user's repository.

## Files

- `SKILL.md` — full workflow and constraints.
- `references/validation-checklist.md` — compact pre-export checklist.
- `references/project-integration.md` — how to connect the skill to the user's Python CLI/backend.

## Important boundary

This package is an agent instruction skill, not a replacement for the Python generator. It cannot itself call Ollama/Groq, write a valid `.lss` through the user's backend, or verify LimeSurvey import unless the agent has access to the repository and can execute the required tools.

## Install on Windows

### Codex CLI

Copy this folder to the global Codex skills directory:

```powershell
New-Item -ItemType Directory -Force "$HOME\.codex\skills" | Out-Null
Copy-Item -Recurse -Force ".\limesurvey-survey-creator" "$HOME\.codex\skills\"
Test-Path "$HOME\.codex\skills\limesurvey-survey-creator\SKILL.md"
```

Restart Codex. Open the project folder and prompt:

> Use the LimeSurvey Survey Creator skill at `$HOME\.codex\skills\limesurvey-survey-creator\SKILL.md`. First inspect my current CLI, schemas, question type mappings, builder, validator, and existing skill at `skills/limesurvey-ollama-survey/SKILL.md`. Preserve all compatible existing rules. Do not edit application code until you report the supported question types and validation gaps.

### Claude Code

```powershell
New-Item -ItemType Directory -Force "$HOME\.claude\skills" | Out-Null
Copy-Item -Recurse -Force ".\limesurvey-survey-creator" "$HOME\.claude\skills\"
Test-Path "$HOME\.claude\skills\limesurvey-survey-creator\SKILL.md"
```

Restart Claude Code and ask it to use the skill by name. If you want the skill only in one repository, place it under that repository's `.claude/skills/limesurvey-survey-creator/` directory instead.

## Connect it to the project

From your project root, for example `D:\liveproject\limesurvey-ai-creator`:

```powershell
uv run python -m survey_creator.cli --help
```

Then generate with the syntax shown by the actual CLI help. A previously documented example is:

```powershell
uv run python -m survey_creator.cli "customer satisfaction survey for a hotel" -n 5 -o hotel.lss
```

This command is an example only; confirm options with `--help`. If using Groq, `GROQ_API_KEY` must be configured in the project's local `.env`. If using Ollama, ensure Ollama is running and the configured model is installed. Do not paste API keys into the agent conversation.

## ChatGPT

A folder containing `SKILL.md` does not automatically become a persistent, callable ChatGPT skill just by uploading it into a chat. This package is directly installable in compatible coding agents such as Codex CLI and Claude Code. In ChatGPT, you can upload `SKILL.md` to a conversation and ask the model to follow it, but actually executing the local Python CLI still requires an available computer/workspace with access to the project files and dependencies.

## Suggested smoke test

Ask the agent to:
1. read the current project skill and compare its rules with this one;
2. list the exact supported question type codes from source;
3. create a 5-question hotel survey plan in English;
4. validate question count, groups, codes, answer options/subquestions, and relevance references;
5. show the exact CLI command it proposes;
6. run it only if local execution is available and report precisely which validations passed.
