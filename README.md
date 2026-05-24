# TechSmart Grading Companion

AI-powered rubric grading for TechSmart Python assignments. Replaces TechSmart's line-count proxy with substantive evaluation: rubric scoring (0/1/2/3 → 0/50/75/100), integrity checks, and per-student feedback. Currently in classroom use for CS101 Units 3.3, 3.5, and 3.6.

---

## Why this exists

TechSmart evaluates student Python assignments using a **line-count proxy** — a pie-chart bubble that fills as students write more lines of code. Per TechSmart's own gradebook documentation, certain assignment indicators are scored by *number of lines written*. The only way a syntax error surfaces is if the student runs their program before turning it in; if they don't, the system stays silent.

This creates a critical gap: students can game the system by copying random or incomplete lines to fill the bubble without producing functional programs. A full green bubble does not mean working code.

For a teacher managing 60+ students with 6–15 programs per unit, manually running every submission is unsustainable — a two-week unit means 600–900 programs. This companion analyzes actual student code against assignment-specific solution code, requirements, and integrity rules, returning meaningful feedback the bubble system never provides.

---

## What it does

Two interfaces, one shared grading engine:

**Web app** — manual single-submission grading. FastAPI + Jinja2. Pick a unit, pick an assignment, paste student code, get a rubric score with both a teacher-facing explanation and a student-facing feedback message.

**Desktop batch GUI** — full-class processing. Tkinter front end driving a Playwright-based scraper. Logs into TechSmart, auto-discovers assignment URLs from the gradebook, scrapes every student's submission, grades the whole class in parallel, and exports CSV + HTML reports. Includes an anonymization mode that maps real student names to placeholders before reports are written, saving the mapping locally as `DO_NOT_SHARE_*.json` (gitignored) so you can share reports with developers without leaking student PII.

Both interfaces share `app/ai_grader.py` (the LLM grading engine) and `app/context_scraper.py` (the cache hydration layer that fetches requirements from TechSmart).

---

## How a submission is graded

For each student submission, the LLM grader receives:

- **Requirements** — assignment text scraped from TechSmart
- **Starter code** — what TechSmart shows for an unstarted assignment (hand-curated; not student-written)
- **Solution code** — what a complete correct submission looks like (hand-curated)
- **Student code** — what the student actually wrote
- **TechSmart submission status** — `not_assigned` / `not_started` / `started_not_submitted` / `turned_in`
- **Optional per-assignment notes** — human-authored grading hints in `ASSIGNMENT_NOTES`
- **Integrity rules** — patterns that should flag a submission for teacher review

The grader returns a rubric score (0–3), a teacher-facing explanation, and a short student-facing feedback string. Flagged submissions enter a **pending review** state — excluded from grade averages and surfaced in a confirm-or-override dialog before reports write.

### Integrity flags

The grader flags submissions matching any of:

- **Line count > 150% of expected** (programmatic check against the curated starter/solution) — possible AI-assisted padding
- **Print-only code** with no logic
- **Random / unrelated lines** that don't relate to the assignment objective
- **Code from a different assignment** (wrong shapes, wrong variables, wrong objective)
- **Above-grade-level constructs** (classes, list comprehensions, lambdas, unusual imports)
- **Two separate program implementations** in one submission (copy-paste from elsewhere)
- **Starter-template only** (no student-written code beyond what TechSmart provides)

Flags surface in a teacher-review dialog at the end of grading. The teacher confirms, adjusts, or overrides each before reports are written.

---

## Architecture

```
TechSmart solutions PDF (per-unit)
        │
        ▼  pdf_solutions_to_markdown.py
unit_X_Y_solutions.md           ← edited to match current TechSmart curriculum
        │
        ▼  (duplicated and trimmed by hand)
unit_X_Y_starter_code.md        ← what TechSmart shows for unstarted assignment
        │
        ▼  load_unit_from_markdown.py
context_cache_X_Y.json          ← populated starter_code + solution_code
        │
        ▼  context_scraper.refresh_context_cache (Playwright)
context_cache_X_Y.json          ← + requirements (preserves markdown-sourced fields)
        │
        ▼  Web app (single submission) or batch GUI (whole class)
Per-student rubric scores → CSV + HTML reports
```

The markdown files are the **source of truth** for starter and solution code. They are gitignored — TechSmart's curriculum is their copyrighted material — but live in your project root so you can re-edit and re-load whenever TechSmart revises a lesson.

---

## Stack

- **Python 3.11+**
- **FastAPI + Jinja2** — web interface
- **Tkinter** — desktop batch GUI
- **Playwright** — TechSmart automation (gradebook scraping, per-student submission scraping)
- **LLM providers** (configurable in `llm_config.json`):
  - **Anthropic** (`claude-haiku-4-5` — recommended; strong instruction-following at temperature 0)
  - **OpenAI** (`gpt-4o-mini` — cheaper but weaker on nuanced grading rules)
  - **Groq** (free tier, rate-limited)
  - **Ollama** (fully local, no API cost)
