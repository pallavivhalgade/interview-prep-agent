"""
Interview Prep Agent - core logic.

A simple 4-step agentic pipeline:
  1. Extract key skills/requirements from a job description
  2. Generate likely interview questions based on those skills
  3. Generate sample strong answers / frameworks for each question
  4. Generate a short study plan

Each step's output is fed as input into the next step - this chaining
is what makes it "agentic" rather than a single one-shot prompt.
"""

import os
import json
from groq import Groq
from dotenv import load_dotenv

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
    system_prompt = (
        "You are a recruiting analyst. Extract the key technical skills, "
        "tools, and soft skills required from the job description. "
        "Return a concise bulleted list only, no extra commentary."
    )
    return _call_llm(system_prompt, job_description)


def generate_questions(requirements: str) -> str:
    """Step 2: Generate likely interview questions from the requirements."""
    system_prompt = (
        "You are an experienced technical interviewer. Based on the given "
        "list of required skills, generate 8 likely interview questions: "
        "5 technical and 3 behavioral. Number them 1-8."
    )
    return _call_llm(system_prompt, requirements)


def generate_answers(questions: str) -> str:
    """Step 3: Generate a sample strong answer/framework for each question."""
    system_prompt = (
        "You are an interview coach. For each numbered question given, "
        "provide a short sample answer or answer framework (2-4 sentences). "
        "For behavioral questions, use the STAR method structure. "
        "Keep the same numbering as the input questions."
    )
    return _call_llm(system_prompt, questions)


def generate_study_plan(requirements: str) -> str:
    """Step 4: Generate a short pre-interview study plan."""
    system_prompt = (
        "You are a career coach. Based on these required skills, create a "
        "focused 3-day study plan (Day 1, Day 2, Day 3) with 2-3 concrete "
        "topics/actions per day to prepare for an interview."
    )
    return _call_llm(system_prompt, requirements)


def run_pipeline(job_description: str) -> dict:
    """Runs all 4 steps in sequence and returns everything as a dict."""
    requirements = extract_requirements(job_description)
    questions = generate_questions(requirements)
    answers = generate_answers(questions)
    study_plan = generate_study_plan(requirements)

    return {
        "requirements": requirements,
        "questions": questions,
        "answers": answers,
        "study_plan": study_plan,
    }
