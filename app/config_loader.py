"""
Config loader — simplified for the AI-powered grader.

No longer reads YAML rubric files. Responsibilities:
  - Defines the UNIT_REGISTRY (which units exist and their labels)
  - Provides assignment lists for the UI dropdown (from context cache,
    or fallback hardcoded list if cache hasn't been populated yet)
  - Loads llm_config.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# Unit registry — add new units here, nothing else changes
# ---------------------------------------------------------------------------

UNIT_REGISTRY: dict[str, dict] = {
    "3_3": {
        "label": "Unit 3.3 — Animation",
        # Fallback assignment list used when context cache is empty.
        # IDs and titles must match what TechSmart shows in the gradebook.
        "fallback_assignments": [
            ("3_3_animating_shapes_1_technique1practice1_py",       "3.3 Animating Shapes (1)"),
            ("3_3_animating_shapes_2_technique1practice2_py",       "3.3 Animating Shapes (2)"),
            ("3_3_animating_rect_shapes_1_technique2practice1_py",  "3.3 Animating Rect Shapes (1)"),
            ("3_3_animating_rect_shapes_2_technique2practice2_py",  "3.3 Animating Rect Shapes (2)"),
            ("3_3_adjust_animation_speed_1_technique3practice1_py", "3.3 Adjust Animation Speed (1)"),
            ("3_3_adjust_animation_speed_2_technique3practice2_py", "3.3 Adjust Animation Speed (2)"),
            ("3_3_backgrounds_and_trails_1_technique4practice1_py", "3.3 Backgrounds and Trails (1)"),
            ("3_3_backgrounds_and_trails_2_technique4practice2_py", "3.3 Backgrounds and Trails (2)"),
            ("3_3_stick_dance_random_stickdancerandom_solution_py", "3.3 Stick Dance: Random"),
            ("3_3_healthful_ufo_healthfulufo_solution_py",          "3.3 Healthful UFO"),
            ("3_3_stick_dance_smooth_stickdancesmooth_solution_py", "3.3 Stick Dance: Smooth"),
            ("3_3_bouncing_ball_bouncingball_solution_py",          "3.3 Bouncing Ball"),
        ],
    },
    "3_5": {
        "label": "Unit 3.5 — Mouse & Keyboard",
        "fallback_assignments": [
            ("3_5_saving_a_tuple_1_technique1practice1_py",        "3.5 Saving a Tuple (1)"),
            ("3_5_saving_a_tuple_2_technique1practice2_py",        "3.5 Saving a Tuple (2)"),
            ("3_5_follow_mouse_1_technique2practice1_py",          "3.5 Follow Mouse (1)"),
            ("3_5_follow_mouse_2_technique2practice2_py",          "3.5 Follow Mouse (2)"),
            ("3_5_check_event_key_1_technique3practice1_py",       "3.5 Check Event Key (1)"),
            ("3_5_check_event_key_2_technique3practice2_py",       "3.5 Check Event Key (2)"),
            ("3_5_move_arrow_keys_1_technique4practice1_py",       "3.5 Move With Arrow Keys (1)"),
            ("3_5_move_arrow_keys_2_technique4practice2_py",       "3.5 Move With Arrow Keys (2)"),
            ("3_5_sports_hero_sportshero_py",                      "3.5 Sports Hero"),
            ("3_5_virtual_jumprope_virtualjumprope_py",            "3.5 Virtual Jumprope"),
            ("3_5_custom_cursor_customcursor_py",                  "3.5 Custom Cursor"),
            ("3_5_zen_flycatcher_zenflycatcher_py",                "3.5 Zen Flycatcher"),
            ("3_5_color_picker_colorpicker_py",                    "3.5 Color Picker"),
            ("3_5_code_your_own_cyo3_5_py",                        "3.5 Code Your Own"),
        ],
    },
}


# ---------------------------------------------------------------------------
# Assignment list for UI dropdown
# ---------------------------------------------------------------------------

def get_unit_assignments(unit_slug: str) -> list[tuple[str, str]]:
    """Return (assignment_id, title) pairs for a unit.

    Prefers the context cache (live-scraped data) over the fallback list.
    Falls back to the hardcoded list if cache hasn't been populated yet.
    """
    # Try context cache first
    cache_path = _ROOT / f"context_cache_{unit_slug}.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            assignments = data.get("assignments", {})
            if assignments:
                return [
                    (aid, info.get("title", aid))
                    for aid, info in assignments.items()
                    if info.get("title")
                ]
        except Exception:
            pass

    # Fallback to hardcoded list
    unit = UNIT_REGISTRY.get(unit_slug, {})
    return unit.get("fallback_assignments", [])


def get_assignment_context(unit_slug: str, assignment_id: str):
    """Load a single AssignmentContext from the cache, or return None."""
    from app.models import AssignmentContext

    cache_path = _ROOT / f"context_cache_{unit_slug}.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        entry = data.get("assignments", {}).get(assignment_id)
        if not entry:
            return None
        return AssignmentContext(
            assignment_id=assignment_id,
            title=entry.get("title", assignment_id),
            unit=unit_slug,
            kind=entry.get("kind", "assignment"),
            requirements=entry.get("requirements", ""),
            starter_code=entry.get("starter_code", ""),
            solution_code=entry.get("solution_code", ""),
            weight=float(entry.get("weight", 1.0)),
            count_in_unit_grade=entry.get("count_in_unit_grade", True),
        )
    except Exception:
        return None


def get_all_contexts(unit_slug: str) -> dict[str, Any]:
    """Return all cached contexts for a unit as {assignment_id: AssignmentContext}."""
    assignments = get_unit_assignments(unit_slug)
    result = {}
    for aid, _ in assignments:
        ctx = get_assignment_context(unit_slug, aid)
        if ctx:
            result[aid] = ctx
    return result


# ---------------------------------------------------------------------------
# LLM config
# ---------------------------------------------------------------------------

def load_llm_config() -> dict[str, Any]:
    config_path = _ROOT / "llm_config.json"
    if config_path.exists():
        return json.loads(config_path.read_text(encoding="utf-8"))
    return {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "temperature": 0.1,
        "max_tokens": 600,
    }
