"""Apply model-proposed JSON patches to a node dict (whitelist)."""

from __future__ import annotations

import copy
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


def whitelisted_config_diff(baseline: dict[str, Any], effective: dict[str, Any]) -> dict[str, Any]:
    """Keys in ``_ALLOWED`` whose values differ between baseline and effective (deep ``!=``).

    ``core_logic`` is omitted: the UI uses top-level ``core_logic`` from :func:`finalize_parsed_turn`.
    """
    patch: dict[str, Any] = {}
    for k in _ALLOWED:
        if k == "core_logic":
            continue
        b_val = baseline.get(k)
        e_val = effective.get(k)
        if b_val != e_val:
            patch[k] = copy.deepcopy(e_val)
    return patch


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
