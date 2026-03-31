"""AI assistant internals: turn running pipeline and helper modules."""

from .client import build_chat_model
from .messages import history_to_messages, messages_for_stream
from .output_parser import (
    JSON_SEP,
    chunk_text,
    finalize_parsed_turn,
    invoke_structured_function_calling,
    invoke_structured_json_prompt,
)
from .turn_runner import run_assistant_turn, run_turn_respecting_stream_flag, stream_assistant_turn

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
