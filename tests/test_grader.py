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


def test_animating_shapes_1_true_one_started_not_submitted_early_attempt_scores_one():
    assignment = _assignment()
    code = """
import pygame
frames = 0
yoyo_offset = 0
while frames < 30:
    yoyo_offset += 4
    frames += 1
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
    assert "offset_setup_and_update" in result.matched_fill_zones


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


def test_animating_shapes_1_true_zero_template_or_irrelevant_submission_scores_zero():
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
    assert result.rubric_score == 0
    assert result.explanation == "Turned in, but only starter/template structure was detected (no assignment-specific motion logic attempt)."


def test_animating_shapes_1_true_zero_starter_template_loop_flip_wait_only_scores_zero():
    assignment = _assignment()
    code = """
import pygame
window = pygame.display.set_mode((400, 300))
frames = 0
yoyo_x = 200
yoyo_y = 100
string_start = (yoyo_x, 0)

while frames < 60:
    window.fill((0, 0, 0))
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 0


def test_animating_shapes_1_true_two_meaningful_but_incomplete_scores_two():
    assignment = _assignment()
    code = """
import pygame
frames = 0
yoyo_x = 10
yoyo_y = 20
yoyo_offset = 0
string_start = (yoyo_x, 0)
while frames < 100:
    yoyo_offset += 4
    point = (yoyo_x, yoyo_y + yoyo_offset)
    pygame.draw.circle(screen, (255,0,0), point, 8)
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
    assert result.rubric_score == 2


def test_animating_shapes_1_true_three_complete_solution_scores_three():
    assignment = _assignment()
    code = """
import pygame
frames = 0
yoyo_x = 10
yoyo_y = 20
yoyo_offset = 0
string_start = (yoyo_x, 0)
clock = pygame.time.Clock()
while frames < 10:
    yoyo_offset += 4
    point = (yoyo_x, yoyo_y + yoyo_offset)
    pygame.draw.line(screen, (255, 255, 255), string_start, point)
    pygame.draw.circle(screen, (255, 0, 0), point, 20)
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
string_start = (yoyo_x, 0)
string_color = (255, 255, 255)
yoyo_color = (255, 0, 0)

while frames < 100:
    yoyo_offset += 4
    point = (yoyo_x, yoyo_y + yoyo_offset)

    window.fill((0, 0, 0))
    pygame.draw.line(window, string_color, string_start, point)
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



