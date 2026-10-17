---
name: LimeSurvey Survey Creator
description: Plan, draft, validate, and generate LimeSurvey 6 surveys using the user's existing LimeSurvey AI Creator project and only its implemented question types.
---

# LimeSurvey Survey Creator

## Purpose and boundaries

Use this skill to turn a survey request or supplied questionnaire into a structured, reviewable survey plan and, when the user's project tools are available, a LimeSurvey 6 `.lss` file.

This skill is an instruction set for an AI coding agent. It does not itself contain the user's Python generator, LLM provider, validator, LimeSurvey instance, credentials, or execution environment. Never claim to have run local commands, tested an import, or created a file on the user's computer unless tool output proves that happened.

Prefer the existing project implementation over inventing a second generator. For the user's repository, the documented project root has been `D:\liveproject\limesurvey-ai-creator`, with CLI entry point `python -m survey_creator.cli` and skill path `skills/limesurvey-ollama-survey/SKILL.md`. If the current checkout differs, inspect it and use the actual paths.

## Intake: collect the survey brief

Before drafting questions, gather these fields. Ask concise follow-up questions for missing essentials; allow sensible defaults when the user asks you to proceed.

1. **Topic and goal** — what should the survey measure or help decide?
2. **Audience** — who will answer it and in what context?
3. **Language** — one primary LimeSurvey language (default to English only when reasonable). Do not assume a language code without checking the project's supported language configuration.
4. **Question count** — exact requested number, excluding group headings. Treat this as a hard constraint unless the user explicitly permits changes.
5. **Groups** — requested group names/order, or propose a small number of logical groups. Groups must contain questions; do not create decorative/empty groups unless the user requests them.
6. **Question types** — requested mix, if any. Resolve friendly labels to the generator's real type codes only after inspecting the CLI help, schemas, type map, themes, builder, and validator in the current checkout.
7. **Optional but useful** — required questions, branching/skip rules, sensitive-data handling, anonymity, source questionnaire, and whether the user wants a preview before file generation.

A compact intake prompt may be used:

- Topic/goal:
- Audience:
- Language:
- Exact question count:
- Groups (or “suggest them”):
- Preferred question types (or “use a balanced supported mix”):
- Required questions / branching / other constraints:
- Output path:

Do not repeatedly ask for details already supplied. If a missing detail is nonessential, state the assumption and continue.

## Workflow

### 1. Inspect the real implementation first

When filesystem/terminal access is available, inspect the repository and run the CLI help before generating:

- Read the existing skill file and preserve its rules.
- Inspect `pyproject.toml`, CLI argument parser, question schemas/classifier, type mappings/themes, LSS builder, validation code, and tests.
- Run `uv run python -m survey_creator.cli --help` from the project root.
- Determine the accepted language flags, question-type flags, group behavior, output argument, and provider requirements from the current implementation.
- If the environment is unavailable, ask the user to run these commands and paste the output. Do not guess that a type is supported merely because LimeSurvey itself supports it.

### 2. Build a survey blueprint before generating

Create a structured plan containing:

- survey title and purpose;
- language;
- ordered groups;
- each question's stable code, exact text, implemented type code, required flag, answer options and/or subquestions as appropriate;
- relevance condition, only when explicitly requested or logically necessary and unambiguous;
- a brief rationale for each question and a duplicate-check note.

Check that the planned question count exactly matches the requested count. Group headings do not count as questions. Show the plan for review if the user asks or if important assumptions/branching are ambiguous.

### 3. Write meaningful, non-duplicate questions

- Every question must contribute a distinct measurement or decision.
- Avoid paraphrase duplicates, repeated demographic questions, and multiple questions that collect the same information without a stated reason.
- Use one clear idea per question. Avoid leading, loaded, double-barrelled, or needlessly technical wording.
- Keep response options mutually exclusive where possible and collectively appropriate for the question.
- Include “Other (please specify)” only when appropriate and supported by the generator's schema.
- Include “None of the above” only when semantically valid and only apply exclusivity if the generator supports it.
- Never invent answers, placeholders, or options such as “Option 1”, “Option 2”.
- When transforming a supplied questionnaire, preserve its meaning, codes, options, mandatory markers, skip instructions, and order unless the user requests changes.
- If the user requests English-only output, omit non-English question text rather than creating bilingual text.

### 4. Preserve LimeSurvey-specific rules

Retain and apply these rules from the user's existing workflow where supported by the project:

- Real headings marked `[H]` start groups. If explicit headings are absent, infer a small number of coherent groups from topic flow.
- A question explicitly marked required/mandatory or with `*` is mandatory.
- Personal-data questions (for example name, phone, or email) should be flagged for privacy review and encrypted only if the existing project has a verified encryption feature/configuration. Do not pretend ordinary `.lss` export guarantees encryption.
- Preserve “ask if” / skip instructions as relevance equations when the condition is clear and the generator supports the referenced question/answer codes.
- Preserve minimum/maximum text lengths only when the current generator schema and LSS builder implement them; otherwise report the limitation rather than silently dropping the constraint.
- “Other (please specify)” maps to the project's supported other-answer mechanism; “None of the above” maps to an exclusive option only if implemented.
- Explicit single-choice versus multiple-choice wording takes precedence over inference.
- Lines beginning with checkbox markers such as `☐` are candidate answer options, not separate questions, unless the source context clearly indicates otherwise.
- Matrix/rating questions must use actual supported subquestion/answer structures; do not fabricate a matrix type if the generator cannot emit it.
- Preserve the user's requested question order and group order.

