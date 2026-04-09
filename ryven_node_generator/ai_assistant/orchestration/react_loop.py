"""ReAct-style agent loop: model ↔ tools until submit_node_turn (Claude Code–style tool loop)."""

from __future__ import annotations

import copy
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from ..config import (
    ai_agent_session_log_field_chars,
    ai_agent_session_log_path,
    ai_context_compact_node_json,
    default_agent_project_root,
    get_llm_request_timeout_sec,
    load_env,
)
from ..context_budget import build_node_context_json
from ..session_file_log import (
    append_jsonl,
    log_tool_round_trip,
    serialize_message,
    serialize_messages,
    utc_iso,
)
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

def _apply_compress_prior_turns(
    messages: list[Any],
    *,
    history_start_idx: int,
    current_user_msg_idx_ref: list[int],
    summary_of_older_turns: str,
    keep_last_messages: int,
) -> str:
    """Replace chat before the session user message: keep last N prior messages, prepend summary."""
    cur = current_user_msg_idx_ref[0]
    start = history_start_idx
    if cur <= start:
        return "[ok] nothing to compress (no prior turns)."
    region = messages[start:cur]
    if keep_last_messages > 0 and len(region) <= keep_last_messages:
        return (
            f"[ok] prior chat is short ({len(region)} messages ≤ keep_last_messages="
            f"{keep_last_messages}); nothing dropped."
        )
    if keep_last_messages <= 0:
        kept: list[Any] = []
    else:
        kept = region[-keep_last_messages:]
    header = "[Prior turns compressed — older messages replaced by the summary below]\n\n"
    replacement = [HumanMessage(content=header + summary_of_older_turns)] + kept
    old_len = len(region)
    new_len = len(replacement)
    delta = new_len - old_len
    messages[start:cur] = replacement
    current_user_msg_idx_ref[0] = cur + delta
    dropped = old_len - len(kept)
    return (
        f"[ok] compressed prior chat: dropped {dropped} older message(s); "
        f"kept {len(kept)} message(s) before the current user request."
    )


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
    """Normalize submit_node_turn args to satisfy AssistantTurn schema.

    Models sometimes send ``""`` for "no value"; Pydantic expects ``null``/omitted for optional
    dict/list fields — coerce empty strings and parse stringified JSON where needed.
    """
    if not isinstance(args, dict):
        return args
    out = dict(args)

    # core_logic: optional str — empty string means "no code change"
    if "core_logic" in out and isinstance(out.get("core_logic"), str) and not str(out["core_logic"]).strip():
        out["core_logic"] = None

    # config_patch: optional dict — never use "" (common provider mistake after shell-only turns)
    if "config_patch" in out:
        cp: Any = out.get("config_patch")
        if cp is None:
            pass
        elif isinstance(cp, str):
            s = cp.strip()
            if not s:
                out["config_patch"] = None
            else:
                parsed = _maybe_json_loads(cp)
                out["config_patch"] = parsed if isinstance(parsed, dict) else None
        elif isinstance(cp, dict):
            out["config_patch"] = cp
        else:
            out["config_patch"] = None

    # self_test_cases: optional list — same empty-string / string-JSON pattern
    if "self_test_cases" in out:
        st: Any = out.get("self_test_cases")
        if st is None:
            pass
        elif isinstance(st, str):
            s = st.strip()
            if not s:
                out["self_test_cases"] = None
            else:
                parsed = _maybe_json_loads(st)
                out["self_test_cases"] = parsed if isinstance(parsed, list) else None
        elif isinstance(st, list):
            out["self_test_cases"] = st
        else:
            out["self_test_cases"] = None

    return out


def _merge_core_logic_from_draft(turn: AssistantTurn, draft_node: dict[str, Any]) -> AssistantTurn:
    """If the model omitted core_logic on submit, inherit from the working draft."""
    if turn.core_logic is not None and str(turn.core_logic).strip():
        return turn
    cl = (draft_node.get("core_logic") or "").strip()
    if not cl:
        return turn
    return turn.model_copy(update={"core_logic": cl})


