from __future__ import annotations

import ast
import re
from dataclasses import dataclass

from app.models import AssignmentConfig, GradingInput, GradingResult, SubmissionStatus, ZoneMatch
from app.utils import find_main_loop_block, has_non_comment_statement, regex_any_match, strip_comment_blank_lines, token_present

TARGET_ASSIGNMENT_POINT_PATTERN = "3_3_animating_shapes_1_technique1practice1_py"
TARGET_ASSIGNMENT_POLYGON_PATTERN = "3_3_animating_shapes_2_technique1practice2_py"
TARGET_ASSIGNMENT_RECT_PATTERN = "3_3_animating_rect_shapes_1_technique2practice1_py"


@dataclass
class AnalysisSummary:
    zone_matches: list[ZoneMatch]
    requirement_failures: list[str]
    coherence_failures: list[str]
    relevant_zone_match_count: int
    meaningful_zone_match_count: int
    meaningful_attempt: bool


def _extract_point_vars_derived_from_offset(code: str) -> list[str]:
    pattern = re.compile(r"\b([A-Za-z_]\w*)\s*=\s*\([^\n\)]*\b\w*offset\w*\b[^\n\)]*\)", flags=re.MULTILINE)
    return [match.group(1) for match in pattern.finditer(code)]


def _extract_point_collection_vars(point_vars: list[str], code: str) -> list[str]:
    if not point_vars:
        return []
    collections: list[str] = []
    for var in point_vars:
        for match in re.finditer(rf"\b([A-Za-z_]\w*)\s*=\s*\[[^\n]*\b{re.escape(var)}\b[^\n]*\]", code):
            collections.append(match.group(1))
    return list(dict.fromkeys(collections))


def _polygon_call_uses_var(code: str, var_name: str) -> bool:
    pattern = rf"pygame\.draw\.polygon\s*\([^\n]*\b{re.escape(var_name)}\b[^\n]*\)"
    try:
        return regex_any_match([pattern], code)
    except re.error:
        return "pygame.draw.polygon" in code and var_name in code


def _matches_point_based_movement_pattern(assignment: AssignmentConfig, zone_name: str, code: str) -> bool:
    if assignment.id != TARGET_ASSIGNMENT_POINT_PATTERN:
        return False

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    while_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    if not while_nodes:
        return False
    main_loop = min(while_nodes, key=lambda node: node.lineno)

    initialized_before_loop: set[str] = set()
    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno >= main_loop.lineno:
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            initialized_before_loop.add(node.targets[0].id)

    motion_vars: set[str] = set()
    point_vars: set[str] = set()
    line_uses_point_var = False
    circle_uses_point_var = False
    has_flip_or_update_in_loop = False
    has_timing_in_loop = False

    for node in ast.walk(main_loop):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, ast.Add):
            if isinstance(node.value, ast.Constant) and node.value.value == 4 and node.target.id in initialized_before_loop:
                motion_vars.add(node.target.id)

        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0]
            if isinstance(node.value, ast.BinOp) and isinstance(node.value.op, ast.Add) and isinstance(node.value.right, ast.Constant) and node.value.right.value == 4:
                if isinstance(node.value.left, ast.Name) and node.value.left.id == target.id and target.id in initialized_before_loop:
                    motion_vars.add(target.id)

    if motion_vars:
        for node in ast.walk(main_loop):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if isinstance(node.value, ast.Tuple) and len(node.value.elts) == 2:
                    tuple_names = {sub.id for sub in ast.walk(node.value) if isinstance(sub, ast.Name)}
                    if "yoyo_y" in tuple_names and tuple_names.intersection(motion_vars):
                        point_vars.add(node.targets[0].id)

            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "pygame" and node.func.value.attr == "draw":
                    draw_name = node.func.attr
                    arg_names = {sub.id for arg in node.args for sub in ast.walk(arg) if isinstance(sub, ast.Name)}
                    if draw_name == "line" and "string_start" in arg_names and point_vars.intersection(arg_names):
                        line_uses_point_var = True
                    if draw_name == "circle" and point_vars.intersection(arg_names):
                        circle_uses_point_var = True

                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "pygame" and node.func.value.attr == "display" and node.func.attr in {"flip", "update"}:
                    has_flip_or_update_in_loop = True

                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name) and node.func.value.value.id == "pygame" and node.func.value.attr == "time" and node.func.attr == "wait":
                    has_timing_in_loop = True
                if isinstance(node.func.value, ast.Name) and node.func.value.id == "clock" and node.func.attr == "tick":
                    has_timing_in_loop = True

    if zone_name == "offset_setup_and_update":
        return bool(motion_vars)
    if zone_name == "point_from_offset":
        return bool(point_vars)
    if zone_name == "draw_line":
        return line_uses_point_var
    if zone_name == "draw_circle":
        return circle_uses_point_var
    if zone_name == "flip_and_wait":
        return has_flip_or_update_in_loop and has_timing_in_loop
    return False


