from __future__ import annotations

import re
from typing import Iterable


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def is_comment_or_blank(line: str) -> bool:
    stripped = line.strip()
    return not stripped or stripped.startswith("#")


def strip_comment_blank_lines(code: str) -> list[str]:
    lines = normalize_newlines(code).split("\n")
    return [line for line in lines if not is_comment_or_blank(line)]


def has_non_comment_statement(code: str) -> bool:
    return any(line.strip() for line in strip_comment_blank_lines(code))


def regex_any_match(patterns: Iterable[str], text: str) -> bool:
    return any(re.search(pattern, text, flags=re.MULTILINE) for pattern in patterns)


def token_present(token: str, code: str) -> bool:
    return token in code


def find_main_loop_block(code: str) -> str:
    lines = normalize_newlines(code).split("\n")
    start = None
    indent = 0
    for i, line in enumerate(lines):
        if re.match(r"^\s*while\b.*:\s*$", line):
            start = i + 1
            indent = len(line) - len(line.lstrip())
            break
    if start is None:
        return ""

    block_lines: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            block_lines.append(line)
            continue
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent:
            break
        block_lines.append(line)
    return "\n".join(block_lines)
