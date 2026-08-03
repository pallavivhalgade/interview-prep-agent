"""
Tests for src/agent.py.

The LLM call (_call_llm) is mocked throughout - these tests check OUR
logic (pipeline step ordering, JSON parsing, fallback handling), not
Groq's API. That distinction matters: we're testing that our code
handles the LLM's response correctly, not testing the LLM itself.
"""

from unittest.mock import patch

from src.agent import run_pipeline, analyze_skill_gap
from src.models import InterviewPrepResult, SkillGapResult


@patch("src.agent._call_llm")
def test_run_pipeline_calls_llm_five_times(mock_call_llm):
    """5 pipeline steps: requirements, questions, review, answers, study plan."""
    mock_call_llm.return_value = "mocked response"

    result = run_pipeline("Sample job description")

    assert mock_call_llm.call_count == 5
    assert isinstance(result, InterviewPrepResult)


@patch("src.agent._call_llm")
def test_run_pipeline_returns_expected_fields(mock_call_llm):
    mock_call_llm.return_value = "mocked response"

    result = run_pipeline("Sample job description")

    assert result.requirements == "mocked response"
    assert result.reviewed_questions == "mocked response"
    assert result.answers == "mocked response"
    assert result.study_plan == "mocked response"


@patch("src.agent._call_llm")
def test_analyze_skill_gap_parses_valid_json(mock_call_llm):
    mock_call_llm.return_value = (
        '{"matching_skills": "Python, SQL", '
        '"missing_skills": "Docker", '
        '"suggestion": "Learn Docker basics"}'
    )

    result = analyze_skill_gap("resume text", "job description text")

    assert isinstance(result, SkillGapResult)
    assert result.matching_skills == "Python, SQL"
    assert result.missing_skills == "Docker"
    assert result.suggestion == "Learn Docker basics"


@patch("src.agent._call_llm")
def test_analyze_skill_gap_falls_back_on_invalid_json(mock_call_llm):
    """If the LLM doesn't return valid JSON, we should not crash - we
    fall back to showing the raw text instead of an error."""
    mock_call_llm.return_value = "This is not JSON at all"

    result = analyze_skill_gap("resume text", "job description text")

    assert isinstance(result, SkillGapResult)
    assert result.matching_skills == "This is not JSON at all"
    assert "could not parse" in result.missing_skills
