"""AI assistant internals: turn running pipeline and helper modules.

Lazy exports so importing e.g. ``output_parser`` alone does not pull LangChain.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "JSON_SEP",
    "build_chat_model",
    "chunk_text",
    "finalize_parsed_turn",
    "history_to_messages",
    "invoke_structured_function_calling",
    "invoke_structured_json_prompt",
    "messages_for_stream",
    "run_assistant_turn",
    "run_turn_respecting_stream_flag",
    "stream_assistant_turn",
]


def __getattr__(name: str) -> Any:
    if name == "build_chat_model":
        from .client import build_chat_model

        return build_chat_model
    if name in ("history_to_messages", "messages_for_stream"):
        from . import messages

        return getattr(messages, name)
    if name in ("JSON_SEP", "chunk_text"):
        from ..contracts import streaming

        return getattr(streaming, name)
    if name == "finalize_parsed_turn":
        from .finalize_turn import finalize_parsed_turn

        return finalize_parsed_turn
    if name in ("invoke_structured_function_calling", "invoke_structured_json_prompt"):
        from . import output_parser

        return getattr(output_parser, name)
    if name in ("run_assistant_turn", "run_turn_respecting_stream_flag", "stream_assistant_turn"):
        from . import turn_runner

        return getattr(turn_runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
