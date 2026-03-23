"""LangChain: one structured turn for node assistance."""

from __future__ import annotations

import json
from typing import Any, Callable, Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from ai_assistant.config import (
    ai_stream_enabled,
    get_base_url,
    get_model_name,
    get_openai_api_key,
    get_temperature,
    load_env,
    use_json_prompt_for_structured,
)
from ai_assistant.json_parse import parse_assistant_turn_json
from ai_assistant.prompts import STREAM_FORMAT_SUFFIX, SYSTEM_PROMPT
from ai_assistant.schemas import AssistantTurn
from ai_assistant.validation import dedent_core_logic, validate_core_logic

load_env()

_JSON_FORMAT_SYSTEM = """Output a single JSON object only (no markdown fences, no extra prose).
Keys:
- "message": string, required — same language as you would use in chat: English by default; match Chinese (or other) if the user wrote in that language; honor explicit language requests.
- "core_logic": string or null — Python for the node try-block; English identifiers and comments by default unless the user asked otherwise. Non-null whenever behavior is requested.
- "config_patch": object or null — partial node config; null if unchanged. Prefer English for title/description/port labels unless the user asked otherwise.

Example: {"message":"OK.","core_logic":null,"config_patch":null}
Escape newlines and quotes inside strings."""

JSON_SEP = "<<<JSON>>>"


def _history_to_messages(
    system: str,
    pairs: Iterable[tuple[str, str]],
    user_text: str,
    context_json: str,
) -> list[BaseMessage]:
    out: list[BaseMessage] = [
        SystemMessage(content=system),
        SystemMessage(
            content=(
                "Current node JSON (authoritative for port indices and labels):\n```json\n"
                f"{context_json}\n```"
            )
        ),
    ]
    for role, text in pairs:
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=user_text))
    return out


def _messages_for_stream(
    pairs: Iterable[tuple[str, str]],
    user_text: str,
    context_json: str,
) -> list[BaseMessage]:
    out: list[BaseMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
        SystemMessage(
            content=(
                "Current node JSON (authoritative for port indices and labels):\n```json\n"
                f"{context_json}\n```"
            )
        ),
        SystemMessage(content=STREAM_FORMAT_SUFFIX),
    ]
    for role, text in pairs:
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=user_text))
    return out


