"""LangGraph wiring of the generation pipeline.

    START -> plan -> question (loops once per question) -> format -> validate -> END

The loop is a conditional edge that routes back to ``question`` until every question has been
processed, so progress can be reported after each single question.
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from .models import Survey
from .pipeline import PipelineContext, fill_question, finish_llm_stages, format_survey, plan_survey, validate_output


class GraphState(TypedDict, total=False):
    """Data that flows through the graph. Every key a node returns must be declared here."""

    # inputs
    request: str
    total_questions: int
    per_group: Any            # int, "auto" or None (None = use settings)
    language: str
    allowed_types: list[str] | None
    # working data
    survey: Survey
    cursor: int               # index of the next question to process (flat order over all groups)
    # outputs
    lss_bytes: bytes
    issues: list[str]


def build_graph(ctx: PipelineContext):
    """Create and compile the graph. ``ctx`` is captured by the node functions (closure)."""

    def plan_node(state: GraphState) -> dict:
        survey = plan_survey(ctx, state["request"], state["total_questions"], state.get("per_group"),
                             state["language"], state.get("allowed_types"))
        return {"survey": survey, "cursor": 0}

    def question_node(state: GraphState) -> dict:
        survey: Survey = state["survey"]
        cursor = state["cursor"]
        pairs = list(survey.iter_questions())  # flat list: the loop walks all groups in order
        group, question = pairs[cursor]
        fill_question(ctx, survey, group, question)
        return {"cursor": cursor + 1}

    def route_after_question(state: GraphState) -> str:
        """Keep looping while questions are left, otherwise continue to the formatter."""
        return "question" if state["cursor"] < state["survey"].question_count else "format"

    def format_node(state: GraphState) -> dict:
        finish_llm_stages(ctx)
        return {"lss_bytes": format_survey(ctx, state["survey"])}

    def validate_node(state: GraphState) -> dict:
        return {"issues": validate_output(ctx, state["lss_bytes"])}

    graph = StateGraph(GraphState)
    graph.add_node("plan", plan_node)
    graph.add_node("question", question_node)
    graph.add_node("format", format_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "question")
    graph.add_conditional_edges("question", route_after_question, {"question": "question", "format": "format"})
    graph.add_edge("format", "validate")
    graph.add_edge("validate", END)
    return graph.compile()
