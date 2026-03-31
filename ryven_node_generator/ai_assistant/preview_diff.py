"""JSON list diff HTML and per-field change detection for AI preview."""

from __future__ import annotations

import difflib
import html
import json
from typing import Any


class _Missing:
    pass


_MISSING = _Missing()


def _json_equal(a: Any, b: Any) -> bool:
    try:
        return json.dumps(a, sort_keys=True, default=str) == json.dumps(
            b, sort_keys=True, default=str
        )
    except TypeError:
        return a == b


def node_changed_keys(before: dict[str, Any], after: dict[str, Any]) -> set[str]:
    keys = set(before.keys()) | set(after.keys())
    changed: set[str] = set()
    for k in keys:
        vb, va = before.get(k, _MISSING), after.get(k, _MISSING)
        if vb is _MISSING:
            if va is not _MISSING:
                changed.add(k)
            continue
        if va is _MISSING:
            changed.add(k)
            continue
        if not _json_equal(vb, va):
            changed.add(k)
    return changed


def dumps_pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False)


# Muted retro palette (matches Generator/ui_new.py theme)
_DIFF_EQ = "#aeb4bd"
_DIFF_DEL_FG = "#b89b98"
_DIFF_DEL_BG = "#3a2a2c"
_DIFF_INS_FG = "#9eb0a0"
_DIFF_INS_BG = "#273228"


def json_list_diff_html(
    before: list[Any],
    after: list[Any],
    *,
    bg: str = "#0c0e11",
) -> str:
    old_lines = dumps_pretty(before).splitlines(keepends=True)
    new_lines = dumps_pretty(after).splitlines(keepends=True)
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for line in old_lines[i1:i2]:
                parts.append(f'<span style="color:{_DIFF_EQ};">{html.escape(line)}</span>')
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )
    body = "".join(parts)
    legend = (
        '<div style="margin-bottom:8px;color:#8e96a0;font-size:11px;">'
        "<b>Red</b>: removed &nbsp;|&nbsp; <b>Green</b>: added "
        "&nbsp;—&nbsp; pending AI edit; use <b>Keep</b> or <b>Undo</b>.</div>"
    )
    return (
        f"{legend}"
        f'<pre style="margin:0;font-family:Consolas,\'Courier New\',monospace;'
        f"font-size:10pt;background:{bg};white-space:pre-wrap;\">{body}</pre>"
    )


def json_list_diff_html_and_first_change(
    before: list[Any],
    after: list[Any],
    *,
    bg: str = "#0c0e11",
) -> tuple[str, str]:
    """Same as json_list_diff_html, but also returns a snippet for first-change scrolling."""
    old_lines = dumps_pretty(before).splitlines(keepends=True)
    new_lines = dumps_pretty(after).splitlines(keepends=True)
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)

    first_snippet = ""
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal" and not first_snippet:
            if tag in ("delete", "replace") and i1 < len(old_lines):
                first_snippet = old_lines[i1].rstrip("\r\n")
            elif tag in ("insert", "replace") and j1 < len(new_lines):
                first_snippet = new_lines[j1].rstrip("\r\n")

        if tag == "equal":
            for line in old_lines[i1:i2]:
                parts.append(f'<span style="color:{_DIFF_EQ};">{html.escape(line)}</span>')
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )

    body = "".join(parts)
    legend = (
        '<div style="margin-bottom:8px;color:#8e96a0;font-size:11px;">'
        "<b>Red</b>: removed &nbsp;|&nbsp; <b>Green</b>: added "
        "&nbsp;—&nbsp; pending AI edit; use <b>Keep</b> or <b>Undo</b>.</div>"
    )
    html_doc = (
        f"{legend}"
        f'<pre style="margin:0;font-family:Consolas,\'Courier New\',monospace;'
        f"font-size:10pt;background:{bg};white-space:pre-wrap;\">{body}</pre>"
    )
    return html_doc, first_snippet


def text_diff_html_and_first_change(
    before: str,
    after: str,
    *,
    bg: str = "#0c0e11",
) -> tuple[str, str]:
    """Unified text diff renderer for nodes.py / gui.py.

    Returns:
      (html_doc, first_change_snippet)
    """
    old_lines = before.splitlines(keepends=True)
    new_lines = after.splitlines(keepends=True)
    sm = difflib.SequenceMatcher(a=old_lines, b=new_lines)

    first_snippet = ""
    parts: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal" and not first_snippet:
            if tag in ("delete", "replace") and i1 < len(old_lines):
                first_snippet = old_lines[i1].rstrip("\r\n")
            elif tag in ("insert", "replace") and j1 < len(new_lines):
                first_snippet = new_lines[j1].rstrip("\r\n")

        if tag == "equal":
            for line in old_lines[i1:i2]:
                parts.append(f'<span style="color:{_DIFF_EQ};">{html.escape(line)}</span>')
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )
        elif tag == "replace":
            for line in old_lines[i1:i2]:
                parts.append(
                    f'<span style="color:{_DIFF_DEL_FG};background:{_DIFF_DEL_BG};">{html.escape(line)}</span>'
                )
            for line in new_lines[j1:j2]:
                parts.append(
                    f'<span style="color:{_DIFF_INS_FG};background:{_DIFF_INS_BG};">{html.escape(line)}</span>'
                )

    body = "".join(parts)
    legend = (
        '<div style="margin-bottom:8px;color:#8e96a0;font-size:11px;">'
        "<b>Red</b>: removed &nbsp;|&nbsp; <b>Green</b>: added "
        "&nbsp;—&nbsp; pending AI edit; use <b>Keep</b> or <b>Undo</b>.</div>"
    )
    html_doc = (
        f"{legend}"
        f'<pre style="margin:0;font-family:Consolas,\'Courier New\',monospace;'
        f"font-size:10pt;background:{bg};white-space:pre-wrap;\">{body}</pre>"
    )
    return html_doc, first_snippet
