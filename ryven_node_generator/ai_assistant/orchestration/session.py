"""Single entry for AI agent runs (orchestrator)."""

from __future__ import annotations

from typing import Any, Callable

from ..config import (
    ai_agent_max_steps,
    ai_agent_mode,
    ai_context_max_chars_per_message,
    ai_context_max_user_assistant_messages,
)
from ..context_budget import trim_history_pairs, truncate_history_message_texts

ProgressCallback = Callable[[dict[str, Any]], None]
DeltaCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


def run_agent_session(
    *,
    user_text: str,
    current_node: dict[str, Any],
    existing_class_names: list[str],
    history: list[tuple[str, str]] | None = None,
    project_root: str | None = None,
    on_progress: ProgressCallback | None = None,
    on_reply_delta: DeltaCallback | None = None,
    should_stop: StopCallback | None = None,
    shell_approval_controller: Any | None = None,
) -> dict[str, Any]:
    """Run one user-visible AI session.

    - ``AI_AGENT_MODE=react`` (default): ReAct tool loop until ``submit_node_turn``.
    - ``AI_AGENT_MODE=legacy``: single turn via ``run_turn_respecting_stream_flag`` (<<<JSON>>> / structured output).

    ``project_root`` scopes read/write/run_shell tools to the open workspace; if ``None``, the generator repo root is used.

    Returned dict matches :func:`~ryven_node_generator.ai_assistant.core.finalize_turn.finalize_parsed_turn`
    plus optional ``react_trace``, ``repair_trace``, ``_streamed_reply_plain``.
    """
    mode = ai_agent_mode()
    history = trim_history_pairs(
        history, max_user_assistant_messages=ai_context_max_user_assistant_messages()
    )
    history = truncate_history_message_texts(
        history, max_chars_per_message=ai_context_max_chars_per_message()
    )
    if on_progress:
        on_progress({"phase": "session", "detail": "begin", "engine": mode})

    if mode == "legacy":
        from ..core.turn_runner import run_turn_respecting_stream_flag

        out = run_turn_respecting_stream_flag(
            user_text=user_text,
            current_node=current_node,
            existing_class_names=existing_class_names,
            history=history,
            on_reply_delta=on_reply_delta,
        )
        out.setdefault("repair_trace", [])
        out.setdefault("react_trace", [])
        out.setdefault("repair_round", 1)
        return out

    from .react_loop import run_react_session

    return run_react_session(
        user_text=user_text,
        current_node=current_node,
        existing_class_names=existing_class_names,
        history=history,
        project_root=project_root,
        on_progress=on_progress,
        on_reply_delta=on_reply_delta,
        should_stop=should_stop,
        shell_approval_controller=shell_approval_controller,
        max_steps=ai_agent_max_steps(),
    )
