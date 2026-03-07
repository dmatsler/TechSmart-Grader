from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.config_loader import assignment_lookup, load_config
from app.grader import grade_submission
from app.models import GradingInput, SubmissionStatus, UnitGradeEntry

BASE_DIR = Path(__file__).resolve().parent.parent

app = FastAPI(title="TechSmart Grading Companion")
app.add_middleware(SessionMiddleware, secret_key="techsmart-mvp-secret")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

CONFIG = load_config(BASE_DIR / "unit_3_3_animation_grading_config_working.yaml", BASE_DIR / "unit_3_3_animation_grading_config_working.json")
ASSIGNMENTS = assignment_lookup(CONFIG)
SESSION_RESULTS: dict[str, list[UnitGradeEntry]] = {}


def _session_key(request: Request) -> str:
    sid = request.session.get("sid")
    if not sid:
        sid = secrets.token_hex(16)
        request.session["sid"] = sid
    return sid


@app.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "assignments": CONFIG.assignments,
            "statuses": [s.value for s in SubmissionStatus],
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
    assignment = ASSIGNMENTS[assignment_id]
    payload = GradingInput(
        assignment_id=assignment_id,
        status=status,
        student_code=student_code,
        techsmart_lines_completed=techsmart_lines_completed,
        techsmart_lines_expected=techsmart_lines_expected,
    )
    result = grade_submission(assignment, payload)

    sid = _session_key(request)
    entry = UnitGradeEntry(
        assignment_id=assignment.id,
        assignment_label=assignment.display_name,
        points=result.points,
        include=assignment.count_in_unit_grade_default,
        weight=assignment.weight,
    )
    SESSION_RESULTS.setdefault(sid, [])
    SESSION_RESULTS[sid] = [e for e in SESSION_RESULTS[sid] if e.assignment_id != entry.assignment_id] + [entry]

    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "result": result,
            "points_map": assignment.rubric_to_points_default,
        },
    )


@app.get("/unit-grade", response_class=HTMLResponse)
async def unit_grade_page(request: Request) -> HTMLResponse:
    sid = _session_key(request)
    entries = SESSION_RESULTS.get(sid, [])
    include_ids = {e.assignment_id for e in entries if e.include}
    avg = _calculate_unit_grade(entries, include_ids)
    return templates.TemplateResponse(
        request,
        "unit_grade.html",
        {
            "entries": entries,
            "unit_grade": avg,
            "included_ids": include_ids,
        },
    )


@app.post("/unit-grade", response_class=HTMLResponse)
async def unit_grade_recalc(request: Request) -> HTMLResponse:
    sid = _session_key(request)
    form = await request.form()
    entries = SESSION_RESULTS.get(sid, [])
    include_ids = {v for k, v in form.multi_items() if k == "include"}
    for e in entries:
        e.include = e.assignment_id in include_ids
    avg = _calculate_unit_grade(entries, include_ids)
    return templates.TemplateResponse(
        request,
        "unit_grade.html",
        {
            "entries": entries,
            "unit_grade": avg,
            "included_ids": include_ids,
        },
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/reset")
async def reset_session(request: Request) -> RedirectResponse:
    sid = _session_key(request)
    SESSION_RESULTS[sid] = []
    return RedirectResponse("/unit-grade", status_code=303)


def _calculate_unit_grade(entries: list[UnitGradeEntry], include_ids: set[str]) -> float:
    included = [e for e in entries if e.assignment_id in include_ids]
    if not included:
        return 0.0
    total_weight = sum(e.weight for e in included)
    if total_weight <= 0:
        return 0.0
    return round(sum(e.points * e.weight for e in included) / total_weight, 2)
