# TechSmart Grading Companion (MVP)

TechSmart Grading Companion is a **local, teacher-facing MVP web app** for grading **CS101 Unit 3.3 Python/Pygame assignments** with rubric-based scoring.

> This is an MVP prototype for TechSmart-style rubric grading. It prioritizes static checks + template-aware fill-zone matching over full runtime execution.

## What this app does

- Grades pasted student code against the provided Unit 3.3 config.
- Returns:
  - rubric score (`0`, `1`, `2`, `3`)
  - point score (`0`, `50`, `75`, `100`)
  - teacher-facing explanation
  - matched/unmet fill zones
  - coherence guardrail failures
  - requirement check failures
- Tracks graded assignments in-memory per browser session and computes a **unit grade out of 100**.

## Stack

- Python 3.11+
- FastAPI
- Jinja2 templates
- PyYAML config loading
- pytest test suite

## Project structure

- `app/main.py` – FastAPI routes + in-memory session results
- `app/config_loader.py` – YAML-first / JSON-fallback config loader + validation
- `app/grader.py` – grading engine and rule evaluation
- `app/models.py` – typed dataclass models for config, request, and grading output
- `app/utils.py` – parsing/matching helpers
- `templates/` – server-rendered pages
- `static/style.css` – minimal CSS
- `tests/test_grader.py` – MVP grading rules tests

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run locally

```bash
uvicorn app.main:app --reload
```

Open: <http://127.0.0.1:8000>

## Run tests

```bash
pytest -q
```

## Grading rules implemented

1. **Turned-in + 0/X lines rule** (only line-count rule):
   - If status is `turned_in` and `techsmart_lines_completed == 0` and `techsmart_lines_expected > 0`, score is `0` immediately.
2. **Status rules**:
   - `not_started` -> score `0`
   - `started_not_submitted` -> `0` or `1` depending on meaningful attempt
   - `turned_in` -> `1`, `2`, or `3` based on meaningful attempt, syntax/requirement/coherence checks
3. **Meaningful attempt**:
   - Template-aware zone matching via `fill_zones`
   - Excludes anti-pattern matches
   - Requires minimum relevant zone matches
4. **Score 3 expectations**:
   - Expected patterns + requirement checks + guardrails must pass
   - Syntax parse via `ast.parse`

## MVP assumptions / limitations

- Runtime smoke execution is intentionally disabled for MVP (pygame runtime sandboxing can be fragile in generic local environments).
- Coherence checks are text-based and intentionally lightweight; architecture is ready for deeper AST-based checks later.
- Session history is in-memory only (no DB, reset on server restart).
- No authentication, deployment, TechSmart API integration, or browser extension integration yet.

## Future extensibility

The app is structured so later versions can add:

- browser extension ingestion from TechSmart “More Actions -> View”
- PDF/template diff helpers
- AST-level semantic checks
- additional units beyond CS101 Unit 3.3
