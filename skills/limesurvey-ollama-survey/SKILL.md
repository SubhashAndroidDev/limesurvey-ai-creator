---
name: limesurvey-ollama-survey
description: Generate a LimeSurvey survey file (.lss) from a plain-language description using any local Ollama model, fully offline with no API key. Use this skill whenever the user asks to create, generate, draft or build a survey, questionnaire or feedback form for LimeSurvey, wants a .lss file, mentions Ollama, a local LLM or offline survey generation, or wants to pick which local model writes the survey, even if they never say "skill" or "LimeSurvey" explicitly.
license: MIT
compatibility: Needs Python 3.10+, Ollama (recent version with structured-output support), and the limesurvey-ai-creator project with its dependencies installed.
---

# Generate LimeSurvey surveys with a local Ollama model

Turns a short request such as "customer satisfaction survey for a hotel" into an importable LimeSurvey `.lss` file. A local Ollama model writes the survey, and the project's `survey_creator` package builds and validates the file. Nothing is sent to an online service in this mode.

## 1. Locate the project

All commands run from the **project root**: the folder that contains `survey_creator/`, `config/` and `templates/`.

- If you are already inside it, continue.
- If this skill was installed on its own and the project is not on the machine, ask the user where it is or whether to clone it from its GitHub repository, then follow the install steps in the project's `README.md`.

## 2. Pre-flight checks

Check each item. Do not assume any of them.

1. **Dependencies installed.** `python -c "import survey_creator.service"` should run without error. If a module such as `langgraph` is missing, install with `pip install -r requirements.txt` (or `uv pip install -r requirements.txt`).
2. **Template present.** `templates/blank.lss` must exist. The builder reads it and fails with "Template .lss not found" if it is missing. If it is absent, tell the user to export an empty survey from LimeSurvey (Survey structure, `.lss`) and save it at that path.
3. **Ollama is running.** `ollama list` should work. If it cannot connect, start the server with `ollama serve`.
4. **A model is available.** See the next section.

## 3. Choose the Ollama model

Any model that Ollama can run may be used, but the project asks the model for JSON that matches a schema, so pick an instruction-tuned model.

- If the user named a model, use it. If it is not in `ollama list`, tell the user and ask before running `ollama pull <model>`, because downloads can be large.
- If they did not name one, use the project default from `config/settings.yaml` (`llm.model`), if installed. Otherwise pick the most capable installed instruction-tuned model and say which one you chose.
- Bigger models usually produce better and more valid surveys. Very small models can return invalid output. The project retries and has a fallback, but quality may suffer.

## 4. Gather the survey details

Take these from the user's message and ask only for what is missing, in one short question:

- **Request**: what the survey is about (required)
- **Number of questions** (`-n`, default 10, allowed range comes from `config/settings.yaml`)
- **Language code** (`-l`, for example `en`, `hi`, `es`; default from config)
- **Questions per group** (`-g`, a number or `auto`)
- **Question types** (`-t`, keys defined in `config/question_types.yaml`; omit to allow all)

## 5. Generate

Select Ollama with environment variables, which override `config/settings.yaml` without editing it:

macOS / Linux:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL="<model>" \
python -m survey_creator.cli "<request>" -n 10 -l en -g auto -o survey.lss
```

Windows PowerShell:

```powershell
$env:LLM_PROVIDER="ollama"; $env:OLLAMA_MODEL="<model>"
python -m survey_creator.cli "<request>" -n 10 -l en -g auto -o survey.lss
```

Notes:

- `OLLAMA_BASE_URL` defaults to `http://localhost:11434`. Set it only if Ollama runs elsewhere.
- Run `python -m survey_creator.cli --help` if you are unsure about a flag.
- Use a descriptive output name, for example `hotel-feedback.lss`. Do not overwrite an existing file without asking.
- Generation can take a while on a local model. Progress lines are printed per stage.

## 6. Check the result

Do not say the survey is ready until these pass.

1. The CLI printed `Saved <file>` and exited with code 0. Read any `warning:` lines and any `skipped failed questions:` line. Report them to the user.
2. The file is well-formed and has the expected size. Replace `survey.lss` with the output file:

   ```bash
   python - <<'EOF'
   from lxml import etree
   root = etree.parse("survey.lss").getroot()
   groups = root.findall("groups/rows/row")
   questions = root.findall("questions/rows/row")
   print("groups:", len(groups), "| questions:", len(questions))
   EOF
   ```

3. The question count is close to what was requested. If failed questions were skipped, the count will be lower, so say so.
4. Spot-check a few questions: language is right, no empty or duplicate questions, choice questions have answer options.

If it fails, retry once with a larger model or fewer questions per group, then report honestly what went wrong.

## 7. Report back

Tell the user:

- the output file path
- the Ollama model used
- how many groups and questions were generated
- any warnings or skipped questions
- how to import: LimeSurvey admin, **Surveys, Create a new survey, Import**, choose the `.lss` file

Remind them to read the questions before launching, since local models can make mistakes.

## Visual editor (optional)

If the user wants to review and edit groups and questions before exporting, start the Streamlit app and set the provider in the environment first:

```bash
LLM_PROVIDER=ollama OLLAMA_MODEL="<model>" streamlit run app.py
```

## Troubleshooting

| Message or symptom | What to do |
| --- | --- |
| `Cannot reach Ollama at ...` | Start Ollama with `ollama serve`; check `OLLAMA_BASE_URL` |
| `model '...' is missing. Run: ollama pull ...` | Pull the model or choose one from `ollama list` |
| `Template .lss not found` | Add `templates/blank.lss` (export an empty survey from LimeSurvey) |
| `Model returned invalid JSON` | Use a larger instruction-tuned model, update Ollama, or reduce questions per group |
| `GROQ_API_KEY is missing` | The provider is still `groq`. Set `LLM_PROVIDER=ollama` |
| Very slow output | Use a smaller model or fewer questions |

## Rules

- Keep everything local. Do not send survey content to an external service in this mode.
- Never print, request or store API keys here.
- Do not edit prompts in `config/prompts/` unless the user asks.
