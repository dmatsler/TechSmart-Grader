# Adding or updating a unit

The end state of this workflow: students' submissions for a new (or updated) TechSmart unit can be scraped and graded through the web app or the batch GUI.

Plan for roughly **2–4 hours of focused work** when adding a fresh unit. The bulk is hand-trimming the starter file in step 3.

---

## Prerequisites

- The unit's official solutions PDF from TechSmart. A single PDF may cover multiple sub-units (e.g., `CS101_Unit_3_Solutions.pdf` covers 3.1 through 3.6 plus Unit 3 quiz items).
- `pdfplumber` and `pypdf` installed:
  ```bash
  pip install pdfplumber pypdf
  ```

---

## Step 1 — Convert the PDF to markdown

```bash
python pdf_solutions_to_markdown.py \
    --pdf path/to/CS101_Unit_X_Solutions.pdf \
    --out-dir .
```

This produces one markdown file per sub-unit (`unit_3_1_solutions.md` through `unit_3_6_solutions.md`, plus `unit_3_quiz_solutions.md` if the PDF contains quiz items).

Each file contains one section per assignment with the solution code in a fenced `python` block. The script keys on the `.py` filename anchor that appears on the first page of each assignment, so it correctly handles every assignment type: **Instruction**, **Coding Technique Demo**, **Coding Technique Practice**, **Code Writing**, **Warm Up**, **Code Restructure**, **Code Debug**, and **Student Coding Project**.

---

## Step 2 — Verify the solutions markdown against current TechSmart

**TechSmart sometimes updates their live curriculum without regenerating the solutions PDF.** Always spot-check that the extracted code matches what TechSmart's editor currently displays for that unit. If TechSmart has updated, edit the markdown's code blocks to match the current state.

The markdown is the source of truth — it is what gets compared to student submissions during grading. A stale solution will produce wrong grades.

**Recommended spot-check:** open one Code Writing assignment in TechSmart's teacher view, compare its solution to the markdown, resolve any differences. If you find changes, audit the rest of the unit before moving on.

When you edit a code block, the `**Solution non-blank lines:**` metadata line for that section will be stale. The loader recomputes this from the actual code at load time, so the displayed value is cosmetic — fix it manually if you want the file to be self-consistent.

---

## Step 3 — Create the starter file

```bash
cp unit_X_Y_solutions.md unit_X_Y_starter_code.md
```

Then edit `unit_X_Y_starter_code.md` and, for each section's code block, **delete only the lines TechSmart leaves blank for students to write**.

**Keep in the starter:**

- All comments — TechSmart's instructional comments are part of the scaffolding
- All `import` statements
- All variable initializations TechSmart pre-fills
- Structural keywords (`while drawing:`, `for event in pygame.event.get():`, `if event.type == pygame.QUIT:`)
- TechSmart-provided helper calls — `input("Press enter to continue...")`, `pygame.time.wait(800)`, `pygame.display.flip()`, etc.
- Anything that's in TechSmart's editor before the student starts typing

**Delete from the starter:**

- Implementation lines under `# Your code here` style comments
- Logic the student is supposed to write themselves
- Calculation, conditional, and draw-call bodies that the student is expected to produce

### Special cases

- **Code Debug** assignments — students don't add lines; they fix bugs in existing code. The starter keeps the bugs intact; the LLM grader compares the student's edits to the solution to evaluate whether the bugs were fixed. Line-count integrity check correctly stays silent for these.
- **Code Restructure** assignments — students rearrange or rewrite existing code. Same pattern as Code Debug. Keep TechSmart's starter as-is.
- **Coding Technique Practice** assignments — sometimes the starter is essentially the complete program and students just modify a value or two. Keep whatever TechSmart actually shows in the editor. Zero or near-zero line diff vs solution is normal here.
- **Warm Up** assignments — often partially complete. Trim to match TechSmart's actual starter view; orphan `if` statements or stray indentation that students are expected to wire up are real and should stay.
- **Instruction** sections — students don't write code in these. Keep `starter` = `solution`. They're not typically graded; the loader includes them so teachers can choose to grade them in a separate run if needed.

