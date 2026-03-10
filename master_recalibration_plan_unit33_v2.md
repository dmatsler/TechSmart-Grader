# Master Recalibration Plan — Unit 3.3 Animation (v2)

This version expands the first plan to include the later Unit 3.3 graded exercises/projects:
- Stick Dance: Random
- Healthful UFO
- Stick Dance: Smooth
- Bouncing Ball

Source PDFs used:
- `TechSmart Middle School CS101 Unit 3.3 Animation Assingment Requirements.pdf`
- `CS101_Unit_3_3_Starter_and_Solution_Master.pdf`
- `CS100-CS102 Lesson Rubrics-Unit 3_3 Animation.pdf`

## How to use this plan

For each assignment:
1. Confirm what the **starter/template already gives** the student.
2. Identify the **student-added logic** that should drive grading.
3. Build assignment-specific grader zones around the taught concept.
4. Test a real **0 / 1 / 2 / 3** example before trusting that assignment.

## Scoring frame for every assignment

- **0**: template only / no meaningful assignment-specific attempt
- **1**: early relevant attempt, but incomplete or weak
- **2**: meaningful assignment-specific work, but incomplete / buggy / incorrect
- **3**: concept implemented correctly and completely

## Common guardrails for all Unit 3.3 assignments

- Do **not** count starter/template code by itself.
- Do **not** require exact student variable names unless the assignment explicitly teaches a fixed name.
- Prefer **structural / AST-based checks** over brittle regex-only checks when students can choose their own names.
- A draw call should only count when it is tied to the **intended object/shape** for that assignment.
- Flip/wait should rarely count by themselves in starter-heavy files.

---

# Core paired practice assignments

## 1) Animating Shapes (1)
**File:** `Technique1Practice1.py`  
**Concept:** offset-based movement of a yoyo using line + circle

### Starter already provides
- window setup
- colors
- `string_start`, `yoyo_x`, `yoyo_y`
- loop structure
- background fill scaffold
- flip/wait scaffold

### Student must add
- offset variable setup
- offset update each frame (+4)
- point/center using `yoyo_y + offset`
- line from `string_start` to point
- circle at that point

### Sidebar requirements
- Draw a yoyo moving down, using a line and circle
- Make an offset that moves by four pixels every frame
- Use an offset to move a circle's center down
- Draw a line from `string_start` to the circle's center
- Every frame, flip and wait for 40 milliseconds

### Recommended fill zones
- `offset_setup_and_update`
- `point_from_offset`
- `draw_line`
- `draw_circle`
- `flip_and_wait`

### Must not count
- starter loop alone
- starter variables alone
- flip/wait by themselves

### Structural checks
- detect a motion variable initialized before loop and updated in loop
- detect a point tuple or center expression using the motion variable
- detect that point used in both line/circle draw context

---

## 2) Animating Shapes (2)
**File:** `Technique1Practice2.py`  
**Concept:** clockwise polygon rotation using four points and one offset

### Starter already provides
- `left`, `right`, `top`, `bottom`
- window setup
- loop scaffold
- background fill scaffold

### Student must add
- offset setup/update (+5)
- four point tuples
- clockwise movement pattern
- `pygame.draw.polygon(...)`
- flip/wait

### Sidebar requirements
- Make an offset that moves by five pixels every frame
- Create and draw a polygon with four corners the size of the screen
- Use the offset to move all four corners clockwise
- Every frame, flip and wait for 40 milliseconds

### Recommended fill zones
- `offset_setup_and_update`
- `polygon_points`
- `draw_polygon`
- `flip_and_wait`

### Must not count
- starter side variables alone
- generic shape drawing
- hardcoded variable names should not be required

### Structural checks
- detect a motion variable by role, not name
- detect the four clockwise point roles:
  - `(left + motion, top)`
  - `(right, top + motion)`
  - `(right - motion, bottom)`
  - `(left, bottom - motion)`
- detect those points passed into `pygame.draw.polygon(...)`

---

## 3) Animating Rect Shapes (1)
**File:** `Technique2Practice1.py`  
**Concept:** move elevator upward by offset applied to rect y

### Starter already provides
- `ground_rect`, `building_rect`, `elevator_rect`
- `elevator_start`
- colors
- loop structure
- background fill

### Student must add
- elevator offset setup
- offset update each frame (-2)
- `elevator_rect.y = elevator_start + motion_var`
- draw elevator rect
- flip/wait

