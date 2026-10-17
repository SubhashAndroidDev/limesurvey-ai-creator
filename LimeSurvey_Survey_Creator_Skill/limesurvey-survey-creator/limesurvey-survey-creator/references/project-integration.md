# Project integration contract

This skill expects the agent to use the repository's existing implementation instead of creating a parallel generator.

## Inspect these components in the current checkout

- Existing skill: `skills/limesurvey-ollama-survey/SKILL.md`
- CLI: `survey_creator.cli` and its argument parser
- Configuration: `config/settings.yaml`, `.env.example`, and provider code
- Question schema/classifier and type map
- LSS builder/template
- Validation code and tests

Names may differ by checkout; locate them rather than assuming.

## Type allow-list

Never maintain a guessed static list of all LimeSurvey types. Derive the allow-list from the actual schema/enums, CLI `--help`, classifier prompts, type-to-theme mappings, builder implementation, and tests. All these layers should agree. A type accepted by an LLM prompt but not emitted by the builder is not supported.

## Relevance conditions

Use the exact syntax expected by the project and verify every referenced code. Preserve source conditions only when they can be represented safely. If a condition needs an unsupported question type or unknown answer code, report it and request a decision rather than guessing.

## Output validation levels

1. **Blueprint validation:** count, groups, uniqueness, type allow-list, options/subquestions, references.
2. **Generator validation:** existing project validator and tests.
3. **File validation:** exact file exists, XML parses, output is non-empty.
4. **Import validation:** import into a LimeSurvey 6 staging instance and verify language and question structure.

Report each level separately. Never describe level 1 or 3 as proof that level 4 passed.
