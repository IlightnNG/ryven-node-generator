"""Turn payload normalization (no LangChain — safe for contract unit tests)."""

from __future__ import annotations

from typing import Any

from ..schemas import AssistantTurn
from ..validation import dedent_core_logic, validate_core_logic


def finalize_parsed_turn(parsed: AssistantTurn, *, streamed_reply_plain: str = "") -> dict[str, Any]:
    """Build the UI-facing dict from a parsed :class:`AssistantTurn`.

    Keys: message, core_logic, config_patch, self_test_cases, validation_error.
    See docs/agent-refactor-roadmap-for-ai.md §0.
    """
    message = (parsed.message or "").strip()
    if not message and streamed_reply_plain:
        message = streamed_reply_plain.strip()

    raw_logic = parsed.core_logic
    if isinstance(raw_logic, str) and not raw_logic.strip():
        raw_logic = None
    if raw_logic is None and parsed.config_patch:
        candidate = parsed.config_patch.get("core_logic")
        if isinstance(candidate, str) and candidate.strip():
            raw_logic = candidate

    clean_patch: dict[str, Any] | None = None
    if parsed.config_patch:
        clean_patch = {k: v for k, v in parsed.config_patch.items() if k != "core_logic"}
        if not clean_patch:
            clean_patch = None

    out: dict[str, Any] = {
        "message": message,
        "core_logic": None,
        "config_patch": clean_patch,
        "self_test_cases": parsed.self_test_cases or [],
        "validation_error": None,
    }

    if raw_logic is not None and str(raw_logic).strip():
        logic = dedent_core_logic(str(raw_logic))
        ok, err = validate_core_logic(logic)
        if ok:
            out["core_logic"] = logic
        else:
            out["validation_error"] = err
            out["message"] += f"\n\n(core_logic validation failed: {err})"

    return out
