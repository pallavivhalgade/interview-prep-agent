"""Core AI pipeline for Interview Prep Agent.

Groq is used directly for LLM inference. The application keeps the workflow
explicit in Python so each processing stage is easy to test and explain.
"""

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


def _call_llm(
    instruction: str,
    input_text: str,
    max_tokens: int = 3000,
) -> str:
    """Run one LLM step directly through the Groq SDK."""
    if not input_text or not str(input_text).strip():
        raise RuntimeError("The AI step received empty input.")

    prompt = f"""TASK INSTRUCTIONS:
{instruction}

INPUT:
{input_text}

Follow the requested output format exactly.
Do not ask the user for additional information.
Return only the requested final output.
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
        logger.info("LLM call succeeded | output_chars=%s", len(content))
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
    if not question_items:
        return False
    if len(question_items) != len(answer_items):
        return False
    return [n for n, _ in question_items] == [n for n, _ in answer_items]


def analyze_role(job_description: str) -> tuple[str, list[str], str]:
    raw = _call_llm(ANALYZE_ROLE_PROMPT, job_description, max_tokens=2200)
    data = _parse_json(raw)

    role_title = str(data.get("role_title") or "Target Role").strip()
    required_skills = data.get("required_skills") or []
    if not isinstance(required_skills, list):
        required_skills = [str(required_skills)]
    required_skills = [
        str(skill).strip() for skill in required_skills if str(skill).strip()
    ]
    requirements = str(data.get("requirements_markdown") or "").strip()
    return role_title, required_skills, requirements


def generate_questions(
    requirements: str,
    required_skills: list[str],
    focus_context: str = "",
) -> str:
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


def _is_experience_question(question: str) -> bool:
    """Return True when a question asks for the candidate's real experience."""
    text = question.casefold()
    patterns = [
        "tell me about a time",
        "describe a time",
        "give an example",
        "describe an example",
        "provide an example",
        "tell me about an experience",
        "describe your experience",
        "project where you",
        "pipeline you built",
        "model you built",
        "system you built",
        "solution you built",
        "approach you used",
        "techniques did you use",
        "how you handled",
        "how did you handle",
        "how you dealt with",
        "how did you deal with",
        "time when you",
        "when you had to",
        "have you ever",
        "what did you do",
        "what was the outcome",
        "what impact did it have",
        "what factors influenced your decision",
        "walk through a feature engineering pipeline you built",
        "describe a scenario where you",
        "provide an example of how you",
        "explain a time you",
    ]
    return any(pattern in text for pattern in patterns)


def _has_fake_experience(questions: str, answers: str) -> bool:
    """Detect unsupported first-person stories in experience answers."""
    question_items = dict(_parse_numbered_items(questions))
    answer_items = dict(_parse_numbered_items(answers))

    claim_patterns = [
        r"\bi worked\b", r"\bi developed\b", r"\bi built\b",
        r"\bi created\b", r"\bi implemented\b", r"\bi designed\b",
        r"\bi identified\b", r"\bi improved\b", r"\bi increased\b",
        r"\bi reduced\b", r"\bi achieved\b", r"\bi presented\b",
        r"\bi deployed\b", r"\bi handled\b", r"\bi collaborated\b",
        r"\bi resolved\b", r"\bour team\b", r"\bmy team\b",
        r"\bmy manager\b", r"\bmy client\b", r"\bmy company\b",
    ]

    for number, question in question_items.items():
        if not _is_experience_question(question):
            continue
        answer = answer_items.get(number, "").casefold()
        if any(re.search(pattern, answer) for pattern in claim_patterns):
            return True
    return False


def generate_answers(
    questions: str,
    focus_context: str = "",
) -> str:
    """Generate grounded answers without inventing candidate experience."""
    candidate_context = (
        focus_context.strip()
        if focus_context and focus_context.strip()
        else "No verified candidate-specific evidence was provided."
    )

    grounding_rules = """
STRICT GROUNDING RULES:
1. Never invent candidate experience, achievements, metrics, employers,
   customers, stakeholders, deployments, projects, team sizes, or results.
2. For technical questions, give a clear answer suitable for a fresher.
3. For real-experience questions, use candidate facts only when explicitly
   supported by VERIFIED CANDIDATE CONTEXT.
4. If evidence is insufficient, return a STAR framework with placeholders:
   Situation: [Insert a real situation]
   Task: [State your real responsibility]
   Action: [State what you actually did]
   Result: [State the real outcome; do not invent metrics]
5. Never invent percentages or performance improvements.
6. Never write a fictional story and then ask the candidate to replace it.
7. Preserve numbering and return exactly one answer per question.
8. Do not claim personal use of a technology unless context supports it.
9. For scenario or hypothetical questions that do not ask for verified past
   experience, answer in hypothetical language such as "I would..." or
   "A suitable approach would be...". Do not use past-tense claims like
   "I built...", "I used...", or "I improved..." unless VERIFIED CANDIDATE
   CONTEXT explicitly supports them.
10. Treat phrases such as "pipeline you built", "describe a scenario where you",
    "provide an example of how you", "how did you handle", and "what impact did
    it have" as experience questions. If VERIFIED CANDIDATE CONTEXT does not
    support the experience, return only STAR placeholders.
11. For unsupported past-experience questions, return only the STAR
    placeholders described above.
"""

    input_text = f"""INTERVIEW QUESTIONS:
{questions}

VERIFIED CANDIDATE CONTEXT:
{candidate_context}

{grounding_rules}"""

    answers = _call_llm(
        GENERATE_ANSWERS_PROMPT,
        input_text,
        max_tokens=4200,
    )

    if not _validate_answers(questions, answers) or _has_fake_experience(
        questions, answers
    ):
        logger.warning(
            "Answer grounding/format validation failed; retrying once"
        )
        answers = _call_llm(
            GENERATE_ANSWERS_PROMPT
            + """
CRITICAL: Do not invent personal experience or metrics. For unsupported
experience questions, return only a STAR framework with placeholders.
For hypothetical/scenario questions, use "I would..." language instead of
claiming the candidate already performed the action.
Return exactly one numbered answer per numbered question.
""",
            input_text,
            max_tokens=4200,
        )

    if not _validate_answers(questions, answers):
        raise RuntimeError(
            "The AI did not return one answer for every interview question."
        )

    if _has_fake_experience(questions, answers):
        raise RuntimeError(
            "The AI attempted to generate unsupported candidate experience. "
            "Please generate again."
        )

    return answers


def generate_study_plan(
    role_title: str,
    requirements: str,
    required_skills: list[str],
    focus_context: str = "",
) -> str:
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

    answers = generate_answers(
        reviewed_questions,
        focus_context=focus_context,
    )
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
            str(skill).strip() for skill in matching if str(skill).strip()
        ],
        missing_skills=[
            str(skill).strip() for skill in missing if str(skill).strip()
        ],
        priority_gap=str(data.get("priority_gap") or "").strip(),
        priority_reason=str(data.get("priority_reason") or "").strip(),
        suggestion=str(data.get("suggestion") or "").strip(),
    )
