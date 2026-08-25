"""Core agentic pipeline for Interview Prep Agent."""

import json
import re

from groq import Groq

from src.config import GROQ_API_KEY, LLM_MODEL, LLM_TEMPERATURE
from src.logger import get_logger
from src.models import InterviewPrepResult, SkillGapResult
from src.prompts import (
    ANALYZE_ROLE_PROMPT,
    GENERATE_QUESTIONS_PROMPT,
    REVIEW_QUESTIONS_PROMPT,
    GENERATE_ANSWERS_PROMPT,
    GENERATE_STUDY_PLAN_PROMPT,
    SKILL_GAP_PROMPT,
)

logger = get_logger(__name__)
client = Groq(api_key=GROQ_API_KEY)


def _call_llm(instruction: str, input_text: str, max_tokens: int = 3000) -> str:
    """Call Groq using one user message for reliable GPT-OSS behavior."""
    if not input_text or not str(input_text).strip():
        raise RuntimeError("The AI step received empty input.")

    prompt = f"""TASK INSTRUCTIONS:
{instruction}

INPUT:
{input_text}

Follow the requested output format exactly.
Do not ask the user for more information.
Return the final requested content only.
"""

    logger.info(
        "Calling LLM | model=%s | input_chars=%s | prompt_preview='%s...'",
        LLM_MODEL,
        len(str(input_text)),
        instruction.strip()[:60],
    )

    try:
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=LLM_TEMPERATURE,
            max_tokens=max_tokens,
        )

        content = response.choices[0].message.content

        if content is None or not str(content).strip():
            raise RuntimeError("The AI returned an empty response.")

        content = str(content).strip()

        logger.info(
            "LLM call succeeded | output_chars=%s | preview='%s...'",
            len(content),
            content[:100].replace("\n", " "),
        )

        return content

    except RuntimeError:
        raise
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        raise RuntimeError(
            "Something went wrong generating this section. Please try again."
        ) from exc


def _clean_json_text(raw: str) -> str:
    text = raw.strip()

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    return text.strip()


def _parse_json(raw: str) -> dict:
    try:
        return json.loads(_clean_json_text(raw))
    except json.JSONDecodeError as exc:
        logger.error("Invalid JSON from LLM: %s", raw[:500])
        raise RuntimeError(
            "The AI returned an invalid structured response. Please generate again."
        ) from exc


def _parse_numbered_items(text: str) -> list[tuple[int, str]]:
    items = []

    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)[\.\)]\s+(.+)$", line.strip())
        if match:
            items.append((int(match.group(1)), match.group(2).strip()))

    return items


def _validate_questions(text: str) -> bool:
    items = _parse_numbered_items(text)

    if not 6 <= len(items) <= 10:
        return False

    if not all("[" in item and "]" in item for _, item in items):
        return False

    return True


def _validate_answers(questions: str, answers: str) -> bool:
    question_items = _parse_numbered_items(questions)
    answer_items = _parse_numbered_items(answers)

    if not question_items or len(question_items) != len(answer_items):
        return False

    q_numbers = [number for number, _ in question_items]
    a_numbers = [number for number, _ in answer_items]

    return q_numbers == a_numbers


def analyze_role(job_description: str) -> tuple[str, list[str], str]:
    """Extract role title, required skills, and responsibility-level requirements."""
    raw = _call_llm(
        ANALYZE_ROLE_PROMPT,
        job_description,
        max_tokens=2200,
    )
    data = _parse_json(raw)

    role_title = str(data.get("role_title") or "Target Role").strip()

    required_skills = data.get("required_skills") or []
    if not isinstance(required_skills, list):
        required_skills = [str(required_skills)]

    required_skills = [
        str(skill).strip()
        for skill in required_skills
        if str(skill).strip()
    ]

    requirements = str(
        data.get("requirements_markdown") or ""
    ).strip()

    return role_title, required_skills, requirements


def generate_questions(
    requirements: str,
    required_skills: list[str],
    focus_context: str = "",
) -> str:
    """Generate 6-10 high-value questions; retry once if format is poor."""
    input_text = (
        f"ROLE REQUIREMENTS:\n{requirements}\n\n"
        f"REQUIRED SKILLS:\n{', '.join(required_skills)}"
    )

    if focus_context:
        input_text += f"\n\nCANDIDATE FOCUS CONTEXT:\n{focus_context}"

    questions = _call_llm(
        GENERATE_QUESTIONS_PROMPT,
        input_text,
        max_tokens=2300,
    )

    if not _validate_questions(questions):
        logger.warning("Question output failed validation; retrying once")

        questions = _call_llm(
            GENERATE_QUESTIONS_PROMPT
            + "\nIMPORTANT: Return 6-10 numbered questions in the exact [Domain] format.",
            input_text,
            max_tokens=2300,
        )

    if not _validate_questions(questions):
        raise RuntimeError(
            "The AI did not return a valid high-priority interview-question set."
        )

    return questions


