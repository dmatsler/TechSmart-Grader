from __future__ import annotations

from app.models import UnitGradeEntry


def calculate_unit_grade(entries: list[UnitGradeEntry], include_ids: set[str]) -> float:
    included = [entry for entry in entries if entry.assignment_id in include_ids]
    if not included:
        return 0.0
    total_weight = sum(entry.weight for entry in included)
    if total_weight <= 0:
        return 0.0
    return round(sum(entry.points * entry.weight for entry in included) / total_weight, 2)
