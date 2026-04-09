"""
Run **real** W4 / W5 / W6 benchmark trials against the 20 tasks in
`data/node_tasks_bench_sat_ml_v1.json` (satellite / TF / PyTorch spec from
`node_tasks_bench_sat_ml_en.md`; override with ``--tasks-json``): each trial calls the same ReAct entrypoint as the
desktop app (`run_react_session`), records wall-clock minutes, and scores `core_logic`
with `evaluate_stub_cases` (demo + robust columns in the CSV).

This is **not** a human study: it is an automated API benchmark (real LLM + real
timings + deterministic stub checks). For thesis text, describe it as such; do not
present it as measured end-user lab sessions.

Outputs:
  - Tidy CSV rows compatible with `plot_strategy_results.py` (same core columns as the
    Monte Carlo script, plus token usage: ``tokens_prompt``, ``tokens_completion``,
    ``tokens_total``, ``usage_steps`` when the chat API reports usage via LangChain).
  - `w456_benchmark_manifest.json` with model/env hints and git revision.

W4: one ReAct session, low `max_steps` (single-turn–style agent).
W5: three sequential ReAct sessions (skeleton → ports → logic → hardening prompts).
W6: one ReAct session, higher `max_steps`.

Usage (from repo root, with API keys in `.env`):
  python scripts/evaluation/run_w456_benchmark.py --runs 3
  python scripts/evaluation/run_w456_benchmark.py --dry-run --task-ids N01,N02

Incremental result file (one task per run, append rows).
  Use a **dedicated** CSV for W4–W6 only (e.g. result_w456.csv), not the full six-workflow simulated export.
  PowerShell: define the path first, or use equals form so -o is not glued to --append:
    $R = "scripts/evaluation/data/result_w456.csv"
    python scripts/evaluation/run_w456_benchmark.py --out-csv=$R --append --task-ids N01 --runs 3
  python scripts/evaluation/run_w456_benchmark.py -o scripts/evaluation/data/result_w456.csv --append \\
      --task-ids N01 --runs 3
  python scripts/evaluation/run_w456_benchmark.py -o scripts/evaluation/data/result_w456.csv --append \\
      --task-ids N02 --runs 3
  # Re-run the same task and overwrite its old rows only:
  python scripts/evaluation/run_w456_benchmark.py -o scripts/evaluation/data/result.csv --append \\
      --replace-existing-tasks --task-ids N01 --runs 3

Hybrid CSV for six-workflow plots (simulated W1–W3 + all real rows in -o):
  python scripts/evaluation/run_w456_benchmark.py --merge-hybrid
  python scripts/evaluation/run_w456_benchmark.py -o scripts/evaluation/data/result.csv --append \\
      --task-ids N03 --runs 3 --merge-hybrid
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Repo root on sys.path for `ryven_node_generator`
_EVAL_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _EVAL_DIR.parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ryven_node_generator.ai_assistant.core.stub_runner import evaluate_stub_cases, normalize_test_cases
from ryven_node_generator.ai_assistant.exceptions import GenerationStopped
from ryven_node_generator.ai_assistant.merge import apply_config_patch
from ryven_node_generator.ai_assistant.orchestration.react_loop import run_react_session
from ryven_node_generator.codegen.generator import generate_code_from_data

try:
    from ryven_node_generator.ai_assistant.config import get_model_name
except Exception:  # pragma: no cover
    get_model_name = None  # type: ignore[misc, assignment]

from strategy_constants import USES_GENERATOR, WORKFLOW_LABELS, task_band

DEFAULT_TASKS_JSON = _EVAL_DIR / "data" / "node_tasks_bench_sat_ml_v1.json"
DEFAULT_OUT_CSV = _EVAL_DIR / "data" / "w456_real_trials.csv"
DEFAULT_MANIFEST = _EVAL_DIR / "data" / "w456_benchmark_manifest.json"
DEFAULT_SIMULATED_CSV = _EVAL_DIR / "data" / "strategy_trials_simulated.csv"
DEFAULT_MERGE_HYBRID_OUT = _EVAL_DIR / "data" / "strategy_trials_hybrid.csv"

# Stable column order for CSV read/write (append / merge).
RESULT_CSV_FIELDNAMES: tuple[str, ...] = (
    "task_id",
    "task_band",
    "workflow",
    "workflow_label",
    "run_id",
    "operator",
    "time_to_demo_min",
    "instant_demo_ok",
    "time_to_robust_min",
    "final_robust_ok",
    "validation_on",
    "uses_generator",
    "loop_mode",
    "llm_rounds",
    "tool_calls",
    "tokens_prompt",
    "tokens_completion",
    "tokens_total",
    "usage_steps",
    "errors_top",
    "latent_hardness",
    "sim_schema",
)

W4 = "W4_gen_single"
W5 = "W5_gen_3stage"
W6 = "W6_gen_react"
W456 = (W4, W5, W6)


def _fill_token_fields_from_session_out(target: dict[str, Any], out: dict[str, Any]) -> None:
    """Map ``run_react_session`` token keys into CSV-bound fields (empty if provider omitted usage)."""
    steps = int(out.get("llm_usage_steps") or 0)
    p, c, t = out.get("llm_prompt_tokens"), out.get("llm_completion_tokens"), out.get("llm_total_tokens")
    if steps == 0 and p is None and c is None and t is None:
        target["tokens_prompt"] = ""
        target["tokens_completion"] = ""
        target["tokens_total"] = ""
        target["usage_steps"] = ""
        return
    target["tokens_prompt"] = int(p) if p is not None else ""
    target["tokens_completion"] = int(c) if c is not None else ""
    target["tokens_total"] = int(t) if t is not None else ""
    target["usage_steps"] = steps if steps else ""


def _fill_token_fields_w5_sessions(target: dict[str, Any], outs: list[dict[str, Any]]) -> None:
    sp = sc = st = su = 0
    any_prompt = any_completion = any_total = False
    for o in outs:
        su += int(o.get("llm_usage_steps") or 0)
        if o.get("llm_prompt_tokens") is not None:
            any_prompt = True
            sp += int(o["llm_prompt_tokens"])
        if o.get("llm_completion_tokens") is not None:
            any_completion = True
            sc += int(o["llm_completion_tokens"])
        if o.get("llm_total_tokens") is not None:
            any_total = True
            st += int(o["llm_total_tokens"])
    if not any_prompt and not any_completion and not any_total and su == 0:
        target["tokens_prompt"] = ""
        target["tokens_completion"] = ""
        target["tokens_total"] = ""
        target["usage_steps"] = ""
        return
    target["tokens_prompt"] = sp if any_prompt else ""
    target["tokens_completion"] = sc if any_completion else ""
    target["tokens_total"] = st if any_total else ""
    target["usage_steps"] = su if su else ""


class DenyShellController:
    """Headless benchmark: decline `run_shell` so no subprocesses run without a UI gate."""

    def begin(self, request_id: str) -> None:
        _ = request_id

    def wait_approved(self, request_id: str, *, should_stop=None) -> bool:
        _ = request_id, should_stop
        return False


class AutoApproveShellController:
    """Use only in trusted sandboxes — approves every shell request."""

    def begin(self, request_id: str) -> None:
        _ = request_id

    def wait_approved(self, request_id: str, *, should_stop=None) -> bool:
        _ = request_id, should_stop
        return True


def _git_head() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return None


def _loop_mode(wf: str) -> str:
    if wf == W4:
        return "single"
    if wf == W5:
        return "3stage"
    if wf == W6:
        return "react"
    raise ValueError(wf)


def task_skeleton(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "class_name": task["class_name_suggestion"],
        "title": task["title"],
        "description": task.get("description_zh") or task["title"],
        "color": "#6b7280",
        "inputs": copy.deepcopy(task["inputs"]),
        "outputs": copy.deepcopy(task["outputs"]),
        "core_logic": "# Benchmark skeleton — replace with implementation.\npass",
        "has_main_widget": False,
        "main_widget_template": "button",
        "main_widget_args": "",
        "main_widget_pos": "below ports",
        "main_widget_code": "# Your custom initialization code here",
    }


def merge_session_output(baseline: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    n = copy.deepcopy(baseline)
    patch = out.get("config_patch")
    if patch:
        apply_config_patch(n, patch)
    cl = out.get("core_logic")
    if isinstance(cl, str) and cl.strip():
        n["core_logic"] = cl
    return n


def _count_tool_calls(react_trace: list[dict[str, Any]] | None) -> int:
    n = 0
    for row in react_trace or []:
        n += len(row.get("tools") or [])
    return n


def _stub_passes(node: dict[str, Any], task: dict[str, Any], *, demo: bool) -> bool:
    key = "demo_stub_cases" if demo else "robust_stub_cases"
    raw = task.get(key) or []
    cases = normalize_test_cases(raw, node)
    core = node.get("core_logic") or ""
    r = evaluate_stub_cases(core, node, cases)
    return bool(r.get("all_passed"))


def _error_label(out: dict[str, Any], demo_ok: bool, robust_ok: bool) -> str:
    ve = out.get("validation_error")
    if ve:
        s = str(ve).replace("\n", " ").strip()
        return s[:120] if len(s) > 120 else s
    if not demo_ok:
        return "demo_stub_fail"
    if not robust_ok:
        return "robust_stub_fail"
    return "none"


def _build_benchmark_body(task: dict[str, Any]) -> str:
    return (
        f"Task {task['task_id']}: {task['title']}\n"
        f"Description (ZH): {task.get('description_zh', '')}\n"
        f"Requirement: {task.get('core_logic_requirement', '')}\n"
        f"Inputs (JSON): {json.dumps(task['inputs'], ensure_ascii=False)}\n"
        f"Outputs (JSON): {json.dumps(task['outputs'], ensure_ascii=False)}\n"
    )


def prompt_w4(task: dict[str, Any]) -> str:
    return (
        _build_benchmark_body(task)
        + "\nYou are in a **short** tool loop (prefer completing in few steps).\n"
        "Implement `core_logic` with `self.get_input_val` / `self.set_output_val` as in Ryven templates. "
        "Use validate_core_logic_tool and run_stub_test when helpful. "
        "When satisfied, call submit_node_turn with a brief message and the final core_logic.\n"
    )


def prompt_w6(task: dict[str, Any]) -> str:
    return (
        _build_benchmark_body(task)
        + "\nUse the ReAct tools freely (within policy) to implement and verify the node. "
        "When satisfied, call submit_node_turn.\n"
    )


def prompt_w5_stage1(task: dict[str, Any]) -> str:
    return (
        "Stage 1/3 — **Ports & metadata only**.\n"
        + _build_benchmark_body(task)
        + "\nEnsure class_name, title, description, inputs, outputs match the benchmark. "
        "For core_logic you may keep a minimal placeholder that passes validate_core_logic_tool (e.g. `pass`). "
        "Then submit_node_turn.\n"
    )


def prompt_w5_stage2(task: dict[str, Any]) -> str:
    return (
        "Stage 2/3 — **Implement core_logic**.\n"
        + _build_benchmark_body(task)
        + "\nReplace placeholder logic. Use validate_core_logic_tool and run_stub_test. "
        "Aim to satisfy typical/demo behavior. Then submit_node_turn.\n"
    )


def prompt_w5_stage3(task: dict[str, Any]) -> str:
    return (
        "Stage 3/3 — **Hardening**.\n"
        + _build_benchmark_body(task)
        + "\nImprove edge-case behavior (None, coercion, empty inputs) per the requirement. "
        "Use run_stub_test again. Then submit_node_turn.\n"
    )


def _run_one_session(
    *,
    user_text: str,
    node: dict[str, Any],
    project_root: str,
    max_steps: int,
    shell_ctrl: Any,
) -> dict[str, Any]:
    return run_react_session(
        user_text=user_text,
        current_node=copy.deepcopy(node),
        existing_class_names=[],
        history=None,
        project_root=project_root,
        max_steps=max_steps,
        shell_approval_controller=shell_ctrl,
    )


def run_w4(
    task: dict[str, Any],
    *,
    project_root: str,
    max_steps: int,
    shell_ctrl: Any,
) -> dict[str, Any]:
    skel = task_skeleton(task)
    t0 = time.perf_counter()
    out = _run_one_session(
        user_text=prompt_w4(task),
        node=skel,
        project_root=project_root,
        max_steps=max_steps,
        shell_ctrl=shell_ctrl,
    )
    wall_min = (time.perf_counter() - t0) / 60.0
    merged = merge_session_output(skel, out)
    demo_ok = _stub_passes(merged, task, demo=True)
    robust_ok = _stub_passes(merged, task, demo=False)
    m4: dict[str, Any] = {
        "out": out,
        "merged": merged,
        "wall_min": wall_min,
        "time_to_demo_min": wall_min if demo_ok else wall_min,
        "time_to_robust_min": wall_min if robust_ok else "",
        "instant_demo_ok": int(demo_ok),
        "final_robust_ok": int(robust_ok),
        "llm_rounds": int(out.get("repair_round") or 0),
        "tool_calls": _count_tool_calls(out.get("react_trace")),
    }
    _fill_token_fields_from_session_out(m4, out)
    return m4


def run_w6(
    task: dict[str, Any],
    *,
    project_root: str,
    max_steps: int,
    shell_ctrl: Any,
) -> dict[str, Any]:
    skel = task_skeleton(task)
    t0 = time.perf_counter()
    out = _run_one_session(
        user_text=prompt_w6(task),
        node=skel,
        project_root=project_root,
        max_steps=max_steps,
        shell_ctrl=shell_ctrl,
    )
    wall_min = (time.perf_counter() - t0) / 60.0
    merged = merge_session_output(skel, out)
    demo_ok = _stub_passes(merged, task, demo=True)
    robust_ok = _stub_passes(merged, task, demo=False)
    m6: dict[str, Any] = {
        "out": out,
        "merged": merged,
        "wall_min": wall_min,
        "time_to_demo_min": wall_min if demo_ok else wall_min,
        "time_to_robust_min": wall_min if robust_ok else "",
        "instant_demo_ok": int(demo_ok),
        "final_robust_ok": int(robust_ok),
        "llm_rounds": int(out.get("repair_round") or 0),
        "tool_calls": _count_tool_calls(out.get("react_trace")),
    }
    _fill_token_fields_from_session_out(m6, out)
    return m6


def run_w5(
    task: dict[str, Any],
    *,
    project_root: str,
    max_steps: tuple[int, int, int],
    shell_ctrl: Any,
) -> dict[str, Any]:
    skel = task_skeleton(task)
    t0 = time.perf_counter()
    rounds = 0
    tools = 0
    node = copy.deepcopy(skel)
    outs: list[dict[str, Any]] = []
    demo_ok_time: float | None = None

    s1, s2, s3 = max_steps
    for prompt, ms in (
        (prompt_w5_stage1(task), s1),
        (prompt_w5_stage2(task), s2),
        (prompt_w5_stage3(task), s3),
    ):
        out = _run_one_session(
            user_text=prompt,
            node=node,
            project_root=project_root,
            max_steps=ms,
            shell_ctrl=shell_ctrl,
        )
        outs.append(out)
        node = merge_session_output(node, out)
        rounds += int(out.get("repair_round") or 0)
        tools += _count_tool_calls(out.get("react_trace"))
        if demo_ok_time is None and _stub_passes(node, task, demo=True):
            demo_ok_time = (time.perf_counter() - t0) / 60.0

    wall_min = (time.perf_counter() - t0) / 60.0
    demo_ok = _stub_passes(node, task, demo=True)
    robust_ok = _stub_passes(node, task, demo=False)

    if demo_ok_time is None:
        demo_ok_time = wall_min

    m5: dict[str, Any] = {
        "out": outs[-1],
        "merged": node,
        "wall_min": wall_min,
        "time_to_demo_min": demo_ok_time,
        "time_to_robust_min": wall_min if robust_ok else "",
        "instant_demo_ok": int(demo_ok),
        "final_robust_ok": int(robust_ok),
        "llm_rounds": rounds,
        "tool_calls": tools,
        "_outs": outs,
    }
    _fill_token_fields_w5_sessions(m5, outs)
    return m5


def _row(
    *,
    task: dict[str, Any],
    wf: str,
    run_id: int,
    metrics: dict[str, Any],
    tasks_schema: str,
) -> dict[str, Any]:
    tid = task["task_id"]
    err = _error_label(metrics["out"], bool(metrics["instant_demo_ok"]), bool(metrics["final_robust_ok"]))
    data: dict[str, Any] = {
        "task_id": tid,
        "task_band": task.get("band") or task_band(tid),
        "workflow": wf,
        "workflow_label": WORKFLOW_LABELS[wf],
        "run_id": run_id,
        "operator": "automated_api_benchmark",
        "time_to_demo_min": round(float(metrics["time_to_demo_min"]), 4),
        "instant_demo_ok": metrics["instant_demo_ok"],
        "time_to_robust_min": (
            round(float(metrics["time_to_robust_min"]), 4)
            if metrics["time_to_robust_min"] != ""
            else ""
        ),
        "final_robust_ok": metrics["final_robust_ok"],
        "validation_on": 1,
        "uses_generator": USES_GENERATOR[wf],
        "loop_mode": _loop_mode(wf),
        "llm_rounds": metrics["llm_rounds"],
        "tool_calls": metrics["tool_calls"],
        "tokens_prompt": metrics.get("tokens_prompt", ""),
        "tokens_completion": metrics.get("tokens_completion", ""),
        "tokens_total": metrics.get("tokens_total", ""),
        "usage_steps": metrics.get("usage_steps", ""),
        "errors_top": err,
        "latent_hardness": "",
        "sim_schema": tasks_schema,
    }
    return {k: data[k] for k in RESULT_CSV_FIELDNAMES}


def _normalize_csv_row(d: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in RESULT_CSV_FIELDNAMES:
        out[k] = d.get(k, "")
    return out


def _read_result_csv(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.stat().st_size == 0:
        return []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return [_normalize_csv_row(r) for r in reader if r]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(RESULT_CSV_FIELDNAMES))
        w.writeheader()
        for r in rows:
            w.writerow(_normalize_csv_row(r))


def _append_or_write_result_csv(
    path: Path,
    new_rows: list[dict[str, Any]],
    *,
    append: bool,
    replace_task_ids: set[str] | None,
) -> int:
    """Write or merge into path. Returns final row count."""
    if append:
        existing = _read_result_csv(path)
        _warn_if_results_csv_mixed_w123(existing)
        if replace_task_ids:
            existing = [r for r in existing if str(r.get("task_id", "")) not in replace_task_ids]
        combined = existing + [_normalize_csv_row(r) for r in new_rows]
        _write_csv(path, combined)
        return len(combined)
    _write_csv(path, new_rows)
    return len(new_rows)


def merge_with_simulated(*, real_df_path: Path, simulated_path: Path, out_path: Path) -> None:
    import pandas as pd

    sim = pd.read_csv(simulated_path)
    real = pd.read_csv(real_df_path)
    # Only W4–W6 rows from the results file (ignore W1–W3 if the CSV was accidentally mixed).
    real_w456 = real.loc[real["workflow"].isin(W456)].copy()
    drop_w = real_w456["workflow"].unique()
    if len(drop_w) == 0:
        print(
            "[warn] No W4/W5/W6 rows in --out-csv; hybrid output will match simulated CSV only "
            "(add benchmark rows or fix the file).",
            file=sys.stderr,
        )
    sim2 = sim.loc[~sim["workflow"].isin(drop_w)]
    merged = pd.concat([sim2, real_w456], ignore_index=True)
    merged = merged.sort_values(["workflow", "task_id", "run_id"], kind="mergesort").reset_index(drop=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")


def _validate_out_csv(path: Path) -> str | None:
    """Return error message if -o path is invalid (common PowerShell / copy-paste mistakes)."""
    s = str(path).strip()
    if not s:
        return "Empty --out-csv / -o path. In PowerShell set $R='...path...' first, or use --out-csv=scripts/evaluation/data/result_w456.csv"
    name = path.name
    if name.startswith("-"):
        return (
            f"Invalid -o value {name!r} (looks like a flag). "
            "In PowerShell an unset $R makes -o swallow --append. "
            "Use: $R='scripts/evaluation/data/result_w456.csv'; python ... -o $R --append ..."
        )
    return None


def _warn_if_results_csv_mixed_w123(existing: list[dict[str, Any]]) -> None:
    bad = {str(r.get("workflow", "")) for r in existing if r.get("workflow") not in W456 and r.get("workflow")}
    if not bad:
        return
    print(
        f"[warn] --out-csv already contains non-W456 workflows {sorted(bad)[:6]}{'...' if len(bad) > 6 else ''}. "
        "Use a file that only accumulates W4_gen_single / W5_gen_3stage / W6_gen_react (e.g. result_w456.csv). "
        "Merge still uses only W456 rows from this file.",
        file=sys.stderr,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Real W4/W5/W6 benchmark via run_react_session + stub_runner.")
    parser.add_argument("--tasks-json", type=Path, default=DEFAULT_TASKS_JSON)
    parser.add_argument("-o", "--out-csv", type=Path, default=DEFAULT_OUT_CSV)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--runs", type=int, default=3, help="Repeats per task × workflow (e.g. 3 groups).")
    parser.add_argument(
        "--workflows",
        type=str,
        default=",".join(W456),
        help="Comma-separated subset of W4_gen_single,W5_gen_3stage,W6_gen_react.",
    )
    parser.add_argument("--task-ids", type=str, default="", help="Optional filter: N01,N03,...")
    parser.add_argument("--dry-run", action="store_true", help="No LLM calls; write placeholder rows.")
    parser.add_argument("--project-root", type=Path, default=None, help="Agent workspace (default: temp dir).")
    parser.add_argument("--keep-temp-dir", action="store_true")
    parser.add_argument("--w4-max-steps", type=int, default=8)
    parser.add_argument("--w6-max-steps", type=int, default=28)
    parser.add_argument("--w5-max-steps", type=str, default="8,14,18", help="Three integers: stage1,2,3 max_steps.")
    parser.add_argument(
        "--shell-policy",
        choices=("deny", "approve"),
        default="deny",
        help="Headless shell gate: deny run_shell (default) or auto-approve (unsafe).",
    )
    parser.add_argument("--codegen-smoke", action="store_true", help="After each trial, call generate_code_from_data (no write).")
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append this run's rows to --out-csv (keeps prior tasks). Creates file + header if missing.",
    )
    parser.add_argument(
        "--replace-existing-tasks",
        action="store_true",
        help="With --append: remove existing rows whose task_id appears in this run, then append (avoid duplicates when re-testing one task).",
    )
    parser.add_argument(
        "--merge-with",
        type=Path,
        default=None,
        help="Simulated/template CSV (W1–W6). If set alone: after run, write hybrid = (this file minus W4–W6) + all rows from --out-csv → --merge-out.",
    )
    parser.add_argument(
        "--merge-out",
        type=Path,
        default=DEFAULT_MERGE_HYBRID_OUT,
        help="Hybrid CSV path (six workflows for plotting). Used when merging.",
    )
    parser.add_argument(
        "--merge-hybrid",
        action="store_true",
        help="After run, build hybrid CSV. Merge-base is --merge-with if set, else strategy_trials_simulated.csv.",
    )
    args = parser.parse_args(argv)

    # Per-LLM-call progress inside run_react_session (stderr); unset BENCHMARK_LLM_STEP_LOG=0 to silence.
    os.environ.setdefault("BENCHMARK_LLM_STEP_LOG", "1")

    out_err = _validate_out_csv(args.out_csv)
    if out_err:
        print(out_err, file=sys.stderr)
        return 2

    raw = json.loads(args.tasks_json.read_text(encoding="utf-8"))
    tasks: list[dict[str, Any]] = raw["tasks"]
    want_ids: set[str] = set()
    for part in args.task_ids.split(","):
        p = part.strip().upper()
        if not p:
            continue
        if p.isdigit():
            p = f"N{int(p):02d}"
        want_ids.add(p)
    if want_ids:
        tasks = [t for t in tasks if t["task_id"] in want_ids]

    if not tasks:
        print("No tasks selected. Use --task-ids N01,... or omit it to run all 20.", file=sys.stderr)
        return 2

    wf_list = [w.strip() for w in args.workflows.split(",") if w.strip()]
    for w in wf_list:
        if w not in W456:
            print(f"Unknown workflow {w!r}; expected one of {W456}", file=sys.stderr)
            return 2

    try:
        w5_steps = tuple(int(x.strip()) for x in args.w5_max_steps.split(","))
    except ValueError:
        print("--w5-max-steps must be three comma-separated integers.", file=sys.stderr)
        return 2
    if len(w5_steps) != 3:
        print("--w5-max-steps must have exactly three values.", file=sys.stderr)
        return 2

    shell_ctrl = AutoApproveShellController() if args.shell_policy == "approve" else DenyShellController()

    bench_ref = str(args.tasks_json.resolve()).replace("\\", "/")
    tasks_schema = str(raw.get("schema_version") or "unknown")

    rows: list[dict[str, Any]] = []
    tmp_ctx = None
    project_root_str: str
    if args.project_root is not None:
        project_root_str = str(args.project_root.resolve())
        os.makedirs(project_root_str, exist_ok=True)
    else:
        tmp_ctx = tempfile.TemporaryDirectory(prefix="w456_bench_")
        project_root_str = tmp_ctx.name

    model_name = None
    if get_model_name is not None:
        try:
            model_name = get_model_name()
        except Exception:
            model_name = None

    t_start_wall = time.time()
    interrupted = False

    try:
        for task in tasks:
            tid = task["task_id"]
            for wf in wf_list:
                for run_id in range(1, args.runs + 1):
                    print(f"[start] {tid} {wf} run_id={run_id} …", flush=True)
                    if args.dry_run:
                        fake_out = {"validation_error": "dry_run"}
                        m = {
                            "out": fake_out,
                            "time_to_demo_min": 0.0,
                            "time_to_robust_min": "",
                            "instant_demo_ok": 0,
                            "final_robust_ok": 0,
                            "llm_rounds": 0,
                            "tool_calls": 0,
                        }
                        rows.append(_row(task=task, wf=wf, run_id=run_id, metrics=m, tasks_schema=tasks_schema))
                        print(f"[done]  {tid} {wf} run_id={run_id} (dry-run)", flush=True)
                        continue

                    try:
                        if wf == W4:
                            metrics = run_w4(
                                task,
                                project_root=project_root_str,
                                max_steps=args.w4_max_steps,
                                shell_ctrl=shell_ctrl,
                            )
                        elif wf == W6:
                            metrics = run_w6(
                                task,
                                project_root=project_root_str,
                                max_steps=args.w6_max_steps,
                                shell_ctrl=shell_ctrl,
                            )
                        else:
                            metrics = run_w5(
                                task,
                                project_root=project_root_str,
                                max_steps=w5_steps,
                                shell_ctrl=shell_ctrl,
                            )

                        if args.codegen_smoke:
                            n_code, _g = generate_code_from_data([metrics["merged"]])
                            if len(n_code) < 50:
                                raise RuntimeError("codegen_smoke: nodes.py unexpectedly short")

                        rows.append(
                            _row(task=task, wf=wf, run_id=run_id, metrics=metrics, tasks_schema=tasks_schema)
                        )
                        print(f"[done]  {tid} {wf} run_id={run_id}", flush=True)
                    except GenerationStopped as e:
                        fake = {"validation_error": f"stopped: {e}"}
                        m = {
                            "out": fake,
                            "time_to_demo_min": 0.0,
                            "time_to_robust_min": "",
                            "instant_demo_ok": 0,
                            "final_robust_ok": 0,
                            "llm_rounds": 0,
                            "tool_calls": 0,
                        }
                        rows.append(_row(task=task, wf=wf, run_id=run_id, metrics=m, tasks_schema=tasks_schema))
                        print(f"[done]  {tid} {wf} run_id={run_id} (stopped)", flush=True)
                    except Exception as e:
                        fake = {"validation_error": f"{type(e).__name__}: {e}"}
                        m = {
                            "out": fake,
                            "time_to_demo_min": 0.0,
                            "time_to_robust_min": "",
                            "instant_demo_ok": 0,
                            "final_robust_ok": 0,
                            "llm_rounds": 0,
                            "tool_calls": 0,
                        }
                        row = _row(task=task, wf=wf, run_id=run_id, metrics=m, tasks_schema=tasks_schema)
                        row["errors_top"] = f"runner_exception: {type(e).__name__}"
                        rows.append(row)
                        print(f"[done]  {tid} {wf} run_id={run_id} (error logged)", flush=True)
                        print(f"[error] {tid} {wf} run{run_id}: {e}", file=sys.stderr)
    except KeyboardInterrupt:
        interrupted = True
        print(
            f"\n[interrupt] KeyboardInterrupt — writing {len(rows)} row(s) collected so far.",
            file=sys.stderr,
        )
    finally:
        if tmp_ctx is not None and not args.keep_temp_dir:
            tmp_ctx.cleanup()

    args.out_csv = args.out_csv.resolve()

    if not rows:
        print("No result rows to write (nothing ran or empty selection).", file=sys.stderr)
        return 3

    replace_ids: set[str] | None = None
    if args.append and args.replace_existing_tasks:
        replace_ids = {t["task_id"] for t in tasks}

    total_in_out = _append_or_write_result_csv(
        args.out_csv,
        rows,
        append=bool(args.append),
        replace_task_ids=replace_ids,
    )

    do_merge = bool(args.merge_hybrid or args.merge_with is not None)
    merge_base_path: Path | None = None
    if do_merge:
        merge_base_path = args.merge_with.resolve() if args.merge_with is not None else DEFAULT_SIMULATED_CSV.resolve()

    manifest = {
        "schema": "w456_benchmark_manifest_v1",
        "started_unix": t_start_wall,
        "finished_unix": time.time(),
        "tasks_json": bench_ref,
        "tasks_schema_version": tasks_schema,
        "out_csv": str(args.out_csv).replace("\\", "/"),
        "n_rows_this_run": len(rows),
        "out_csv_total_rows": total_in_out,
        "append_mode": bool(args.append),
        "replace_existing_tasks": bool(args.replace_existing_tasks),
        "workflows": wf_list,
        "runs_per_task": args.runs,
        "task_ids_this_run": [t["task_id"] for t in tasks],
        "dry_run": bool(args.dry_run),
        "shell_policy": args.shell_policy,
        "model_name_resolved": model_name,
        "git_rev": _git_head(),
        "merge_hybrid": bool(args.merge_hybrid),
        "merge_base_csv": str(merge_base_path).replace("\\", "/") if merge_base_path else None,
        "merge_hybrid_out": str(args.merge_out.resolve()).replace("\\", "/") if do_merge else None,
        "interpretation": (
            "Automated API benchmark: real LLM calls via run_react_session; "
            "correctness from evaluate_stub_cases on the tasks JSON (see tasks_json + tasks_schema_version). "
            "Not a human factors study."
        ),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    if do_merge:
        mp = merge_base_path
        assert mp is not None
        mo = args.merge_out.resolve()
        if not mp.is_file():
            print(f"Merge base CSV not found: {mp}", file=sys.stderr)
            return 3
        merge_with_simulated(real_df_path=args.out_csv, simulated_path=mp, out_path=mo)
        print(f"Wrote hybrid CSV: {mo}")

    print(f"Wrote: {args.out_csv} ({total_in_out} total rows)")
    print(f"Wrote: {args.manifest.resolve()}")
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
