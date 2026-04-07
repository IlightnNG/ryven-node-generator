"""Trim chat history and build compact node JSON for LLM context (token budget)."""

from __future__ import annotations

import json
from typing import Any


def trim_history_pairs(
    history: list[tuple[str, str]] | None,
    *,
    max_user_assistant_messages: int,
) -> list[tuple[str, str]]:
    """Keep only user/assistant turns (same roles the API uses), then the last *max* items.

    ``max_user_assistant_messages <= 0`` means no limit (full history).
    UI ``system`` rows are dropped here — they were never sent to the model in ReAct anyway.
    """
    if not history:
        return []
    pairs = [(r, t) for r, t in history if r in ("user", "assistant")]
    if max_user_assistant_messages <= 0 or len(pairs) <= max_user_assistant_messages:
        return pairs
    return pairs[-max_user_assistant_messages:]


def truncate_history_message_texts(
    history: list[tuple[str, str]],
    *,
    max_chars_per_message: int,
) -> list[tuple[str, str]]:
    """Truncate each message body when longer than ``max_chars_per_message``.

    ``max_chars_per_message <= 0`` means no truncation (pass-through).
    """
    if not history or max_chars_per_message <= 0:
        return list(history) if history else []
    suffix = "\n\n[truncated: AI_CONTEXT_MAX_CHARS_PER_MESSAGE]"
    out: list[tuple[str, str]] = []
    cap = max_chars_per_message
    for role, text in history:
        if len(text) <= cap:
            out.append((role, text))
            continue
        budget = max(0, cap - len(suffix))
        out.append((role, text[:budget] + suffix))
    return out


def build_node_context_json(
    node: dict[str, Any],
    existing_class_names: list[str],
    *,
    compact: bool,
) -> str:
    """Serialize current node + class names for the second system message."""
    payload = {"node": node, "existing_class_names": list(existing_class_names)}
    if compact:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(payload, ensure_ascii=False, indent=2)
