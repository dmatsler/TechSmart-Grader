from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class SubmissionStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED_NOT_SUBMITTED = "started_not_submitted"
    TURNED_IN = "turned_in"


@dataclass
class AssignmentContext:
    """Everything the AI needs to know about one assignment.
    Populated by context_scraper.py and cached to disk.
    """
    assignment_id: str
    title: str
    unit: str
    kind: str                  # practice | exercise | warmup | demo | instruction
    requirements: str          # scraped from TechSmart assignment page
    starter_code: str          # scraped from TechSmart
    solution_code: str         # scraped from TechSmart solution page
    weight: float = 1.0
    count_in_unit_grade: bool = True


@dataclass
class GradingInput:
    assignment_id: str
    status: SubmissionStatus
    student_code: str = ""
    techsmart_lines_completed: int | None = None
    techsmart_lines_expected: int | None = None


@dataclass
class GradingResult:
    assignment_id: str
    assignment_title: str
    status: SubmissionStatus
    rubric_score: int           # 0 / 1 / 2 / 3
    points: int                 # 0 / 50 / 75 / 100
    explanation: str            # teacher-facing summary
    student_feedback: str = ""  # student-facing actionable feedback
    flag_reasons: list[str] = field(default_factory=list)
    confirmed: bool = True      # False = held for teacher review


@dataclass
class UnitGradeEntry:
    assignment_id: str
    assignment_label: str
    points: int
    include: bool = False       # all OFF by default — teacher toggles on
    weight: float = 1.0
    pending: bool = False       # True = flagged, held for review
    flag_reasons: list[str] = field(default_factory=list)
    computed_rubric_score: int = 0
