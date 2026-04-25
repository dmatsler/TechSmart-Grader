from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.ai_grader import grade_submission
from app.config_loader import UNIT_REGISTRY, get_assignment_context, get_unit_assignments
from app.models import GradingInput, SubmissionStatus, UnitGradeEntry
from app.unit_grade import calculate_unit_grade

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="TechSmart Grading Companion")
app.add_middleware(SessionMiddleware, secret_key="techsmart-mvp-secret")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

POINTS_MAP = {0: 0, 1: 50, 2: 75, 3: 100}

# ── Session helpers ───────────────────────────────────────────────────────────

SESSION_RESULTS: dict[str, list[UnitGradeEntry]] = {}


def _session_key(request: Request) -> str:
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_hex(16)
        request.session["sid"] = sid
    return sid


def _active_unit(request: Request) -> str:
    return request.session.get("active_unit", "3_3")


def _unit_entries(request: Request, unit_slug: str) -> list[UnitGradeEntry]:
    sid = _session_key(request)
    key = f"{sid}:{unit_slug}"
    return SESSION_RESULTS.setdefault(key, [])


def _save_unit_entries(request: Request, unit_slug: str, entries: list[UnitGradeEntry]) -> None:
    sid = _session_key(request)
    SESSION_RESULTS[f"{sid}:{unit_slug}"] = entries


def _entry_by_id(entries: list[UnitGradeEntry]) -> dict[str, UnitGradeEntry]:
    return {e.assignment_id: e for e in entries}


# ── Unit selector ─────────────────────────────────────────────────────────────

@app.post("/select-unit")
async def select_unit(request: Request, unit_slug: str = Form(...)) -> RedirectResponse:
    if unit_slug not in UNIT_REGISTRY:
        raise HTTPException(status_code=400, detail="Unknown unit")
    request.session["active_unit"] = unit_slug
    return RedirectResponse("/", status_code=303)


# ── Grade submission ──────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    unit_slug = _active_unit(request)
    assignments = get_unit_assignments(unit_slug)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "assignments": [
                type("A", (), {"id": aid, "display_name": title})()
                for aid, title in assignments
            ],
            "statuses": [s.value for s in SubmissionStatus],
            "unit_registry": UNIT_REGISTRY,
            "active_unit": unit_slug,
            "active_unit_label": UNIT_REGISTRY[unit_slug]["label"],
        },
    )


@app.post("/grade", response_class=HTMLResponse)
async def grade(
    request: Request,
    assignment_id: str = Form(...),
    status: SubmissionStatus = Form(...),
    student_code: str = Form(""),
    techsmart_lines_completed: int | None = Form(default=None),
    techsmart_lines_expected: int | None = Form(default=None),
) -> HTMLResponse:
    unit_slug = _active_unit(request)

    payload = GradingInput(
        assignment_id=assignment_id,
        status=status,
        student_code=student_code,
        techsmart_lines_completed=techsmart_lines_completed,
        techsmart_lines_expected=techsmart_lines_expected,
    )

    # Load context from cache (may be None if cache not yet populated)
    context = get_assignment_context(unit_slug, assignment_id)

    result = grade_submission(assignment_id, payload, context)

    entries = _unit_entries(request, unit_slug)
    existing = _entry_by_id(entries).get(assignment_id)
    include_default = False if existing is None else existing.include

    entry = UnitGradeEntry(
        assignment_id=assignment_id,
        assignment_label=result.assignment_title,
        points=result.points,
        include=include_default,
        weight=1.0,
        pending=not result.confirmed,
        flag_reasons=result.flag_reasons,
        computed_rubric_score=result.rubric_score,
    )
    updated = [e for e in entries if e.assignment_id != assignment_id] + [entry]
    _save_unit_entries(request, unit_slug, updated)

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "result": result,
            "points_map": POINTS_MAP,
            "active_unit_label": UNIT_REGISTRY[unit_slug]["label"],
        },
    )


# ── Confirm flagged submission ────────────────────────────────────────────────

@app.post("/confirm")
async def confirm_grade(
    request: Request,
    assignment_id: str = Form(...),
    override_score: int = Form(...),
) -> RedirectResponse:
    unit_slug = _active_unit(request)
    entries = _unit_entries(request, unit_slug)
    for entry in entries:
        if entry.assignment_id == assignment_id:
            entry.points = POINTS_MAP.get(override_score, 0)
            entry.computed_rubric_score = override_score
            entry.pending = False
            entry.flag_reasons = []
            break
    _save_unit_entries(request, unit_slug, entries)
    return RedirectResponse("/unit-grade", status_code=303)


# ── Unit grade ────────────────────────────────────────────────────────────────

@app.get("/unit-grade", response_class=HTMLResponse)
async def unit_grade_page(request: Request) -> HTMLResponse:
    unit_slug = _active_unit(request)
    entries = _unit_entries(request, unit_slug)
    confirmed = [e for e in entries if not e.pending]
    include_ids = {e.assignment_id for e in confirmed if e.include}
    avg = calculate_unit_grade(confirmed, include_ids)
    return templates.TemplateResponse(
        request,
        "unit_grade.html",
        {
            "entries": sorted(entries, key=lambda x: x.assignment_label),
            "unit_grade": avg,
            "included_ids": include_ids,
            "unit_registry": UNIT_REGISTRY,
            "active_unit": unit_slug,
            "active_unit_label": UNIT_REGISTRY[unit_slug]["label"],
            "points_map": POINTS_MAP,
        },
    )


@app.post("/unit-grade", response_class=HTMLResponse)
async def unit_grade_recalc(request: Request) -> HTMLResponse:
    unit_slug = _active_unit(request)
    form = await request.form()
    entries = _unit_entries(request, unit_slug)
    include_ids = {v for k, v in form.multi_items() if k == "include"}
    for entry in entries:
        if not entry.pending:
            entry.include = entry.assignment_id in include_ids
    confirmed = [e for e in entries if not e.pending]
    avg = calculate_unit_grade(confirmed, include_ids)
    _save_unit_entries(request, unit_slug, entries)
    return templates.TemplateResponse(
        request,
        "unit_grade.html",
        {
            "entries": sorted(entries, key=lambda x: x.assignment_label),
            "unit_grade": avg,
            "included_ids": include_ids,
            "unit_registry": UNIT_REGISTRY,
            "active_unit": unit_slug,
            "active_unit_label": UNIT_REGISTRY[unit_slug]["label"],
            "points_map": POINTS_MAP,
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reset")
async def reset_session(request: Request) -> RedirectResponse:
    unit_slug = _active_unit(request)
    _save_unit_entries(request, unit_slug, [])
    return RedirectResponse("/unit-grade", status_code=303)
