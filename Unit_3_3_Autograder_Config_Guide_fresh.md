# Unit 3.3 Animation — Autograder Config Guide (Teacher + Developer)

These files are **configuration** for an autograder you can build (or ask TechSmart to build).
They do **not** run by themselves. Think of them as the “rules” the checker follows.

## Files
- `unit_3_3_animation_grading_config_v3.yaml` — human-friendly config (recommended to edit)
- `unit_3_3_animation_grading_config_v3.json` — same config in JSON (useful for apps)

## What the config controls
### 1) Which activities count in the unit grade
Each assignment has:
- `count_in_unit_grade_default: true/false`
- `weight: 1.0` (you said equal weights)

### 2) Rubric mapping (0–3) → points (0–100)
Default mapping:
- 0 → 0
- 1 → 50
- 2 → 75
- 3 → 100

### 3) “Turned in empty” rule (only time lines matter)
If TechSmart shows `0 / X lines of code` in the popup:
- Score must be 0 (even if Turned In)

### 4) Meaningful Attempt (anti-gaming)
For template-heavy tasks, students must match the **fill zones**:
- zones are identified by nearby comment prompts (e.g., “Subtract from offset”)
- student code must include a real statement AND match an expected pattern for that zone
- coherence guardrails prevent “keyword stuffing” (e.g., offset defined but never used)

### 5) Score 3 requirements
Each assignment has a `requirement_checks.score3_minimums` list.
These are the “must-haves” to award a 3.

## What you (teacher) should do with these files
### Right now
- You don’t have to change anything if the True/False and weights are already correct.

### When you want to customize
Open the YAML in any text editor and adjust:
- which assignments count (true/false)
- rubric-to-points mapping (if you ever change it)
- per-assignment patterns (if TechSmart changes prompts)

## What a developer (or Codex) builds using this config
A simple app with:
1) A “grade” button that takes student code (paste/upload)
2) Selects the assignment (file_name)
3) Applies the rules in this config:
   - determine 0/1/2/3
   - output points and reasons (missing zone, missing loop, etc.)
4) Computes unit grade out of 100 across counted assignments.

## Your workflow (today vs later)
- **Today (manual):** Click cell → More Actions → View → copy code → paste into grader app → get score
- **Later (extension):** Click cell → extension auto-grabs code + popup status → sends to grader → shows score
