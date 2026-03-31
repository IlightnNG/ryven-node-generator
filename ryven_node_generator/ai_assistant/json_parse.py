"""Parse model plain-text JSON into AssistantTurn (DashScope / OpenAI-compatible)."""

from __future__ import annotations

import json
import re

from .schemas import AssistantTurn


def parse_assistant_turn_json(content: str) -> AssistantTurn:
    text = (content or "").strip()
    if not text:
        raise ValueError("Empty model response")

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE | re.MULTILINE)
        text = re.sub(r"\s*```\s*$", "", text, flags=re.MULTILINE).strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("No JSON object found in response")

    raw = text[start : end + 1]
    data = json.loads(raw)
    return AssistantTurn.model_validate(data)
