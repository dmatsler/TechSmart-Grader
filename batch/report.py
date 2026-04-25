"""
Report generator — writes grading results to CSV and a simple HTML summary.

CSV format:
  Student | Run1_Grade | Run2_Grade | ... | Assign1_Score | Assign1_Points | Assign1_Flag | ...

HTML format:
  A clean table version of the CSV, color-coded by score (0=red, 1=yellow,
  2=light-green, 3=green), with ⚠ indicators on flagged/teacher-reviewed cells.
"""
from __future__ import annotations

import csv
import html
from datetime import datetime
from pathlib import Path

from batch.batch_runner import StudentUnitResult

# ---------------------------------------------------------------------------
# CSV — summary (one row per student)
# ---------------------------------------------------------------------------

def write_csv(
    all_students: dict[str, StudentUnitResult],
    runs: dict[str, list[str]],
    output_path: Path,
) -> Path:
    """Write a flat CSV with one row per student."""

    all_assignment_ids: list[str] = []
    seen: set[str] = set()
    for student in all_students.values():
        for ar in student.assignment_results:
            if ar.assignment_id not in seen:
                all_assignment_ids.append(ar.assignment_id)
                seen.add(ar.assignment_id)

    header = ["Student"]
    for run_name in runs:
        header.append(f"{run_name} Grade")
    for aid in all_assignment_ids:
        short = _short_name(aid)
        header.append(f"{short} Score (0-3)")
        header.append(f"{short} Points")
        header.append(f"{short} Status")
        header.append(f"{short} Flag")          # ← new column

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
                row.append(_flag_cell_text(ar))
            else:
                row.extend(["", "", "", ""])
        rows.append(row)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    return output_path


# ---------------------------------------------------------------------------
# HTML — color-coded summary table
# ---------------------------------------------------------------------------

_SCORE_COLORS = {
    0: "#ffcccc",
    1: "#fff3cd",
    2: "#d4edda",
    3: "#c3e6cb",
}
_PENDING_COLOR  = "#ffe0b2"   # orange — flagged but not yet confirmed
_REVIEWED_COLOR = "#e8f5e9"   # pale green — teacher confirmed after flag


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

    # Count flagged submissions for the summary banner
    total_flagged   = sum(1 for s in all_students.values()
                          for ar in s.assignment_results if ar.flag_reasons)
    total_pending   = sum(1 for s in all_students.values()
                          for ar in s.assignment_results if ar.pending)
    total_confirmed = total_flagged - total_pending

    lines: list[str] = [
        "<!DOCTYPE html>",
        "<html><head>",
        "<meta charset='utf-8'>",
        f"<title>Grade Report — {timestamp}</title>",
        "<style>",
        "  body { font-family: Arial, sans-serif; font-size: 13px; margin: 20px; }",
        "  h1 { font-size: 18px; }",
        "  .banner { background:#fffbeb; border:1px solid #f59e0b; border-radius:6px;",
        "            padding:8px 14px; margin-bottom:14px; font-size:13px; color:#78350f; }",
        "  table { border-collapse: collapse; width: 100%; }",
        "  th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: center; white-space: nowrap; }",
        "  th { background: #333; color: #fff; }",
        "  td.name { text-align: left; font-weight: bold; }",
        "  td.grade { font-weight: bold; background: #e8f4fd; }",
        "  .s0 { background: #ffcccc; }",
        "  .s1 { background: #fff3cd; }",
        "  .s2 { background: #d4edda; }",
        "  .s3 { background: #c3e6cb; }",
        "  .flagged  { background: #ffe0b2; }",   # pending / unconfirmed
        "  .reviewed { background: #e8f5e9; }",   # teacher confirmed after flag
        "  .flag-icon { font-size:10px; margin-left:3px; }",
        "</style>",
        "</head><body>",
        f"<h1>TechSmart Grade Report — Generated {timestamp}</h1>",
    ]

    # Summary banner if any flags exist
    if total_flagged > 0:
        lines.append("<div class='banner'>")
        lines.append(
            f"⚠ {total_flagged} submission(s) were flagged for integrity review. "
            f"{total_confirmed} confirmed by teacher. "
            f"{total_pending} still pending (excluded from grades below)."
        )
        lines.append("</div>")

    lines += [
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
                cell_class, icon, tooltip = _cell_style(ar)
                feedback = getattr(ar, "student_feedback", "")
                full_tooltip = tooltip
                if feedback:
                    full_tooltip = tooltip + " | FEEDBACK: " + html.escape(feedback[:80])
                lines.append(
                    f"  <td class='{cell_class}' title='{full_tooltip}'>"
                    f"{ar.rubric_score}/3 ({ar.points}pt){icon}</td>"
                )
            else:
                lines.append("  <td>—</td>")

        lines.append("</tr>")

    lines += ["</tbody></table>", "</body></html>"]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


# ---------------------------------------------------------------------------
# CSV — detailed per-(student, assignment) breakdown
# ---------------------------------------------------------------------------

def write_detail_csv(
    all_students: dict[str, StudentUnitResult],
    output_path: Path,
) -> Path:
    """Write a detailed CSV with one row per (student, assignment) pair."""
    header = [
        "Student", "Assignment", "TechSmart Status",
        "Rubric Score", "Points",
        "Flag Status", "Flag Reasons",
        "Explanation",
        "Student Feedback",      # ← AI-generated feedback for the student
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
                _flag_cell_text(ar),
                " | ".join(ar.flag_reasons),
                ar.explanation,
                getattr(ar, "student_feedback", ""),
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

def _flag_cell_text(ar) -> str:
    """Return the flag status string for CSV cells."""
    if not ar.flag_reasons:
        return "Auto-confirmed"
    if ar.pending:
        return "⚠ Pending review"
    return "⚠ Teacher reviewed"


def _cell_style(ar) -> tuple[str, str, str]:
    """Return (css_class, icon_html, tooltip_text) for an HTML table cell."""
    explanation = html.escape(ar.explanation[:120] if ar.explanation else "")

    if ar.pending:
        tooltip = "PENDING — " + html.escape("; ".join(ar.flag_reasons[:2]))
        return "flagged", "<span class='flag-icon'>⚠</span>", tooltip

    if ar.flag_reasons:
        # Teacher confirmed after flag
        tooltip = "Reviewed — " + explanation
        return "reviewed", "<span class='flag-icon'>✔</span>", tooltip

    score_class = f"s{ar.rubric_score}"
    return score_class, "", explanation


def _short_name(assignment_id: str) -> str:
    """Shorten an assignment_id to a readable column header."""
    parts = assignment_id.split("_")
    skip_prefixes = {"3", "py"}
    meaningful = []
    for p in parts[2:]:
        if p.lower() in skip_prefixes:
            continue
        if p.startswith("technique") or p.startswith("practice") or \
           p.startswith("stickdance") or p.startswith("healthful") or \
           p.startswith("bouncing") or p.startswith("sportshero") or \
           p.startswith("virtualjumprope") or p.startswith("customcursor") or \
           p.startswith("zenflycatcher") or p.startswith("colorpicker") or \
           p.startswith("cyo"):
            break
        meaningful.append(p.capitalize())
    return " ".join(meaningful) if meaningful else assignment_id
