from __future__ import annotations

import ast
from dataclasses import dataclass

from app.models import AssignmentConfig, GradingInput, GradingResult, SubmissionStatus, ZoneMatch
from app.utils import find_main_loop_block, has_non_comment_statement, regex_any_match, token_present


@dataclass
class AnalysisSummary:
    zone_matches: list[ZoneMatch]
    requirement_failures: list[str]
    coherence_failures: list[str]
    meaningful_attempt: bool
    expected_zone_count: int
    required_zone_count: int


def _check_fill_zones(assignment: AssignmentConfig, code: str) -> list[ZoneMatch]:
    matches: list[ZoneMatch] = []
    for zone in assignment.fill_zones:
        attempt_patterns = zone.attempt_patterns or zone.expected_patterns
        matched_attempt = regex_any_match(attempt_patterns, code) if attempt_patterns else False
        matched_expected = regex_any_match(zone.expected_patterns, code) if zone.expected_patterns else False
        anti_hit = regex_any_match(zone.anti_patterns, code) if zone.anti_patterns else False
        meaningful_line = matched_attempt and has_non_comment_statement(code)
        matched = (matched_attempt or matched_expected) and not anti_hit and meaningful_line
        details = ""
        if anti_hit:
            details = "Anti-pattern detected"
        elif not meaningful_line:
            details = "No meaningful line"
        elif not matched_expected:
            details = "Attempt pattern matched, expected pattern missing"
        matches.append(
            ZoneMatch(
                name=zone.name,
                matched=matched,
                matched_expected=matched_expected,
                matched_attempt=matched_attempt,
                anti_pattern_hit=anti_hit,
                has_meaningful_line=meaningful_line,
                details=details,
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


def _check_coherence_guardrails(assignment: AssignmentConfig, code: str) -> list[str]:
    failures: list[str] = []
    loop_block = find_main_loop_block(code)

    if "draw_inside_loop" in str(assignment.requirement_checks.coherence_guardrails):
        if "pygame.draw" in code and "pygame.draw" not in loop_block:
            failures.append("Draw call appears only outside main while-loop")

    if "flip_inside_loop" in str(assignment.requirement_checks.coherence_guardrails):
        has_flip = "pygame.display.flip" in code or "pygame.display.update" in code
        in_loop_flip = "pygame.display.flip" in loop_block or "pygame.display.update" in loop_block
        if has_flip and not in_loop_flip:
            failures.append("Display flip/update appears only outside main while-loop")

    if "updated_pos_used_in_draw" in str(assignment.requirement_checks.coherence_guardrails):
        updated = any(t in code for t in ["x +=", "y +=", "offset +=", "offset -=", "x = x", "y = y"])
        draw_uses = any(
            token in code
            for token in [
                "pygame.draw.circle(screen,",
                "pygame.draw.rect(screen,",
                "pygame.draw.line(screen,",
                "(x",
                ", x",
                "(y",
                ", y",
                "offset",
            ]
        )
        if updated and not draw_uses:
            failures.append("Position/offset updated but never used in draw context")

    if "offset_used_with_rect" in str(assignment.requirement_checks.coherence_guardrails):
        updated_offset = "offset +=" in code or "offset -=" in code or "offset = offset" in code
        used_with_rect = any(
            fragment in code
            for fragment in [
                "rect.y =",
                "rect.x =",
                "_rect.y =",
                "_rect.top =",
                "elevator_rect",
            ]
        ) and "offset" in code
        if updated_offset and not used_with_rect:
            failures.append("Offset updated but not applied to rect position")

    return failures


def analyze_submission(assignment: AssignmentConfig, code: str) -> AnalysisSummary:
    zone_matches = _check_fill_zones(assignment, code)
    matched_required = [z for z in zone_matches if z.matched]
    required_zones = [z for z in zone_matches if True]
    required_zone_count = len(required_zones)
    expected_zone_count = max(assignment.min_zones_matched_default, min(2, required_zone_count))
    requirement_failures = _check_requirements(assignment, code)
    coherence_failures = _check_coherence_guardrails(assignment, code)
    meaningful_attempt = len(matched_required) >= expected_zone_count
    if coherence_failures and not matched_required:
        meaningful_attempt = False
    return AnalysisSummary(
        zone_matches=zone_matches,
        requirement_failures=requirement_failures,
        coherence_failures=coherence_failures,
        meaningful_attempt=meaningful_attempt,
        expected_zone_count=expected_zone_count,
        required_zone_count=required_zone_count,
    )


def grade_submission(assignment: AssignmentConfig, payload: GradingInput) -> GradingResult:
    code = payload.student_code or ""

    if (
        payload.status == SubmissionStatus.TURNED_IN
        and payload.techsmart_lines_completed == 0
        and (payload.techsmart_lines_expected or 0) > 0
    ):
        score = 0
        explanation = (
            f"Turned in with 0/{payload.techsmart_lines_expected} lines, so this counts as no attempt."
        )
        return _to_result(assignment, payload, score, explanation, [], [], [], [])

    if payload.status == SubmissionStatus.NOT_STARTED:
        return _to_result(
            assignment,
            payload,
            0,
            "Assignment marked not started, so score is 0.",
            [],
            [],
            [],
            [],
        )

    analysis = analyze_submission(assignment, code)
    matched_names = [z.name for z in analysis.zone_matches if z.matched_expected]
    unmet_names = [z.name for z in analysis.zone_matches if not z.matched_expected]

    if payload.status == SubmissionStatus.STARTED_NOT_SUBMITTED:
        score = 1 if analysis.meaningful_attempt else 0
        explanation = (
            f"Relevant attempt detected in {len(matched_names)} required zones, but not submitted."
            if score == 1
            else "Started but no meaningful assignment-specific attempt detected."
        )
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

    syntax_error = False
    if code.strip():
        try:
            ast.parse(code)
        except SyntaxError:
            syntax_error = True

    if not analysis.meaningful_attempt:
        score = 1
        explanation = "Turned in, but only weak or non-relevant work was detected."
    else:
        score = 3
        explanation = "Program includes loop, drawing, timing control, and required logic."
        if syntax_error or analysis.requirement_failures or analysis.coherence_failures or unmet_names:
            score = 2
            if syntax_error:
                explanation = "Meaningful attempt found, but code has syntax issues."
            elif analysis.coherence_failures:
                explanation = analysis.coherence_failures[0]
            else:
                explanation = "Relevant attempt detected, but key requirements were missing."

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