### Sidebar requirements
- Move the elevator upwards, two pixels every frame
- Move the elevator by using an offset to change its Rect
- Draw the elevator as a rectangle
- Remember to flip and wait for 40 milliseconds every frame

### Recommended fill zones
- `offset_update`
- `apply_offset_to_rect`
- `draw_elevator_rect`
- `flip_and_wait`

### Must not count
- drawing `ground_rect`
- drawing `building_rect`
- starter structure alone

### Structural checks
- detect motion variable initialized before loop and updated in loop
- detect `elevator_rect.y` or equivalent y-update using that same variable
- detect draw call specifically using `elevator_rect`

---

## 4) Animating Rect Shapes (2)
**File:** `Technique2Practice2.py`  
**Concept:** two-shape animation with conditional second motion

### Starter already provides
- `rock_rect`, `person_rect`, ground/background scaffolding
- start coordinates and loop scaffold

### Student must add
- rock offset moving downward 2 px/frame
- person offset moving right 3 px/frame
- conditional person movement after rock offset > 80
- apply offsets to the shapes' rects
- draw rock rectangle and person ellipse
- flip/wait

### Sidebar requirements
- Move the rock rectangle downwards, two pixels every frame
- When the rock has moved over 80 pixels, the person ellipse should start moving too
- The person ellipse moves right at three pixels per frame
- Move each shape by using an offset to change its Rect
- Draw the rock as a rectangle, and the person as an ellipse
- Remember to flip and wait for 40 milliseconds every frame

### Recommended fill zones
- `rock_offset_update`
- `person_offset_conditional_update`
- `apply_offsets_to_shapes`
- `draw_rock_and_person`
- `flip_and_wait`

### Must not count
- ground/background draws
- moving only one shape without the intended threshold logic
- generic draw calls without both target shapes

### Structural checks
- detect one motion variable used on the rock rect y-position
- detect another motion variable used on person position after a threshold condition
- detect threshold logic tied to rock movement rather than arbitrary frame count unless the assignment allows it

---

## 5) Adjust Animation Speed (1)
**File:** `Technique3Practice1.py`  
**Concept:** acceleration using a speed variable and modulo timing

### Starter already provides
- window, car rect, road rect
- `car_offset += 1`
- draw code
- flip/wait

### Student must add
- speed variable
- use speed to update offset
- every-5-frames conditional using `%`
- speed increase by 2

### Sidebar requirements
- Make the car accelerate (speed up)
- Use a number variable to store the car's speed
- Use the speed to change the car's offset every frame
- The speed should increase by 2 every 5 frames
- You can use `%` to find every five frames

### Recommended fill zones
- `speed_setup`
- `offset_uses_speed`
- `modulo_every_five`
- `speed_increment`

### Must not count
- starter `car_offset += 1`
- starter draw code
- loop alone

### Structural checks
- detect a speed variable and its reuse in offset update
- detect a modulo or equivalent every-5-frames condition
- detect speed change, not just constant offset movement

---

## 6) Adjust Animation Speed (2)
**File:** `Technique3Practice2.py`  
**Concept:** variable frame delay and slow-motion interval

### Starter already provides
- jumping dodge motion logic
- frame count logic
- draw code
- fixed `pygame.time.wait(40)`

### Student must add
- delay variable
- use variable in `pygame.time.wait(...)`
- slow motion on at frame 30
- slow motion off at frame 50
- recommended delay around 200 ms during slow motion

### Sidebar requirements
- Add a slow motion effect to this jumping dodge
- The slow motion should last from frame 30 to frame 50
- Turn slow motion on and off by changing the delay in `pygame.time.wait()`
- A good speed for slow motion is 200 ms between frames

### Recommended fill zones
- `frame_delay_setup`
- `wait_uses_variable`
- `slow_motion_on`
- `slow_motion_off`

### Must not count
- existing jump logic
- frame count logic alone
- fixed wait call

### Structural checks
- detect delay variable initialization
- detect wait call changed to use variable
- detect frame 30 and frame 50 logic that changes delay

---

## 7) Backgrounds and Trails (1)
**File:** `Technique4Practice1.py`  
**Concept:** conditional trails based on user input

### Starter already provides
- offset increment
- circle drawing loop
- flip/wait

### Student must add
- input prompt
- boolean based on answer
- conditional `window.fill(...)` only when trails are off

### Sidebar requirements
- Ask the user whether they want trails to appear
- Make the circles leave trails only if the user wants

### Recommended fill zones
- `user_input`
- `boolean_from_answer`
- `conditional_prevent_trails`
- `flip_and_wait`

