from survey_creator.config import QuestionTypeSpec
from survey_creator.fallback import apply_fallback
from survey_creator.models import Group, Question, Survey
from survey_creator.validation import options_problems


def make_spec(code="L", needs_answers=True, needs_subquestions=False):
    return QuestionTypeSpec(
        key="test_type",
        label="Test type",
        code=code,
        theme="listradio",
        description="Test question type",
        weight=1,
        enabled=True,
        answers_min=3 if needs_answers else 0,
        answers_max=7 if needs_answers else 0,
        subq_min=3 if needs_subquestions else 0,
        subq_max=8 if needs_subquestions else 0,
    )


def test_placeholder_answer_options_are_rejected():
    spec = make_spec()
    problems = options_problems(spec, ["Option 1", "Option 2", "Option 3"], [])
    assert any("generic placeholder" in problem for problem in problems)


def test_placeholder_subquestions_are_rejected():
    spec = make_spec(code="M", needs_answers=False, needs_subquestions=True)
    problems = options_problems(spec, [], ["Item 1", "Item 2", "Row 3"])
    assert sum("generic placeholder" in problem for problem in problems) == 3


def test_fallback_preserves_generated_question_and_uses_device_choices():
    survey = Survey(title="Chromium Browser Survey", request="Create a survey about Chromium browser usage")
    group = Group(name="Devices and Platforms")
    question = Question(
        code="Q001",
        type_key="single_choice",
        text="Which devices do you regularly use to access the Chromium browser?",
    )
    apply_fallback(survey, group, question, make_spec())
    assert question.text == "Which devices do you regularly use to access the Chromium browser?"
    assert "Desktop or laptop" in question.answers
    assert "Android phone" in question.answers
    assert not any("Option " in answer for answer in question.answers)


def test_fallback_never_pads_with_numbered_placeholders():
    spec = make_spec()
    spec = QuestionTypeSpec(
        key=spec.key,
        label=spec.label,
        code=spec.code,
        theme=spec.theme,
        description=spec.description,
        weight=spec.weight,
        enabled=spec.enabled,
        answers_min=6,
        answers_max=7,
    )
    survey = Survey(title="Test survey")
    group = Group(name="Test section")
    question = Question(code="Q001", type_key="test_type")
    apply_fallback(survey, group, question, spec)
    assert len(question.answers) >= 6
    assert not any(answer.startswith("Option ") for answer in question.answers)