def _collect_loop_motion_vars_and_rect_usage(code: str) -> tuple[set[str], set[str], bool, bool, bool]:
    """Return motion vars and whether they are used for elevator movement + drawing/timing in loop."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set(), set(), False, False, False

    while_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    if not while_nodes:
        return set(), set(), False, False, False
    main_loop = min(while_nodes, key=lambda node: node.lineno)

    initialized_before_loop: set[str] = set()
    for node in ast.walk(tree):
        if not hasattr(node, "lineno") or node.lineno >= main_loop.lineno:
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            initialized_before_loop.add(node.targets[0].id)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            initialized_before_loop.add(node.target.id)

    updated_in_loop: set[str] = set()
    used_on_elevator_y: set[str] = set()
    elevator_drawn = False
    has_flip_or_update_in_loop = False
    has_timing_in_loop = False

    for node in ast.walk(main_loop):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, (ast.Add, ast.Sub)):
            updated_in_loop.add(node.target.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if _is_self_increment_or_decrement(target, node.value):
                updated_in_loop.add(target)

        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Attribute):
            target = node.targets[0]
            if isinstance(target.value, ast.Name) and target.value.id == "elevator_rect" and target.attr in {"y", "top"}:
                used_on_elevator_y.update({sub.id for sub in ast.walk(node.value) if isinstance(sub, ast.Name)})

        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Attribute):
            target = node.target
            if isinstance(target.value, ast.Name) and target.value.id == "elevator_rect" and target.attr in {"y", "top"}:
                used_on_elevator_y.update({sub.id for sub in ast.walk(node.value) if isinstance(sub, ast.Name)})

        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0]
            if target.id == "elevator_rect" and isinstance(node.value, ast.Call):
                func = node.value.func
                if (
                    isinstance(func, ast.Attribute)
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "pygame"
                    and func.attr == "Rect"
                    and len(node.value.args) >= 2
                ):
                    used_on_elevator_y.update({sub.id for sub in ast.walk(node.value.args[1]) if isinstance(sub, ast.Name)})

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in {"flip", "update"}:
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    if node.func.value.value.id == "pygame" and node.func.value.attr == "display":
                        has_flip_or_update_in_loop = True

            if node.func.attr == "wait":
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    if node.func.value.value.id == "pygame" and node.func.value.attr == "time":
                        has_timing_in_loop = True
            if node.func.attr == "tick":
                has_timing_in_loop = True

            if node.func.attr == "rect":
                if isinstance(node.func.value, ast.Attribute) and isinstance(node.func.value.value, ast.Name):
                    if node.func.value.value.id == "pygame" and node.func.value.attr == "draw":
                        rect_arg_is_elevator = len(node.args) >= 3 and isinstance(node.args[2], ast.Name) and node.args[2].id == "elevator_rect"
                        rect_kw_is_elevator = any(kw.arg == "rect" and isinstance(kw.value, ast.Name) and kw.value.id == "elevator_rect" for kw in node.keywords)
                        if rect_arg_is_elevator or rect_kw_is_elevator:
                            elevator_drawn = True

    motion_vars = {name for name in (initialized_before_loop & updated_in_loop) if name not in {"frames", "frame", "i"}}
    applied_motion_vars = motion_vars & used_on_elevator_y
    return motion_vars, applied_motion_vars, elevator_drawn, has_flip_or_update_in_loop, has_timing_in_loop


def _matches_rect_shapes_pattern(assignment: AssignmentConfig, zone_name: str, code: str) -> bool:
    if assignment.id != TARGET_ASSIGNMENT_RECT_PATTERN:
        return False

    motion_vars, applied_motion_vars, elevator_drawn, has_flip_or_update_in_loop, has_timing_in_loop = _collect_loop_motion_vars_and_rect_usage(code)

    if zone_name == "offset_update":
        return bool(motion_vars)
    if zone_name == "apply_offset_to_rect":
        return bool(applied_motion_vars)
    if zone_name == "draw_elevator_rect":
        return bool(applied_motion_vars) and elevator_drawn
    if zone_name == "flip_and_wait":
        return bool(applied_motion_vars) and has_flip_or_update_in_loop and has_timing_in_loop
    return False


def _linear_name_coeffs(node: ast.AST) -> dict[str, int] | None:
    if isinstance(node, ast.Name):
        return {node.id: 1}
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return {}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _linear_name_coeffs(node.operand)
        if inner is None:
            return None
        return {name: -coef for name, coef in inner.items()}
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        left = _linear_name_coeffs(node.left)
        right = _linear_name_coeffs(node.right)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Sub):
            right = {name: -coef for name, coef in right.items()}
        merged: dict[str, int] = dict(left)
        for name, coef in right.items():
            merged[name] = merged.get(name, 0) + coef
        return {name: coef for name, coef in merged.items() if coef != 0}
    return None


def _extract_clockwise_rotation_point_roles(code: str) -> dict[str, str]:
    motion_vars = _extract_initialized_then_updated_vars(code)
    if not motion_vars:
        return {}

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {}

    roles_by_motion: dict[str, dict[str, str]] = {var: {} for var in motion_vars}

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not isinstance(node.value, ast.Tuple) or len(node.value.elts) != 2:
            continue

        x_coeffs = _linear_name_coeffs(node.value.elts[0])
        y_coeffs = _linear_name_coeffs(node.value.elts[1])
        if x_coeffs is None or y_coeffs is None:
            continue

        for motion_var, roles in roles_by_motion.items():
            if (
                x_coeffs.get("left") == 1
                and x_coeffs.get(motion_var) == 1
                and set(x_coeffs).issubset({"left", motion_var})
                and y_coeffs == {"top": 1}
            ):
                roles.setdefault("top_edge", target.id)
            elif (
                x_coeffs == {"right": 1}
                and y_coeffs.get("top") == 1
                and y_coeffs.get(motion_var) == 1
                and set(y_coeffs).issubset({"top", motion_var})
            ):
                roles.setdefault("right_edge", target.id)
            elif (
                x_coeffs.get("right") == 1
                and x_coeffs.get(motion_var) == -1
                and set(x_coeffs).issubset({"right", motion_var})
                and y_coeffs == {"bottom": 1}
            ):
                roles.setdefault("bottom_edge", target.id)
            elif (
                x_coeffs == {"left": 1}
                and y_coeffs.get("bottom") == 1
                and y_coeffs.get(motion_var) == -1
                and set(y_coeffs).issubset({"bottom", motion_var})
            ):
                roles.setdefault("left_edge", target.id)

    for roles in roles_by_motion.values():
        if len(roles) == 4:
            return roles

    return {}


def _extract_initialized_then_updated_vars(code: str) -> set[str]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()

    while_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    if not while_nodes:
        return set()

    main_loop = min(while_nodes, key=lambda node: node.lineno)
    initialized_before_loop: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.lineno < main_loop.lineno:
            initialized_before_loop.add(node.targets[0].id)

    updated_in_loop: set[str] = set()
    for node in ast.walk(main_loop):
        if isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name) and isinstance(node.op, (ast.Add, ast.Sub)):
            updated_in_loop.add(node.target.id)
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if _is_self_increment_or_decrement(target, node.value):
                updated_in_loop.add(target)

    return initialized_before_loop & updated_in_loop


def _extract_initialized_then_updated_vars_with_constant_step(code: str, required_step: int) -> set[str]:
    """Return vars initialized before main loop and updated in loop by an exact constant step."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()

    while_nodes = [node for node in ast.walk(tree) if isinstance(node, ast.While)]
    if not while_nodes:
        return set()

    main_loop = min(while_nodes, key=lambda node: node.lineno)
    initialized_before_loop: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.lineno < main_loop.lineno:
            initialized_before_loop.add(node.targets[0].id)

    updated_with_step: set[str] = set()
    for node in ast.walk(main_loop):
        if (
            isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Name)
            and isinstance(node.op, (ast.Add, ast.Sub))
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
        ):
            step = int(node.value.value)
            if isinstance(node.op, ast.Sub):
                step = -step
            if step == required_step:
                updated_with_step.add(node.target.id)

        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            value = node.value
            if not isinstance(value, ast.BinOp) or not isinstance(value.op, (ast.Add, ast.Sub)):
                continue

            if isinstance(value.left, ast.Name) and value.left.id == target and isinstance(value.right, ast.Constant) and isinstance(value.right.value, (int, float)):
                step = int(value.right.value)
                if isinstance(value.op, ast.Sub):
                    step = -step
                if step == required_step:
                    updated_with_step.add(target)
            elif isinstance(value.right, ast.Name) and value.right.id == target and isinstance(value.left, ast.Constant) and isinstance(value.left.value, (int, float)) and isinstance(value.op, ast.Add):
                if int(value.left.value) == required_step:
                    updated_with_step.add(target)

    return initialized_before_loop & updated_with_step


