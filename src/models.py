"""Typed data structures for Interview Prep Agent results."""

from dataclasses import dataclass, field


@dataclass
class InterviewPrepResult:
    role_title: str
    required_skills: list[str] = field(default_factory=list)
    requirements: str = ""
    questions: str = ""
    reviewed_questions: str = ""
    answers: str = ""
    study_plan: str = ""


@dataclass
class SkillGapResult:
    matching_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    priority_gap: str = ""
    priority_reason: str = ""
    suggestion: str = ""
