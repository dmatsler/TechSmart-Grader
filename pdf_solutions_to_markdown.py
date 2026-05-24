"""
pdf_solutions_to_markdown.py

Extract a TechSmart unit-solutions PDF into one markdown file per sub-unit
(unit_3_5_solutions.md, etc.). Includes every assignment in the PDF —
Instructions, Demos, Practices, Code Writing, Warm Ups, and any other
section types — because the teacher decides which ones to grade.

Each section becomes:
    ## <title>
    - Type: <subtitle>
    - Source: p.N or p.N–M
    - Solution non-blank lines: <count>
    ```python
    <code>
    ```

The solution code text is the source of truth. To produce the matching
starter file, duplicate the unit_X_Y_solutions.md to unit_X_Y_starters.md
and trim each block manually to whatever TechSmart actually shows students
for an unstarted assignment (don't trust an auto-stripper — some lines
under instructional comments are TechSmart-provided scaffolding, not
student work).

Detection of an assignment's first page:
    A page is a "first page" iff, after stripping date/URL/copyright noise,
    its third non-blank line matches a Python filename like
    "TechniqueXPracticeY.py" or "OutfitPicker_solution.py". The first two
    lines are the title and subtitle in that case. Continuation pages
    dive straight into numbered code and have no such triple.

Sub-unit grouping:
    Most titles start with "3.5 ..." or similar; that prefix becomes the
    unit slug ("3_5" -> "unit_3_5_solutions.md"). Items without such a
    prefix (the Unit 3 Quiz items) are emitted to a separate
    unit_3_quiz_solutions.md.

Usage:
    pip install pdfplumber
    python pdf_solutions_to_markdown.py \\
        --pdf /path/to/CS101_Unit_3_Solutions.pdf \\
        --out-dir /path/to/grader/data/
"""
from __future__ import annotations
import argparse
import re
import sys
from datetime import date
from pathlib import Path

import pdfplumber


# --- Patterns from the TechSmart PDF page format --------------------------

# Date line — appears at the very top of every page (sometimes also at
# the bottom). Two observed formats:
#   "1/18/2021 Code: Saving a Tuple"
#   "10/14/21, 10:36 AM Code: 3.5 Code Your Own"
RE_DATE = re.compile(r"^\d+/\d+/\d+(,\s+\d+:\d+\s+(AM|PM))?\s+Code:")
RE_URL = re.compile(r"^https://platform\.techsmart\.codes")
RE_COPYRIGHT = re.compile(r"^Copyright\b")

# Python filename — the third non-noise line on a first-page. This is the
# anchor we trust most: continuation pages don't have it.
RE_PY_FILENAME = re.compile(r"^[A-Za-z0-9_]+\.py\s*$")

# Line-number gutter: "16 color = ..." or just "37" for a blank source line.
RE_LINE_NUM = re.compile(r"^(\d+)(?:\s(.*))?$")

# Sub-unit prefix on a title: "3.5 Saving a Tuple" -> "3.5"
# Some titles double-up like "3.5 3.5 Code Your Own" -> still "3.5"
RE_SUBUNIT = re.compile(r"^(\d+\.\d+)")


def fix_ligatures(s: str) -> str:
    """
    pdfplumber returns NUL (\\x00) when it can't map a glyph. In TechSmart's
    PDFs every observed NUL is the 'fi' ligature: 'Defining', 'Outfit'.
    Map it back. If a different ligature ever shows up we'll iterate.
    """
    return s.replace("\x00", "fi")


# --- Page extraction ------------------------------------------------------

def parse_page(page) -> dict:
    """
    Return {"title": str|None, "subtitle": str|None, "body": [str, ...]}.
    title/subtitle are non-None only when the page is the first page of an
    assignment (detected by a "<title>/<subtitle>/<filename>.py" triple
    at the top of the page).
    """
    text = page.extract_text() or ""
    raw = [fix_ligatures(ln.rstrip()) for ln in text.splitlines()]

    cleaned: list[str] = []
    for ln in raw:
        if not ln.strip():
            continue
        if RE_DATE.match(ln) or RE_URL.match(ln) or RE_COPYRIGHT.match(ln):
            continue
        cleaned.append(ln)

    title = None
    subtitle = None
    body_start = 0
    # First-page signature: line[2] is a Python filename.
    if len(cleaned) >= 3 and RE_PY_FILENAME.match(cleaned[2]):
        # Sanity check: line[0] and line[1] should look like text, not code.
        # A line is "code-like" if it starts with a digit + space (numbered
        # gutter line). Skip if so — false-positive guard.
        if not RE_LINE_NUM.match(cleaned[0]) and not RE_LINE_NUM.match(cleaned[1]):
            title = cleaned[0].strip()
            subtitle = cleaned[1].strip()
            body_start = 3

    return {"title": title, "subtitle": subtitle, "body": cleaned[body_start:]}


def collect_assignments(pdf_path: Path) -> list[dict]:
    """Walk pages and group continuation pages into the prior assignment."""
    assignments: list[dict] = []
    current: dict | None = None
    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages, start=1):
            info = parse_page(page)
            if info["title"] is not None:
                if current is not None:
                    assignments.append(current)
                current = {
                    "title": info["title"],
                    "subtitle": info["subtitle"],
                    "first_page": page_idx,
                    "last_page": page_idx,
                    "body_lines": list(info["body"]),
                }
            else:
                if current is None:
                    continue  # pre-content page (cover/ToC)
                current["body_lines"].extend(info["body"])
                current["last_page"] = page_idx
    if current is not None:
        assignments.append(current)
    return assignments


