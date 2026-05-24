"""
AI Grader — replaces the static AST/regex grader.

Builds a grading prompt from the assignment context and student code,
calls the LLM via llm_client.py, and returns a GradingResult in the
same shape the rest of the system (main.py, batch_runner, reports) expects.
"""
from __future__ import annotations

from pathlib import Path

from app.llm_client import call as llm_call
from app.models import AssignmentContext, GradingInput, GradingResult, SubmissionStatus

POINTS_MAP = {0: 0, 1: 50, 2: 75, 3: 100}

# ---------------------------------------------------------------------------
# Rubric definitions — your scale, not TechSmart's default
# ---------------------------------------------------------------------------

RUBRIC_DEFINITIONS = """
RUBRIC SCALE (use this exact scale — do not deviate):
  0 = No attempt. Blank, template-only, or code completely unrelated to the assignment.
  1 = Attempt made but NOT submitted, OR submitted but shows no real engagement
      with the assignment's core concept. Getting the program to "run" by adding
      random lines does not count as a meaningful attempt.
  2 = Submitted. Student clearly attempted the assignment concept and shows
      understanding, but the implementation is incomplete, has errors, or is
      missing key requirements.
  3 = Submitted. Assignment concept is correctly and completely implemented.
      Program would run and produce the expected result.

POINT VALUES: 0→0pts, 1→50pts, 2→75pts, 3→100pts
""".strip()

# ---------------------------------------------------------------------------
# Gaming / integrity rules — baked into every prompt
# ---------------------------------------------------------------------------

INTEGRITY_RULES = """
INTEGRITY RULES — apply these before scoring:
  - Code that is ONLY print() statements with no pygame logic = score 0, flag it.
  - Random lines of code that don't relate to the assignment's objective = score 0, flag it.
  - Code clearly copied from a DIFFERENT assignment (wrong shapes, wrong variables,
    wrong objective entirely) = score 0, flag it.
  - Code using constructs not taught at this level (classes, decorators, list
    comprehensions, lambda) should be flagged as possible AI-generated or
    copied code. Score the work on its merits but flag it for teacher review.
    Do NOT flag imports that appear in the SOLUTION CODE — those are
    curriculum-standard. Only flag imports that are clearly outside the
    curriculum (e.g. numpy, requests, tensorflow).
  - Starter/template code alone (code the teacher provided that the student
    did not modify) = score 0 or 1 depending on submission status.
""".strip()

# ---------------------------------------------------------------------------
# Grading priorities — how to read the context above
# ---------------------------------------------------------------------------

GRADING_PRIORITIES = """
HOW TO READ THE CONTEXT ABOVE — apply these before scoring:

  1. SOLUTION CODE is the authoritative reference for what the student's
     code should DO. Compare the student's submission against what the
     solution code produces — NOT against what the assignment title's
     plain-English reading suggests the lesson "should" teach. If the
     title and the solution code seem to conflict, the solution code wins.

  2. STARTER CODE is given to every student. It is fixed background — the
     student did not write it. Do not credit, penalise, or flag the student
     for starter lines. If a line is in the starter, treat it as given.

  3. The student's actual work is only what they ADDED to the starter.
     This may be just a few lines. A submission is correct when the
     student's added code, combined with the unchanged starter, produces
     the same observable behavior as the solution.

  4. Stylistic differences from the solution do NOT lower the score:
     different variable names, f-strings vs string concatenation, or
     reordering of statements that don't affect behavior are all fine.
     Grade behavior, not surface form.
""".strip()

# ---------------------------------------------------------------------------
# Curriculum context — what counts as "expected" for TechSmart CS101
# ---------------------------------------------------------------------------

TECHSMART_CONTEXT = """
TECHSMART CURRICULUM CONTEXT — read carefully:
  - This is TechSmart CS101, a middle-school Python/Pygame curriculum.
  - The 'tsk' module is a TechSmart-provided helper library used throughout
    this curriculum for keyboard input and other utilities. 'import tsk',
    'tsk.is_key_down(...)', 'tsk.get_key_pressed(...)' and similar calls
    are LEGITIMATE and EXPECTED. Do NOT flag tsk as undefined, unknown,
    non-standard, or AI-generated. It is part of the standard environment
    for these students.
  - When evaluating whether an import or library call is "expected," check
    the SOLUTION CODE first. If the same import or call appears in the
    solution, it is taught content and must be treated as legitimate.
  - Other modules that may appear and are expected at this level: pygame,
    random, tsk. Standard library modules (math, time, etc.) are also fine.
""".strip()

# ---------------------------------------------------------------------------
# Per-assignment grading notes — for assignments where the title misleads
# ---------------------------------------------------------------------------