def _usage_delta_from_ai_message(ai: Any) -> tuple[int, int, int] | None:
    """Per-completion token counts from one ``model.invoke`` return value.

    Uses LangChain ``AIMessage.usage_metadata`` (input/output/total) or legacy
    ``response_metadata['token_usage']`` (prompt/completion/total). Returns
    ``None`` if the provider did not report usage for this call.
    """
    prompt: int | None = None
    completion: int | None = None
    total: int | None = None

    um = getattr(ai, "usage_metadata", None)
    if isinstance(um, dict):
        it = um.get("input_tokens")
        ot = um.get("output_tokens")
        tt = um.get("total_tokens")
        if isinstance(it, int):
            prompt = it
        if isinstance(ot, int):
            completion = ot
        if isinstance(tt, int):
            total = tt

    rm = getattr(ai, "response_metadata", None)
    if isinstance(rm, dict):
        tu = rm.get("token_usage")
        if isinstance(tu, dict):
            if prompt is None:
                p = tu.get("prompt_tokens")
                if isinstance(p, int):
                    prompt = p
            if completion is None:
                c = tu.get("completion_tokens")
                if isinstance(c, int):
                    completion = c
            if total is None:
                t = tu.get("total_tokens")
                if isinstance(t, int):
                    total = t

    if prompt is None and completion is None and total is None:
        return None
    p = int(prompt or 0)
    c = int(completion or 0)
    t = int(total) if total is not None else p + c
    return p, c, t


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

    context_json = build_node_context_json(
        draft_ref["node"],
        existing_class_names,
        compact=ai_context_compact_node_json(),
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

    history_list = history or []
    history_start_idx = 2
    current_user_msg_idx_ref = [history_start_idx + len(history_list)]

    log_path = ai_agent_session_log_path(str(root))
    field_chars = ai_agent_session_log_field_chars()
    session_log_id = uuid.uuid4().hex[:16]

    def _log_event(payload: dict[str, Any]) -> None:
        if not log_path:
            return
        payload.setdefault("session_id", session_log_id)
        payload.setdefault("ts", utc_iso())
        append_jsonl(log_path, payload)

    if log_path:
        _log_event(
            {
                "event": "session_start",
                "user_text": user_text,
                "project_root": str(root.resolve()),
                "history_turns": len(history or []),
                "messages": serialize_messages(messages, field_chars),
            }
        )

    trace: list[dict[str, Any]] = []
    shell_request_seq = 0
    last_step_tool_names: list[str] = []
    acc_prompt_tokens = 0
    acc_completion_tokens = 0
    acc_total_tokens = 0
    usage_reported_steps = 0
    nudge_default = (
        "You must use the provided tools only (no raw <<<JSON>>>). "
        "Pick tools by the user request: do not call read_project_file, apply_node_patch, "
        "validate_core_logic_tool, or run_stub_test unless that step is actually needed "
        "(e.g. read_file only when you need file contents; validate/stub only when core_logic changed). "
        "Finish with submit_node_turn."
    )
    nudge_after_validate_stub = (
        "You just ran validate_core_logic_tool and/or run_stub_test. "
        "Do NOT answer with plain assistant text only. "
        "Your NEXT message must be tool calls whose only node-final tool is submit_node_turn "
        "(put the full user-visible explanation in submit_node_turn.message; optional core_logic/config_patch). "
        "Do not emit a separate free-text-only turn before submit."
    )

    for step in range(1, max_steps + 1):
        if _stopped(should_stop):
            _log_event({"event": "session_end", "reason": "stopped_before_step", "step": step})
            raise GenerationStopped("stopped by user")

        if log_path:
            _log_event(
                {
                    "event": "llm_request",
                    "step": step,
                    "message_count": len(messages),
                    "messages": serialize_messages(messages, field_chars),
                }
            )

        if os.getenv("BENCHMARK_LLM_STEP_LOG", "").lower() in ("1", "true", "yes"):
            to = get_llm_request_timeout_sec()
            ts = f"{to:g}s" if to is not None else "none"
            print(
                f"[llm] ReAct step {step}/{max_steps} (HTTP timeout={ts}) …",
                flush=True,
                file=sys.stderr,
            )

        try:
            ai = model.invoke(messages)
        except Exception as exc:
            if log_path:
                _log_event({"event": "llm_invoke_error", "step": step, "error": repr(exc)})
            low = str(exc).lower()
            if "timeout" in low or "timed out" in low:
                raise RuntimeError(
                    f"LLM HTTP timeout or stall at ReAct step {step}/{max_steps}: {exc!r}. "
                    "Set a larger LLM_REQUEST_TIMEOUT in .env (seconds), or fix network/API."
                ) from exc
            raise

        if log_path:
            _log_event({"event": "llm_response", "step": step, "message": serialize_message(ai, field_chars)})

        usage_triple = _usage_delta_from_ai_message(ai)
        if usage_triple is not None:
            dp, dc, dt = usage_triple
            acc_prompt_tokens += dp
            acc_completion_tokens += dc
            acc_total_tokens += dt
            usage_reported_steps += 1

        if not getattr(ai, "tool_calls", None):
            messages.append(ai)
            nudge_text = (
                nudge_after_validate_stub
                if set(last_step_tool_names) & {"validate_core_logic_tool", "run_stub_test"}
                else nudge_default
            )
            messages.append(HumanMessage(content=nudge_text))
            trace.append({"step": step, "tools": [], "note": "no_tool_calls"})
            _log_event({"event": "no_tool_calls_nudge", "step": step})
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
        last_step_tool_names = tool_names

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
                    rej = (
                        f"submit_node_turn rejected: {exc}. Fix fields and call submit_node_turn again. "
                        "Tip: optional fields must match JSON types — use null or omit `config_patch` / "
                        "`self_test_cases` / `core_logic` when unused; never use empty string \"\" for them."
                    )
                    messages.append(ToolMessage(content=rej, tool_call_id=tid or "submit"))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="submit_node_turn",
                        args=args,
                        tool_message_content=rej,
                        max_chars=field_chars,
                    )
                else:
                    ok_msg = "Submission recorded."
                    messages.append(ToolMessage(content=ok_msg, tool_call_id=tid or "submit"))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="submit_node_turn",
                        args=args,
                        tool_message_content=ok_msg,
                        max_chars=field_chars,
                    )
                continue

            if name not in tool_map:
                unk = f"Unknown tool {name!r}."
                messages.append(ToolMessage(content=unk, tool_call_id=tid or name))
                log_tool_round_trip(
                    log_path,
                    session_id=session_log_id,
                    step=step,
                    tool=name or "unknown",
                    args=args,
                    tool_message_content=unk,
                    max_chars=field_chars,
                )
                continue

            if name == "compress_conversation_context":
                if not isinstance(args, dict):
                    args = {}
                summary = str(args.get("summary_of_older_turns") or "").strip()
                try:
                    keep = int(args.get("keep_last_messages", 8))
                except (TypeError, ValueError):
                    keep = 8
                keep = max(0, min(500, keep))
                if not summary:
                    err = (
                        "[error] compress_conversation_context requires non-empty "
                        "summary_of_older_turns (describe what you removed)."
                    )
                    messages.append(ToolMessage(content=err, tool_call_id=tid or name))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="compress_conversation_context",
                        args=args,
                        tool_message_content=err,
                        max_chars=field_chars,
                    )
                    continue
                if len(summary) > 48_000:
                    summary = summary[:48_000] + "\n[truncated]"
                result = _apply_compress_prior_turns(
                    messages,
                    history_start_idx=history_start_idx,
                    current_user_msg_idx_ref=current_user_msg_idx_ref,
                    summary_of_older_turns=summary,
                    keep_last_messages=keep,
                )
                messages.append(ToolMessage(content=result, tool_call_id=tid or name))
                log_tool_round_trip(
                    log_path,
                    session_id=session_log_id,
                    step=step,
                    tool="compress_conversation_context",
                    args=args,
                    tool_message_content=result,
                    max_chars=field_chars,
                )
                if on_progress:
                    on_progress({"type": "react_context_compressed", "step": step})
                continue

            # Manual shell execution gate (UI approval): ask user, then run one guarded command.
            if name == "run_shell":
                if not isinstance(args, dict):
                    rs_err = "[error] run_shell args must be an object."
                    messages.append(ToolMessage(content=rs_err, tool_call_id=tid or name))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="run_shell",
                        args=args,
                        tool_message_content=rs_err,
                        max_chars=field_chars,
                    )
                    continue
                cmd = str(args.get("command") or "").strip()
                shell_request_seq += 1
                request_id = f"shell_req_{step}_{shell_request_seq}"

                if shell_approval_controller is None:
                    sh_err = "[error] shell approval controller missing; cannot run shell safely."
                    messages.append(ToolMessage(content=sh_err, tool_call_id=tid or name))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="run_shell",
                        args=args,
                        tool_message_content=sh_err,
                        max_chars=field_chars,
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
                    can_msg = "Shell cancelled by user."
                    messages.append(ToolMessage(content=can_msg, tool_call_id=tid or name))
                    log_tool_round_trip(
                        log_path,
                        session_id=session_log_id,
                        step=step,
                        tool="run_shell",
                        args=args,
                        tool_message_content=can_msg,
                        max_chars=field_chars,
                    )
                    continue

            try:
                result = tool_map[name].invoke(args)
            except Exception as exc:
                result = f"Tool error: {exc}"
            content = result if isinstance(result, str) else str(result)
            capped = content[:120_000]
            messages.append(ToolMessage(content=capped, tool_call_id=tid or name))
            log_tool_round_trip(
                log_path,
                session_id=session_log_id,
                step=step,
                tool=name,
                args=args,
                tool_message_content=capped,
                max_chars=field_chars,
            )
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
            _log_event(
                {
                    "event": "session_end",
                    "ok": True,
                    "step": step,
                    "message_preview": (turn.message or "")[:4000],
                    "llm_prompt_tokens": acc_prompt_tokens if usage_reported_steps else None,
                    "llm_completion_tokens": acc_completion_tokens if usage_reported_steps else None,
                    "llm_total_tokens": acc_total_tokens if usage_reported_steps else None,
                    "llm_usage_steps": usage_reported_steps,
                }
            )
            if usage_reported_steps:
                out["llm_prompt_tokens"] = acc_prompt_tokens
                out["llm_completion_tokens"] = acc_completion_tokens
                out["llm_total_tokens"] = acc_total_tokens
                out["llm_usage_steps"] = usage_reported_steps
            else:
                out["llm_prompt_tokens"] = None
                out["llm_completion_tokens"] = None
                out["llm_total_tokens"] = None
                out["llm_usage_steps"] = 0
            return out

    _log_event({"event": "session_end", "ok": False, "reason": "max_steps", "max_steps": max_steps})
    out_fail: dict[str, Any] = {
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
    if usage_reported_steps:
        out_fail["llm_prompt_tokens"] = acc_prompt_tokens
        out_fail["llm_completion_tokens"] = acc_completion_tokens
        out_fail["llm_total_tokens"] = acc_total_tokens
        out_fail["llm_usage_steps"] = usage_reported_steps
    else:
        out_fail["llm_prompt_tokens"] = None
        out_fail["llm_completion_tokens"] = None
        out_fail["llm_total_tokens"] = None
        out_fail["llm_usage_steps"] = 0
    return out_fail