def _is_self_increment_or_decrement(name: str, expr: ast.AST) -> bool:
    if not isinstance(expr, ast.BinOp) or not isinstance(expr.op, (ast.Add, ast.Sub)):
        return False

    left_has_name = isinstance(expr.left, ast.Name) and expr.left.id == name
    right_has_name = isinstance(expr.right, ast.Name) and expr.right.id == name

    if not (left_has_name or right_has_name):
        return False

    non_name_side = expr.right if left_has_name else expr.left
    return not (isinstance(non_name_side, ast.Constant) and non_name_side.value == 0)


def _polygon_call_uses_clockwise_points(code: str) -> bool:
    roles = _extract_clockwise_rotation_point_roles(code)
    if len(roles) < 4:
        return False

    required_vars = set(roles.values())
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False

    list_assignments: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if isinstance(node.value, (ast.List, ast.Tuple)):
            names = {elt.id for elt in node.value.elts if isinstance(elt, ast.Name)}
            if names:
                list_assignments[target.id] = names

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "polygon":
            continue
        func_value = node.func.value
        if not isinstance(func_value, ast.Attribute) or func_value.attr != "draw":
            continue
        module = func_value.value
        if not isinstance(module, ast.Name) or module.id != "pygame":
            continue
        if len(node.args) < 3:
            continue

        points_arg = node.args[2]
        if isinstance(points_arg, (ast.List, ast.Tuple)):
            names = {elt.id for elt in points_arg.elts if isinstance(elt, ast.Name)}
            if required_vars.issubset(names):
                return True
        if isinstance(points_arg, ast.Name):
            referenced = list_assignments.get(points_arg.id, set())
            if required_vars.issubset(referenced):
                return True

    return False


