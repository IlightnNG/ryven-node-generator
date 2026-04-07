"""Orchestration: ReAct session and legacy single-turn entry."""

from __future__ import annotations

from typing import Any

from .session import run_agent_session

__all__ = ["run_agent_session", "run_react_session"]


def __getattr__(name: str) -> Any:
    if name == "run_react_session":
        from .react_loop import run_react_session

        return run_react_session
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(__all__)
