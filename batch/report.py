"""
Report generator — writes grading results to CSV and a simple HTML summary.

CSV format:
  Student | Run1_Grade | Run2_Grade | ... | Assign1_Score | Assign1_Points | ...

HTML format:
  A clean table version of the CSV, color-coded by score (0=red, 1=yellow,
  2=light-green, 3=green), viewable in any browser.
"""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

from batch.batch_runner import StudentUnitResult

# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

def write_csv(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],          # {run_name: [assignment_id, ...]}
    output_path: Path,
) -> Path:
    """Write a flat CSV with one row per student."""

    # Collect all assignment IDs that were actually graded (in order)
    all_assignment_ids: list[str] = []
    seen: set[str] = set()
    for student in all_students.values():
        for ar in student.assignment_results:
            if ar.assignment_id not in seen:
                all_assignment_ids.append(ar.assignment_id)
                seen.add(ar.assignment_id)

    # Build header
    header = ["Student"]
    for run_name in runs:
        header.append(f"{run_name} Grade")
    for aid in all_assignment_ids:
        short = _short_name(aid)
        header.append(f"{short} Score (0-3)")
        header.append(f"{short} Points")
        header.append(f"{short} Status")

    rows: list[list] = []
    for student_name in sorted(all_students.keys()):
        student = all_students[student_name]
        result_by_id = {r.assignment_id: r for r in student.assignment_results}

        row = [student_name]
        for run_name in runs:
            row.append(student.run_grades.get(run_name, ""))
        for aid in all_assignment_ids:
            ar = result_by_id.get(aid)
            if ar:
                row.append(ar.rubric_score)
                row.append(ar.points)
                row.append(ar.ts_status)
            else:
                row.extend(["", "", ""])
        rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return output_path


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

_SCORE_COLORS = {
    0: "#ffcccc",   # light red
    1: "#fff3cd",   # amber
    2: "#d4edda",   # light green
    3: "#c3e6cb",   # green
}

def write_html(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],
    output_path: Path,
) -> Path:
    """Write a color-coded HTML grade report."""

    all_assignment_ids: list[str] = []
    seen: set[str] = set()
    for student in all_students.values():
        for ar in student.assignment_results:
            if ar.assignment_id not in seen:
                all_assignment_ids.append(ar.assignment_id)
                seen.add(ar.assignment_id)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines: list[str] = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        f"<title>Grade Report — {timestamp}</title>",
        "<style>",
        "  body { font-family: Arial, sans-serif; font-size: 13px; margin: 20px; }",
        "  h1 { font-size: 18px; }",
        "  table { border-collapse: collapse; width: 100%; }",
        "  th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: center; white-space: nowrap; }",
        "  th { background: #333; color: #fff; }",
        "  td.name { text-align: left; font-weight: bold; }",
        "  td.grade { font-weight: bold; background: #e8f4fd; }",
        "  .s0 { background: #ffcccc; }",
        "  .s1 { background: #fff3cd; }",
        "  .s2 { background: #d4edda; }",
        "  .s3 { background: #c3e6cb; }",
        "</style>",
        "</head><body>",
        f"<h1>TechSmart Grade Report — Generated {timestamp}</h1>",
        "<table>",
        "<thead><tr>",
        "  <th>Student</th>",
    ]

    for run_name in runs:
        lines.append(f"  <th>{html.escape(run_name)}<br>Grade</th>")
    for aid in all_assignment_ids:
        lines.append(f"  <th>{html.escape(_short_name(aid))}</th>")

    lines.append("</tr></thead><tbody>")

    for student_name in sorted(all_students.keys()):
        student = all_students[student_name]
        result_by_id = {r.assignment_id: r for r in student.assignment_results}

        lines.append("<tr>")
        lines.append(f"  <td class='name'>{html.escape(student_name)}</td>")

        for run_name in runs:
            grade = student.run_grades.get(run_name, "")
            lines.append(f"  <td class='grade'>{grade}</td>")

        for aid in all_assignment_ids:
            ar = result_by_id.get(aid)
            if ar:
                score_class = f"s{ar.rubric_score}"
                tooltip = html.escape(ar.explanation[:120] if ar.explanation else "")
                lines.append(
                    f"  <td class='{score_class}' title='{tooltip}'>"
                    f"{ar.rubric_score}/3 ({ar.points}pt)</td>"
                )
            else:
                lines.append("  <td>—</td>")

        lines.append("</tr>")

    lines += ["</tbody></table>", "</body></html>"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# Detailed per-student breakdown (optional second CSV)
# ---------------------------------------------------------------------------

def write_detail_csv(
    all_students: dict[str, StudentUnitResult],
    output_path: Path,
) -> Path:
    """
    Write a detailed CSV with one row per (student, assignment) pair.
    Includes explanation text, matched zones, failures — useful for reviewing
    edge cases and calibrating the grader.
    """
    header = [
        "Student", "Assignment", "TechSmart Status",
        "Rubric Score", "Points",
        "Matched Zones", "Unmet Zones",
        "Guardrail Failures", "Requirement Failures",
        "Explanation",
    ]

    rows = []
    for student_name in sorted(all_students.keys()):
        student = all_students[student_name]
        for ar in student.assignment_results:
            rows.append([
                student_name,
                ar.assignment_title,
                ar.ts_status,
                ar.rubric_score,
                ar.points,
                "; ".join(ar.matched_zones),
                "; ".join(ar.unmet_zones),
                "; ".join(ar.guardrail_failures),
                "; ".join(ar.requirement_failures),
                ar.explanation,
            ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return output_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_name(assignment_id: str) -> str:
    """Shorten an assignment_id to a readable column header."""
    # e.g. "3_3_animating_shapes_1_technique1practice1_py" → "Anim Shapes 1"
    parts = assignment_id.split("_")
    # Drop numeric prefix (3_3) and file-name suffix (techniqueXpracticeY_py)
    # Keep the middle descriptive words
    skip_prefixes = {"3", "py"}
    meaningful = []
    for p in parts[2:]:  # skip leading "3_3"
        if p.lower() in skip_prefixes:
            continue
        if p.startswith("technique") or p.startswith("practice") or p.startswith("stickdance") or p.startswith("healthful") or p.startswith("bouncing"):
            break
        meaningful.append(p.capitalize())
    return " ".join(meaningful) if meaningful else assignment_id