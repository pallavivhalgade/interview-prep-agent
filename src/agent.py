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

Each step's output is fed as input into the next step - this chaining,
plus the Reviewer step critiquing another step's output, is what makes
this genuinely "agentic" rather than a single one-shot prompt.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

from src.models import InterviewPrepResult, SkillGapResult
from src.prompts import (
    EXTRACT_REQUIREMENTS_PROMPT,
    GENERATE_QUESTIONS_PROMPT,
    REVIEW_QUESTIONS_PROMPT,
    GENERATE_ANSWERS_PROMPT,
    GENERATE_STUDY_PLAN_PROMPT,
    SKILL_GAP_PROMPT,
)

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
MODEL = "llama-3.1-8b-instant"  # free, fast Groq model


def _call_llm(system_prompt: str, user_prompt: str) -> str:
    """Single helper so every step calls the LLM the same way."""
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.4,
    )
    return response.choices[0].message.content


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
    requirements = extract_requirements(job_description)
    questions = generate_questions(requirements)
    reviewed_questions = review_questions(questions)
    answers = generate_answers(reviewed_questions)
    study_plan = generate_study_plan(requirements)

    return InterviewPrepResult(
        requirements=requirements,
        questions=questions,
        reviewed_questions=reviewed_questions,
        answers=answers,
        study_plan=study_plan,
    )


def analyze_skill_gap(resume_text: str, job_description: str) -> SkillGapResult:
    """Compares resume text against the JD and returns a structured
    breakdown of matching skills, missing skills, and one suggestion.

    Asks the LLM for JSON so we can parse it reliably instead of
    guessing at text structure. Falls back gracefully if the LLM
    doesn't return valid JSON (rare, but LLMs aren't 100% reliable
    about format instructions)."""
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
        return SkillGapResult(
            matching_skills=raw_output,
            missing_skills="(could not parse structured response)",
            suggestion="",
        )
