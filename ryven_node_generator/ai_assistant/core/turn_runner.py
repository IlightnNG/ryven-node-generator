"""Run one assistant turn (streaming or non-streaming)."""

from __future__ import annotations

import json
from typing import Any, Callable

from ..config import ai_stream_enabled, load_env, use_json_prompt_for_structured
from ..prompts import SYSTEM_PROMPT
from .client import build_chat_model
from .messages import history_to_messages, messages_for_stream
from .output_parser import (
    JSON_SEP,
    chunk_text,
    finalize_parsed_turn,
    invoke_structured_function_calling,
    invoke_structured_json_prompt,
)
from ..json_parse import parse_assistant_turn_json

load_env()


def stream_assistant_turn(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    on_reply_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Stream user-visible text before JSON_SEP; parse JSON payload at the end."""
    model = build_chat_model()

    context_json = json.dumps(
        {"node": current_node, "existing_class_names": existing_class_names},
        ensure_ascii=False,
        indent=2,
    )
    messages = messages_for_stream(pairs=history or [], user_text=user_text, context_json=context_json)

    all_text = ""
    emitted_upto = 0
    json_start: int | None = None
    emitted_any = False

    def emit(chunk: str) -> None:
        nonlocal emitted_any
        if chunk:
            emitted_any = True
        if on_reply_delta:
            on_reply_delta(chunk)

    for stream_chunk in model.stream(messages):
        text = chunk_text(stream_chunk)
        if not text:
            continue

        all_text += text
        if json_start is None:
            pos = all_text.find(JSON_SEP)
            if pos == -1:
                safe = len(all_text)
                max_k = min(len(JSON_SEP) - 1, len(all_text))
                for k in range(max_k, 0, -1):
                    if all_text[-k:] == JSON_SEP[:k]:
                        safe = len(all_text) - k
                        break
                if safe > emitted_upto:
                    emit(all_text[emitted_upto:safe])
                    emitted_upto = safe
            else:
                if pos > emitted_upto:
                    emit(all_text[emitted_upto:pos])
                    emitted_upto = pos
                json_start = pos + len(JSON_SEP)

    streamed_reply = ""
    if json_start is not None:
        sep_pos = all_text.find(JSON_SEP)
        streamed_reply = all_text[:sep_pos].strip()
        json_raw = all_text[json_start:].strip()
    else:
        json_raw = all_text.strip()

    try:
        parsed = parse_assistant_turn_json(json_raw)
    except Exception:
        try:
            parsed = parse_assistant_turn_json(all_text)
        except Exception as parse_err:
            raise RuntimeError(
                f"Failed to parse model JSON. After the user-visible explanation, output a single line {JSON_SEP!r} "
                f"then one JSON object. Parse error: {parse_err}"
            ) from parse_err

    out = finalize_parsed_turn(parsed, streamed_reply_plain=streamed_reply)
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
    model = build_chat_model()

    context_json = json.dumps(
        {"node": current_node, "existing_class_names": existing_class_names},
        ensure_ascii=False,
        indent=2,
    )
    messages = history_to_messages(
        system=SYSTEM_PROMPT,
        pairs=history or [],
        user_text=user_text,
        context_json=context_json,
    )

    if use_json_prompt_for_structured():
        parsed = invoke_structured_json_prompt(model, messages)
    else:
        parsed = invoke_structured_function_calling(model, messages)

    return finalize_parsed_turn(parsed)


def run_turn_respecting_stream_flag(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    on_reply_delta: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """UI entrypoint: choose stream or non-stream based on AI_STREAM."""
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
