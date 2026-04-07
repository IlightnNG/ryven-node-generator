"""Append-only JSONL session log for ReAct (debugging: full message flow + tool I/O)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate_field(s: str, max_chars: int) -> str:
    if max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n… [truncated, total {len(s)} chars]"


def serialize_message(m: Any, max_chars: int) -> dict[str, Any]:
    """Best-effort LangChain message → JSON-serializable dict."""
    name = m.__class__.__name__
    if name == "SystemMessage":
        return {"role": "system", "content": truncate_field(str(getattr(m, "content", "") or ""), max_chars)}
    if name == "HumanMessage":
        return {"role": "user", "content": truncate_field(str(getattr(m, "content", "") or ""), max_chars)}
    if name == "AIMessage":
        out: dict[str, Any] = {
            "role": "assistant",
            "content": truncate_field(str(getattr(m, "content", "") or ""), max_chars),
        }
        tc = getattr(m, "tool_calls", None)
        if tc:
            try:
                raw = json.dumps(tc, ensure_ascii=False)
            except Exception:
                raw = str(tc)
            out["tool_calls"] = truncate_field(raw, max_chars)
        return out
    if name == "ToolMessage":
        return {
            "role": "tool",
            "tool_call_id": getattr(m, "tool_call_id", None),
            "content": truncate_field(str(getattr(m, "content", "") or ""), max_chars),
        }
    return {
        "role": "unknown",
        "class": name,
        "content": truncate_field(str(getattr(m, "content", "") or ""), max_chars),
    }


def serialize_messages(messages: list[Any], max_chars: int) -> list[dict[str, Any]]:
    return [serialize_message(m, max_chars) for m in messages]


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def log_tool_round_trip(
    path: Path | None,
    *,
    session_id: str,
    step: int,
    tool: str,
    args: Any,
    tool_message_content: str,
    max_chars: int,
) -> None:
    """One line per tool call: args the model sent + exact string fed back as ToolMessage."""
    if not path:
        return
    try:
        args_s = json.dumps(args, ensure_ascii=False) if isinstance(args, dict) else str(args)
    except Exception:
        args_s = str(args)
    append_jsonl(
        path,
        {
            "event": "tool_round_trip",
            "ts": utc_iso(),
            "session_id": session_id,
            "step": step,
            "tool": tool,
            "args": truncate_field(args_s, max_chars),
            "tool_message_content": truncate_field(tool_message_content, max_chars),
        },
    )
