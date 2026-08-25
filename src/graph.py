"""LangGraph orchestration for the Interview Prep Agent."""

from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from src.agent import (
    _call_llm,
    _validate_questions,
    analyze_role,
    generate_answers,
    generate_questions,
    generate_study_plan,
)
from src.models import InterviewPrepResult
from src.prompts import REVIEW_QUESTIONS_PROMPT

MAX_REVIEW_ATTEMPTS = 2


class InterviewState(TypedDict, total=False):
    job_description: str
    focus_context: str
    role_title: str
    required_skills: list[str]
    requirements: str
    questions: str
    reviewed_questions: str
    answers: str
    study_plan: str
    review_attempts: int
    review_passed: bool


def analyze_role_node(state: InterviewState) -> dict:
    role_title, required_skills, requirements = analyze_role(
        state["job_description"]
    )
    return {
        "role_title": role_title,
        "required_skills": required_skills,
        "requirements": requirements,
    }


def generate_questions_node(state: InterviewState) -> dict:
    questions = generate_questions(
        requirements=state["requirements"],
        required_skills=state["required_skills"],
        focus_context=state.get("focus_context", ""),
    )
    return {"questions": questions}


def review_questions_node(state: InterviewState) -> dict:
    reviewed = _call_llm(
        REVIEW_QUESTIONS_PROMPT,
        state["questions"],
        max_tokens=2300,
    )

    attempts = state.get("review_attempts", 0) + 1
    review_passed = _validate_questions(reviewed)

    if not review_passed:
        reviewed = state["questions"]

    return {
        "reviewed_questions": reviewed,
        "review_attempts": attempts,
        "review_passed": review_passed,
    }


def route_after_review(state: InterviewState) -> str:
    if state.get("review_passed", False):
        return "continue"
    if state.get("review_attempts", 0) >= MAX_REVIEW_ATTEMPTS:
        return "continue"
    return "regenerate"


def generate_answers_node(state: InterviewState) -> dict:
    final_questions = state.get("reviewed_questions") or state["questions"]
    answers = generate_answers(
        final_questions,
        focus_context=state.get("focus_context", ""),
    )
    return {"answers": answers}


def generate_study_plan_node(state: InterviewState) -> dict:
    study_plan = generate_study_plan(
        role_title=state["role_title"],
        requirements=state["requirements"],
        required_skills=state["required_skills"],
        focus_context=state.get("focus_context", ""),
    )
    return {"study_plan": study_plan}


def build_interview_graph():
    workflow = StateGraph(InterviewState)

    workflow.add_node("analyze_role", analyze_role_node)
    workflow.add_node("generate_questions", generate_questions_node)
    workflow.add_node("review_questions", review_questions_node)
    workflow.add_node("generate_answers", generate_answers_node)
    workflow.add_node("generate_study_plan", generate_study_plan_node)

    workflow.add_edge(START, "analyze_role")
    workflow.add_edge("analyze_role", "generate_questions")
    workflow.add_edge("generate_questions", "review_questions")

    workflow.add_conditional_edges(
        "review_questions",
        route_after_review,
        {
            "regenerate": "generate_questions",
            "continue": "generate_answers",
        },
    )

    workflow.add_edge("generate_answers", "generate_study_plan")
    workflow.add_edge("generate_study_plan", END)

    return workflow.compile()


interview_graph = build_interview_graph()


def run_graph_pipeline(
    job_description: str,
    focus_context: str = "",
) -> InterviewPrepResult:
    if not job_description or not job_description.strip():
        raise RuntimeError("Job description cannot be empty.")

    initial_state: InterviewState = {
        "job_description": job_description.strip(),
        "focus_context": focus_context,
        "review_attempts": 0,
        "review_passed": False,
    }

    final_state = interview_graph.invoke(initial_state)

    return InterviewPrepResult(
        role_title=final_state.get("role_title", "Target Role"),
        required_skills=final_state.get("required_skills", []),
        requirements=final_state.get("requirements", ""),
        questions=final_state.get("questions", ""),
        reviewed_questions=final_state.get(
            "reviewed_questions",
            final_state.get("questions", ""),
        ),
        answers=final_state.get("answers", ""),
        study_plan=final_state.get("study_plan", ""),
    )
