"""Pydantic schemas describing what the LLM must return (structured JSON output)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class GroupPlan(BaseModel):
    """One group (section) proposed by the planner."""

    name: str = Field(description="Short group name, max 6 words.")
    description: str = Field(default="", description="One sentence about what the group covers.")


class SurveyPlan(BaseModel):
    """Skeleton of the survey produced by the 'Survey Planner' agent."""
    # The planner prompt returns ``is_survey_request``; when it is false the pipeline raises
    is_survey_request: bool = Field(default=True, description="true if the user wants a survey on some topic; false if they ask for anything else.")
    reason: str = Field(default="", description="One short sentence, only when is_survey_request is false.")
    
    title: str = Field(description="Short professional survey title.")
    description: str = Field(default="", description="Purpose of the survey for the administrator.")
    welcome_text: str = Field(default="", description="Welcome message shown to respondents.")
    end_text: str = Field(default="", description="Thank-you message shown at the end.")
    groups: list[GroupPlan] = Field(default_factory=list, description="Ordered list of groups.")


class QuestionDraft(BaseModel):
    """Question text produced by the 'Question Generator' agent."""

    text: str = Field(description="The question shown to the respondent.")
    help: str = Field(default="", description="Optional one-sentence help text.")


class OptionsDraft(BaseModel):
    """Answer structure produced by the 'Answer Options' agent."""

    answers: list[str] = Field(default_factory=list, description="Answer choices / matrix columns.")
    subquestions: list[str] = Field(default_factory=list, description="Options / matrix rows / text boxes.")