- **pdfplumber, pypdf** — PDF → markdown conversion (only needed when adding a new unit)
- **pytest** — test suite

---

## Project structure

```
app/                              FastAPI web app + shared grading engine
  main.py                           web routes + session state
  ai_grader.py                      LLM grading engine (shared by web + batch)
  config_loader.py                  UNIT_REGISTRY, active-unit selection
  context_scraper.py                cache hydration via Playwright (requirements only)
  models.py                         typed dataclasses
  unit_grade.py                     unit grade calculation

batch/                            Desktop batch GUI
  gui.py                            Tkinter UI
  batch_runner.py                   orchestrates scrape → grade → report
  scraper.py                        per-student submission scraping
  report.py                         CSV + HTML report writers

templates/                        Jinja2 templates for the web app
static/                           CSS for the web app

load_unit_from_markdown.py        CLI: markdown → context_cache JSON
pdf_solutions_to_markdown.py      CLI: TechSmart solutions PDF → markdown
inspect_cache.py                  CLI: read and pretty-print a cache file
llm_config.json                   provider/model selection
.env                              API keys + TechSmart credentials (gitignored)

context_cache_*.json              per-unit cache (gitignored — TechSmart material)
unit_*_solutions.md               hand-curated solution code (gitignored)
unit_*_starter_code.md            hand-curated starter code (gitignored)
```

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install firefox
```

Create a `.env` file in the project root:

```
ANTHROPIC_API_KEY=sk-ant-...      # if using Anthropic (recommended)
OPENAI_API_KEY=sk-...             # if using OpenAI
GROQ_API_KEY=gsk_...              # if using Groq
TECHSMART_USERNAME=your-username
TECHSMART_PASSWORD=your-password
```

If you'll be adding new units, install the PDF conversion dependencies:

```bash
pip install pdfplumber pypdf
```

---

## Run

**Web app:**
```bash
uvicorn app.main:app --reload
# → http://127.0.0.1:8000
```

**Desktop batch GUI:**
```bash
python -m batch.gui
```

**Tests:**
```bash
pytest -q
```

---

## Adding or updating a unit

When TechSmart releases new curriculum or updates an existing unit, see **[`docs/adding_a_unit.md`](docs/adding_a_unit.md)** for the full step-by-step workflow.

Quick overview:

1. Get the unit's solutions PDF from TechSmart.
2. Run `pdf_solutions_to_markdown.py` to convert it to one markdown file per sub-unit.
3. Edit the solutions markdown to match what TechSmart actually shows (the PDFs sometimes lag the live curriculum).
4. Duplicate to `unit_X_Y_starter_code.md` and trim each block to match what TechSmart shows for unstarted assignments.
5. Run `load_unit_from_markdown.py` to populate the cache.
6. Register the unit in `app/config_loader.py` (`UNIT_REGISTRY`) and `batch/scraper.py` (`ASSIGNMENT_TITLE_MAP`).
7. Run the scraper to fill requirements.

---

## Screenshots

### Grade Submission
![Grade Submission](screenshots/Submission_entry_screenshot.png)

### Grading Result — Score 0
![True 0](screenshots/True_0_screenshot.png)

### Grading Result — Score 1 (50/100)
![True 1](screenshots/True_1_screenshot.png)

### Grading Result — Score 2 (75/100)
![True 2](screenshots/True_2_screenshot.png)

### Grading Result — Score 3 (100/100)
![True 3](screenshots/True_3_screenshot.png)

### Unit Grade Calculator
![Unit Grade](screenshots/Unit_Grade_screenshot.png)

---

## Known limitations

- **Runtime smoke execution not implemented.** Grading is static via LLM + integrity rules. Pygame sandboxing is fragile in generic local environments; this is intentionally deferred.
- **Web app session results are in-memory only.** Reset on server restart. No database.
- **"Stop Grading" button** in the batch GUI exists but the cancellation token isn't checked by async tasks yet. Closing the window mid-run loses progress for in-flight assignments.
- **Flag Reasons column** in the web `unit_grade.html` and the desktop review dialog have known wrapping/sizing issues being tracked.
- **No browser extension yet.** Pre-submit student-facing validation is the long-term goal but not built.

---

## Roadmap

- **Chrome extension** that intercepts TechSmart's Turn In button and runs grader checks before submission, returning actionable feedback to the student at submission time
- **AST-level semantic verification** — confirm students used required structures (loops, functions, conditionals) rather than inflating line counts
- **Safe sandboxed runtime execution** for programs that benefit from "does it actually run"
- **Coverage for additional units** beyond 3.3, 3.5, 3.6
- **Workflow polish** — a single CLI that runs the full add-a-unit pipeline (PDF → markdown → load → register) end-to-end
