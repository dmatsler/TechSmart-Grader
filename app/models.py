from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SubmissionStatus(str, Enum):
    NOT_STARTED = "not_started"
    STARTED_NOT_SUBMITTED = "started_not_submitted"
    TURNED_IN = "turned_in"


@dataclass
class FillZoneConfig:
    name: str
    prompt_hints: list[str] = field(default_factory=list)
    required: bool = True
    attempt_patterns: list[str] = field(default_factory=list)
    expected_patterns: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    notes: str | None = None


@dataclass
class RequirementChecks:
    required_imports: list[str] = field(default_factory=list)
    must_have_tokens: list[str] = field(default_factory=list)
    must_have_any: list[list[str]] = field(default_factory=list)
    must_have_wait_any: list[list[str]] = field(default_factory=list)
    must_have_draw_any: list[list[str]] = field(default_factory=list)
    coherence_guardrails: list[dict[str, Any]] = field(default_factory=list)
    score3_minimums: list[str] = field(default_factory=list)


@dataclass
class AssignmentConfig:
    id: str
    title: str
    file_name: str
    kind: str
    count_in_unit_grade_default: bool = False
    weight: float = 1.0
    rubric_to_points_default: dict[int, int] = field(default_factory=lambda: {0: 0, 1: 50, 2: 75, 3: 100})
    fill_zones: list[FillZoneConfig] = field(default_factory=list)
    requirement_checks: RequirementChecks = field(default_factory=RequirementChecks)
    min_zones_matched_default: int = 1

    @property
    def display_name(self) -> str:
        return f"{self.title} ({self.file_name})"


@dataclass
class GradingModel:
    unit_score_out_of: int = 100
    unit_aggregation: str = "weighted_average_of_counted_assignments"


@dataclass
class AppConfig:
    course: str
    unit: str
    grading_model: GradingModel
    assignments: list[AssignmentConfig]


@dataclass
class GradingInput:
    assignment_id: str
    status: SubmissionStatus
    student_code: str = ""
    techsmart_lines_completed: int | None = None
    techsmart_lines_expected: int | None = None


@dataclass
class ZoneMatch:
    name: str
    matched: bool
    matched_expected: bool
    matched_attempt: bool
    anti_pattern_hit: bool
    has_meaningful_line: bool
    details: str = ""


@dataclass
class GradingResult:
    assignment_id: str
    assignment_title: str
    status: SubmissionStatus
    rubric_score: int
    points: int
    explanation: str
    matched_fill_zones: list[str] = field(default_factory=list)
    unmet_fill_zones: list[str] = field(default_factory=list)
    coherence_guardrail_failures: list[str] = field(default_factory=list)
    requirement_check_failures: list[str] = field(default_factory=list)


@dataclass
class UnitGradeEntry:
    assignment_id: str
    assignment_label: str
    points: int
    include: bool = True
    weight: float = 1.0
