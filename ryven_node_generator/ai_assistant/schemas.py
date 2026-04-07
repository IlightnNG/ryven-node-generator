"""Structured model output for one assistant turn.

This Pydantic model is the JSON contract for the final assistant payload.
UI and merge logic depend on these fields — see docs/agent-refactor-roadmap-for-ai.md §0.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AssistantTurn(BaseModel):
    """One model response: `message` follows user language (default English); `core_logic` prefers English unless user asked otherwise."""

    message: str = Field(
        description=(
            "Short summary for chat history; MUST match streamed text before <<<JSON>>>. "
            "English by default; use Chinese (or the user's language) when they wrote in that language; honor explicit language requests."
        )
    )
    core_logic: Optional[str] = Field(
        default=None,
        description=(
            "Highest-priority field: Python body inside the try-block. English identifiers and comments by default; "
            "another language only if the user explicitly requested it for code/comments. "
            "The generated nodes provide `self.get_input_val(K)` (returns the unwrapped payload when the wire carries "
            "`Data(payload)`). Therefore, `core_logic` should explicitly call `self.get_input_val(K)` for each data input "
            "index K, then optionally assign the value to a local variable with a meaningful name. "
            "For arrays use `np.asarray(value)`; for typed literals use `ast.literal_eval(str(value))` when the port has "
            "a `line_edit` widget. Use `self.set_output_val(j, Data(...))` for data outputs. "
            "Non-null whenever behavior is requested. For tool calls: use JSON null or omit when unchanged — never \"\"."
        ),
    )
    config_patch: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Partial node JSON. When inputs/outputs or titles change, include the **full** `inputs` and "
            "`outputs` arrays (all ports). Keys: class_name, title, description, color, inputs, outputs, "
            "core_logic, has_main_widget, main_widget_template, main_widget_args, main_widget_pos, "
            "main_widget_code. Omit widget on data-only ports. "
            "Null only when there is truly no structural/metadata change. "
            "Must be a JSON object or null when using tools — never an empty string."
        ),
    )
    self_test_cases: Optional[list[dict[str, Any]]] = Field(
        default=None,
        description=(
            "Optional lightweight test cases for core_logic self-check. "
            "Each item may contain: inputs (list or dict), expected_outputs (dict keyed by output index), "
            "and note (string). Keep cases small and deterministic. "
            "JSON array or null/omit — never \"\"."
        ),
    )
