# LimeSurvey AI Creator

Describe a survey in plain language and let an AI model build it. The app plans question groups, writes the questions one by one, checks the result and exports a `.lss` file that you can import into [LimeSurvey](https://www.limesurvey.org/).

Two model back ends are supported:

- **Ollama**: a local model on your own machine, no API key
- **Groq**: a hosted model, needs a Groq API key

You can use it from a **Streamlit web app** or from the **command line**.

## Features

- Groups appear first, then questions arrive one by one. Edit or delete them while the rest are being written
- Sidebar options: language, number of questions, questions per group, question types
- Preview and edit survey title, messages, groups, questions and answer options
- Validation of the generated `.lss` file and retry/fallback when a model answers badly
- Saved drafts in `data/surveys/`
- Few-shot examples: put real `.lss` exports in `examples/` to improve question style
- Behaviour is configured in `config/` (YAML and prompt text files), not hard-coded

## Requirements

- Python 3.10 or newer
- For local models: [Ollama](https://ollama.com/download) (use a recent version, the app asks models for JSON that follows a schema)
- For Groq: an API key from <https://console.groq.com/keys>

## Installation

```bash
git clone https://github.com/<your-username>/limesurvey-ai-creator.git
cd limesurvey-ai-creator

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

With `uv`:

```bash
uv venv
uv pip install -r requirements.txt
```

## Configuration

### Choose the model provider

Default values are in `config/settings.yaml`. Environment variables override them, so you can switch without editing files.

| Variable | Meaning | Default (from `settings.yaml`) |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` or `groq` | `groq` |
| `OLLAMA_MODEL` | Ollama model name | `qwen2.5:7b-instruct` |
| `OLLAMA_BASE_URL` | Ollama server address | `http://localhost:11434` |
| `GROQ_API_KEY` | Groq API key (secret) | none |
| `GROQ_MODEL` | Groq model name | `openai/gpt-oss-120b` |
| `SURVEY_CONFIG_DIR` | Use a different config folder | `config/` |

Put them in a `.env` file in the project root (loaded automatically):

```bash
cp .env.example .env
```

### Option A: Ollama (local)

```bash
ollama serve                         # if it is not already running
ollama pull qwen2.5:7b-instruct      # or any instruction-tuned model you prefer
```

Then in `.env`:

```env
LLM_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b-instruct
```

Any model available in `ollama list` can be used by changing `OLLAMA_MODEL`. Larger models usually give better surveys.

### Option B: Groq (cloud)

In `.env`:

```env
LLM_PROVIDER=groq
GROQ_API_KEY=your_key_here
```

Never commit `.env`. It is listed in `.gitignore`. If `tokens_per_minute` in `config/settings.yaml` does not match your Groq plan, adjust it to avoid rate limits.

### LimeSurvey template

The builder starts from `templates/blank.lss`, an empty survey exported from LimeSurvey. Keep that file in the repo. To use your own, export a blank survey from LimeSurvey (Survey structure, `.lss`) and set `template.file` in `config/settings.yaml`.

## Usage

### Web app

```bash
streamlit run app.py
```

Open the address printed in the terminal (usually <http://localhost:8501>), describe your survey, choose options in the sidebar and click **Generate survey**. Edit the preview, then download the `.lss` when at least one question is complete.

### Command line

```bash
python -m survey_creator.cli "customer satisfaction survey for a hotel" -n 10 -o hotel.lss
```

| Option | Meaning |
| --- | --- |
| `request` | What the survey is about |
| `-n`, `--questions` | Number of questions (default 10) |
| `-g`, `--per-group` | Questions per group: a number or `auto` |
| `-l`, `--language` | Language code, for example `en`, `hi` |
| `-t`, `--types` | Allowed question type keys (see `config/question_types.yaml`) |
| `-o`, `--output` | Output file (default `survey.lss`) |

Use a specific local model for one run:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL=llama3.1:8b python -m survey_creator.cli "mobile app feedback" -n 8 -o app.lss
```

On Windows PowerShell: `$env:LLM_PROVIDER="ollama"; $env:OLLAMA_MODEL="llama3.1:8b"` before the command.

## Import into LimeSurvey

LimeSurvey admin, **Surveys, Create a new survey, Import**, then choose the `.lss` file.

## Use as an agent skill (Claude Code, Codex)

`skills/limesurvey-ollama-survey/SKILL.md` lets an AI coding agent generate surveys with any local Ollama model. Copy the folder into your agent's skills directory and restart it:

```bash
# Claude Code (all projects)
cp -r skills/limesurvey-ollama-survey ~/.claude/skills/

# Codex CLI
cp -r skills/limesurvey-ollama-survey ~/.codex/skills/
```

Then ask, for example: "Create a 10 question employee feedback survey for LimeSurvey using my local Ollama model."

## Project structure

```
limesurvey-ai-creator/
├── app.py                    # Streamlit app
├── config/
│   ├── settings.yaml         # provider, models, limits, template
│   ├── defaults.yaml         # defaults for generated questions
│   ├── question_types.yaml   # supported question types
│   └── prompts/              # planner.txt, question.txt, options.txt
├── examples/                 # real .lss exports used as few-shot examples
├── templates/blank.lss       # empty survey used as the base file
├── data/surveys/             # saved drafts (not committed)
├── skills/                   # agent skill (SKILL.md)
└── survey_creator/
    ├── cli.py                # command line interface
    ├── service.py            # high-level generate API
    ├── pipeline.py, graph.py # generation workflow
    ├── agents.py, planning.py, intent.py, fallback.py
    ├── llm.py                # Ollama and Groq clients
    ├── lss/                  # builder, reader, validator
    └── config.py, models.py, schemas.py, storage.py, validation.py ...
```

## Troubleshooting

| Message | What to do |
| --- | --- |
| `GROQ_API_KEY is missing` | Add the key to `.env`, or set `LLM_PROVIDER=ollama` |
| `Cannot reach Ollama at ...` | Start Ollama (`ollama serve`) and check `OLLAMA_BASE_URL` |
| `model '...' is missing. Run: ollama pull ...` | Run the pull command or change `OLLAMA_MODEL` |
| `Template .lss not found` | Make sure `templates/blank.lss` exists |
| `Model returned invalid JSON` | Use a larger instruction-tuned model or update Ollama |

## Security

- Keep API keys in `.env` only, never in code or commits
- If a key was ever committed, revoke it in the Groq console and create a new one
- Read generated questions before publishing a survey

## License

MIT. See [LICENSE](LICENSE).