### Must not count
- unconditional background fill
- circle drawing loop alone
- offset update alone

### Structural checks
- detect input()/answer handling
- detect boolean or equivalent truth flag
- detect conditional fill tied to that flag

---

## 8) Backgrounds and Trails (2)
**File:** `Technique4Practice2.py`  
**Concept:** trails plus random bright colors

### Starter already provides
- imports, offsets, loop
- background fill line
- circle draw scaffold
- flip/wait

### Student must add
- remove or bypass background redraw for trails
- random color tuple
- three `random.randint(200, 255)` calls or equivalent
- draw circle using the random color

### Sidebar requirements
- Make the circle leave a trail instead of redrawing the background
- Make the circle draw in a random color every frame
- The R, G, and B of the color should each be random numbers between 200 and 255

### Recommended fill zones
- `disable_background_redraw`
- `random_color_tuple`
- `randint_200_255_three_times`
- `draw_circle_with_color`

### Must not count
- importing `random` alone
- a static color tuple
- leaving `window.fill(bg_color)` active each frame if trails are required

### Structural checks
- detect three random components in the required range
- detect circle draw uses that generated color
- detect background is not redrawn every frame

---

# Extended Unit 3.3 exercises/projects

## 9) Stick Dance: Random
**File:** `StickDanceRandom_solution.py`  
**Concept:** random coordinate animation for stick-figure limbs

### Starter already provides
- setup comments and scaffolding
- body/head drawing prompts
- loop scaffold
- finish scaffold

### Student must add
- import `random`
- full pygame setup
- frame counter and loop
- white background fill
- body circle + torso line
- random leg coordinates and leg lines
- random arm coordinates and arm lines
- display flip and 100 ms wait

### Sidebar requirements
- Re-set coordinates every frame to create animation
- Use the random library to determine position
- Comments are more instructive

### Recommended fill zones
- `setup_and_loop`
- `body_draw`
- `leg_randomization`
- `leg_draws`
- `arm_randomization`
- `arm_draws`
- `flip_and_wait`

### Must not count
- importing `random` alone
- drawing only the body without animated limbs
- loop alone

### Structural checks
- detect `random.randint(25, 100)` and `random.randint(200, 275)` for legs, or equivalent ranges
- detect arm random ranges between 100 and 250
- detect limb lines use those random values
- for Score 3, both arms and both legs should animate via random coordinates

### Suggested scoring notes
- **0**: mostly starter/template only
- **1**: partial setup or one limb group attempted
- **2**: body plus one or more animated limb groups, but incomplete
- **3**: body plus both animated arms and legs with proper random coordinate logic and finish steps

---

## 10) Healthful UFO
**File:** `HealthfulUFO_solution.py`  
**Concept:** code restructure / comment placement in a multi-object animation

### Starter already provides
- working code body with numbered placeholders/comments out of place
- all objects and variables are already present in code

### Student must add
- place the instructional comments in the correct locations
- effectively map numbered sections to the right code blocks

### Sidebar requirements
- Take the comments from the top of the program and place them where they go in the code

### Recommended fill zones
- `ship_setup_comment_mapping`
- `package_setup_comment_mapping`
- `start_positions_comment_mapping`
- `animation_variables_comment_mapping`
- `move_ship_comment_mapping`
- `move_package_comment_mapping`
- `reset_ship_comment_mapping`
- `reset_package_comment_mapping`
- `draw_background_comment_mapping`
- `draw_package_comment_mapping`
- `draw_ship_comment_mapping`
- `finish_drawing_comment_mapping`

### Must not count
- code execution alone, because the code already largely exists
- generic comment presence without correct placement

### Structural checks
- this one is closer to a **code organization / comment placement** exercise than a pure logic-write task
- likely best graded by checking whether each numbered comment or phrase appears adjacent to the correct code block
- for Score 3, comments should be placed in the intended locations for ship setup, package setup, movement, reset logic, and draw sections

### Suggested scoring notes
- **0**: little or no comment-placement work
- **1**: a few comments moved but mostly incomplete
- **2**: substantial comment placement with some wrong locations
- **3**: comments placed correctly throughout the program

---

## 11) Stick Dance: Smooth
**File:** `StickDanceSmooth_Solution.py`  
**Concept:** smooth animation using offsets and speeds rather than random positions

### Starter already provides
- setup
- body/head drawing
- random placeholder logic for legs/arms
- loop and finish scaffolding

