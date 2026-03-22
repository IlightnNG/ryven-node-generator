"""Structured model output for one assistant turn."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class AssistantTurn(BaseModel):
    """One model response: Chinese `message` for the user; English Python in `core_logic`."""

    message: str = Field(
        description="Short summary for chat history; MUST be Simplified Chinese, same as streamed text before <<<JSON>>>."
    )
    core_logic: Optional[str] = Field(
        default=None,
        description=(
            "Highest-priority field: Python body inside the try-block. English only. "
            "The template binds each data input as inK = self.get_input_val(K); inK is already the unwrapped value "
            "when upstream sends Data(payload). Use np.asarray(inK) for arrays; use widgets/literal_eval only when "
            "the port has a line_edit etc. Use self.set_output_val(j, Data(...)) for data outputs. "
            "Non-null whenever behavior is requested."
        ),
    )
    config_patch: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Partial node JSON. Include class_name when the Python class name in nodes.py should change. "
            "Keys: class_name, title, description, color, inputs, outputs, core_logic, "
            "has_main_widget, main_widget_template, main_widget_args, main_widget_pos, main_widget_code. "
            "Omit widget on data ports that only receive upstream Data. Null if no config change."
        ),
    )