def _has_four_side_points_with_offset(code: str) -> bool:
    return len(_extract_clockwise_rotation_point_roles(code)) == 4


def _matches_polygon_side_point_pattern(assignment: AssignmentConfig, zone_name: str, code: str) -> bool:
    if assignment.id != TARGET_ASSIGNMENT_POLYGON_PATTERN:
        return False

    if zone_name == "polygon_points":
        return _has_four_side_points_with_offset(code)

    if zone_name == "offset_setup_and_update":
        return bool(_extract_initialized_then_updated_vars_with_constant_step(code, 5))

    if zone_name == "draw_polygon":
        return _polygon_call_uses_clockwise_points(code)

    return False


def _check_fill_zones(assignment: AssignmentConfig, code: str) -> list[ZoneMatch]:
    matches: list[ZoneMatch] = []
    code_lines = strip_comment_blank_lines(code)

    for zone in assignment.fill_zones:
        attempt_patterns = zone.attempt_patterns or zone.expected_patterns
        anti_hit = regex_any_match(zone.anti_patterns, code) if zone.anti_patterns else False

        matched_attempt_line = False
        matched_expected_line = False
        for line in code_lines:
            if attempt_patterns and regex_any_match(attempt_patterns, line):
                matched_attempt_line = True
            if zone.expected_patterns and regex_any_match(zone.expected_patterns, line):
                matched_expected_line = True

        point_zone_match = _matches_point_based_movement_pattern(assignment, zone.name, code)
        if point_zone_match:
            matched_attempt_line = True
            matched_expected_line = True

        if _matches_polygon_side_point_pattern(assignment, zone.name, code):
            matched_attempt_line = True
            matched_expected_line = True

        rect_zone_match = _matches_rect_shapes_pattern(assignment, zone.name, code)
        if rect_zone_match:
            matched_attempt_line = True
            matched_expected_line = True

        if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN and zone.name in {"offset_update", "apply_offset_to_rect", "draw_elevator_rect", "flip_and_wait"}:
            matched_attempt_line = rect_zone_match
            matched_expected_line = rect_zone_match

        if assignment.id == TARGET_ASSIGNMENT_POINT_PATTERN and zone.name in {"offset_setup_and_update", "point_from_offset", "draw_line", "draw_circle", "flip_and_wait"}:
            matched_attempt_line = point_zone_match
            matched_expected_line = point_zone_match

        if assignment.id == TARGET_ASSIGNMENT_POLYGON_PATTERN and zone.name == "polygon_points":
            matched_expected_line = _has_four_side_points_with_offset(code)
            matched_attempt_line = matched_attempt_line or regex_any_match(
                [r"\b[A-Za-z_]\w*\s*=\s*\([^\n]*\)", r"\b(left|right|top|bottom)\b"],
                code,
            )

        if assignment.id == TARGET_ASSIGNMENT_POLYGON_PATTERN and zone.name == "offset_setup_and_update":
            matched_expected_line = bool(_extract_initialized_then_updated_vars_with_constant_step(code, 5))
            matched_attempt_line = matched_attempt_line or matched_expected_line

        meaningful_line = matched_attempt_line and not anti_hit
        matched = meaningful_line and (matched_attempt_line or matched_expected_line)

        detail = ""
        if anti_hit:
            detail = "Anti-pattern detected"
        elif not matched_attempt_line:
            detail = "No assignment-relevant line found"
        elif not matched_expected_line:
            detail = "Attempt pattern matched, expected pattern missing"

        matches.append(
            ZoneMatch(
                name=zone.name,
                matched=matched,
                matched_expected=matched_expected_line,
                matched_attempt=matched_attempt_line,
                anti_pattern_hit=anti_hit,
                has_meaningful_line=meaningful_line,
                details=detail,
            )
        )
    return matches