### Student must add
- leg animation variables (`l_leg_start`, `r_leg_start`, `leg_offset`, `leg_speed`)
- arm animation variables (`l_arm_start`, `r_arm_start`, `arm_offset`, `arm_speed`)
- replace random limb values with offset-based values
- boundary conditions for reversing leg/arm motion
- single connecting arm line
- shorter wait (10 ms)
- increase frames from 100 to 300

### Sidebar requirements
- Change coordinates every frame to create animation
- Use an offset that changes every frame to determine position
- Comments are more instructive

### Recommended fill zones
- `leg_animation_variables`
- `arm_animation_variables`
- `leg_position_updates`
- `leg_boundary_reverse`
- `arm_position_updates`
- `arm_upper_boundary_reverse`
- `arm_lower_boundary_reverse`
- `single_arm_line`
- `frame_and_wait_adjustments`

### Must not count
- leftover random limb code
- body drawing alone
- partial variable setup without using them in limb positions

### Structural checks
- detect offsets and speeds for both arms and legs
- detect increment/update each frame
- detect reversal conditions (`> 125 or < 0` for legs; upper/lower limits for arms)
- detect one line connecting `(25, left_arm)` to `(275, right_arm)`
- detect wait changed from 100 to 10 and frames to 300

### Suggested scoring notes
- **0**: template/random starter mostly unchanged
- **1**: partial offset setup or one limb group converted
- **2**: meaningful offset-based animation for limbs but incomplete boundary logic or finish
- **3**: smooth leg and arm animation fully implemented as intended

---

## 12) Bouncing Ball
**File:** `BouncingBall_solution.py`  
**Concept:** bouncing motion with shrinking bounce height via ceiling adjustments

### Starter already provides
- assignment comments and scaffolding only
- no full motion logic yet

### Student must add
- pygame setup and window
- movement variables (`x_speed`, `y_speed`, `ball_x`, `ball_y`, `ceiling_y`, `floor_y`, `ceiling_increment`)
- loop while `ball_x < 800`
- position updates each frame
- bounce off floor by reversing `y_speed`
- raise `ceiling_y` by `int(ceiling_increment)` on each bounce
- reduce `ceiling_increment *= .5`
- bounce off ceiling by reversing `y_speed`
- draw circle, fill background, flip, wait 10 ms

### Sidebar requirements
- Change the position of a circle every frame
- Change the minimum y value each bounce so the bounces get smaller
- Comments are more instructive

### Recommended fill zones
- `animation_variable_setup`
- `loop_condition`
- `ball_position_updates`
- `floor_bounce_logic`
- `ceiling_increment_update`
- `ceiling_bounce_logic`
- `draw_ball`
- `flip_and_wait`

### Must not count
- setup alone
- moving only in x or only in y
- a simple bounce without shrinking bounce height

### Structural checks
- detect `ball_x += x_speed` and `ball_y += y_speed`
- detect floor condition and `y_speed *= -1`
- detect `ceiling_y += int(ceiling_increment)`
- detect `ceiling_increment *= .5`
- detect ceiling condition and second y-speed reversal
- detect circle draw uses `(ball_x, ball_y)`

### Suggested scoring notes
- **0**: little or no student code
- **1**: some setup and motion attempt, but not enough bounce logic
- **2**: meaningful motion and bounce logic, but missing shrinking-bounce concept or finish steps
- **3**: full bouncing-ball behavior with shrinking bounce height implemented correctly

---

# Recommended recalibration order (updated)

1. Animating Shapes (1)
2. Animating Shapes (2) ✅
3. Animating Rect Shapes (1) ✅
4. Animating Rect Shapes (2)
5. Adjust Animation Speed (1)
6. Adjust Animation Speed (2)
7. Backgrounds and Trails (1)
8. Backgrounds and Trails (2)
9. Stick Dance: Random
10. Healthful UFO
11. Stick Dance: Smooth
12. Bouncing Ball

Use ✅ only after you have real regression checks for 0 / 1 / 2 / 3 or enough confidence from your examples.

# Per-assignment calibration checklist

```text
Assignment:
File name:
Starter provides:
Student must add:
Sidebar requirements:
Must not count:
Recommended fill zones:
Structural checks:
True 0 tested: ☐
True 1 tested: ☐
True 2 tested: ☐
True 3 tested: ☐
Notes / edge cases:
```

# Safer Codex workflow rule

For each new fix:
- start a **fresh Codex task**
- tell it to start from the latest current `main` only
- create a **fresh branch**
- make only that targeted fix
- open a fresh PR
- merge, then in Codespaces run:

```bash
git checkout main
git pull
python3 -m uvicorn app.main:app --reload
```