def review_questions(questions: str) -> str:
    """Review questions while preserving a valid 6-10 question set."""
    reviewed = _call_llm(
        REVIEW_QUESTIONS_PROMPT,
        questions,
        max_tokens=2300,
    )

    if not _validate_questions(reviewed):
        logger.warning(
            "Reviewer output failed validation; using original valid questions"
        )
        return questions

    return reviewed


def generate_answers(questions: str) -> str:
    """Generate exactly one answer per final question."""
    answers = _call_llm(
        GENERATE_ANSWERS_PROMPT,
        questions,
        max_tokens=4200,
    )

    if not _validate_answers(questions, answers):
        logger.warning("Answer count mismatch; retrying once")

        answers = _call_llm(
            GENERATE_ANSWERS_PROMPT
            + "\nIMPORTANT: Answer every numbered question exactly once.",
            questions,
            max_tokens=4200,
        )

    if not _validate_answers(questions, answers):
        raise RuntimeError(
            "The AI did not return one answer for every interview question."
        )

    return answers


def generate_study_plan(
    role_title: str,
    requirements: str,
    required_skills: list[str],
    focus_context: str = "",
) -> str:
    """Generate a detailed, actionable 3-day plan."""
    input_text = (
        f"ROLE: {role_title}\n\n"
        f"REQUIREMENTS:\n{requirements}\n\n"
        f"REQUIRED SKILLS:\n{', '.join(required_skills)}"
    )

    if focus_context:
        input_text += f"\n\nCANDIDATE SKILL-GAP CONTEXT:\n{focus_context}"

    return _call_llm(
        GENERATE_STUDY_PLAN_PROMPT,
        input_text,
        max_tokens=4200,
    )


def run_pipeline(
    job_description: str,
    focus_context: str = "",
) -> InterviewPrepResult:
    """Run the full role-aware interview preparation pipeline."""
    logger.info("Starting interview prep pipeline")

    role_title, required_skills, requirements = analyze_role(job_description)

    logger.info(
        "Role analysis complete | role=%s | skills=%s",
        role_title,
        len(required_skills),
    )

    questions = generate_questions(
        requirements,
        required_skills,
        focus_context=focus_context,
    )
    logger.info(
        "Question generation complete | questions=%s",
        len(_parse_numbered_items(questions)),
    )

    reviewed_questions = review_questions(questions)
    logger.info(
        "Question review complete | questions=%s",
        len(_parse_numbered_items(reviewed_questions)),
    )

    answers = generate_answers(reviewed_questions)
    logger.info(
        "Answer generation complete | answers=%s",
        len(_parse_numbered_items(answers)),
    )

    study_plan = generate_study_plan(
        role_title,
        requirements,
        required_skills,
        focus_context=focus_context,
    )

    logger.info("Pipeline completed successfully")

    return InterviewPrepResult(
        role_title=role_title,
        required_skills=required_skills,
        requirements=requirements,
        questions=questions,
        reviewed_questions=reviewed_questions,
        answers=answers,
        study_plan=study_plan,
    )


def analyze_skill_gap(
    resume_text: str,
    job_description: str,
) -> SkillGapResult:
    """Compare resume against JD and return structured skill-gap analysis."""
    logger.info("Running skill gap analysis")

    raw = _call_llm(
        SKILL_GAP_PROMPT,
        f"RESUME:\n{resume_text}\n\nJOB DESCRIPTION:\n{job_description}",
        max_tokens=2200,
    )

    data = _parse_json(raw)

    matching = data.get("matching_skills") or []
    missing = data.get("missing_skills") or []

    if not isinstance(matching, list):
        matching = [str(matching)]
    if not isinstance(missing, list):
        missing = [str(missing)]

    return SkillGapResult(
        matching_skills=[
            str(skill).strip()
            for skill in matching
            if str(skill).strip()
        ],
        missing_skills=[
            str(skill).strip()
            for skill in missing
            if str(skill).strip()
        ],
        priority_gap=str(data.get("priority_gap") or "").strip(),
        priority_reason=str(data.get("priority_reason") or "").strip(),
        suggestion=str(data.get("suggestion") or "").strip(),
    )