def _build_chat_model() -> ChatOpenAI:
    api_key = get_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "API key missing. Set DASHSCOPE_API_KEY or OPENAI_API_KEY in Generator/.env. "
            "For Alibaba Bailian, set LLM_PROVIDER=dashscope or set OPENAI_BASE_URL to the compatible-mode endpoint."
        )

    base_url = get_base_url()
    kwargs: dict[str, Any] = {
        "model": get_model_name(),
        "temperature": get_temperature(),
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def _chunk_text(chunk: Any) -> str:
    c = getattr(chunk, "content", None)
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        parts: list[str] = []
        for block in c:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            else:
                parts.append(str(block))
        return "".join(parts)
    return str(c or "")


def _invoke_structured_function_calling(
    model: ChatOpenAI,
    messages: list[BaseMessage],
) -> AssistantTurn:
    structured = model.with_structured_output(AssistantTurn, method="function_calling")
    return structured.invoke(messages)


def _invoke_structured_json_prompt(model: ChatOpenAI, messages: list[BaseMessage]) -> AssistantTurn:
    if not messages or not isinstance(messages[-1], HumanMessage):
        raise RuntimeError("internal: last message must be HumanMessage")
    *rest, last_human = messages
    augmented = [
        *rest,
        SystemMessage(content=_JSON_FORMAT_SYSTEM),
        last_human,
    ]
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


def _finalize_parsed_turn(
    parsed: AssistantTurn,
    *,
    streamed_reply_plain: str = "",
) -> dict[str, Any]:
    msg = (parsed.message or "").strip()
    if not msg and streamed_reply_plain:
        msg = streamed_reply_plain.strip()

    raw_logic = parsed.core_logic
    if isinstance(raw_logic, str) and not raw_logic.strip():
        raw_logic = None
    if raw_logic is None and parsed.config_patch:
        cl = parsed.config_patch.get("core_logic")
        if isinstance(cl, str) and cl.strip():
            raw_logic = cl

    clean_patch: dict[str, Any] | None = None
    if parsed.config_patch:
        clean_patch = {k: v for k, v in parsed.config_patch.items() if k != "core_logic"}
        if not clean_patch:
            clean_patch = None

    out: dict[str, Any] = {
        "message": msg,
        "core_logic": None,
        "config_patch": clean_patch,
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


def stream_assistant_turn(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    on_reply_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Stream user-visible text before JSON_SEP; parse JSON for message / core_logic / config_patch."""
    model = _build_chat_model()

    ctx = {
        "node": current_node,
        "existing_class_names": existing_class_names,
    }
    context_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    messages = _messages_for_stream(history or [], user_text, context_json)

    all_text = ""
    reply_emitted_upto = 0
    json_start: int | None = None
    emitted_any = False

    def emit(s: str) -> None:
        nonlocal emitted_any
        if s:
            emitted_any = True
        if on_reply_delta:
            on_reply_delta(s)

    for chunk in model.stream(messages):
        t = _chunk_text(chunk)
        if not t:
            continue
        all_text += t
        if json_start is None:
            p = all_text.find(JSON_SEP)
            if p == -1:
                safe = len(all_text)
                max_k = min(len(JSON_SEP) - 1, len(all_text))
                for k in range(max_k, 0, -1):
                    if all_text[-k:] == JSON_SEP[:k]:
                        safe = len(all_text) - k
                        break
                if safe > reply_emitted_upto:
                    emit(all_text[reply_emitted_upto:safe])
                    reply_emitted_upto = safe
            else:
                if p > reply_emitted_upto:
                    emit(all_text[reply_emitted_upto:p])
                    reply_emitted_upto = p
                json_start = p + len(JSON_SEP)

    streamed_reply = ""
    if json_start is not None:
        streamed_reply = all_text[: all_text.find(JSON_SEP)].strip()
        json_raw = all_text[json_start:].strip()
    else:
        json_raw = all_text.strip()

    try:
        parsed = parse_assistant_turn_json(json_raw)
    except Exception:
        try:
            parsed = parse_assistant_turn_json(all_text)
        except Exception as e2:
            raise RuntimeError(
                f"Failed to parse model JSON. After the user-visible explanation, output a single line {JSON_SEP!r} "
                f"then one JSON object. Parse error: {e2}"
            ) from e2

    out = _finalize_parsed_turn(parsed, streamed_reply_plain=streamed_reply)
    out["_stream_had_visible_reply"] = emitted_any
    out["_streamed_reply_plain"] = streamed_reply
    return out


def run_assistant_turn(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
) -> dict[str, Any]:
    """Single non-streaming call when AI_STREAM=false."""
    model = _build_chat_model()

    ctx = {
        "node": current_node,
        "existing_class_names": existing_class_names,
    }
    context_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    messages = _history_to_messages(
        SYSTEM_PROMPT,
        history or [],
        user_text,
        context_json,
    )

    if use_json_prompt_for_structured():
        parsed = _invoke_structured_json_prompt(model, messages)
    else:
        parsed = _invoke_structured_function_calling(model, messages)

    return _finalize_parsed_turn(parsed)


def run_turn_respecting_stream_flag(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    on_reply_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Entry point for the UI: stream or not based on AI_STREAM."""
    if ai_stream_enabled():
        return stream_assistant_turn(
            user_text=user_text,
            current_node=current_node,
            existing_class_names=existing_class_names,
            history=history,
            on_reply_delta=on_reply_delta,
        )
    return run_assistant_turn(
        user_text=user_text,
        current_node=current_node,
        existing_class_names=existing_class_names,
        history=history,
    )
