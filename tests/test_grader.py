from app.config_loader import load_config
from app.grader import grade_submission
from app.models import GradingInput, SubmissionStatus


def _config_and_assignment():
    config = load_config()
    assignment = next(
        a for a in config.assignments if a.id == "3_3_animating_shapes_1_technique1practice1_py"
    )
    return config, assignment


def test_turned_in_zero_lines_scores_zero():
    _, assignment = _config_and_assignment()
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.TURNED_IN,
            student_code="print('hello')",
            techsmart_lines_completed=0,
            techsmart_lines_expected=12,
        ),
    )
    assert result.rubric_score == 0
    assert result.points == 0


def test_not_started_scores_zero():
    _, assignment = _config_and_assignment()
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.NOT_STARTED,
            student_code="pygame.draw.circle(screen, (255,0,0), (x, y), 10)",
        ),
    )
    assert result.rubric_score == 0


def test_started_not_submitted_meaningful_attempt_scores_one():
    _, assignment = _config_and_assignment()
    code = """
import pygame
frames = 0
x = 10
y = 20
while frames < 100:
    x += 2
    pygame.draw.circle(screen, (255,0,0), (x, y), 8)
"""
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.STARTED_NOT_SUBMITTED,
            student_code=code,
        ),
    )
    assert result.rubric_score == 1


def test_turned_in_meaningful_attempt_with_syntax_failure_scores_two():
    _, assignment = _config_and_assignment()
    code = """
import pygame
frames = 0
x = 10
y = 20
while frames < 100:
    x += 2
    pygame.draw.circle(screen, (255,0,0), (x, y), 8)
    pygame.display.flip(
"""
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.TURNED_IN,
            student_code=code,
        ),
    )
    assert result.rubric_score == 2


def test_turned_in_complete_submission_scores_three():
    _, assignment = _config_and_assignment()
    code = """
import pygame
frames = 0
x = 10
y = 20
clock = pygame.time.Clock()
while frames < 10:
    x += 2
    pygame.draw.circle(screen, (255, 0, 0), (x, y), 20)
    pygame.display.flip()
    clock.tick(30)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.TURNED_IN,
            student_code=code,
        ),
    )
    assert result.rubric_score == 3
    assert result.points == 100
