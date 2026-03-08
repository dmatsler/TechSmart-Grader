from pathlib import Path


CONFLICT_PRONE_FILES = [
    "README.md",
    "app/grader.py",
    "app/main.py",
    "requirements.txt",
    "tests/test_grader.py",
]


def test_no_merge_conflict_markers_in_conflict_prone_files():
    markers = ("<<<<<<<", "=======", ">>>>>>>")
    root = Path(__file__).resolve().parents[1]

    for rel_path in CONFLICT_PRONE_FILES:
        content = (root / rel_path).read_text(encoding="utf-8")
        for marker in markers:
            assert marker not in content, f"Found merge-conflict marker '{marker}' in {rel_path}"
