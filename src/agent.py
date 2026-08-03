"""
Interview Prep Agent - core logic.

A 5-step agentic pipeline:
  1. Extract key skills/requirements from a job description
  2. Generate likely interview questions based on those skills
  3. Review Agent: critique and sharpen the questions
  4. Generate sample strong answers / frameworks for the reviewed questions
  5. Generate a short study plan

Plus a separate skill gap analysis function that compares an uploaded
resume against the job description.
"""

import json
from groq import Groq

from src.config import GROQ_API_KEY, LLM_MODEL, LLM_TEMPERATURE
from src.logger import get_logger
from src.models import InterviewPrepResult, SkillGapResult
from src.prompts import (
    EXTRACT_REQUIREMENTS_PROMPT,
    GENERATE_QUESTIONS_PROMPT,
    REVIEW_QUESTIONS_PROMPT,
    GENERATE_ANSWERS_PROMPT,
    GENERATE_STUDY_PLAN_PROMPT,
    SKILL_GAP_PROMPT,
)

logger = get_logger(__name__)
client = Groq(api_key=GROQ_API_KEY)


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Single helper so every step calls the LLM the same way, with
    logging and a friendly error message if the call fails."""
    logger.info(f"Calling LLM | prompt_preview='{system_prompt[:50]}...'")
    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=LLM_TEMPERATURE,
        )
        logger.info("LLM call succeeded")
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise RuntimeError(
            "Something went wrong generating this section. Please try again."
        ) from e


def extract_requirements(job_description: str) -> str:
    """Step 1: Pull out the key skills/requirements from the JD."""
    return _call_llm(EXTRACT_REQUIREMENTS_PROMPT, job_description)


def generate_questions(requirements: str) -> str:
    """Step 2: Generate likely interview questions from the requirements."""
    return _call_llm(GENERATE_QUESTIONS_PROMPT, requirements)


def review_questions(questions: str) -> str:
    """Step 3: Reviewer Agent - critiques and sharpens the question list
    before it's used downstream."""
    return _call_llm(REVIEW_QUESTIONS_PROMPT, questions)


def generate_answers(questions: str) -> str:
    """Step 4: Generate a sample strong answer/framework for each question."""
    return _call_llm(GENERATE_ANSWERS_PROMPT, questions)


def generate_study_plan(requirements: str) -> str:
    """Step 5: Generate a short pre-interview study plan."""
    return _call_llm(GENERATE_STUDY_PLAN_PROMPT, requirements)


def run_pipeline(job_description: str) -> InterviewPrepResult:
    """Runs all 5 steps in sequence and returns a structured result."""
    logger.info("Starting interview prep pipeline")

    requirements = extract_requirements(job_description)
    questions = generate_questions(requirements)
    reviewed_questions = review_questions(questions)
    answers = generate_answers(reviewed_questions)
    study_plan = generate_study_plan(requirements)

    logger.info("Pipeline completed successfully")

    return InterviewPrepResult(
        requirements=requirements,
        questions=questions,
        reviewed_questions=reviewed_questions,
        answers=answers,
        study_plan=study_plan,
    )


def analyze_skill_gap(resume_text: str, job_description: str) -> SkillGapResult:
    """Compares resume text against the JD and returns a structured
    breakdown of matching skills, missing skills, and one suggestion."""
    logger.info("Running skill gap analysis")
    combined_input = f"RESUME:\n{resume_text}\n\nJOB DESCRIPTION:\n{job_description}"
    raw_output = _call_llm(SKILL_GAP_PROMPT, combined_input)

    try:
        parsed = json.loads(raw_output)
        return SkillGapResult(
            matching_skills=parsed.get("matching_skills", ""),
            missing_skills=parsed.get("missing_skills", ""),
            suggestion=parsed.get("suggestion", ""),
        )
    except json.JSONDecodeError:
        logger.warning("Skill gap response wasn't valid JSON, returning raw text")
        return SkillGapResult(
            matching_skills=raw_output,
            missing_skills="(could not parse structured response)",
            suggestion="",
        )