ASSIGNMENT_NOTES: dict[str, str] = {
    "3_5_saving_a_tuple_2_technique1practice2_py": (
        "This lesson teaches UNPACKING a tuple into separate variables "
        "(the technique 'r, g, b = color'), NOT creating a new tuple. "
        "The student's task is to:\n"
        "  1. Unpack the existing 'color' tuple into three variables (any names: r/g/b or red/green/blue).\n"
        "  2. Print each of the three variables on a separate line.\n"
        "A student who does these two things has fully completed the assignment "
        "and MUST receive 3/3. Do NOT require them to create a new tuple variable. "
        "Do NOT require f-strings or string concatenation — either is acceptable. "
        "The 'input()' call and 'pygame.time.wait()' call are in the starter code; "
        "do not flag, penalise, or comment on them."
    ),
}

# ---------------------------------------------------------------------------
# Deterministic line-count helpers — for AI-assistance detection
# ---------------------------------------------------------------------------

def _count_nonblank_lines(code: str) -> int:
    """Count non-blank lines (any line with at least one non-whitespace char)."""
    return sum(1 for line in code.splitlines() if line.strip())


def _added_line_counts(
    student_code: str, context: AssignmentContext
) -> tuple[int, int] | None:
    """
    Compute (actual_added, expected_added) — lines the student wrote BEYOND
    the starter code, vs. lines the solution adds BEYOND the starter.

    Returns None when starter or solution are missing (no meaningful ratio
    can be computed) or when the assignment has no "added" work to compare.
    """
    if not context.starter_code or not context.solution_code or not student_code:
        return None
    starter_lines = _count_nonblank_lines(context.starter_code)
    solution_lines = _count_nonblank_lines(context.solution_code)
    student_lines = _count_nonblank_lines(student_code)
    expected_added = solution_lines - starter_lines
    actual_added = student_lines - starter_lines
    if expected_added <= 0:
        return None
    return (actual_added, expected_added)

# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    context: AssignmentContext,
    student_code: str,
    status: SubmissionStatus,
    lines_completed: int | None,
    lines_expected: int | None,
) -> str:
    lines_info = ""
    if lines_completed is not None and lines_expected is not None:
        pct = int((lines_completed / lines_expected) * 100) if lines_expected > 0 else 0
        lines_info = (
            f"\nLINE COUNT: {lines_completed} lines submitted, "
            f"{lines_expected} expected ({pct}% of expected)."
        )

    status_note = {
        SubmissionStatus.NOT_STARTED: "Student has NOT started this assignment.",
        SubmissionStatus.STARTED_NOT_SUBMITTED: (
            "Student started but did NOT submit. "
            "Maximum possible score is 1."
        ),
        SubmissionStatus.TURNED_IN: "Student has submitted (Turned In).",
    }.get(status, "")

    requirements_section = (
        f"ASSIGNMENT REQUIREMENTS:\n{context.requirements}"
        if context.requirements
        else f"ASSIGNMENT: {context.title}"
    )

    starter_section = (
        f"\nSTARTER CODE (provided to all students — do NOT credit this):\n"
        f"```python\n{context.starter_code}\n```"
        if context.starter_code
        else ""
    )

    note = ASSIGNMENT_NOTES.get(context.assignment_id, "")
    note_section = (
        f"\nPER-ASSIGNMENT GRADING NOTE — this OVERRIDES any conflicting "
        f"interpretation from the title, requirements, or your own assumptions:\n{note}\n"
        if note else ""
    )

    solution_section = (
        f"\nSOLUTION CODE (reference for what a correct answer looks like):\n"
        f"```python\n{context.solution_code}\n```"
        if context.solution_code
        else ""
    )

    return f"""You are grading a middle school Python/Pygame assignment.

{TECHSMART_CONTEXT}
{note_section}
{requirements_section}{starter_section}{solution_section}

{GRADING_PRIORITIES}

{RUBRIC_DEFINITIONS}

{INTEGRITY_RULES}

SUBMISSION STATUS: {status_note}{lines_info}

STUDENT CODE:
```python
{student_code if student_code.strip() else "(empty — no code submitted)"}
```

Grade this submission and respond with ONLY a JSON object (no markdown, no extra text):
{{
  "score": <integer 0-3>,
  "points": <0, 50, 75, or 100>,
  "explanation": "<one to two sentences for the teacher explaining the score>",
  "student_feedback": "<two to four sentences of specific, encouraging feedback directly to the student — tell them what they did well and exactly what to fix to improve their score>",
  "flags": ["<flag reason if any>"]
}}

The "flags" list should be empty [] if nothing is suspicious.
The "student_feedback" should be written directly to the student (use 'you/your'), be specific about what to improve, and be encouraging in tone."""


