"""Apply model-proposed JSON patches to a node dict (whitelist)."""

from __future__ import annotations

from typing import Any

_ALLOWED = frozenset({
    "class_name",
    "title",
    "description",
    "color",
    "inputs",
    "outputs",
    "core_logic",
    "has_main_widget",
    "main_widget_template",
    "main_widget_args",
    "main_widget_pos",
    "main_widget_code",
})


def apply_config_patch(node: dict[str, Any], patch: dict[str, Any] | None) -> list[str]:
    """Merge whitelisted keys from patch into node. Returns human-readable skip reasons."""
    if not patch:
        return []
    skipped: list[str] = []
    for k, v in patch.items():
        if k not in _ALLOWED:
            skipped.append(f"Ignored disallowed key: {k!r}")
            continue
        node[k] = v
    return skipped