def _check_requirements(assignment: AssignmentConfig, code: str) -> list[str]:
    failures: list[str] = []
    req = assignment.requirement_checks

    for imp in req.required_imports:
        if f"import {imp}" not in code and f"from {imp}" not in code:
            failures.append(f"Missing required import: {imp}")

    for token in req.must_have_tokens:
        if assignment.id == TARGET_ASSIGNMENT_POLYGON_PATTERN and token == "offset":
            if _extract_initialized_then_updated_vars(code):
                continue
        if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN and token in {"offset", "elevator_rect"}:
            continue
        if not token_present(token, code):
            failures.append(f"Missing required token: {token}")

    def check_any(groups: list[list[str]], label: str) -> None:
        for options in groups:
            if not any(token_present(option, code) for option in options):
                failures.append(f"Missing one of {label}: {', '.join(options)}")

    check_any(req.must_have_any, "required calls")
    check_any(req.must_have_wait_any, "timing calls")
    check_any(req.must_have_draw_any, "draw calls")
    return failures


def _guardrail_names(assignment: AssignmentConfig) -> set[str]:
    return {item.get("name", "") for item in assignment.requirement_checks.coherence_guardrails}


def _check_coherence_guardrails(assignment: AssignmentConfig, code: str) -> list[str]:
    failures: list[str] = []
    guardrails = _guardrail_names(assignment)
    loop_block = find_main_loop_block(code)

    if "draw_inside_loop" in guardrails:
        if "pygame.draw" in code and "pygame.draw" not in loop_block:
            failures.append("Draw call appears only outside main while-loop")

    if "flip_inside_loop" in guardrails:
        has_flip = "pygame.display.flip" in code or "pygame.display.update" in code
        in_loop_flip = "pygame.display.flip" in loop_block or "pygame.display.update" in loop_block
        if has_flip and not in_loop_flip:
            failures.append("Display flip/update appears only outside main while-loop")

    if "updated_pos_used_in_draw" in guardrails:
        updated = regex_any_match([
            r"\b(x|y|offset|dx|dy)\s*[-+]=\s*\d+",
            r"\b\w*offset\w*\s*[-+]=\s*\d+",
            r"\b\w*offset\w*\s*=\s*\w*offset\w*\s*[-+]\s*\d+",
        ], code)
        draw_line_with_position = regex_any_match([r"pygame\.draw\.(circle|rect|line)\s*\([^\n]*(\bx\b|\by\b|\boffset\b)"], code)
        draw_uses_point_from_offset = False

        if assignment.id in {TARGET_ASSIGNMENT_POINT_PATTERN, TARGET_ASSIGNMENT_POLYGON_PATTERN}:
            point_vars = _extract_point_vars_derived_from_offset(code)
            point_collection_vars = _extract_point_collection_vars(point_vars, code)
            draw_uses_point_from_offset = any(
                regex_any_match([rf"pygame\.draw\.(line|circle|rect|polygon)\s*\([^\n]*\b{re.escape(point_var)}\b"], code)
                for point_var in point_vars
            ) or any(_polygon_call_uses_var(code, collection_var) for collection_var in point_collection_vars)

        if updated and not (draw_line_with_position or draw_uses_point_from_offset):
            failures.append("Position/offset updated but never used in draw context")

    if "offset_used_with_rect" in guardrails:
        if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN:
            _, applied_motion_vars, _, _, _ = _collect_loop_motion_vars_and_rect_usage(code)
            if not applied_motion_vars:
                failures.append("Offset updated but not applied to rect position")
        else:
            updated_offset = regex_any_match([r"\boffset\s*[-+]=\s*\d+", r"\boffset\s*=\s*offset\s*[-+]\s*\d+"], code)
            offset_on_rect_line = regex_any_match([
                r"\b\w*_rect\.(x|y|top|left)\s*=\s*[^\n]*\boffset\b",
                r"\belevator_rect\.(x|y|top|left)\s*=\s*[^\n]*\boffset\b",
            ], code)
            if updated_offset and not offset_on_rect_line:
                failures.append("Offset updated but not applied to rect position")

    if "elevator_offset_step_negative_two" in guardrails and assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN:
        motion_vars, applied_motion_vars, _, _, _ = _collect_loop_motion_vars_and_rect_usage(code)
        negative_two_vars = _extract_initialized_then_updated_vars_with_constant_step(code, -2)
        if motion_vars and applied_motion_vars and not (applied_motion_vars & negative_two_vars):
            failures.append("Elevator offset should move upward by 2 pixels per frame")

    if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN:
        _, _, elevator_drawn, has_flip_or_update_in_loop, has_timing_in_loop = _collect_loop_motion_vars_and_rect_usage(code)
        if not elevator_drawn and "pygame.draw.rect" in code:
            failures.append("Elevator rect is not drawn in the animation loop")
        if ("pygame.display.flip" in code or "pygame.display.update" in code) and not has_flip_or_update_in_loop:
            failures.append("Display flip/update appears only outside main while-loop")
        if ("pygame.time.wait" in code or "tick(" in code) and not has_timing_in_loop:
            failures.append("Timing call appears only outside main while-loop")


    return failures


