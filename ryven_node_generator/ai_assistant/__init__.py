"""Public API for the node AI assistant package.

Heavy deps (LangChain) load only when you access turn-runner symbols — keeps
`import ryven_node_generator.ai_assistant.json_parse` lightweight for tests.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AssistantTurn",
    "apply_config_patch",
    "json_list_diff_html",
    "node_changed_keys",
    "run_agent_session",
    "run_assistant_turn",
    "run_turn_respecting_stream_flag",
    "stream_assistant_turn",
]


def __getattr__(name: str) -> Any:
    if name == "AssistantTurn":
        from .schemas import AssistantTurn

        return AssistantTurn
    if name == "apply_config_patch":
        from .merge import apply_config_patch

        return apply_config_patch
    if name in ("json_list_diff_html", "node_changed_keys"):
        from . import preview_diff

        return getattr(preview_diff, name)
    if name == "run_agent_session":
        from .orchestration import run_agent_session

        return run_agent_session
    if name in ("run_assistant_turn", "run_turn_respecting_stream_flag", "stream_assistant_turn"):
        from .core import turn_runner

        return getattr(turn_runner, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
