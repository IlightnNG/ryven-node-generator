"""Parse and validate model outputs into UI-consumable turn payloads."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ..json_parse import parse_assistant_turn_json
from ..schemas import AssistantTurn
from ..validation import dedent_core_logic, validate_core_logic


JSON_SEP = "<<<JSON>>>"

_JSON_FORMAT_SYSTEM = """Output a single JSON object only (no markdown fences, no extra prose).
Keys:
- "message": string, required — same language as you would use in chat: English by default; match Chinese (or other) if the user wrote in that language; honor explicit language requests.
- "core_logic": string or null — Python for the node try-block; English identifiers and comments by default unless the user asked otherwise. Non-null whenever behavior is requested.
- "config_patch": object or null — partial node config; null if unchanged. Prefer English for title/description/port labels unless the user asked otherwise.
- "self_test_cases": array or null — optional tiny test cases. Each item can include "inputs", "expected_outputs", "note".

Example: {"message":"OK.","core_logic":null,"config_patch":null,"self_test_cases":null}
Escape newlines and quotes inside strings."""


def chunk_text(chunk: Any) -> str:
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(content or "")


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


def finalize_parsed_turn(parsed: AssistantTurn, *, streamed_reply_plain: str = "") -> dict[str, Any]:
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
