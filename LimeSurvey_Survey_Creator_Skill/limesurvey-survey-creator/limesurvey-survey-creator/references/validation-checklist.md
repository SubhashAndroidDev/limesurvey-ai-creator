# Pre-export validation checklist

- [ ] Intake fields are captured: topic, audience, language, count, groups, supported types.
- [ ] Existing project skill and source mappings were inspected.
- [ ] Question count matches exactly; group headings are not counted as questions.
- [ ] Every group is named and used; each question belongs to one group.
- [ ] Question codes are valid and unique under the project's conventions.
- [ ] Type codes are confirmed by the current generator schema and builder.
- [ ] Required answers/subquestions exist, have unique codes, and have meaningful labels.
- [ ] No placeholder answer options or duplicate/near-duplicate questions.
- [ ] Mandatory flags and supported text constraints are preserved.
- [ ] Relevance references resolve to existing question/answer codes and conditions are syntactically supported.
- [ ] Unsupported constraints are reported instead of silently discarded.
- [ ] Existing validator/tests have been run when possible.
- [ ] Output exists, is non-empty XML, and has been import-tested in a LimeSurvey 6 staging instance if available.
- [ ] Final report distinguishes executed checks from checks not run.
