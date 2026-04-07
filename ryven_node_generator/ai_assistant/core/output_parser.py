"""Parse and validate model outputs into UI-consumable turn payloads.

Final dict keys consumed by the UI / ReAct orchestrator are documented in
docs/agent-refactor-roadmap-for-ai.md §0. Re-export JSON_SEP/chunk_text from contracts.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..contracts.streaming import JSON_SEP, chunk_text
from ..json_parse import parse_assistant_turn_json
from ..schemas import AssistantTurn
from .finalize_turn import finalize_parsed_turn

# Back-compat: historically imported from output_parser
__all__ = [
    "JSON_SEP",
    "chunk_text",
    "finalize_parsed_turn",
    "invoke_structured_function_calling",
    "invoke_structured_json_prompt",
]

_JSON_FORMAT_SYSTEM = """Output a single JSON object only (no markdown fences, no extra prose).
Keys:
- "message": string, required — same language as you would use in chat: English by default; match Chinese (or other) if the user wrote in that language; honor explicit language requests.
- "core_logic": string or null — Python for the node try-block; English identifiers and comments by default unless the user asked otherwise. Non-null whenever behavior is requested.
- "config_patch": object or null — partial node config; null if unchanged. Prefer English for title/description/port labels unless the user asked otherwise.
- "self_test_cases": array or null — optional tiny test cases. Each item can include "inputs", "expected_outputs", "note".

Example: {"message":"OK.","core_logic":null,"config_patch":null,"self_test_cases":null}
Escape newlines and quotes inside strings."""


def invoke_structured_function_calling(model: ChatOpenAI, messages: list[BaseMessage]) -> AssistantTurn:
    structured = model.with_structured_output(AssistantTurn, method="function_calling")
    return structured.invoke(messages)


def invoke_structured_json_prompt(model: ChatOpenAI, messages: list[BaseMessage]) -> AssistantTurn:
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise RuntimeError("internal: last message must be HumanMessage")

    *rest, last_human = messages
    augmented = [*rest, SystemMessage(content=_JSON_FORMAT_SYSTEM), last_human]

    resp = model.invoke(augmented)
    raw = resp.content
    if isinstance(raw, list):
        parts = []
        for block in raw:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
            else:
                parts.append(str(block))
        raw = "".join(parts)

    return parse_assistant_turn_json(str(raw))