# --- Body -> code ---------------------------------------------------------

def body_to_code(body_lines: list[str]) -> tuple[str, int]:
    """
    Convert numbered + wrap-continuation lines to clean Python text.
    Returns (code_text, non_blank_line_count).
    """
    python_lines: list[str] = []
    current: str | None = None
    for ln in body_lines:
        m = RE_LINE_NUM.match(ln)
        if m:
            if current is not None:
                python_lines.append(current)
            current = (m.group(2) or "").rstrip()
        else:
            if current is None:
                current = ln.rstrip()
            else:
                current = (current + " " + ln.strip()).rstrip()
    if current is not None:
        python_lines.append(current)
    code = "\n".join(python_lines).rstrip()
    nonblank = sum(1 for L in code.splitlines() if L.strip())
    return code, nonblank


# --- Markdown emission ----------------------------------------------------

def emit_unit_markdown(unit_label: str, unit_name: str, assignments: list[dict],
                       source_pdf: str, out_path: Path) -> None:
    """Write one markdown file with all sections of this sub-unit."""
    first_page = min(a["first_page"] for a in assignments)
    last_page = max(a["last_page"] for a in assignments)

    out = []
    out.append(f"# Unit {unit_label} — {unit_name}")
    out.append("")
    out.append(
        f"Solutions extracted from `{source_pdf}` "
        f"(pages {first_page}–{last_page})."
    )
    out.append(
        f"Extracted on {date.today().isoformat()}. "
        f"{len(assignments)} sections."
    )
    out.append("")
    out.append(
        "Each section below is a TechSmart assignment in this unit. The "
        "fenced Python block is the *solution*. To produce the matching "
        "starter file, duplicate this file as "
        f"`unit_{unit_label.replace('.', '_')}_starters.md` and trim each "
        "block to match what TechSmart actually shows students for the "
        "unstarted assignment."
    )
    out.append("")
    out.append("---")
    out.append("")

    for a in assignments:
        code, nonblank = body_to_code(a["body_lines"])
        page_span = (f"p.{a['first_page']}" if a["first_page"] == a["last_page"]
                     else f"p.{a['first_page']}–{a['last_page']}")
        out.append(f"## {a['title']}")
        out.append("")
        out.append(f"- **Type:** {a['subtitle']}")
        out.append(f"- **Source:** {page_span}")
        out.append(f"- **Solution non-blank lines:** {nonblank}")
        out.append("")
        out.append("```python")
        out.append(code)
        out.append("```")
        out.append("")
        out.append("---")
        out.append("")

    out_path.write_text("\n".join(out), encoding="utf-8")


def derive_unit_name(assignments: list[dict], unit_label: str) -> str:
    """
    The first Instruction's title minus the leading '<unit> ' prefix is
    typically the unit's display name (e.g., '3.5 Mouse & Keyboard' ->
    'Mouse & Keyboard'). Falls back to the first section's title if no
    Instruction is present.
    """
    for a in assignments:
        if a["subtitle"] == "Instruction":
            t = a["title"]
            t = re.sub(
                rf"^{re.escape(unit_label)}\s+(?:{re.escape(unit_label)}\s+)?",
                "",
                t,
            )
            return t
    # Fallback: use the first title verbatim
    return assignments[0]["title"]


# --- Main -----------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--pdf", required=True, type=Path,
                    help="Path to a TechSmart unit-solutions PDF")
    ap.add_argument("--out-dir", required=True, type=Path,
                    help="Directory to write unit_X_Y_solutions.md files")
    args = ap.parse_args()

    if not args.pdf.exists():
        sys.exit(f"PDF not found: {args.pdf}")
    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Reading {args.pdf} ...")
    all_assignments = collect_assignments(args.pdf)
    print(f"Found {len(all_assignments)} sections total.\n")

    # Group by sub-unit prefix; items without one go to a 'quiz' bucket.
    by_unit: dict[str, list[dict]] = {}
    quiz_items: list[dict] = []
    for a in all_assignments:
        m = RE_SUBUNIT.match(a["title"])
        if m:
            by_unit.setdefault(m.group(1), []).append(a)
        else:
            quiz_items.append(a)

    for unit_label, items in sorted(by_unit.items()):
        unit_name = derive_unit_name(items, unit_label)
        slug = unit_label.replace(".", "_")
        out_path = args.out_dir / f"unit_{slug}_solutions.md"
        emit_unit_markdown(unit_label, unit_name, items,
                           args.pdf.name, out_path)
        print(f"  unit_{slug}_solutions.md  ({len(items)} sections, "
              f"{unit_name})")

    if quiz_items:
        # Try to infer a quiz unit (e.g., "Unit 3 Quiz") from a docstring
        out_path = args.out_dir / "unit_3_quiz_solutions.md"
        emit_unit_markdown("3 Quiz", "Unit 3 Quiz Items",
                           quiz_items, args.pdf.name, out_path)
        print(f"  unit_3_quiz_solutions.md  ({len(quiz_items)} quiz sections)")

    print(f"\nDone. Wrote {len(by_unit) + (1 if quiz_items else 0)} files "
          f"to {args.out_dir}.")


if __name__ == "__main__":
    main()
