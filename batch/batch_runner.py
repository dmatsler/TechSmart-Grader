"""
Batch runner — wires the scraper + context scraper to the AI grading engine.
"""
from __future__ import annotations

import asyncio
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.ai_grader import grade_submission
from app.config_loader import UNIT_REGISTRY, get_all_contexts, get_unit_assignments
from app.context_scraper import load_context_cache, refresh_context_cache
from app.models import AssignmentContext, GradingInput, GradingResult, SubmissionStatus, UnitGradeEntry
from app.unit_grade import calculate_unit_grade

from batch.scraper import ScrapedSubmission, scrape_all_assignments

_STATUS_MAP = {
    "turned_in":             SubmissionStatus.TURNED_IN,
    "started_not_submitted": SubmissionStatus.STARTED_NOT_SUBMITTED,
    "not_started":           SubmissionStatus.NOT_STARTED,
}


# ---------------------------------------------------------------------------
# Rate limiter — controls API call frequency for any provider
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Token bucket rate limiter for async code.

    Ensures we never exceed calls_per_minute regardless of how many
    coroutines are running concurrently.
    """
    def __init__(self, calls_per_minute: int):
        self._min_interval = 60.0 / max(calls_per_minute, 1)
        self._lock = asyncio.Lock()
        self._last_call: float = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()


def _get_rate_limit() -> int:
    """Read calls_per_minute from llm_config.json. Defaults to 25 (free tier)."""
    import json
    config_path = _ROOT / "llm_config.json"
    if config_path.exists():
        cfg = json.loads(config_path.read_text())
        return int(cfg.get("calls_per_minute", 25))
    return 25


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
    student_feedback: str = ""   # ← new: student-facing feedback
    flag_reasons: list[str] = field(default_factory=list)
    pending: bool = False


@dataclass
class StudentUnitResult:
    student_name: str
    assignment_results: list[StudentAssignmentResult] = field(default_factory=list)
    run_grades: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helper: assignment title lookup
# ---------------------------------------------------------------------------

def _get_title(assignment_id: str, contexts: dict, unit_slug: str) -> str:
    ctx = contexts.get(assignment_id)
    if ctx:
        return ctx.title
    # Fallback to registry
    for aid, title in UNIT_REGISTRY.get(unit_slug, {}).get("fallback_assignments", []):
        if aid == assignment_id:
            return title
    return assignment_id


# ---------------------------------------------------------------------------
# Batch grading
# ---------------------------------------------------------------------------

async def grade_scraped_submissions(
    scraped: dict[str, list[ScrapedSubmission]],
    unit_slug: str,
    contexts: dict[str, AssignmentContext],
    progress_callback: Optional[Callable[[str], None]] = None,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[dict[str, StudentUnitResult], dict[str, int]]:
    """Grade all scraped submissions in parallel using asyncio.

    All students for all assignments are graded concurrently, throttled by
    a rate limiter so we never exceed the API's calls-per-minute cap.
    Not-started submissions are resolved instantly without an API call.
    """
    import concurrent.futures

    # Thread pool for running synchronous Groq calls without blocking event loop
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=5)
    rate_limiter = _RateLimiter(_get_rate_limit())
    # Semaphore caps concurrent in-flight API calls at 5 — prevents token bursts
    api_semaphore = asyncio.Semaphore(5)
    loop = asyncio.get_event_loop()

    # Pre-populate all_students so dict writes are safe
    all_students: dict[str, StudentUnitResult] = {}
    for submissions in scraped.values():
        for sub in submissions:
            if sub.student_name not in all_students:
                all_students[sub.student_name] = StudentUnitResult(
                    student_name=sub.student_name
                )

    # Count real API calls (skip not_started — they need no API call)
    total_api_calls = sum(
        1 for subs in scraped.values()
        for sub in subs
        if sub.ts_status != "not_started"
    )
    total_all = sum(len(v) for v in scraped.values())
    if progress_callback:
        progress_callback(
            f"  {total_all} total submissions — "
            f"{total_api_calls} require AI grading, "
            f"{total_all - total_api_calls} auto-scored (not started)"
        )

    completed = 0
    lock = asyncio.Lock()

    # Counters for live summary
    counters = {
        "graded": 0,
        "flagged": 0,
        "api_errors": 0,
        "not_started": 0,
        "cancelled": 0,
        "errors": 0,
    }

    async def _emit_live_summary():
        """Emit a short progress summary every 10 completed tasks."""
        if progress_callback and (
            counters["graded"] + counters["flagged"] + counters["api_errors"]
        ) % 10 == 0:
            progress_callback(
                f"  📊 [graded: {counters['graded']} | "
                f"flagged: {counters['flagged']} | "
                f"errors: {counters['api_errors']}]"
            )

    async def _grade_one(
        assignment_id: str,
        sub: ScrapedSubmission,
        context,
        title: str,
    ) -> None:
        nonlocal completed
        name = sub.student_name
        status = _STATUS_MAP.get(sub.ts_status, SubmissionStatus.NOT_STARTED)

        # Early cancellation check
        if cancel_event is not None and cancel_event.is_set():
            async with lock:
                counters["cancelled"] += 1
                all_students[name].assignment_results.append(
                    StudentAssignmentResult(
                        student_name=name,
                        assignment_id=assignment_id,
                        assignment_title=title,
                        ts_status=sub.ts_status,
                        rubric_score=0,
                        points=0,
                        explanation="Grading cancelled by user — not graded.",
                        flag_reasons=["Cancelled"],
                        pending=True,
                    )
                )
            return

        payload = GradingInput(
            assignment_id=assignment_id,
            status=status,
            student_code=sub.code,
            techsmart_lines_completed=getattr(sub, "lines_completed", None),
            techsmart_lines_expected=getattr(sub, "lines_expected", None),
        )

        try:
            if status == SubmissionStatus.NOT_STARTED:
                # Fast path — no API call needed
                result = GradingResult(
                    assignment_id=assignment_id,
                    assignment_title=title,
                    status=status,
                    rubric_score=0,
                    points=0,
                    explanation="Assignment not started.",
                    student_feedback="This assignment hasn't been started yet. Give it a try!",
                    confirmed=True,
                )
                async with lock:
                    counters["not_started"] += 1
            else:
                # Acquire semaphore (max 5 concurrent) + rate limit token
                async with api_semaphore:
                    # Re-check cancellation after waiting for semaphore slot
                    if cancel_event is not None and cancel_event.is_set():
                        async with lock:
                            counters["cancelled"] += 1
                            all_students[name].assignment_results.append(
                                StudentAssignmentResult(
                                    student_name=name,
                                    assignment_id=assignment_id,
                                    assignment_title=title,
                                    ts_status=sub.ts_status,
                                    rubric_score=0,
                                    points=0,
                                    explanation="Grading cancelled by user.",
                                    flag_reasons=["Cancelled"],
                                    pending=True,
                                )
                            )
                        return

                    await rate_limiter.acquire()
                    result = await loop.run_in_executor(
                        executor,
                        lambda p=payload, ctx=context: grade_submission(
                            assignment_id, p, ctx
                        )
                    )

            async with lock:
                completed += 1
                if result.flag_reasons:
                    is_api_error = any(
                        "AI grader error" in r for r in result.flag_reasons
                    )
                    if is_api_error:
                        counters["api_errors"] += 1
                        if progress_callback:
                            progress_callback(
                                f"  ✗ {name} / {title} — API error"
                            )
                    else:
                        counters["flagged"] += 1
                        if progress_callback:
                            progress_callback(
                                f"  ⚠  {name} / {title} — flagged"
                            )
                else:
                    if status != SubmissionStatus.NOT_STARTED:
                        counters["graded"] += 1
                    if progress_callback and status != SubmissionStatus.NOT_STARTED:
                        progress_callback(
                            f"  ✓  [{completed}/{total_api_calls}] "
                            f"{name} / {title} — {result.rubric_score}/3"
                        )

                all_students[name].assignment_results.append(
                    StudentAssignmentResult(
                        student_name=name,
                        assignment_id=assignment_id,
                        assignment_title=title,
                        ts_status=sub.ts_status,
                        rubric_score=result.rubric_score,
                        points=result.points,
                        explanation=result.explanation,
                        student_feedback=result.student_feedback,
                        flag_reasons=result.flag_reasons,
                        pending=not result.confirmed,
                    )
                )

                await _emit_live_summary()

        except Exception as exc:
            async with lock:
                counters["errors"] += 1
                if progress_callback:
                    progress_callback(f"  ✗ Error — {name} / {title}: {exc}")
                all_students[name].assignment_results.append(
                    StudentAssignmentResult(
                        student_name=name,
                        assignment_id=assignment_id,
                        assignment_title=title,
                        ts_status=sub.ts_status,
                        rubric_score=0,
                        points=0,
                        explanation=f"Grading error: {exc}",
                    )
                )

    # Build all tasks
    tasks = []
    for assignment_id, submissions in scraped.items():
        context = contexts.get(assignment_id)
        title = _get_title(assignment_id, contexts, unit_slug)
        if progress_callback:
            ctx_note = "✓ context" if context else "⚠ no context"
            progress_callback(f"⚙  Queuing: {title} ({ctx_note})")
        for sub in submissions:
            tasks.append(_grade_one(assignment_id, sub, context, title))

    # Run all concurrently — rate limiter controls actual API call frequency
    await asyncio.gather(*tasks)
    executor.shutdown(wait=False)

    # Sort each student's results by registry assignment order
    from app.config_loader import UNIT_REGISTRY
    order: dict[str, int] = {}
    pos = 0
    for unit_data in UNIT_REGISTRY.values():
        for aid, _ in unit_data.get("fallback_assignments", []):
            if aid not in order:
                order[aid] = pos
                pos += 1

    for student_result in all_students.values():
        student_result.assignment_results.sort(
            key=lambda ar: (order.get(ar.assignment_id, 9999), ar.assignment_id)
        )

    return all_students, counters


# ---------------------------------------------------------------------------
# Composite grade calculation
# ---------------------------------------------------------------------------

def compute_run_grades(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],
    unit_slug: str,
) -> None:
    """Compute composite unit grades. Pending submissions excluded until confirmed."""
    assignments = dict(get_unit_assignments(unit_slug))

    for student_result in all_students.values():
        result_by_id = {r.assignment_id: r for r in student_result.assignment_results}

        for run_name, included_ids in runs.items():
            entries: list[UnitGradeEntry] = []
            for aid in included_ids:
                ar = result_by_id.get(aid)
                if ar and ar.pending:
                    continue
                points = ar.points if ar else 0
                entries.append(UnitGradeEntry(
                    assignment_id=aid,
                    assignment_label=assignments.get(aid, aid),
                    points=points,
                    include=True,
                    weight=1.0,
                ))

            if entries:
                grade = calculate_unit_grade(entries, {e.assignment_id for e in entries})
                student_result.run_grades[run_name] = round(grade, 2)
            else:
                student_result.run_grades[run_name] = 0.0


def recompute_after_review(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],
    unit_slug: str,
) -> None:
    """Re-run grade computation after teacher confirms flagged submissions."""
    compute_run_grades(all_students, runs, unit_slug)


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------

async def run_full_pipeline(
    username: str,
    password: str,
    gradebook_url: str,
    assignment_ids: list[str],
    runs: dict[str, list[str]],
    unit_slug: str = "3_3",
    refresh_context: bool = False,
    progress_callback: Optional[Callable[[str], None]] = None,
    headless: bool = False,
    cancel_event: Optional[asyncio.Event] = None,
) -> tuple[dict[str, StudentUnitResult], dict[str, int]]:
    """
    Full pipeline:
      1. (Optional) Refresh context cache — scrapes requirements/starter/solution
         and updates only what changed.
      2. Scrape student submissions via Playwright.
      3. Grade every submission with the AI grader.
      4. Compute composite grades (confirmed submissions only).
    """
    # ── Step 1: Refresh context cache ────────────────────────────────────────
    if refresh_context:
        if progress_callback:
            progress_callback("=" * 50)
            progress_callback("STEP 1 — Refreshing assignment context cache")
            progress_callback("=" * 50)
        try:
            await refresh_context_cache(
                unit_slug=unit_slug,
                gradebook_url=gradebook_url,
                username=username,
                password=password,
                progress_callback=progress_callback,
                headless=headless,
            )
        except Exception as exc:
            if progress_callback:
                progress_callback(f"⚠ Context refresh failed: {exc}")
                progress_callback("  Continuing with cached/fallback context.")

    # Load contexts for grading
    contexts = get_all_contexts(unit_slug)
    if progress_callback:
        progress_callback(f"  Context loaded for {len(contexts)} assignments\n")

    # ── Step 2: Scrape student submissions ────────────────────────────────────
    if progress_callback:
        progress_callback("=" * 50)
        progress_callback("STEP 2 — Scraping student submissions")
        progress_callback("=" * 50)

    scraped = await scrape_all_assignments(
        username=username,
        password=password,
        gradebook_url=gradebook_url,
        assignment_ids=assignment_ids,
        progress_callback=progress_callback,
        headless=headless,
    )

    total = sum(len(v) for v in scraped.values())
    if progress_callback:
        progress_callback(f"\n✓ Scraping complete — {total} total submissions\n")

    # ── Step 3: Grade submissions ─────────────────────────────────────────────
    if progress_callback:
        progress_callback("=" * 50)
        progress_callback("STEP 3 — Grading submissions (AI)")
        progress_callback("=" * 50)

    all_students, counters = await grade_scraped_submissions(
        scraped, unit_slug, contexts, progress_callback, cancel_event
    )

    flagged_count = sum(
        1 for s in all_students.values()
        for ar in s.assignment_results if ar.pending
    )
    if flagged_count and progress_callback:
        progress_callback(
            f"\n⚠  {flagged_count} submission(s) flagged — excluded from grades until confirmed.\n"
        )

    if progress_callback:
        progress_callback(f"\n✓ Grading complete — {len(all_students)} students\n")

    # ── Step 4: Compute grades ────────────────────────────────────────────────
    if progress_callback:
        progress_callback("=" * 50)
        progress_callback("STEP 4 — Computing composite grades")
        progress_callback("=" * 50)

    compute_run_grades(all_students, runs, unit_slug)

    if progress_callback:
        progress_callback("✓ Composite grades computed\n")

    return all_students, counters
