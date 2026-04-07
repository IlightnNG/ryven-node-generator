"""Lightweight checks for generated core_logic."""

from __future__ import annotations

import ast
import textwrap

# Substring checks (lowercased source). Keep specific enough to avoid false positives
# (e.g. do not ban "exec(" in a way that breaks legitimate APIs — Ryven uses exec_output, not exec()).
_FORBIDDEN = (
    "subprocess",
    "socket",
    "ctypes",
    "__import__",
    "exec(",
    "compile(",
)


def dedent_core_logic(code: str) -> str:
    return textwrap.dedent(code).strip("\n")


def validate_core_logic(code: str) -> tuple[bool, str]:
    if not code.strip():
        return False, "core_logic is empty."
    t = dedent_core_logic(code)
    lower = t.lower()
    for bad in _FORBIDDEN:
        if bad in lower:
            return False, f"Disallowed construct or name: {bad!r}"
    try:
        ast.parse(t)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    return True, ""
