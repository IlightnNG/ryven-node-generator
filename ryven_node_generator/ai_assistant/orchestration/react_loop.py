"""ReAct-style agent loop: model ↔ tools until submit_node_turn (Claude Code–style tool loop)."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..config import default_agent_project_root, load_env
from ..core.client import build_chat_model
from ..core.finalize_turn import finalize_parsed_turn
from ..exceptions import GenerationStopped
from ..merge import apply_config_patch, whitelisted_config_diff
from ..prompts import REACT_TOOL_INSTRUCTIONS, SYSTEM_PROMPT
from ..schemas import AssistantTurn
from ..tools import ReactToolHost, build_langchain_tools
from ..validation import dedent_core_logic

load_env()

ProgressCallback = Callable[[dict[str, Any]], None]
DeltaCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


def _stopped(should_stop: StopCallback | None) -> bool:
    return bool(should_stop and should_stop())


def _parse_tool_args(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    # Some tool-call payloads may carry args as JSON string.
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}

def _preview_text(x: Any, *, max_chars: int = 360) -> str:
    t = str(x if x is not None else "").replace("\r", "\n").strip()
    # Keep up to ~3 visible lines in UI bubbles.
    lines = [ln.strip() for ln in t.split("\n")]
    lines = [ln for ln in lines if ln]
    t = "\n".join(lines[:3])
    if len(t) > max_chars:
        return t[: max_chars - 1] + "…"
    return t


def _extract_tool_args(tc: dict[str, Any]) -> Any:
    """LangChain tool_call dicts vary a bit across backends.

    Prefer common keys; fall back to empty dict.
    """
    if not isinstance(tc, dict):
        return {}
    return (
        tc.get("args")
        or tc.get("arguments")
        or tc.get("input")
        or tc.get("tool_input")
        or tc.get("parameters")
        or {}
    )


def _maybe_json_loads(x: Any) -> Any:
    """If `x` is a JSON-encoded string, parse it.

    This makes submit_node_turn more robust against model mistakes where a
    dict field (e.g. `config_patch`) is passed as a stringified JSON.
    """
    if not isinstance(x, str):
        return x
    s = x.strip()
    if not s:
        return x
    # If the model wraps JSON into fences or adds surrounding text, extract the
    # first {...} or [...] substring first.
    first_obj = s.find("{")
    first_arr = s.find("[")
    start = min(first_obj if first_obj != -1 else 10**9, first_arr if first_arr != -1 else 10**9)
    if start == 10**9:
        return x
    if s[start] not in "{[":
        return x
    end = s.rfind("}") if s[start] == "{" else s.rfind("]")
    if end == -1 or end <= start:
        return x
    candidate = s[start : end + 1]
    try:
        return json.loads(candidate)
    except Exception:
        return x


def _normalize_submit_turn_args(args: Any) -> Any:
    """Normalize submit_node_turn args to satisfy AssistantTurn schema."""
    if not isinstance(args, dict):
        return args
    out = dict(args)
    if "config_patch" in out:
        out["config_patch"] = _maybe_json_loads(out.get("config_patch"))
    if "self_test_cases" in out:
        out["self_test_cases"] = _maybe_json_loads(out.get("self_test_cases"))
    return out


def _merge_core_logic_from_draft(turn: AssistantTurn, draft_node: dict[str, Any]) -> AssistantTurn:
    """If the model omitted core_logic on submit, inherit from the working draft."""
    if turn.core_logic is not None and str(turn.core_logic).strip():
        return turn
    cl = (draft_node.get("core_logic") or "").strip()
    if not cl:
        return turn
    return turn.model_copy(update={"core_logic": cl})


def _finalize_submit_turn(
    turn: AssistantTurn,
    draft_node: dict[str, Any],
    baseline_node: dict[str, Any],
) -> AssistantTurn:
    """Merge submit args with the tool draft so the UI gets a full config patch (not only core_logic).

    Builds an effective node = draft + submit ``config_patch``, then top-level ``core_logic`` wins.
    ``config_patch`` on the returned turn is the whitelisted diff vs ``baseline_node`` (session start).
    """
    turn = _merge_core_logic_from_draft(turn, draft_node)
    effective = copy.deepcopy(draft_node)
    if turn.config_patch:
        apply_config_patch(effective, dict(turn.config_patch))
    if turn.core_logic is not None and str(turn.core_logic).strip():
        effective["core_logic"] = dedent_core_logic(str(turn.core_logic))
    synthetic = whitelisted_config_diff(baseline_node, effective)
    return turn.model_copy(update={"config_patch": synthetic if synthetic else None})


def run_react_session(
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
    max_steps: int = 24,
) -> dict[str, Any]:
    """Multi-step tool loop; exit when model calls ``submit_node_turn`` with valid :class:`AssistantTurn` args."""
    if _stopped(should_stop):
        raise GenerationStopped("stopped by user")

    root = Path(project_root).expanduser() if project_root else default_agent_project_root()
    baseline_node = copy.deepcopy(current_node)
    draft_ref: dict[str, Any] = {"node": copy.deepcopy(current_node)}
    host = ReactToolHost(
        project_root=root,
        draft_ref=draft_ref,
        existing_class_names=list(existing_class_names),
    )
    tools = build_langchain_tools(host)
    model = build_chat_model().bind_tools(tools)

    context_json = json.dumps(
        {"node": draft_ref["node"], "existing_class_names": existing_class_names},
        ensure_ascii=False,
        indent=2,
    )
    messages: list[Any] = [
        SystemMessage(content=SYSTEM_PROMPT + "\n\n" + REACT_TOOL_INSTRUCTIONS),
        SystemMessage(
            content="Current node JSON (authoritative for port indices and labels):\n```json\n"
            + context_json
            + "\n```\nTool filesystem root for read/write/run_shell: "
            + str(root.resolve())
        ),
    ]
    for item in history or []:
        role, text = item[0], item[1]
        if role == "user":
            messages.append(HumanMessage(content=text))
        elif role == "assistant":
            messages.append(AIMessage(content=text))
    messages.append(HumanMessage(content=user_text))

    trace: list[dict[str, Any]] = []
    shell_request_seq = 0
    nudge = (
        "You must use the provided tools only (no raw <<<JSON>>>). "
        "Use read_project_file / apply_node_patch / validate_core_logic_tool / run_stub_test as needed; "
        "run_shell only if enabled. Finish with submit_node_turn."
    )

    for step in range(1, max_steps + 1):
        if _stopped(should_stop):
            raise GenerationStopped("stopped by user")

        ai = model.invoke(messages)
        if not getattr(ai, "tool_calls", None):
            messages.append(ai)
            messages.append(HumanMessage(content=nudge))
            trace.append({"step": step, "tools": [], "note": "no_tool_calls"})
            continue

        assistant_text = ""
        try:
            assistant_text = _preview_text(getattr(ai, "content", "") or "", max_chars=220)
        except Exception:
            assistant_text = ""

        tool_names = [str(tc.get("name", "")) for tc in ai.tool_calls]
        if on_progress:
            on_progress(
                {
                    "type": "react_step",
                    "step": step,
                    "tools": tool_names,
                    "assistant_text": assistant_text,
                }
            )
        trace.append({"step": step, "tools": tool_names})

        messages.append(ai)
        tool_map = {t.name: t for t in tools}

        submit_turn: AssistantTurn | None = None
        for tc in ai.tool_calls:
            tid = str(tc.get("id") or tc.get("tool_call_id") or "")
            name = str(tc.get("name") or tc.get("tool") or "")
            args_raw = _extract_tool_args(tc)
            args = _parse_tool_args(args_raw)

            if on_progress and name and name != "submit_node_turn":
                keys_preview = []
                if isinstance(args, dict):
                    keys_preview = list(args.keys())[:10]
                on_progress(
                    {
                        "type": "react_tool_call",
                        "step": step,
                        "tool": name,
                        "args_preview": keys_preview or _preview_text(args_raw, max_chars=220),
                    }
                )

            if name == "submit_node_turn":
                try:
                    args_norm = _normalize_submit_turn_args(args)
                    submit_turn = AssistantTurn.model_validate(args_norm)
                except Exception as exc:
                    if on_progress:
                        on_progress(
                            {
                                "type": "react_submit_rejected",
                                "step": step,
                                "error": str(exc),
                                "args_preview": _preview_text(args_raw, max_chars=500),
                            }
                        )
                    messages.append(
                        ToolMessage(
                            content=f"submit_node_turn rejected: {exc}. Fix fields and call submit_node_turn again.",
                            tool_call_id=tid or "submit",
                        )
                    )
                else:
                    messages.append(ToolMessage(content="Submission recorded.", tool_call_id=tid or "submit"))
                continue

            if name not in tool_map:
                messages.append(ToolMessage(content=f"Unknown tool {name!r}.", tool_call_id=tid or name))
                continue

            # Manual shell execution gate (UI approval): ask user, then run one guarded command.
            if name == "run_shell":
                if not isinstance(args, dict):
                    messages.append(
                        ToolMessage(content="[error] run_shell args must be an object.", tool_call_id=tid or name)
                    )
                    continue
                cmd = str(args.get("command") or "").strip()
                shell_request_seq += 1
                request_id = f"shell_req_{step}_{shell_request_seq}"

                if shell_approval_controller is None:
                    messages.append(
                        ToolMessage(
                            content="[error] shell approval controller missing; cannot run shell safely.",
                            tool_call_id=tid or name,
                        )
                    )
                    continue

                shell_approval_controller.begin(request_id)
                if on_progress:
                    on_progress(
                        {
                            "type": "react_shell_request",
                            "step": step,
                            "request_id": request_id,
                            "command": cmd,
                        }
                    )
                approved = shell_approval_controller.wait_approved(
                    request_id, should_stop=should_stop
                )
                if not approved:
                    messages.append(
                        ToolMessage(content="Shell cancelled by user.", tool_call_id=tid or name)
                    )
                    continue

            try:
                result = tool_map[name].invoke(args)
            except Exception as exc:
                result = f"Tool error: {exc}"
            content = result if isinstance(result, str) else str(result)
            messages.append(ToolMessage(content=content[:120_000], tool_call_id=tid or name))
            if on_progress:
                on_progress(
                    {
                        "type": "react_tool_result",
                        "step": step,
                        "tool": name,
                        "result_preview": _preview_text(content, max_chars=600),
                    }
                )

        if submit_turn is not None:
            turn = _finalize_submit_turn(submit_turn, draft_ref["node"], baseline_node)
            out = finalize_parsed_turn(turn)
            out.setdefault("repair_trace", trace)
            out["react_trace"] = trace
            out["repair_round"] = step
            out.setdefault("_stream_had_visible_reply", False)
            out.setdefault("_streamed_reply_plain", (turn.message or "").strip())
            if on_reply_delta and turn.message:
                on_reply_delta(turn.message + "\n")
            return out

    return {
        "message": f"ReAct stopped after {max_steps} model steps without a successful submit_node_turn. "
        "Try simplifying the request or increase AI_AGENT_MAX_STEPS.",
        "core_logic": None,
        "config_patch": None,
        "self_test_cases": [],
        "validation_error": "react_max_steps",
        "repair_trace": trace,
        "react_trace": trace,
        "repair_round": max_steps,
    }
