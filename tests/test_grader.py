from app.config_loader import load_config
from app.grader import grade_submission
from app.models import GradingInput, SubmissionStatus, UnitGradeEntry
from app.unit_grade import calculate_unit_grade


def _assignment(assignment_id: str = "3_3_animating_shapes_1_technique1practice1_py"):
    config = load_config()
    return next(a for a in config.assignments if a.id == assignment_id)


def test_turned_in_zero_lines_scores_zero():
    assignment = _assignment()
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
    assignment = _assignment()
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.NOT_STARTED,
            student_code="pygame.draw.circle(screen, (255,0,0), (x, y), 10)",
        ),
    )
    assert result.rubric_score == 0


def test_started_not_submitted_one_relevant_zone_scores_one():
    assignment = _assignment()
    code = """
import pygame
pygame.draw.circle(screen, (255, 0, 0), (50, 50), 20)
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
    assert result.matched_fill_zones == ["draw_shape"]
    assert (
        result.explanation
        == "Relevant attempt detected, but the assignment is still incomplete and was not submitted."
    )


def test_started_not_submitted_irrelevant_code_scores_zero():
    assignment = _assignment()
    code = """
for i in range(5):
    print(i)
"""
    result = grade_submission(
        assignment,
        GradingInput(
            assignment_id=assignment.id,
            status=SubmissionStatus.STARTED_NOT_SUBMITTED,
            student_code=code,
        ),
    )
    assert result.rubric_score == 0


def test_turned_in_no_relevant_attempt_scores_one():
    assignment = _assignment()
    code = """
import random
for i in range(10):
    print(i)
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 1
    assert result.explanation == "Turned in, but no relevant assignment-specific attempt was detected."


def test_turned_in_meaningful_attempt_with_syntax_failure_scores_two():
    assignment = _assignment()
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
    assignment = _assignment()
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


def test_turned_in_point_tuple_offset_pattern_scores_three():
    assignment = _assignment()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
yoyo_x = 250
yoyo_y = 100
yoyo_offset = 0
string_color = (255, 255, 255)
yoyo_color = (255, 0, 0)

while frames < 100:
    yoyo_offset += 4
    point = (yoyo_x, yoyo_y + yoyo_offset)

    window.fill((0, 0, 0))
    pygame.draw.line(window, string_color, (0, 0), point)
    pygame.draw.circle(window, yoyo_color, point, 50)

    pygame.display.flip()
    pygame.time.wait(40)
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



def test_weighted_unit_grade_calculation():
    entries = [
        UnitGradeEntry("a", "A", 100, include=True, weight=2.0),
        UnitGradeEntry("b", "B", 50, include=True, weight=1.0),
        UnitGradeEntry("c", "C", 0, include=False, weight=1.0),
    ]
    assert calculate_unit_grade(entries, {"a", "b"}) == 83.33


def _assignment_animating_shapes_2():
    return _assignment("3_3_animating_shapes_2_technique1practice2_py")


def test_animating_shapes_2_true_zero_no_relevant_attempt():
    assignment = _assignment_animating_shapes_2()
    code = """
print('hello world')
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.STARTED_NOT_SUBMITTED, student_code=code),
    )
    assert result.rubric_score == 0


def test_animating_shapes_2_true_one_early_offset_attempt():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
frames = 0
offset = 0
while frames < 100:
    offset += 1
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 1


def test_animating_shapes_2_true_two_meaningful_but_incomplete():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
frames = 0
offset = 0
left = 100
right = 200
top = 50
bottom = 150

while frames < 100:
    offset += 2
    point1 = (left, top + offset)
    point2 = (right, top + offset)
    pygame.draw.polygon(window, (255, 0, 0), [point1, point2])
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 2


def test_animating_shapes_2_true_three_complete_polygon_solution():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
offset = 0
left = 100
right = 200
top = 50
bottom = 150

while frames < 100:
    offset += 4
    point1 = (left, top + offset)
    point2 = (right, top + offset)
    point3 = (right, bottom + offset)
    point4 = (left, bottom + offset)

    pygame.draw.polygon(window, (255, 0, 0), [point1, point2, point3, point4])
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 3
    assert result.points == 100


def test_animating_shapes_2_true_three_with_points_list_variable():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
offset = 0
left = 100
right = 200
top = 50
bottom = 150

while frames < 100:
    offset += 4
    point1 = (left, top + offset)
    point2 = (right, top + offset)
    point3 = (right, bottom + offset)
    point4 = (left, bottom + offset)
    points = [point1, point2, point3, point4]

    pygame.draw.polygon(window, (255, 0, 0), points)
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 3
    assert result.points == 100