### Update the file header

After duplicating, the starter file's header text and per-section metadata still describe the solutions file. Fix:

1. **Intro paragraph** — replace "the fenced Python block is the *solution*" with "the fenced Python block is the *starter* — what TechSmart shows students for the unstarted assignment". Remove the line that tells you to duplicate the file (you already did).
2. **Per-section metadata** — change every `- **Solution non-blank lines:** N` to `- **Starter non-blank lines:** M`, where `M` is the actual starter count. The loader recomputes from code, so the displayed value is cosmetic, but it should be accurate for human reference.

---

## Step 4 — Load into the cache

```bash
python load_unit_from_markdown.py \
    --solutions unit_X_Y_solutions.md \
    --starters unit_X_Y_starter_code.md \
    --cache context_cache_X_Y.json \
    --check-syntax
```

The `--check-syntax` flag runs `ast.parse()` on each starter and reports failures. Some failures are legitimate:

- **Code Debug assignments** will fail (intentional syntax errors are the point).
- **Warm Up assignments** may fail (TechSmart's actual starter shows orphan `if` statements as scaffolding hints).

For each reported failure, verify against TechSmart's editor view that the starter is showing what students actually see. If yes, it's a legitimate scaffolding artifact and you can ignore the syntax warning. If no, fix the starter markdown and re-run.

The loader is **idempotent and non-destructive**: if `context_cache_X_Y.json` already exists, the loader preserves `requirements`, `req_hash`, and `assignment_id` for each entry. You can re-run after editing markdown without losing scraper-populated requirements.

---

## Step 5 — Register the unit in two places

The slugs in the cache need a matching entry in two locations so the GUI knows the unit exists and the scraper knows which gradebook columns to look at.

### 5a. `app/config_loader.py` — `UNIT_REGISTRY`

Append an entry keyed by the unit slug (e.g., `"3_X"`):

```python
"3_X": {
    "label": "Unit 3.X — Unit Name",
    "fallback_assignments": [
        ("3_X_assignment_slug_1", "3.X Assignment Title 1"),
        ("3_X_assignment_slug_2", "3.X Assignment Title 2"),
        # ... one tuple per assignment in the cache
    ],
},
```

The slugs must exactly match the cache keys. To dump the list quickly:

```bash
python -c "import json; print('\n'.join(json.load(open('context_cache_3_X.json'))['assignments'].keys()))"
```

The titles on the right side should be the **full** assignment titles with the unit prefix (e.g., `"3.6 Reaction Timer"`). These are used in the GUI's assignment-selection UI.

### 5b. `batch/scraper.py` — `ASSIGNMENT_TITLE_MAP`

Append entries to map each slug to **the title that appears in TechSmart's gradebook column header**:

```python
# Unit 3.X — Unit Name
"3_X_assignment_slug_1": "Gradebook Column Title 1",
"3_X_assignment_slug_2": "Gradebook Column Title 2",
# ...
```

**These titles often differ from the `UNIT_REGISTRY` titles**. Empirical pattern from existing units:

- Most columns drop the `3.X ` prefix: `"3.5 Saving a Tuple (1)"` in UNIT_REGISTRY → `"Saving a Tuple (1)"` in the gradebook column.
- **Instruction** columns keep the prefix: `"3.6 Time"` in both places.
- **Code Your Own** variants keep the prefix: `"3.5 Code Your Own"` in both places.
- Variant numbers preserve their `(1)` / `(2)` suffix.

Open the TechSmart gradebook in a browser tab and read the column titles directly. Don't guess.

---

## Step 6 — Scrape requirements

From the batch GUI (the "Refresh context cache" button), or programmatically:

```python
from app.context_scraper import refresh_context_cache

await refresh_context_cache(
    unit_slug="3_X",
    gradebook_url="https://platform.techsmart.codes/gradebook/...",
    username="...",
    password="...",
)
```

This fills the `requirements` field in each cache entry. It does **not** touch `starter_code`, `solution_code`, or their hashes — those came from your markdown and are preserved. The two operations are independent; you can re-run either one without disturbing the other's work.

---

## Step 7 — Sanity-check by grading one submission

In the web app: pick the unit, pick an assignment you know has a complete correct submission, paste the code, run it. Confirm:

- The rubric score is reasonable (likely 3/3 for a known correct submission)
- The teacher explanation references the assignment correctly (not a different assignment's content)
- The student feedback is appropriate

Then repeat for a student who you know didn't submit, to confirm the "not submitted" path works (rubric score 0 or 1 depending on submission status).

Once both pass, the unit is ready for batch grading.

---

## Common pitfalls

### `⚠ No title mapping for X` during scrape

The `ASSIGNMENT_TITLE_MAP` entry is missing for slug `X`. Add the entry per step 5b.

### `Discovered 0/N URLs`

None of the title strings matched the gradebook column titles. Double-check:

- Capitalization
- The `3.X ` prefix on Instruction and Code Your Own entries
- TechSmart curriculum rename you may have missed
- Whether the gradebook columns use a different format than other units

If unsure, copy a column title from TechSmart's gradebook (literal text) and paste it as the value in `ASSIGNMENT_TITLE_MAP`.

### Cache shows empty `requirements` after running the scraper

The scraper logged in but failed to navigate to the assignment pages. Check the progress log for `✗ Could not load X` messages. Common causes: TechSmart UI changes (selector mismatch), session expired mid-run, or Playwright timing issues. Re-run; if it persists, the scraper's selectors may need an update.

### Cache shows empty `starter_code` or `solution_code`

The markdown loader didn't run, didn't find your files, or your markdown is missing fenced ```python blocks. Re-run `load_unit_from_markdown.py` and verify each section has a properly fenced python block.

### Grade calculator returns oddly low percentages

A grading run is treating missing scraper results as zero submissions. Make sure `batch/batch_runner.py`'s `compute_run_grades` has the `if ar is None: continue` skip — added in commit `54b52c1`. If you're seeing this on an updated checkout, run `git log batch/batch_runner.py` to confirm.

### Markdown files accidentally committed to git

Verify `.gitignore` includes `unit_*_solutions.md` and `unit_*_starter_code.md`. If they got committed before the ignore rule was added, untrack them without deleting:

```bash
git rm --cached unit_X_Y_solutions.md unit_X_Y_starter_code.md
git commit -m "Untrack curriculum markdown (already gitignored going forward)"
```

The files stay on your disk; only the git tracking is removed. (Note that previously-committed content stays in git history forever unless you scrub it with `git filter-repo` or BFG — separate operation, not usually worth doing unless the repo is public.)

### Per-student click times out during scrape

You may see `Locator.click: Timeout 30000ms exceeded` with `element is not visible`. This is a viewport issue with TechSmart's student picker dropdown when your class has many students — students past the fold aren't visible to Playwright. The fix (already applied as of commit `54b52c1`) is `scroll_into_view_if_needed()` before the click. If you see this on an updated checkout, the fix may have regressed during a refactor — check `batch/scraper.py` around the per-student loop.

---

## Reference: file roles in the cache pipeline

| File | Source | Used by | Gitignored |
|---|---|---|---|
| `unit_X_Y_solutions.md` | hand-curated from PDF, edited to match TechSmart | `load_unit_from_markdown.py` | yes |
| `unit_X_Y_starter_code.md` | hand-trimmed from solutions | `load_unit_from_markdown.py` | yes |
| `context_cache_X_Y.json` | written by loader, requirements added by scraper | grader (web + batch) | yes |
| `app/config_loader.py` (UNIT_REGISTRY) | hand-edited | GUI unit selector, validation | no |
| `batch/scraper.py` (ASSIGNMENT_TITLE_MAP) | hand-edited | gradebook URL discovery | no |
