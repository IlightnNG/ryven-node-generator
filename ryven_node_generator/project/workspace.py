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


def normalize_ai_turn(entry: tuple[str, ...] | list[Any]) -> tuple[str, str, dict[str, Any]]:
    """Normalize stored chat entries to (role, content, meta). Meta is {} except user context fields."""
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        role, content = str(entry[0]), str(entry[1])
        if role in ("user", "assistant", "system"):
            return role, content, {}
    if isinstance(entry, (list, tuple)) and len(entry) >= 3:
        role, content = str(entry[0]), str(entry[1])
        meta = entry[2] if isinstance(entry[2], dict) else {}
        if role in ("user", "assistant", "system"):
            return role, content, dict(meta)
    return "system", "", {}


def ai_history_for_llm(history: list[tuple[str, ...]]) -> list[tuple[str, str]]:
    """Strip metadata for LangChain message building."""
    out: list[tuple[str, str]] = []
    for item in history:
        role, text, _meta = normalize_ai_turn(item)
        if role in ("user", "assistant", "system") and text is not None:
            out.append((role, text))
    return out


def load_ai_history(project_root: str | Path) -> list[tuple[str, str, dict[str, Any]]]:
    """Returns list of (role, text, meta)."""
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
    out: list[tuple[str, str, dict[str, Any]]] = []
    for item in turns:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "")).lower()
        content = item.get("content", "")
        if role not in ("user", "assistant", "system") or not isinstance(content, str):
            continue
        meta: dict[str, Any] = {}
        if role == "user":
            for key in (
                "context_node_idx",
                "context_node_uid",
                "context_class_name",
                "context_title",
                "snapshot_node",
                "snapshot_node_uid",
                "snapshot_nodes",
            ):
                if key in item:
                    meta[key] = item[key]
        out.append((role, content, meta))
    return out


def save_ai_history(project_root: str | Path, history: list[tuple[str, ...]]) -> None:
    p = ai_chat_path(project_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    turns: list[dict[str, Any]] = []
    for item in history:
        role, text, meta = normalize_ai_turn(item)
        if role not in ("user", "assistant", "system"):
            continue
        row: dict[str, Any] = {"role": role, "content": text}
        if role == "user" and meta:
            for key in (
                "context_node_idx",
                "context_node_uid",
                "context_class_name",
                "context_title",
                "snapshot_node",
                "snapshot_node_uid",
                "snapshot_nodes",
            ):
                if key in meta:
                    row[key] = meta[key]
        turns.append(row)
    payload = {"version": 1, "turns": turns}
    with open(p, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
