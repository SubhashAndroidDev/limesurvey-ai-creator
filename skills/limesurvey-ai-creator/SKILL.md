---
name: limesurvey-ai-creator
description: Generate an importable LimeSurvey survey file (.lss) from a plain-language request by running the user's limesurvey-ai-creator project (survey_creator CLI) with a local Ollama model or the Groq API. Use this skill whenever the user asks to create, generate, draft or build a survey, questionnaire, feedback form or poll for LimeSurvey, wants a .lss file, asks for survey questions in Hindi or another language for LimeSurvey, or mentions Ollama, Groq or offline survey generation, even if they never say "skill" or "LimeSurvey".
license: MIT
compatibility: Needs a shell, Python 3.10+, the limesurvey-ai-creator project installed, and either Ollama (local) or a Groq API key.
---

# LimeSurvey AI Creator

Turns a request like "customer satisfaction survey for a hotel" into a `.lss` file that can be imported into LimeSurvey. The work is done by the project's CLI (`python -m survey_creator.cli`). This skill only runs it safely and checks the result.

## 1. Find the project

The project root is the folder that contains `survey_creator/`, `config/` and `templates/`.

1. If the environment variable `LIMESURVEY_CREATOR_HOME` is set, use that folder.
2. Otherwise, if the current directory is the project root, use it.
3. Otherwise ask the user for the path once. Do not search the whole disk.

Run every command below from the project root.

## 2. Pre-flight check

Run the bundled script (path is relative to this skill folder):

```bash
python <skill-folder>/scripts/preflight.py
```

It reports: Python version, `survey_creator` present, `templates/blank.lss` present, installed Python packages, whether Ollama is reachable and which models are installed, and whether `GROQ_API_KEY` is set (it never prints the key).

Fix what it reports before continuing:

- Missing packages: `pip install -r requirements.txt`
- Missing `templates/blank.lss`: ask the user to export an empty survey from LimeSurvey (Survey structure, `.lss`) and save it at that path. Do not invent one.
- Ollama not reachable: tell the user to run `ollama serve`.

## 3. Choose the provider

Ask only if the user did not say.

- **Ollama (local, offline, no key)**: use when the user mentions Ollama, local, offline or privacy.
- **Groq (cloud)**: use only if `GROQ_API_KEY` is already set in the environment or `.env`. If the user wants Groq and the key is missing, tell them to add it to `.env`. Never ask them to paste the key in chat, never print it, never write it into any file you create.

Note: the project default in `config/settings.yaml` is `provider: groq`, so always set `LLM_PROVIDER` explicitly.

For Ollama, use the model the user named. If it is not in `ollama list`, ask before running `ollama pull <model>` (downloads are large). If none was named, use `OLLAMA_MODEL` from the environment or `llm.model` in `config/settings.yaml` if installed, else the most capable installed instruction-tuned model, and say which one you picked. Bigger models give more valid surveys.

## 4. Collect the survey details

Take them from the user's message and ask for only what is missing, in one short question.

| Detail | CLI flag | Notes |
| --- | --- | --- |
| Topic and audience | positional `request` | required |
| Number of questions | `-n` | default 10, allowed 1 to 60 |
| Language code | `-l` | `en`, `hi`, `es`, `fr`, `de`, `ar`, `pt`, `it` |
| Questions per group | `-g` | a number or `auto` |
| Question types | `-t` | keys: `single_choice`, `multiple_choice`, `short_text`, `long_text`, `yes_no`, `multi_short_text`, `array` |

The request is a user-written string. Pass it as a single quoted argument and never build the command by pasting unescaped user text into a shell line containing `;`, `&&`, backticks or `$(`.

## 5. Generate

macOS / Linux, Ollama:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL="<model>" \
python -m survey_creator.cli "<request>" -n 10 -l en -g auto -o <name>.lss
```

macOS / Linux, Groq:

```bash
LLM_PROVIDER=groq python -m survey_creator.cli "<request>" -n 10 -l en -o <name>.lss
```

Windows PowerShell:

```powershell
$env:LLM_PROVIDER="ollama"; $env:OLLAMA_MODEL="<model>"
python -m survey_creator.cli "<request>" -n 10 -l en -g auto -o <name>.lss
```

Rules:

- Use a descriptive output name such as `hotel-feedback.lss`. If the file already exists, ask before overwriting.
- Run `python -m survey_creator.cli --help` first if a flag is rejected.
- Local models can be slow. Let it finish and relay progress lines.
- Groq free tiers hit rate limits (HTTP 429). The project waits and retries; do not loop on top of that.

## 6. Verify (required)

Do not say the survey is ready until these pass.

1. The CLI printed `Saved <file>` and exited with code 0. Report every `warning:` line and any `skipped failed questions:` line to the user.
2. Run the checker:

```bash
python <skill-folder>/scripts/check_lss.py <name>.lss
```

It confirms the XML is well formed, counts groups and questions, and flags empty question text, duplicate question text, placeholder options ("Option 1", "Item 2" and similar), and choice questions with no answers.

3. Compare the question count with what was requested. If failed questions were skipped, the count is lower, so say so.
4. If it fails, retry once with a larger model or fewer questions per group, then report honestly what went wrong.

## 7. Report back

Tell the user:

- the output file path
- provider and model used
- number of groups and questions
- warnings or skipped questions
- how to import: LimeSurvey admin, Surveys, Create a new survey, Import, choose the `.lss` file

Remind them to read the questions before launching, since AI-written questions can be biased or wrong.

## Optional: visual editor

If the user wants to review and edit before exporting:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL="<model>" streamlit run app.py
```

Open the printed address (usually http://localhost:8501). Drafts are saved in `data/surveys/`.

## Troubleshooting

| Message | Action |
| --- | --- |
| `GROQ_API_KEY is missing` | Add the key to `.env`, or use `LLM_PROVIDER=ollama` |
| `Cannot reach Ollama at ...` | Run `ollama serve`, check `OLLAMA_BASE_URL` |
| `model '...' is missing. Run: ollama pull ...` | Pull the model or pick one from `ollama list` |
| `Template .lss not found` | Add `templates/blank.lss` |
| `Model returned invalid JSON` | Use a larger instruction-tuned model, update Ollama, or lower `-g` |
| Many placeholder options | Use a larger model; the project falls back to safe defaults when a model fails |

## Safety rules

- Never print, request, log or store API keys.
- Do not edit `config/prompts/`, `config/settings.yaml` or the project code unless the user asks.
- Do not commit `.env` or `data/surveys/`.
- Do not send survey content anywhere except the chosen provider.