These rules do not override the actual schema. If a rule cannot be represented by the current generator, identify it as unsupported and offer the nearest supported alternative for approval.

### 5. Use only question types implemented by the user's generator

The generator has previously used internal type codes such as `L`, `M`, `T`, `F`, and `5`, with themes such as `listradio`, `multiplechoice`, `longfreetext`, `array`, and `5pointchoice` described in project context. Treat this as a hint, not a guaranteed current type catalogue. Inspect the current checkout and use its exact enum/type map, schema, themes, and builder mappings.

Do not assume all LimeSurvey question types are available. In particular, do not map short text, numeric input, date, ranking, array, or matrix to a similar-looking type unless the current implementation explicitly supports that mapping. If the CLI accepts `-t`, use only its documented values.

### 6. Validate before exporting

Run the repository's validator and tests where possible. At minimum, inspect these invariants:

**Survey structure**
- Survey title is non-empty and the language is supported by the target instance/config.
- Group names are non-empty, unique after normalization, ordered correctly, and referenced consistently.
- Every question belongs to exactly one existing group.
- Question count equals the user's requested count.
- Question codes are non-empty, valid under project conventions, unique case-insensitively, and safe for LimeSurvey/ExpressionScript conventions.

**Question type and content**
- Every type code exists in the current generator's supported mapping.
- Types requiring answers have non-empty, unique answer codes and non-empty labels.
- Types requiring subquestions have non-empty, unique subquestion codes and labels.
- Do not attach answer options or subquestions to types that do not accept them.
- Required/mandatory settings follow the source and user request.
- Answer and subquestion codes satisfy any project/LimeSurvey length limits documented in the implementation.

**Relevance / branching**
- Every referenced question and answer/subquestion code exists.
- Conditions use valid syntax for the generator's supported expression format.
- No self-reference, unknown reference, or obvious circular dependency.
- A relevance condition does not reference a question that cannot be answered earlier in the survey, unless the project's supported design explicitly permits it.
- Do not invent a condition when the intended logic is ambiguous; ask or mark it for review.

**Quality**
- No duplicate or near-duplicate question text after normalization.
- No placeholder answers.
- Every group has a purpose.
- Language is consistent.
- Sensitive-data collection is justified and clearly labelled where appropriate.

If validation fails, fix the blueprint and regenerate; do not deliver a known-invalid artifact as valid.

### 7. Generate using the real CLI/backend

When local execution is available, use the project's own CLI and inspect its actual `--help` first. The documented example has been:

`uv run python -m survey_creator.cli "customer satisfaction survey for a hotel" -n 5 -o hotel.lss`

The project documentation describes options for question count (`-n`), questions per group (`-g`), language (`-l`), question types (`-t`), and output (`-o`), but confirm the current CLI syntax before use.

- Keep API keys in the user's local `.env`; never request them in chat, print them, or commit them.
- The project has documented Ollama and Groq providers. Do not claim OpenAI API support unless the current code proves it has been implemented.
- Run the existing validator and relevant tests after generation.
- Inspect the output file exists, is non-empty, and is well-formed XML. Prefer the project's own structural validator and, where available, import it into a LimeSurvey 6 staging instance to confirm compatibility.
- A well-formed XML file is not proof that LimeSurvey will import it successfully.
- Do not activate or publish a survey, send invitations, or modify a production LimeSurvey instance without explicit user authorization.

When local execution is not available, provide the exact command for the user to run and state clearly that it has not been executed. You may provide the blueprint, validation checklist, and troubleshooting help without claiming a generated `.lss` exists.

### 8. Deliverables and final report

Return:
1. Survey brief summary and assumptions.
2. Group/question outline with type codes.
3. Exact requested count check.
4. Validation status, including any checks not run.
5. `.lss` file path/link only if the file was actually generated and its exact path is verified.
6. Known unsupported requirements or manual follow-up steps.

Distinguish:
- **Instruction-only:** intake, question design, de-duplication, blueprint, and review checklist.
- **Requires repository/backend:** inspect real type mappings, call the configured LLM, run Python CLI, execute validators/tests, write the `.lss`, and test import in LimeSurvey.
- **Requires live LimeSurvey access/credentials:** importing to an instance, activating, publishing, or managing responses.

## Safety and privacy

Collect only data needed for the survey purpose. Warn the user when collecting identifiable or sensitive data. Never place API keys, passwords, session cookies, or personal respondent data in generated documentation or logs. Do not say data is encrypted unless a verified implementation actually encrypts it.

## Example request

“Create a customer satisfaction survey for hotel guests in English, exactly 12 questions, grouped into Stay, Staff, Facilities, and Overall Feedback. Use a balanced mix of question types supported by my generator. Make questions distinct, include appropriate answer choices, and use a relevance condition only where it is clear. Validate it and generate `hotel_satisfaction.lss` using my project CLI.”