def test_animating_shapes_1_true_three_allows_flexible_motion_variable_name():
    assignment = _assignment()
    code = """
import pygame
frames = 0
yoyo_x = 10
yoyo_y = 20
drop = 0
string_start = (yoyo_x, 0)
while frames < 10:
    drop = drop + 4
    center = (yoyo_x, yoyo_y + drop)
    pygame.draw.line(screen, (255, 255, 255), string_start, center)
    pygame.draw.circle(screen, (255, 0, 0), center, 20)
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


def test_weighted_unit_grade_calculation():
    entries = [
        UnitGradeEntry("a", "A", 100, include=True, weight=2.0),
        UnitGradeEntry("b", "B", 50, include=True, weight=1.0),
        UnitGradeEntry("c", "C", 0, include=False, weight=1.0),
    ]
    assert calculate_unit_grade(entries, {"a", "b"}) == 83.33


def _assignment_animating_shapes_2():
    return _assignment("3_3_animating_shapes_2_technique1practice2_py")


def _assignment_animating_rect_shapes_1():
    return _assignment("3_3_animating_rect_shapes_1_technique2practice1_py")


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


def test_animating_shapes_2_true_zero_starter_only_submission_scores_zero():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
window = pygame.display.set_mode((400, 400))
left = 0
right = 400
top = 0
bottom = 400
frames = 0

while frames < 100:
    window.fill((0, 0, 0))
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 0


def test_animating_shapes_2_true_two_complete_clockwise_points_but_wrong_offset_step():
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
    top_left = (left + offset, top)
    top_right = (right, top + offset)
    bottom_right = (right - offset, bottom)
    bottom_left = (left, bottom - offset)

    pygame.draw.polygon(window, (255, 0, 0), [top_left, top_right, bottom_right, bottom_left])
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
    offset += 5
    top_left = (left + offset, top)
    top_right = (right, top + offset)
    bottom_right = (right - offset, bottom)
    bottom_left = (left, bottom - offset)

    pygame.draw.polygon(window, (255, 0, 0), [top_left, top_right, bottom_right, bottom_left])
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
    assert result.unmet_fill_zones == []
    assert result.coherence_guardrail_failures == []


def test_animating_shapes_2_true_three_with_points_list_variable():
    assignment = _assignment_animating_shapes_2()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
slide = 0
left = 100
right = 200
top = 50
bottom = 150

while frames < 100:
    slide = slide + 5
    alpha = (slide + left, top)
    beta = (right, slide + top)
    gamma = (right + -slide, bottom)
    delta = (left, bottom + -slide)
    points = [alpha, beta, gamma, delta]

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
    assert result.unmet_fill_zones == []
    assert result.coherence_guardrail_failures == []



def test_animating_rect_shapes_1_real_starter_score_three_submission_scores_three():
    assignment = _assignment_animating_rect_shapes_1()
    code = '"""\nLESSON: 3.3 - Animation\nTECHNIQUE 2: Animating Rect Shapes\nPRACTICE 1\n"""\n\nimport pygame\npygame.init()\n\nwindow = pygame.display.set_mode([400, 400])\n\nsky_color = (180, 200, 240)\nground_color = (100, 150, 100)\nbuilding_color = (50, 50, 50)\nelevator_color = (100, 100, 100)\n\nground_rect = pygame.Rect(0, 300, 400, 100)\nbuilding_rect = pygame.Rect(250, 20, 100, 280)\n\nelevator_start = 240\nelevator_rect = pygame.Rect(240, elevator_start, 40, 60)\n\n# Declare an offset for the elevator\nele_off = 0\n\nframes = 0\nwhile frames < 100:\n\n    # Subtract from offset\n    ele_off -= 2\n\n    # Use the offset to set the elevator rect\'s y\n    elevator_rect.y = elevator_start + ele_off\n\n    window.fill(sky_color)\n    pygame.draw.rect(window, ground_color, ground_rect)\n    pygame.draw.rect(window, building_color, building_rect)\n\n    # Draw the elevator\n    pygame.draw.rect(window,elevator_color,elevator_rect)\n\n    # Flip and wait every frame\n    pygame.display.flip()\n    pygame.time.wait(40)\n\n\n    frames += 1\n\n\n# Turn in your Coding Exercise.\n'
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 3
    assert result.points == 100


def test_animating_rect_shapes_1_real_starter_true_zero_submission_scores_zero():
    assignment = _assignment_animating_rect_shapes_1()
    code = '"""\nLESSON: 3.3 - Animation\nTECHNIQUE 2: Animating Rect Shapes\nPRACTICE 1\n"""\n\nimport pygame\npygame.init()\n\nwindow = pygame.display.set_mode([400, 400])\n\nsky_color = (180, 200, 240)\nground_color = (100, 150, 100)\nbuilding_color = (50, 50, 50)\nelevator_color = (100, 100, 100)\n\nground_rect = pygame.Rect(0, 300, 400, 100)\nbuilding_rect = pygame.Rect(250, 20, 100, 280)\n\nelevator_start = 240\nelevator_rect = pygame.Rect(240, elevator_start, 40, 60)\n\n# Declare an offset for the elevator\n\n\nframes = 0\nwhile frames < 100:\n\n    # Subtract from offset\n    \n\n    # Use the offset to set the elevator rect\'s y\n\n\n    window.fill(sky_color)\n    pygame.draw.rect(window, ground_color, ground_rect)\n    pygame.draw.rect(window, building_color, building_rect)\n\n    # Draw the elevator\n    \n\n    # Flip and wait every frame\n\n\n\n    frames += 1\n\n\n# Turn in your Coding Exercise.\n'
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 0
    assert "draw_elevator_rect" in result.unmet_fill_zones
    assert "offset_update" in result.unmet_fill_zones
    assert "apply_offset_to_rect" in result.unmet_fill_zones


def test_animating_rect_shapes_1_true_three_custom_offset_variable_scores_three():
    assignment = _assignment_animating_rect_shapes_1()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
elevator_start = 320
elevator_rect = pygame.Rect(350, elevator_start, 50, 70)
ele_off = 0

while frames < 100:
    ele_off -= 2
    elevator_rect.y = elevator_start + ele_off

    window.fill((120, 180, 255))
    pygame.draw.rect(window, (50, 50, 50), pygame.Rect(0, 500, 800, 100))
    pygame.draw.rect(window, (130, 130, 130), pygame.Rect(300, 100, 180, 420))
    pygame.draw.rect(window, (255, 0, 0), elevator_rect)

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


def test_animating_rect_shapes_1_true_two_wrong_rect_target_scores_two_for_correct_reason():
    assignment = _assignment_animating_rect_shapes_1()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
elevator_start = 320
elevator_rect = pygame.Rect(350, elevator_start, 50, 70)
car_offset = 0
car_rect = pygame.Rect(100, 450, 120, 60)

while frames < 100:
    car_offset -= 2
    car_rect.y = 450 + car_offset

    window.fill((120, 180, 255))
    pygame.draw.rect(window, (255, 0, 0), elevator_rect)
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 2
    assert "Offset updated but not applied to rect position" in result.coherence_guardrail_failures




def test_animating_rect_shapes_1_true_two_wrong_speed_scores_two():
    assignment = _assignment_animating_rect_shapes_1()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
elevator_start = 320
elevator_rect = pygame.Rect(350, elevator_start, 50, 70)
slide = 0

while frames < 100:
    slide -= 3
    elevator_rect.y = elevator_start + slide

    window.fill((120, 180, 255))
    pygame.draw.rect(window, (255, 0, 0), elevator_rect)
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 2
    assert "Elevator offset should move upward by 2 pixels per frame" in result.coherence_guardrail_failures

def test_animating_rect_shapes_1_true_one_scores_one():
    assignment = _assignment_animating_rect_shapes_1()
    code = """
import pygame
frames = 0
temp_move = 0
while frames < 100:
    temp_move -= 2
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 1


def test_animating_rect_shapes_1_template_only_scores_zero():
    assignment = _assignment_animating_rect_shapes_1()
    code = """
import pygame
window = pygame.display.set_mode((800, 600))
frames = 0
while frames < 100:
    window.fill((120, 180, 255))
    pygame.draw.rect(window, ground_color, ground_rect)
    pygame.draw.rect(window, building_color, building_rect)
    pygame.display.flip()
    pygame.time.wait(40)
    frames += 1
"""
    result = grade_submission(
        assignment,
        GradingInput(assignment_id=assignment.id, status=SubmissionStatus.TURNED_IN, student_code=code),
    )
    assert result.rubric_score == 0
