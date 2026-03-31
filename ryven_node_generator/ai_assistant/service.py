"""Back-compat service facade.

Historically callers imported assistant turn functions from this module.
The implementation now lives in `ai_assistant.core`.
"""

from .core.turn_runner import (
    run_assistant_turn,
    run_turn_respecting_stream_flag,
    stream_assistant_turn,
)

__all__ = [
    "run_assistant_turn",
    "run_turn_respecting_stream_flag",
    "stream_assistant_turn",
]
