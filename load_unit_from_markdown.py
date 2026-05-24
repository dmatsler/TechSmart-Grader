"""
load_unit_from_markdown.py

Read a pair of markdown files — solutions and starters — for a TechSmart
unit and produce (or merge into) a context_cache_X_Y.json that the grader
can consume.

The markdown code blocks are authoritative (copy-pasted from TechSmart by
hand). The loader never modifies them; it only re-derives counts, slugs,
and hashes for the cache.

Why this replaces the scraper-based starter/solution path:
    The student-facing TechSmart pages don't expose solution code at all,
    and the "starter" the scraper grabbed was actually whatever code was
    in the first student's editor — fully implemented submissions, not
    blank starters. The line-count integrity check (`actual > 1.5 *
    expected`) couldn't fire because `expected_added = solution - starter`
    came out ≈ 0 for almost every assignment. Curated markdown gives both
    sides a real source of truth.

Cache schema produced (per assignment):
    {
        "assignment_id":    str,   # slug (or preserved from existing cache)
        "title":            str,   # "3.6 Saving a Tuple (2)"
        "assignment_type":  str,   # "Warm Up" / "Code Writing" / "Code Debug" / ...
        "requirements":     str,   # preserved from existing cache if present
        "starter_code":     str,   # verbatim from starters markdown
        "solution_code":    str,   # verbatim from solutions markdown
        "req_hash":         str,   # md5 of requirements
        "starter_hash":     str,   # md5 of starter_code
        "solution_hash":    str,   # md5 of solution_code
        "scraped_at":       str    # ISO-8601 UTC timestamp of this load
    }

Why `assignment_type` is now a cache field:
    Code Debug and Code Restructure assignments have starter ≈ solution
    by line count but real student work happens inside the lines (fixing
    bugs, renaming variables). The line-count integrity check correctly
    stays silent on those; the LLM grading is what catches the work. With
    the type carried into the cache, the grader prompt can condition on
    it ("for Code Debug, judge whether bugs are fixed, not line counts").

Usage:
    python load_unit_from_markdown.py \\
        --solutions unit_3_6_solutions.md \\
        --starters unit_3_6_starter_code.md \\
        --cache context_cache_3_6.json \\
        [--check-syntax]   # ast.parse each starter; report failures
        [--dry-run]        # report what would change; don't write

Exit codes:
    0  success
    1  loader error (file missing, section mismatch, etc.)
    2  --check-syntax found one or more starters that don't parse
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# --- Markdown parsing -----------------------------------------------------

# Headers and metadata patterns
RE_SECTION_HEADER = re.compile(r"^## (.+)$")
RE_TYPE = re.compile(r"^- \*\*Type:\*\* (.+)$")
RE_SOURCE = re.compile(r"^- \*\*Source:\*\* (.+)$")
RE_FENCE_PY = re.compile(r"^```python\s*$")
RE_FENCE_CLOSE = re.compile(r"^```\s*$")

# Filename like "unit_3_6_solutions.md" -> unit label "3.6"
RE_UNIT_IN_FILENAME = re.compile(r"unit_(\d+)_(\d+)_")


def parse_markdown_sections(path: Path) -> list[dict]:
    """
    Parse a unit markdown file into a list of section dicts:
        {"title": str, "type": str|None, "source": str|None, "code": str}

    Section boundaries are "## " headers. Within each section, the first
    fenced ```python block is treated as the authoritative code. Anything
    else (metadata bullets, narrative) is read but only `type` is kept.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    sections: list[dict] = []
    current: dict | None = None
    in_code = False
    code_buf: list[str] = []

    for line in lines:
        m = RE_SECTION_HEADER.match(line)
        if m and not in_code:
            # Flush previous section
            if current is not None:
                current["code"] = "\n".join(code_buf)
                sections.append(current)
            current = {
                "title": m.group(1).strip(),
                "type": None,
                "source": None,
                "code": "",
            }
            code_buf = []
            continue

        if current is None:
            continue  # still in the file preamble

        if in_code:
            if RE_FENCE_CLOSE.match(line):
                in_code = False
            else:
                code_buf.append(line)
            continue

        if RE_FENCE_PY.match(line):
            in_code = True
            continue

        m = RE_TYPE.match(line)
        if m:
            current["type"] = m.group(1).strip()
            continue
        m = RE_SOURCE.match(line)
        if m:
            current["source"] = m.group(1).strip()
            continue
        # ignore other lines (Source: line, count line, blank, etc.)

    if current is not None:
        current["code"] = "\n".join(code_buf)
        sections.append(current)

    return sections


# --- Slug generation ------------------------------------------------------

def detect_unit_label(path: Path) -> str:
    """Extract '3.6' from path like 'unit_3_6_solutions.md'."""
    m = RE_UNIT_IN_FILENAME.search(path.name)
    if not m:
        raise ValueError(
            f"Couldn't detect unit label from filename {path.name!r}. "
            f"Expected name like 'unit_3_6_solutions.md'."
        )
    return f"{m.group(1)}.{m.group(2)}"


def title_to_slug(title: str, unit_label: str) -> str:
    """
    Convert a title like '3.6 Saving a Tuple (2)' to '3_6_saving_a_tuple_2'.
    Strips the leading '<unit> ' prefix (and a duplicated prefix in cases
    like '3.6 3.6 Code Your Own'), lowercases, and runs every non-alnum
    character to a single underscore.
    """
    t = title
    # Strip up to two repeats of the unit prefix (handles "3.6 3.6 ...")
    for _ in range(2):
        t = re.sub(rf"^{re.escape(unit_label)}\s+", "", t)
    t = t.lower()
    t = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
    unit_slug = unit_label.replace(".", "_")
    return f"{unit_slug}_{t}" if t else unit_slug


# --- Cache construction ---------------------------------------------------

def md5_str(s: str) -> str:
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def build_cache(unit_label: str,
                sol_sections: list[dict],
                sta_sections: list[dict],
                existing_cache: dict | None) -> tuple[dict, list[str]]:
    """
    Pair sections by title and build the cache dict. Returns
    (cache_dict, warnings).

    Section pairing:
        Titles must match 1:1 in the same order. If not, raises ValueError
        with the specific mismatch so the user can fix the markdown.

    Preservation:
        If `existing_cache` is provided (i.e., we're updating an existing
        cache rather than building from scratch), per-assignment fields
        `assignment_id`, `requirements`, and `req_hash` are preserved.
        Everything else is rebuilt from the markdown.
    """
    if len(sol_sections) != len(sta_sections):
        raise ValueError(
            f"Section count mismatch: {len(sol_sections)} solution sections "
            f"vs {len(sta_sections)} starter sections."
        )

    # Check titles align exactly, in order
    for i, (s, t) in enumerate(zip(sol_sections, sta_sections), start=1):
        if s["title"] != t["title"]:
            raise ValueError(
                f"Section #{i} title mismatch:\n"
                f"  solutions: {s['title']!r}\n"
                f"  starters:  {t['title']!r}"
            )

    warnings: list[str] = []
    unit_slug = unit_label.replace(".", "_")
    now = datetime.now(timezone.utc).isoformat()

    existing_assignments = (existing_cache or {}).get("assignments", {})

    new_assignments: dict[str, dict] = {}
    seen_slugs: set[str] = set()

    for sol, sta in zip(sol_sections, sta_sections):
        title = sol["title"]
        slug = title_to_slug(title, unit_label)
        if slug in seen_slugs:
            raise ValueError(
                f"Slug collision: {title!r} normalizes to {slug!r}, "
                f"which has already been used. Rename one of the sections."
            )
        seen_slugs.add(slug)

        if sol["type"] != sta["type"]:
            warnings.append(
                f"{title!r}: Type differs — solutions says "
                f"{sol['type']!r}, starters says {sta['type']!r}. "
                f"Using solutions value."
            )

        starter_code = sta["code"]
        solution_code = sol["code"]

        prior = existing_assignments.get(slug, {})
        requirements = prior.get("requirements", "")
        req_hash = prior.get("req_hash", md5_str(requirements))
        assignment_id = prior.get("assignment_id", slug)

        new_assignments[slug] = {
            "assignment_id": assignment_id,
            "title": title,
            "assignment_type": sol["type"],
            "requirements": requirements,
            "starter_code": starter_code,
            "solution_code": solution_code,
            "req_hash": req_hash,
            "starter_hash": md5_str(starter_code),
            "solution_hash": md5_str(solution_code),
            "scraped_at": now,
        }

    cache = {
        "unit_slug": unit_slug,
        "last_updated": now,
        "assignments": new_assignments,
    }
    return cache, warnings


# --- Starter syntax check -------------------------------------------------

def check_starter_syntax(sta_sections: list[dict]) -> list[tuple[str, str]]:
    """
    Run ast.parse on each starter's code. Return list of (title, error_msg)
    for the ones that don't parse as valid Python.

    Why this exists:
        Some hand-stripped starters may be syntactically incomplete because
        TechSmart's editor displays them that way (e.g., an indented `if`
        with no `for` above it — the student is expected to write the
        outer structure). The check doesn't block loading; it just surfaces
        a list so you can verify each one matches TechSmart's actual view.
    """
    failures: list[tuple[str, str]] = []
    for sec in sta_sections:
        code = sec.get("code", "")
        if not code.strip():
            continue  # blank starter is fine
        try:
            ast.parse(code)
        except SyntaxError as e:
            failures.append((sec["title"], f"line {e.lineno}: {e.msg}"))
    return failures


# --- Reporting helpers ----------------------------------------------------

def summarize(cache: dict) -> None:
    """Print a human-readable summary of what got loaded."""
    by_type: dict[str, int] = {}
    for entry in cache["assignments"].values():
        t = entry.get("assignment_type") or "(no type)"
        by_type[t] = by_type.get(t, 0) + 1

    print(f"Unit slug: {cache['unit_slug']}")
    print(f"Assignments: {len(cache['assignments'])}")
    print("By type:")
    for t in sorted(by_type):
        print(f"  {t:<32}  {by_type[t]:>3}")


# --- Main -----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Load a TechSmart unit's solutions+starters markdown "
                    "into a context_cache JSON.",
    )
    ap.add_argument("--solutions", required=True, type=Path,
                    help="Path to unit_X_Y_solutions.md")
    ap.add_argument("--starters", required=True, type=Path,
                    help="Path to unit_X_Y_starter_code.md (or similar)")
    ap.add_argument("--cache", required=True, type=Path,
                    help="Path to context_cache_X_Y.json to create or update")
    ap.add_argument("--check-syntax", action="store_true",
                    help="Run ast.parse on each starter; report any failures")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change but do not write the cache")
    args = ap.parse_args()

    for p in (args.solutions, args.starters):
        if not p.exists():
            print(f"ERROR: file not found: {p}", file=sys.stderr)
            return 1

    unit_label = detect_unit_label(args.solutions)
    sol_unit = detect_unit_label(args.solutions)
    sta_unit = detect_unit_label(args.starters)
    if sol_unit != sta_unit:
        print(f"ERROR: solutions file is for unit {sol_unit} but "
              f"starters file is for unit {sta_unit}. Aborting.",
              file=sys.stderr)
        return 1

    print(f"Loading unit {unit_label} ...")
    sol_sections = parse_markdown_sections(args.solutions)
    sta_sections = parse_markdown_sections(args.starters)
    print(f"  solutions:  {len(sol_sections)} sections")
    print(f"  starters:   {len(sta_sections)} sections")

    existing_cache: dict | None = None
    if args.cache.exists():
        try:
            existing_cache = json.loads(args.cache.read_text(encoding="utf-8"))
            print(f"  existing cache loaded "
                  f"({len(existing_cache.get('assignments', {}))} assignments)"
                  " — requirements will be preserved")
        except json.JSONDecodeError as e:
            print(f"WARNING: existing cache exists but isn't valid JSON "
                  f"({e}); starting fresh", file=sys.stderr)

    try:
        cache, warnings = build_cache(
            unit_label, sol_sections, sta_sections, existing_cache,
        )
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print()
    summarize(cache)

    if warnings:
        print()
        print("WARNINGS:")
        for w in warnings:
            print(f"  {w}")

    syntax_failed = False
    if args.check_syntax:
        print()
        print("--- starter syntax check ---")
        failures = check_starter_syntax(sta_sections)
        if not failures:
            print(f"All {len(sta_sections)} starters parse as valid Python.")
        else:
            print(f"{len(failures)} starter(s) don't parse — verify each "
                  f"matches TechSmart's editor view:")
            for title, msg in failures:
                print(f"  {title!r}")
                print(f"      {msg}")
            syntax_failed = True

    if args.dry_run:
        print()
        print("(dry-run — cache not written)")
    else:
        args.cache.parent.mkdir(parents=True, exist_ok=True)
        args.cache.write_text(
            json.dumps(cache, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print()
        print(f"Wrote {args.cache} ({len(cache['assignments'])} assignments).")

    return 2 if syntax_failed else 0


if __name__ == "__main__":
    sys.exit(main())
