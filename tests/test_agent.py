"""Tests for the Interview Prep Agent.

External LLM calls are mocked so the tests remain deterministic
and do not require Groq API access.
"""

from unittest.mock import patch

from src.agent import analyze_skill_gap, run_pipeline
from src.models import InterviewPrepResult, SkillGapResult

ROLE_RESPONSE = """
{
    "role_title": "AI Engineer",
    "required_skills": ["Python", "Machine Learning", "SQL"],
    "requirements_markdown": "Strong Python, machine learning and SQL knowledge."
}
""".strip()


QUESTIONS_RESPONSE = """
1. [Python] Explain Python decorators.
2. [Machine Learning] What is overfitting?
3. [SQL] Explain SQL joins.
4. [Machine Learning] What is cross-validation?
5. [Python] Explain generators.
6. [Behavioral] Tell me about a difficult project.
7. [Behavioral] Describe a disagreement in a team.
8. [Behavioral] Tell me about a technical problem you solved.
""".strip()


ANSWERS_RESPONSE = """
1. Decorators modify the behavior of functions.
2. Overfitting occurs when a model learns training data too closely.
3. SQL joins combine rows from related tables.
4. Cross-validation evaluates a model across multiple data splits.
5. Generators produce values lazily using yield.
6. I would answer this using the STAR method.
7. I would explain the situation, action and outcome.
8. I would describe the problem, solution and measurable result.
""".strip()


STUDY_PLAN_RESPONSE = """
Day 1: Review Python and SQL fundamentals.
Day 2: Review machine-learning concepts and project explanations.
Day 3: Practice technical and behavioral interview questions.
""".strip()


@patch("src.agent._call_llm")
def test_run_pipeline_calls_llm_five_times(mock_call_llm):
    """The core pipeline should execute five LLM stages."""

    mock_call_llm.side_effect = [
        ROLE_RESPONSE,
        QUESTIONS_RESPONSE,
        QUESTIONS_RESPONSE,
        ANSWERS_RESPONSE,
        STUDY_PLAN_RESPONSE,
    ]

    result = run_pipeline("Sample AI Engineer job description")

    assert isinstance(result, InterviewPrepResult)
    assert mock_call_llm.call_count == 5


@patch("src.agent._call_llm")
def test_run_pipeline_returns_expected_fields(mock_call_llm):
    """Pipeline should return the expected structured result."""

    mock_call_llm.side_effect = [
        ROLE_RESPONSE,
        QUESTIONS_RESPONSE,
        QUESTIONS_RESPONSE,
        ANSWERS_RESPONSE,
        STUDY_PLAN_RESPONSE,
    ]

    result = run_pipeline("Sample AI Engineer job description")

    assert result.role_title == "AI Engineer"
    assert result.required_skills == [
        "Python",
        "Machine Learning",
        "SQL",
    ]

    assert result.requirements
    assert result.questions
    assert result.reviewed_questions
    assert result.answers
    assert result.study_plan


@patch("src.agent._call_llm")
def test_analyze_skill_gap_parses_valid_json(mock_call_llm):
    """Skill-gap JSON should be converted into SkillGapResult."""

    mock_call_llm.return_value = """
    {
        "matching_skills": ["Python", "SQL"],
        "missing_skills": ["Docker"],
        "priority_gap": "Docker",
        "priority_reason": "Docker is required by the target role.",
        "suggestion": "Learn Docker fundamentals and containerize a project."
    }
    """

    result = analyze_skill_gap(
        "Python and SQL experience",
        "Python, SQL and Docker required",
    )

    assert isinstance(result, SkillGapResult)

    assert result.matching_skills == [
        "Python",
        "SQL",
    ]

    assert result.missing_skills == [
        "Docker",
    ]

    assert result.priority_gap == "Docker"
    assert result.priority_reason
    assert result.suggestion


@patch("src.agent._call_llm")
def test_analyze_skill_gap_rejects_invalid_json(mock_call_llm):
    """Malformed structured output should fail cleanly."""

    mock_call_llm.return_value = "This is not JSON at all"

    try:
        analyze_skill_gap(
            "resume text",
            "job description text",
        )

    except RuntimeError as exc:
        assert "invalid structured response" in str(exc).lower()

    else:
        raise AssertionError(
            "Expected malformed LLM JSON to raise RuntimeError"
        )