def analyze_submission(assignment: AssignmentConfig, code: str) -> AnalysisSummary:
    zone_matches = _check_fill_zones(assignment, code)
    meaningful_matches = [z for z in zone_matches if z.matched]
    relevant_matches = [z for z in zone_matches if z.matched_attempt and z.has_meaningful_line and not z.anti_pattern_hit]

    required_zones = [z for z in assignment.fill_zones if z.required]
    required_zone_target = assignment.min_zones_matched_default
    if required_zones:
        required_zone_target = max(required_zone_target, min(2, len(required_zones)))

    meaningful_attempt = has_non_comment_statement(code) and len(meaningful_matches) >= required_zone_target

    return AnalysisSummary(
        zone_matches=zone_matches,
        requirement_failures=_check_requirements(assignment, code),
        coherence_failures=_check_coherence_guardrails(assignment, code),
        relevant_zone_match_count=len(relevant_matches),
        meaningful_zone_match_count=len(meaningful_matches),
        meaningful_attempt=meaningful_attempt,
    )


def grade_submission(assignment: AssignmentConfig, payload: GradingInput) -> GradingResult:
    code = payload.student_code or ""

    if (
        payload.status == SubmissionStatus.TURNED_IN
        and payload.techsmart_lines_completed == 0
        and (payload.techsmart_lines_expected or 0) > 0
    ):
        return _to_result(assignment, payload, 0, f"Turned in with 0/{payload.techsmart_lines_expected} lines, so this counts as no attempt.", [], [], [], [])

    if payload.status == SubmissionStatus.NOT_STARTED:
        return _to_result(assignment, payload, 0, "Assignment marked not started, so score is 0.", [], [], [], [])

    analysis = analyze_submission(assignment, code)
    matched_names = [z.name for z in analysis.zone_matches if z.matched_expected]
    unmet_names = [z.name for z in analysis.zone_matches if z.matched_expected is False]

    if payload.status == SubmissionStatus.STARTED_NOT_SUBMITTED:
        score = 1 if analysis.relevant_zone_match_count >= 1 else 0
        explanation = (
            "Relevant attempt detected, but the assignment is still incomplete and was not submitted."
            if score == 1
            else "Started but no assignment-specific fill-zone attempt was detected."
        )
        return _to_result(assignment, payload, score, explanation, matched_names, unmet_names, analysis.coherence_failures, analysis.requirement_failures)

    if analysis.relevant_zone_match_count == 0:
        if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN:
            motion_vars, applied_motion_vars, elevator_drawn, has_flip_or_update_in_loop, has_timing_in_loop = _collect_loop_motion_vars_and_rect_usage(code)
            has_rect_draw_call = "pygame.draw.rect" in code
            has_syntax_error = False
            if code.strip():
                try:
                    ast.parse(code)
                except SyntaxError:
                    has_syntax_error = True
            if motion_vars:
                if has_rect_draw_call and has_flip_or_update_in_loop and has_timing_in_loop:
                    if not has_syntax_error:
                        if not applied_motion_vars and not elevator_drawn:
                            return _to_result(
                                assignment,
                                payload,
                                1,
                                "Relevant early attempt detected (motion/update/draw present), but elevator movement logic is malformed or incomplete.",
                                matched_names,
                                unmet_names,
                                analysis.coherence_failures,
                                analysis.requirement_failures,
                            )
                        return _to_result(
                            assignment,
                            payload,
                            2,
                            analysis.coherence_failures[0] if analysis.coherence_failures else "Relevant attempt detected, but elevator-specific animation logic is incomplete.",
                            matched_names,
                            unmet_names,
                            analysis.coherence_failures,
                            analysis.requirement_failures,
                        )
                    return _to_result(
                        assignment,
                        payload,
                        1,
                        "Relevant early attempt detected (motion/update/draw present), but elevator movement logic is malformed or incomplete.",
                        matched_names,
                        unmet_names,
                        analysis.coherence_failures,
                        analysis.requirement_failures,
                    )
                return _to_result(
                    assignment,
                    payload,
                    1,
                    "Relevant early attempt detected (motion variable setup/update), but elevator movement logic is still incomplete.",
                    matched_names,
                    unmet_names,
                    analysis.coherence_failures,
                    analysis.requirement_failures,
                )
            return _to_result(
                assignment,
                payload,
                0,
                "Turned in, but only starter/template structure was detected (no assignment-specific motion logic attempt).",
                matched_names,
                unmet_names,
                analysis.coherence_failures,
                analysis.requirement_failures,
            )

        if assignment.id in {TARGET_ASSIGNMENT_POINT_PATTERN, TARGET_ASSIGNMENT_POLYGON_PATTERN}:
            return _to_result(
                assignment,
                payload,
                0,
                "Turned in, but only starter/template structure was detected (no assignment-specific motion logic attempt).",
                matched_names,
                unmet_names,
                analysis.coherence_failures,
                analysis.requirement_failures,
            )
        return _to_result(
            assignment,
            payload,
            1,
            "Turned in, but no relevant assignment-specific attempt was detected.",
            matched_names,
            unmet_names,
            analysis.coherence_failures,
            analysis.requirement_failures,
        )

    if assignment.id == TARGET_ASSIGNMENT_POLYGON_PATTERN and analysis.relevant_zone_match_count >= 1 and analysis.meaningful_zone_match_count < 2:
        has_offset_attempt = any(z.name == "offset_setup_and_update" and z.matched_attempt for z in analysis.zone_matches)
        if not has_offset_attempt:
            return _to_result(
                assignment,
                payload,
                0,
                "Turned in, but only starter/template structure was detected (no assignment-specific motion logic attempt).",
                matched_names,
                unmet_names,
                analysis.coherence_failures,
                analysis.requirement_failures,
            )
        return _to_result(
            assignment,
            payload,
            1,
            "Relevant early attempt detected (offset setup/update), but key polygon movement pieces are still missing.",
            matched_names,
            unmet_names,
            analysis.coherence_failures,
            analysis.requirement_failures,
        )



    if assignment.id == TARGET_ASSIGNMENT_RECT_PATTERN and analysis.meaningful_zone_match_count == 1 and "offset_update" in matched_names and not any(token in code for token in ["pygame.draw.rect", "pygame.display.flip", "pygame.display.update", "pygame.time.wait", "tick("]):
        return _to_result(
            assignment,
            payload,
            1,
            "Relevant early attempt detected (motion variable setup/update), but elevator movement logic is still incomplete.",
            matched_names,
            unmet_names,
            analysis.coherence_failures,
            analysis.requirement_failures,
        )

    syntax_error = False
    if code.strip():
        try:
            ast.parse(code)
        except SyntaxError:
            syntax_error = True

    score = 3
    explanation = "Program includes the needed loop, drawing call, timing control, and required logic."
    if not analysis.meaningful_attempt or syntax_error or analysis.requirement_failures or analysis.coherence_failures or unmet_names:
        score = 2
        if syntax_error:
            explanation = "Meaningful attempt found, but code has syntax issues."
        elif analysis.coherence_failures:
            explanation = analysis.coherence_failures[0]
        else:
            explanation = "Relevant attempt detected in required zones, but key requirements were missing."

    return _to_result(
        assignment,
        payload,
        score,
        explanation,
        matched_names,
        unmet_names,
        analysis.coherence_failures,
        analysis.requirement_failures,
    )


def _to_result(
    assignment: AssignmentConfig,
    payload: GradingInput,
    score: int,
    explanation: str,
    matched: list[str],
    unmet: list[str],
    coherence: list[str],
    requirements: list[str],
) -> GradingResult:
    return GradingResult(
        assignment_id=assignment.id,
        assignment_title=assignment.title,
        status=payload.status,
        rubric_score=score,
        points=assignment.rubric_to_points_default.get(score, 0),
        explanation=explanation,
        matched_fill_zones=matched,
        unmet_fill_zones=unmet,
        coherence_guardrail_failures=coherence,
        requirement_check_failures=requirements,
    )
