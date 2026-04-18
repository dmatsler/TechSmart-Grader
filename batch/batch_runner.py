"""
Batch runner — wires the scraper to the existing grading engine.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.config_loader import assignment_lookup, load_config
from app.grader import grade_submission
from app.models import GradingInput, GradingResult, SubmissionStatus, UnitGradeEntry
from app.unit_grade import calculate_unit_grade

from batch.scraper import ScrapedSubmission, scrape_all_assignments


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class StudentAssignmentResult:
    student_name: str
    assignment_id: str
    assignment_title: str
    ts_status: str
    rubric_score: int
    points: int
    explanation: str
    matched_zones: list[str] = field(default_factory=list)
    unmet_zones: list[str] = field(default_factory=list)
    guardrail_failures: list[str] = field(default_factory=list)
    requirement_failures: list[str] = field(default_factory=list)


@dataclass
class StudentUnitResult:
    student_name: str
    assignment_results: list[StudentAssignmentResult] = field(default_factory=list)
    run_grades: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def _load_app_config():
    yaml_path = _ROOT / "unit_3_3_animation_grading_config_working.yaml"
    json_path = _ROOT / "unit_3_3_animation_grading_config_working.json"
    cfg = load_config(yaml_path, json_path)
    return cfg, assignment_lookup(cfg)


_APP_CONFIG, _ASSIGNMENT_LOOKUP = _load_app_config()

_STATUS_MAP = {
    "turned_in":             SubmissionStatus.TURNED_IN,
    "started_not_submitted": SubmissionStatus.STARTED_NOT_SUBMITTED,
    "not_started":           SubmissionStatus.NOT_STARTED,
}


# ---------------------------------------------------------------------------
# Batch grading
# ---------------------------------------------------------------------------

def grade_scraped_submissions(
    scraped: dict[str, list[ScrapedSubmission]],
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict[str, StudentUnitResult]:
    all_students: dict[str, StudentUnitResult] = {}

    for assignment_id, submissions in scraped.items():
        assignment_cfg = _ASSIGNMENT_LOOKUP.get(assignment_id)
        if assignment_cfg is None:
            if progress_callback:
                progress_callback(f"⚠  No config for '{assignment_id}' — skipping")
            continue

        if progress_callback:
            progress_callback(f"⚙  Grading: {assignment_cfg.display_name}")

        for sub in submissions:
            name = sub.student_name
            if name not in all_students:
                all_students[name] = StudentUnitResult(student_name=name)

            status = _STATUS_MAP.get(sub.ts_status, SubmissionStatus.NOT_STARTED)
            grading_input = GradingInput(
                assignment_id=assignment_id,
                status=status,
                student_code=sub.code,
            )

            try:
                result: GradingResult = grade_submission(assignment_cfg, grading_input)
                all_students[name].assignment_results.append(
                    StudentAssignmentResult(
                        student_name=name,
                        assignment_id=assignment_id,
                        assignment_title=assignment_cfg.display_name,
                        ts_status=sub.ts_status,
                        rubric_score=result.rubric_score,
                        points=result.points,
                        explanation=result.explanation,
                        matched_zones=result.matched_fill_zones,
                        unmet_zones=result.unmet_fill_zones,
                        guardrail_failures=result.coherence_guardrail_failures,
                        requirement_failures=result.requirement_check_failures,
                    )
                )
            except Exception as exc:
                if progress_callback:
                    progress_callback(f"  ✗ Error grading {name}: {exc}")
                all_students[name].assignment_results.append(
                    StudentAssignmentResult(
                        student_name=name,
                        assignment_id=assignment_id,
                        assignment_title=assignment_cfg.display_name,
                        ts_status=sub.ts_status,
                        rubric_score=0,
                        points=0,
                        explanation=f"Grading error: {exc}",
                    )
                )

    return all_students


# ---------------------------------------------------------------------------
# Composite grade calculation
# ---------------------------------------------------------------------------

def compute_run_grades(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],
) -> None:
    for student_name, student_result in all_students.items():
        result_by_id = {r.assignment_id: r for r in student_result.assignment_results}

        for run_name, included_ids in runs.items():
            entries: list[UnitGradeEntry] = []
            for aid in included_ids:
                cfg = _ASSIGNMENT_LOOKUP.get(aid)
                if cfg is None:
                    continue
                ar = result_by_id.get(aid)
                points = ar.points if ar else 0
                entries.append(UnitGradeEntry(
                    assignment_id=aid,
                    assignment_label=cfg.display_name,
                    points=points,
                    include=True,
                    weight=cfg.weight,
                ))

            if entries:
                include_ids = {e.assignment_id for e in entries}
                grade = calculate_unit_grade(entries, include_ids)
                student_result.run_grades[run_name] = round(grade, 2)
            else:
                student_result.run_grades[run_name] = 0.0


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def run_full_pipeline(
    username: str,
    password: str,
    gradebook_url: str,
    assignment_ids: list[str],
    runs: dict[str, list[str]],
    progress_callback: Optional[Callable[[str], None]] = None,
    headless: bool = False,
) -> dict[str, StudentUnitResult]:
    """
    Complete pipeline: login → discover URLs → scrape → grade → compute grades.
    """
    if progress_callback:
        progress_callback("=" * 50)
        progress_callback("STEP 1 — Scraping TechSmart submissions")
        progress_callback("=" * 50)

    scraped = await scrape_all_assignments(
        username=username,
        password=password,
        gradebook_url=gradebook_url,
        assignment_ids=assignment_ids,
        progress_callback=progress_callback,
        headless=headless,
    )

    if progress_callback:
        total = sum(len(v) for v in scraped.values())
        progress_callback(f"\n✓ Scraping complete — {total} total submissions\n")
        progress_callback("=" * 50)
        progress_callback("STEP 2 — Grading submissions")
        progress_callback("=" * 50)

    all_students = grade_scraped_submissions(scraped, progress_callback)

    if progress_callback:
        progress_callback(f"\n✓ Grading complete — {len(all_students)} students\n")
        progress_callback("=" * 50)
        progress_callback("STEP 3 — Computing composite grades")
        progress_callback("=" * 50)

    compute_run_grades(all_students, runs)

    if progress_callback:
        progress_callback("✓ Composite grades computed\n")

    return all_students