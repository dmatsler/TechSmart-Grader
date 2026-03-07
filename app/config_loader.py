from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from typing import Any

from app.models import AppConfig, AssignmentConfig, FillZoneConfig, GradingModel, RequirementChecks

REQUIRED_ASSIGNMENT_FIELDS = {
    "id",
    "title",
    "file_name",
    "count_in_unit_grade_default",
    "weight",
    "rubric_to_points_default",
}


class ConfigError(ValueError):
    pass


def _normalize_assignment(assignment: dict[str, Any]) -> dict[str, Any]:
    mapping = assignment.get("rubric_to_points_default", {})
    if mapping:
        assignment["rubric_to_points_default"] = {int(k): int(v) for k, v in mapping.items()}
    assignment.setdefault("min_zones_matched_default", 1)
    return assignment


def _validate_config(raw: dict[str, Any]) -> None:
    for key in ["course", "unit", "grading_model", "assignments"]:
        if key not in raw:
            raise ConfigError(f"Missing required top-level key: {key}")
    assignments = raw.get("assignments", [])
    if not assignments:
        raise ConfigError("Config contains no assignments")
    for assignment in assignments:
        missing = REQUIRED_ASSIGNMENT_FIELDS - set(assignment.keys())
        if missing:
            aid = assignment.get("id", "<unknown>")
            raise ConfigError(f"Assignment {aid} missing fields: {sorted(missing)}")


def _load_yaml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if importlib.util.find_spec("yaml") is None:
        return None
    yaml = importlib.import_module("yaml")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _to_assignment(raw: dict[str, Any]) -> AssignmentConfig:
    req = raw.get("requirement_checks", {})
    requirement_checks = RequirementChecks(
        required_imports=req.get("required_imports", []),
        must_have_tokens=req.get("must_have_tokens", []),
        must_have_any=req.get("must_have_any", []),
        must_have_wait_any=req.get("must_have_wait_any", []),
        must_have_draw_any=req.get("must_have_draw_any", []),
        coherence_guardrails=req.get("coherence_guardrails", []),
        score3_minimums=req.get("score3_minimums", []),
    )
    fill_zones = [
        FillZoneConfig(
            name=z["name"],
            prompt_hints=z.get("prompt_hints", []),
            required=z.get("required", True),
            attempt_patterns=z.get("attempt_patterns", []),
            expected_patterns=z.get("expected_patterns", []),
            anti_patterns=z.get("anti_patterns", []),
            notes=z.get("notes"),
        )
        for z in raw.get("fill_zones", [])
    ]

    return AssignmentConfig(
        id=raw["id"],
        title=raw["title"],
        file_name=raw["file_name"],
        kind=raw.get("kind", "assignment"),
        count_in_unit_grade_default=raw.get("count_in_unit_grade_default", False),
        weight=float(raw.get("weight", 1.0)),
        rubric_to_points_default=raw.get("rubric_to_points_default", {0: 0, 1: 50, 2: 75, 3: 100}),
        fill_zones=fill_zones,
        requirement_checks=requirement_checks,
        min_zones_matched_default=int(raw.get("min_zones_matched_default", 1)),
    )


def load_config(
    yaml_path: str | Path = "unit_3_3_animation_grading_config_working.yaml",
    json_path: str | Path = "unit_3_3_animation_grading_config_working.json",
) -> AppConfig:
    yaml_path = Path(yaml_path)
    json_path = Path(json_path)

    raw: dict[str, Any] | None = _load_yaml(yaml_path)
    if raw is None and json_path.exists():
        raw = json.loads(json_path.read_text(encoding="utf-8"))

    if raw is None:
        raise ConfigError(f"Could not find YAML or JSON config ({yaml_path}, {json_path})")

    _validate_config(raw)
    assignments = [_to_assignment(_normalize_assignment(a)) for a in raw["assignments"]]

    grading_model_raw = raw.get("grading_model", {})
    grading_model = GradingModel(
        unit_score_out_of=grading_model_raw.get("unit_score_out_of", 100),
        unit_aggregation=grading_model_raw.get("unit_aggregation", "weighted_average_of_counted_assignments"),
    )
    return AppConfig(course=raw["course"], unit=raw["unit"], grading_model=grading_model, assignments=assignments)


def assignment_lookup(config: AppConfig) -> dict[str, AssignmentConfig]:
    return {assignment.id: assignment for assignment in config.assignments}
