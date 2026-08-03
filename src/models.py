"""
Typed data structures for the pipeline output.

Using a dataclass instead of a raw dict gives autocomplete, catches typos
at development time, and makes it obvious what fields exist without
having to trace through agent.py.
"""

from dataclasses import dataclass


@dataclass
class InterviewPrepResult:
    requirements: str
    questions: str
    answers: str
    study_plan: str