# ---------------------------------------------------------------------------
# Not-started fast path — no LLM call needed
# ---------------------------------------------------------------------------

def _not_started_result(assignment_id: str, title: str) -> GradingResult:
    return GradingResult(
        assignment_id=assignment_id,
        assignment_title=title,
        status=SubmissionStatus.NOT_STARTED,
        rubric_score=0,
        points=0,
        explanation="Assignment not started.",
        student_feedback="This assignment hasn't been started yet. Give it a try!",
        flag_reasons=[],
        confirmed=True,
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def grade_submission(
    assignment_id: str,
    payload: GradingInput,
    context: AssignmentContext | None = None,
) -> GradingResult:
    """Grade one student submission.

    Args:
        assignment_id: The assignment's slug ID.
        payload: Student submission data (code, status, line counts).
        context: Assignment context (requirements, starter, solution).
                 If None, the AI grades with title only — less accurate
                 but still functional.

    Returns:
        GradingResult ready to display and store.
    """
    # Resolve clean title — prefer context, then registry, then slugify as last resort
    if context:
        title = context.title
    else:
        from app.config_loader import UNIT_REGISTRY
        title = assignment_id  # last resort
        for unit_data in UNIT_REGISTRY.values():
            for aid, t in unit_data.get("fallback_assignments", []):
                if aid == assignment_id:
                    title = t
                    break

    # Fast path — no LLM needed
    if payload.status == SubmissionStatus.NOT_STARTED:
        return _not_started_result(assignment_id, title)

    # Build context object if none provided (degraded mode)
    # Add a note so the AI doesn't invent strict requirements from the title alone
    if context is None:
        context = AssignmentContext(
            assignment_id=assignment_id,
            title=title,
            unit="Unknown",
            kind="assignment",
            requirements=(
                "Note: Full assignment requirements are not yet available. "
                "Grade based on whether the student's code demonstrates the "
                "core concept suggested by the assignment title. Do not penalise "
                "for requirements you cannot verify from the title alone. "
                "When in doubt, be generous — a working, relevant program "
                "that addresses the apparent concept should score 3."
            ),
            starter_code="",
            solution_code="",
        )

    prompt = _build_prompt(
        context=context,
        student_code=payload.student_code or "",
        status=payload.status,
        lines_completed=payload.techsmart_lines_completed,
        lines_expected=payload.techsmart_lines_expected,
    )

    result = llm_call(prompt)

    score = result["score"]
    flags = result.get("flags", [])

    # started_not_submitted caps at 1
    if payload.status == SubmissionStatus.STARTED_NOT_SUBMITTED:
        score = min(score, 1)

    # Compute line counts ONCE — used by both debug logging and integrity check.
    # Order matters: assignment must come before any reference to line_counts.
    line_counts = _added_line_counts(payload.student_code or "", context)

    # TEMP DEBUG — writes to /tmp/grader_debug.log; remove after diagnosis
    try:
        with open("/tmp/grader_debug.log", "a", encoding="utf-8") as _f:
            _starter = _count_nonblank_lines(context.starter_code) if context.starter_code else "EMPTY"
            _solution = _count_nonblank_lines(context.solution_code) if context.solution_code else "EMPTY"
            _student = _count_nonblank_lines(payload.student_code or "")
            _f.write(
                f"{assignment_id} | score={score} | "
                f"starter={_starter} | solution={_solution} | "
                f"student={_student} | line_counts={line_counts}\n"
            )
    except Exception:
        pass  # never let debug logging break grading

    # AI-assisted submission detection: student added significantly more lines
    # than the solution adds AND the code is functional.
    if line_counts is not None and score >= 2:
        actual, expected = line_counts
        if actual > 1.5 * expected:
            pct = int((actual / expected) * 100)
            ai_flag = (
                f"Possible AI-assisted submission: student wrote {pct}% of "
                f"expected line count ({actual} added lines vs {expected} expected) "
                f"AND code is functional. Pattern matches AI/copy submissions — "
                f"review before confirming."
            )
            if ai_flag not in flags:
                flags.append(ai_flag)

    points = POINTS_MAP.get(score, 0)

    return GradingResult(
        assignment_id=assignment_id,
        assignment_title=title,
        status=payload.status,
        rubric_score=score,
        points=points,
        explanation=result.get("explanation", ""),
        student_feedback=result.get("student_feedback", ""),
        flag_reasons=flags,
        confirmed=len(flags) == 0,
    )
