# TechSmart Grading Companion

A prototype teacher-facing grading tool for **CS101 Unit 3.3** that replaces line-count-based progress indicators with a more meaningful rubric-based scoring workflow.

## Purpose

This project is designed to help grade TechSmart Python/Pygame assignments more fairly and more efficiently by using:

- a **0–3 rubric score**
- a **0 / 50 / 75 / 100 point conversion**
- **template-aware attempt detection**
- **assignment-specific fill-zone checks**
- **anti-gaming guardrails** to prevent students from filling bubbles with unrelated code
- a **unit total out of 100** across only the assignments the teacher chooses to count

## Current Scope

This repo currently focuses on:

- **CS101**
- **Unit 3.3 – Animation**
- the assignments the teacher currently grades as part of the unit

## Included Files

- `unit_3_3_animation_grading_config_working.yaml`  
  Primary human-readable grading config.

- `unit_3_3_animation_grading_config_working.json`  
  JSON version of the same grading config.

- `CS101_Unit_3_3_Starter_and_Solution_Master_fresh.pdf`  
  Master reference PDF containing starter/template code followed by solution code for the graded Unit 3.3 assignments.

- `Unit_3_3_Autograder_Config_Guide_fresh.md`  
  Notes explaining how the config is intended to be used.

## MVP Goal

Build a local web app called **TechSmart Grading Companion** that allows a teacher to:

1. Select an assignment
2. Paste student code
3. Indicate assignment status:
   - not started
   - started, not submitted
   - turned in
4. Optionally enter TechSmart line-count values
5. Receive:
   - rubric score (0, 1, 2, 3)
   - point score (0, 50, 75, 100)
   - explanation of why
   - missing requirement flags
   - unit total out of 100

## Rubric Model

- **0** = no meaningful attempt
- **1** = meaningful but incomplete attempt
- **2** = turned in, but incorrect / buggy / incomplete
- **3** = correct

Point conversion:

- **0 → 0**
- **1 → 50**
- **2 → 75**
- **3 → 100**

## Key Grading Rules

- TechSmart line count is **ignored** for grading except in one case:
  - if the assignment is **turned in** and shows **0 / X lines of code**, it counts as **Score 0**
- “Meaningful attempt” must be **relevant to the assignment’s expected fill zones**
- Random pasted code should **not** count as meaningful
- Starter-heavy assignments should **not** get credit just because the template already contains code

## Long-Term Vision

This project can later expand to include:

- more CS101 units
- more TechSmart courses
- browser-extension support for pulling code from TechSmart’s **More Actions → View**
- stronger AST-based analysis
- optional sandboxed runtime checks
- a prototype suitable for proposing to **TechSmart** as a platform improvement

## Notes

This is currently a **prototype / MVP concept** and is intended first for local teacher use, then potentially for broader refinement and demonstration.
