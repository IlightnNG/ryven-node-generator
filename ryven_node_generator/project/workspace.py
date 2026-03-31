"""Project folder layout and load/save for IDE-style persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NODES_CONFIG_NAME = "nodes_config.json"
AI_CHAT_NAME = "generator_ai_chat.json"


def nodes_config_path(project_root: str | Path) -> Path:
    return Path(project_root) / NODES_CONFIG_NAME


def ai_chat_path(project_root: str | Path) -> Path:
    return Path(project_root) / AI_CHAT_NAME


def load_nodes_list(project_root: str | Path) -> list[dict[str, Any]]:
    p = nodes_config_path(project_root)
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"{NODES_CONFIG_NAME} root must be a JSON array.")
    return data


def save_nodes_list(project_root: str | Path, nodes_data: list[dict[str, Any]]) -> None:
    p = nodes_config_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(nodes_data, f, indent=4, ensure_ascii=False)


def load_ai_history(project_root: str | Path) -> list[tuple[str, str]]:
    """Returns list of (role, text) with role in ('user', 'assistant', 'system')."""
    p = ai_chat_path(project_root)
    if not p.is_file():
        return []
    with open(p, encoding="utf-8") as f:
        raw = json.load(f)
    if isinstance(raw, dict) and "turns" in raw:
        turns = raw["turns"]
    elif isinstance(raw, list):
        turns = raw
    else:
        return []
    out: list[tuple[str, str]] = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).lower()
        content = item.get("content", "")
        if role in ("user", "assistant", "system") and isinstance(content, str):
            out.append((role, content))
    return out


def save_ai_history(project_root: str | Path, history: list[tuple[str, str]]) -> None:
    p = ai_chat_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    turns = [{"role": r, "content": t} for r, t in history if r in ("user", "assistant", "system")]
    payload = {"version": 1, "turns": turns}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
