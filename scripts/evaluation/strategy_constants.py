"""Shared labels and ordering for strategy evaluation CSV + figures."""

from __future__ import annotations

# Six workflows: authoring surface (hand vs generator) × LLM / agent depth
WORKFLOWS: tuple[str, ...] = (
    "W1_hand_only",
    "W2_hand_chat",
    "W3_gen_chat",
    "W4_gen_single",
    "W5_gen_3stage",
    "W6_gen_react",
)

WORKFLOW_LABELS: dict[str, str] = {
    "W1_hand_only": "W1 Direct edit nodes/gui (no LLM)",
    "W2_hand_chat": "W2 Direct edit + plain LLM chat",
    "W3_gen_chat": "W3 Generator + plain LLM chat",
    "W4_gen_single": "W4 Generator + single-turn agent",
    "W5_gen_3stage": "W5 Generator + 3-stage pipeline",
    "W6_gen_react": "W6 Generator + ReAct tool loop",
}

WORKFLOW_COLORS: dict[str, str] = {
    "W1_hand_only": "#4E79A7",
    "W2_hand_chat": "#EDC948",
    "W3_gen_chat": "#FF9F40",
    "W4_gen_single": "#59A14F",
    "W5_gen_3stage": "#B279A2",
    "W6_gen_react": "#E15759",
}

# For factorial summaries / regression (optional columns in CSV)
USES_GENERATOR: dict[str, int] = {wf: (0 if wf in ("W1_hand_only", "W2_hand_chat") else 1) for wf in WORKFLOWS}


def task_band(task_id: str) -> str:
    n = int(task_id.replace("N", ""))
    if n <= 8:
        return "L1"
    if n <= 16:
        return "L2"
    return "L3"
