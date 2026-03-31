"""Build LangChain messages for non-streaming and streaming turns."""

from __future__ import annotations

from typing import Iterable

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from ..prompts import STREAM_FORMAT_SUFFIX, SYSTEM_PROMPT


_CONTEXT_PREFIX = "Current node JSON (authoritative for port indices and labels):\n```json\n"
_CONTEXT_SUFFIX = "\n```"


def history_to_messages(
    *,
    system: str,
    pairs: Iterable[tuple[str, str]],
    user_text: str,
    context_json: str,
) -> list[BaseMessage]:
    out: list[BaseMessage] = [
        SystemMessage(content=system),
        SystemMessage(content=f"{_CONTEXT_PREFIX}{context_json}{_CONTEXT_SUFFIX}"),
    ]
    for role, text in pairs:
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=user_text))
    return out


def messages_for_stream(
    *,
    pairs: Iterable[tuple[str, str]],
    user_text: str,
    context_json: str,
) -> list[BaseMessage]:
    out: list[BaseMessage] = [
        SystemMessage(content=SYSTEM_PROMPT),
        SystemMessage(content=f"{_CONTEXT_PREFIX}{context_json}{_CONTEXT_SUFFIX}"),
        SystemMessage(content=STREAM_FORMAT_SUFFIX),
    ]
    for role, text in pairs:
        if role == "user":
            out.append(HumanMessage(content=text))
        elif role == "assistant":
            out.append(AIMessage(content=text))
    out.append(HumanMessage(content=user_text))
    return out
