# AI Survey Creator for LimeSurvey (open source, fully local)

Describe a survey in plain words ("customer satisfaction survey for a hotel"), choose how many
questions you want, review/edit the generated questions, and download a LimeSurvey `.lss` file.
Runs on **Python + LangGraph + LangChain + Ollama**. No paid service, no API keys.

## How it works

```
prompt + N questions
   -> Survey Planner      (LLM)  title, welcome/end text, group names
   -> type assignment     (code) mix of question types from config/question_types.yaml
   -> Question Generator  (LLM)  one question at a time, loops through every group
   -> Answer Options      (LLM)  only for types that need choices / rows / columns
   -> LSS Formatter       (code) builds the .lss XML
   -> LSS Validator       (code) checks the XML before you download it
   -> preview (edit / regenerate) -> Download .lss
```

* Every question lives inside a group. By default **one group = one question**
  (`survey.questions_per_group: 1`). Use a number (e.g. `3`) or `auto` for several questions per group.
* If a question fails (model error, invalid JSON), it is marked **Failed**, the run continues with
  the next question, and you can **Edit** or **Regenerate** it in the preview.
* Supported types: single choice, multiple choice, short text, long text, yes/no, multiple short
  text, array (matrix).

## Nothing is hard-coded

| What | Where |
|---|---|
| Model, URL, limits, grouping, code patterns | `config/settings.yaml` |
| Question types (LimeSurvey code, weight, option counts) | `config/question_types.yaml` |
| Default mandatory flag, validation limits | `config/defaults.yaml` |
| Agent prompts | `config/prompts/*.txt` |
| Survey-level settings of the .lss | `templates/blank.lss` |
| Style examples ("skills") | `examples/*.lss` |

To add a question type, add one block to `question_types.yaml`. To change the writing style,
edit the prompts. Env vars `OLLAMA_BASE_URL` / `OLLAMA_MODEL` override the model settings.

## Setup

1. Install [Ollama](https://ollama.com) and pull a model:
   ```
   ollama pull qwen2.5:7b-instruct     # ~8 GB RAM; use qwen2.5:3b on small machines
   ```
2. Install and run the app with [uv](https://docs.astral.sh/uv/):
   ```
   uv sync                      # creates .venv and installs everything from pyproject.toml
   uv run streamlit run app.py
   ```
   (Without uv: `python -m venv .venv`, `pip install -r requirements.txt`, `streamlit run app.py`.)
3. Or with Docker: `docker compose up -d --build`, then
   `docker compose exec ollama ollama pull qwen2.5:7b-instruct`, open http://localhost:8501.

Command line: `uv run python -m survey_creator.cli "hotel guest survey" -n 10 -o hotel.lss`

## Import into LimeSurvey

Create survey -> **Import** -> choose the downloaded `.lss`.

## Compatibility with your LimeSurvey version (important)

The `.lss` layout changes slightly between LimeSurvey versions. `templates/blank.lss` is a
generic base. For the safest import on your server (for example 7.0.7):

1. In LimeSurvey create an empty survey and export it as **Survey structure (.lss)**.
2. Replace `templates/blank.lss` with that file (or point `template.file` in `settings.yaml` to it).

The builder keeps the template's `DBVersion` and survey-level settings and only regenerates
groups, questions, sub-questions, answers and texts. If an import fails, send the error message
or an exported `.lss` that imports fine, so the builder can be adjusted.

## Teaching the model your style ("skills")

Copy real `.lss` exports of good surveys into `examples/`. At runtime a few questions of the
needed type are shown to the model as style examples (`examples.max_per_type`). Later, the same
files can be turned into a fine-tuning dataset (LoRA) if you need more than prompting.

## Tests

```
uv run pytest
```
The tests use a fake model, so they run without Ollama.

## Project layout

```
app.py                    Streamlit UI
survey_creator/
  config.py               loads YAML config
  schemas.py              JSON schemas the LLM must follow (pydantic)
  llm.py                  Ollama client + retry with error feedback
  agents.py               planner / question / options agents
  pipeline.py             pipeline steps and progress statistics
  graph.py                LangGraph flow
  service.py              generate_survey(), render_lss(), regenerate_question()
  question_types.py       type mix assignment
  planning.py             group sizes and survey skeleton
  validation.py           cleaning and validation of generated content
  examples.py             few-shot examples from examples/*.lss
  lss/                    builder, validator, reader
config/  templates/  examples/  tests/
```
