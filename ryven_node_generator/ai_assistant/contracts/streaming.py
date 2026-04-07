"""Stream chunk helpers and protocol constants for the assistant.

See docs/agent-refactor-roadmap-for-ai.md §0 — UI depends on JSON_SEP streaming split.
"""

from __future__ import annotations

from typing import Any

# Text before this separator is user-visible; after it, one JSON object (AssistantTurn).
JSON_SEP = "<<<JSON>>>"


def chunk_text(chunk: Any) -> str:
    """Extract text from a LangChain stream chunk (str, list of blocks, or other)."""
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
