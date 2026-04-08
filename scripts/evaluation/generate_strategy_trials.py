"""
Simulated evaluation trials for thesis Chapter 8 (aligned with
`strategy/GENERATOR_EVALUATION_STRATEGY.md`).

This is a *Monte Carlo model*, not field data. It encodes plausible mechanisms:
  latent per-trial difficulty, log-normal wall times, rework after first-shot failure,
  operator skill jitter, optional environment noise, and conditional robust success.

Design goal: six workflows separate **authoring surface** (direct edit vs Ryven Node
Generator) from **LLM depth** (none / chat / single agent / 3-stage / ReAct).
W6 (Generator + ReAct) strongest on M2/M3; anchors: ReAct ~1–3 min by tier;
hand-only L1 ~10+ min floor.

Usage:
  python scripts/evaluation/generate_strategy_trials.py
  python scripts/evaluation/generate_strategy_trials.py --runs 5 --seed 7 --out data/foo.csv
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from strategy_constants import USES_GENERATOR, WORKFLOW_LABELS, WORKFLOWS, task_band


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class SimulationParams:
    """Versioned bundle written next to CSV for audit / thesis appendix."""

    schema_version: str = "sim_v3"
    seed: int = 42
    n_tasks: int = 20
    n_runs: int = 3
    env_noise_sigma_min: float = 0.0
    # ReAct anchor medians (minutes) by band — user reference: simple ~1, hard ~3
    react_demo_median_L1: float = 1.05
    react_demo_median_L2: float = 2.0
    react_demo_median_L3: float = 3.0
    manual_floor_L1_min: float = 10.0
    sigma_log_demo: float = 0.28
    sigma_log_rework: float = 0.42


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _react_demo_median(band: str, h: float, p: SimulationParams) -> float:
    m = {"L1": p.react_demo_median_L1, "L2": p.react_demo_median_L2, "L3": p.react_demo_median_L3}[band]
    return max(0.35, m * (1.0 + 0.35 * h))


def _sample_lognormal_minutes(rng: np.random.Generator, median_min: float, sigma_log: float) -> float:
    """LogNormal with median = exp(mu); numpy uses mu, sigma on log scale."""
    med = max(1e-6, median_min)
    mu = math.log(med)
    return float(rng.lognormal(mu, sigma_log))


def _clip01(x: float) -> float:
    return float(min(0.995, max(0.04, x)))


def _workflow_loop_meta(wf: str) -> tuple[bool, str, tuple[int, int], tuple[int, int]]:
    if wf == "W1_hand_only":
        return False, "none", (0, 0), (0, 0)
    if wf == "W2_hand_chat":
        return False, "none", (0, 0), (0, 0)
    if wf == "W3_gen_chat":
        return False, "none", (0, 0), (0, 0)
    if wf == "W4_gen_single":
        return True, "single", (1, 1), (2, 8)
    if wf == "W5_gen_3stage":
        return True, "3stage", (3, 3), (8, 16)
    if wf == "W6_gen_react":
        return True, "react", (2, 8), (10, 36)
    raise ValueError(wf)


def _instant_logit(wf: str, h: float, op_skill: float) -> float:
    """Higher -> more likely first-shot demo pass. h in [0,1] hardness."""
    # Intercepts chosen so E[p] (over h~Beta(2.2,2.2), op~N(0,0.22)) matches thesis narrative.
    base = {
        "W1_hand_only": 1.02,
        "W2_hand_chat": 0.78,
        "W3_gen_chat": 1.12,
        "W4_gen_single": 1.58,
        "W5_gen_3stage": 2.05,
        "W6_gen_react": 2.72,
    }[wf]
    slope_h = -1.65
    slope_op = 0.72
    return base + slope_h * h + slope_op * op_skill


def _final_logit(wf: str, h: float, instant_ok: bool, op_skill: float) -> float:
    base = {
        "W1_hand_only": 2.05,
        "W2_hand_chat": 1.55,
        "W3_gen_chat": 1.78,
        "W4_gen_single": 2.25,
        "W5_gen_3stage": 2.55,
        "W6_gen_react": 2.95,
    }[wf]
    if not instant_ok:
        base -= {
            "W1_hand_only": 0.85,
            "W2_hand_chat": 0.72,
            "W3_gen_chat": 0.70,
            "W4_gen_single": 1.0,
            "W5_gen_3stage": 0.58,
            "W6_gen_react": 0.32,
        }[wf]
    return base - 1.05 * h + 0.48 * op_skill


def _demo_time_base_minutes(
    wf: str,
    band: str,
    h: float,
    rng: np.random.Generator,
    p: SimulationParams,
) -> tuple[float, int, int]:
    """Wall time if the 'happy path' — before first-shot failure rework. Returns (minutes, rounds, tools)."""
    r = _react_demo_median(band, h, p)
    sig = p.sigma_log_demo * (1.12 if band == "L3" else 1.0)

    if wf == "W6_gen_react":
        t = _sample_lognormal_minutes(rng, r, sig)
        rounds = int(rng.integers(2, 9))
        tools = int(rng.integers(10, max(11, 12 + 4 * rounds)))
        return t, rounds, tools

    if wf == "W5_gen_3stage":
        med = r * 0.88
        t = _sample_lognormal_minutes(rng, med, sig * 0.92)
        rounds, tools = 3, int(rng.integers(8, 17))
        return t, rounds, tools

    if wf == "W4_gen_single":
        med = r * 1.05
        t = _sample_lognormal_minutes(rng, med, sig * 0.95)
        rounds, tools = 1, int(rng.integers(2, 9))
        return t, rounds, tools

    if wf == "W3_gen_chat":
        # Templates remove boilerplate; still copy-paste LLM output
        med = r * 2.25
        t = _sample_lognormal_minutes(rng, med, sig * 1.02)
        return t, 0, 0

    if wf == "W2_hand_chat":
        med = r * 4.8
        t = _sample_lognormal_minutes(rng, med, sig * 1.05)
        return t, 0, 0

    # W1_hand_only
    mult = {"L1": 11.5, "L2": 10.5, "L3": 12.0}[band]
    floor = p.manual_floor_L1_min if band == "L1" else (p.manual_floor_L1_min + 8.0 if band == "L2" else p.manual_floor_L1_min + 22.0)
    med = max(floor, r * mult * (1.0 + 0.25 * h))
    t = _sample_lognormal_minutes(rng, med, sig * 1.08)
    t = max(floor * 0.92, t)
    return t, 0, 0


def _rework_minutes(wf: str, band: str, h: float, rng: np.random.Generator, p: SimulationParams) -> float:
    """Extra time when first demo shot fails (debug / paste / misunderstanding)."""
    if wf == "W6_gen_react":
        med = 0.85 + 0.9 * h + (0.35 if band == "L2" else 0.0) + (0.55 if band == "L3" else 0.0)
        return _sample_lognormal_minutes(rng, med, p.sigma_log_rework * 0.85)
    if wf == "W5_gen_3stage":
        med = 1.6 + 1.1 * h
        return _sample_lognormal_minutes(rng, med, p.sigma_log_rework)
    if wf == "W4_gen_single":
        med = 2.8 + 1.8 * h + (1.0 if band == "L3" else 0.0)
        return _sample_lognormal_minutes(rng, med, p.sigma_log_rework * 1.05)
    if wf == "W3_gen_chat":
        med = 4.2 + 3.0 * h
        return _sample_lognormal_minutes(rng, med, p.sigma_log_rework * 1.05)
    if wf == "W2_hand_chat":
        med = 5.5 + 4.0 * h
        return _sample_lognormal_minutes(rng, med, p.sigma_log_rework * 1.1)
    med = 9.0 + 7.0 * h + (4.0 if band == "L3" else 0.0)
    return _sample_lognormal_minutes(rng, med, p.sigma_log_rework * 1.12)


def _robust_tail_minutes(
    wf: str,
    band: str,
    h: float,
    instant_ok: bool,
    rng: np.random.Generator,
    p: SimulationParams,
) -> float:
    """Work after demo to pass robust stub suite."""
    if wf == "W6_gen_react":
        med = 0.65 + 0.45 * h + (0.25 if not instant_ok else 0.0)
        return _sample_lognormal_minutes(rng, med, 0.32)
    if wf == "W5_gen_3stage":
        med = 1.05 + 0.75 * h + (0.85 if not instant_ok else 0.0)
        return _sample_lognormal_minutes(rng, med, 0.36)
    if wf == "W4_gen_single":
        med = 1.85 + 1.25 * h + (1.6 if not instant_ok else 0.0)
        return _sample_lognormal_minutes(rng, med, 0.4)
    if wf == "W3_gen_chat":
        med = 2.6 + 1.9 * h + (2.8 if not instant_ok else 0.0)
        return _sample_lognormal_minutes(rng, med, 0.41)
    if wf == "W2_hand_chat":
        med = 3.2 + 2.2 * h + (3.5 if not instant_ok else 0.0)
        return _sample_lognormal_minutes(rng, med, 0.42)
    med = 4.5 + 3.0 * h + (5.0 if not instant_ok else 0.0)
    return _sample_lognormal_minutes(rng, med, 0.44)


def _error_label(wf: str, instant_ok: bool, final_ok: bool, rng: np.random.Generator) -> str:
    pool_demo = ["stub_mismatch", "syntax_error", "validation_error", "off_by_one_ports"]
    pool_final = ["stub_mismatch", "robust_case_fail", "timeout", "ryven_import_error"]
    if final_ok:
        return "none"
    if not instant_ok:
        return str(rng.choice(pool_demo))
    return str(rng.choice(pool_final))


def simulate_trials(
    *,
    rng: np.random.Generator,
    params: SimulationParams,
    operators: tuple[str, ...] = ("operator_A", "operator_B"),
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    task_ids = [f"N{i:02d}" for i in range(1, params.n_tasks + 1)]

    for task_id in task_ids:
        band = task_band(task_id)
        for wf in WORKFLOWS:
            val_on, loop_mode, _r_fix, _t_fix = _workflow_loop_meta(wf)
            for run_id in range(1, params.n_runs + 1):
                op = operators[int(rng.integers(0, len(operators)))]
                op_skill = float(rng.normal(0.0, 0.22))  # small idiosyncrasy
                h = float(rng.beta(2.2, 2.2))
                env = float(rng.normal(0.0, params.env_noise_sigma_min))

                t0, llm_rounds, tool_calls = _demo_time_base_minutes(wf, band, h, rng, params)
                t_demo = t0 + env

                logit_i = _instant_logit(wf, h, op_skill) + float(rng.normal(0, 0.12))
                p_inst = _clip01(_sigmoid(logit_i))
                instant_ok = bool(rng.random() < p_inst)

                if wf == "W6_gen_react" and not instant_ok:
                    extra_r = int(rng.integers(1, 4))
                    llm_rounds = min(12, llm_rounds + extra_r)
                    tool_calls = int(max(tool_calls, tool_calls + rng.integers(4, 14)))

                if not instant_ok:
                    t_demo += _rework_minutes(wf, band, h, rng, params)
                    t_demo += env * 0.5

                logit_f = _final_logit(wf, h, instant_ok, op_skill) + float(rng.normal(0, 0.14))
                p_fin = _clip01(_sigmoid(logit_f))
                final_ok = bool(rng.random() < p_fin)

                err_top = _error_label(wf, instant_ok, final_ok, rng)
                if instant_ok:
                    err_top = "none"

                if wf in {"W4_gen_single", "W5_gen_3stage"}:
                    _, _, (rl, rh), (tl, th) = _workflow_loop_meta(wf)
                    llm_rounds = rl if wf == "W5_gen_3stage" else llm_rounds
                    tool_calls = int(rng.integers(tl, th + 1))

                t_rob: float | str = ""
                if final_ok:
                    tail = _robust_tail_minutes(wf, band, h, instant_ok, rng, params)
                    t_rob = float(max(t_demo + tail, t_demo + 0.35))

                rows.append(
                    {
                        "task_id": task_id,
                        "task_band": band,
                        "workflow": wf,
                        "workflow_label": WORKFLOW_LABELS[wf],
                        "run_id": run_id,
                        "operator": op,
                        "time_to_demo_min": round(max(0.25, t_demo), 2),
                        "instant_demo_ok": int(instant_ok),
                        "time_to_robust_min": (round(t_rob, 2) if isinstance(t_rob, float) else ""),
                        "final_robust_ok": int(final_ok),
                        "validation_on": int(val_on),
                        "uses_generator": int(USES_GENERATOR[wf]),
                        "loop_mode": loop_mode,
                        "llm_rounds": int(llm_rounds),
                        "tool_calls": int(tool_calls),
                        "errors_top": err_top,
                        "latent_hardness": round(h, 4),
                        "sim_schema": params.schema_version,
                        "notes": "SIMULATED — Monte Carlo; see generate_strategy_trials.py + simulation_manifest.json",
                    }
                )

    df = pd.DataFrame(rows)
    return df.sort_values(["workflow", "task_id", "run_id"], kind="mergesort").reset_index(drop=True)


def summarize(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for wf in WORKFLOWS:
        sub = df.loc[df["workflow"] == wf]
        tro = pd.to_numeric(sub.loc[sub["final_robust_ok"] == 1, "time_to_robust_min"], errors="coerce").dropna()
        out[wf] = {
            "n_trials": int(len(sub)),
            "median_time_to_demo_min": float(np.median(sub["time_to_demo_min"])),
            "median_time_to_robust_min_if_ok": float(tro.median()) if len(tro) else None,
            "mean_instant_demo_ok": float(sub["instant_demo_ok"].mean()),
            "mean_final_robust_ok": float(sub["final_robust_ok"].mean()),
            "mean_llm_rounds": float(sub["llm_rounds"].mean()),
            "mean_tool_calls": float(sub["tool_calls"].mean()),
        }
    return out


def print_summary_table(summary: dict[str, Any]) -> None:
    print("\n=== Simulated summary (median / rates) ===")
    hdr = f"{'Workflow':<26} {'med demo':>10} {'med robust*':>12} {'pass@1':>8} {'final':>8} {'mean rnd':>9}"
    print(hdr)
    print("-" * len(hdr))
    for wf in WORKFLOWS:
        s = summary[wf]
        mr = s["median_time_to_robust_min_if_ok"]
        mrs = f"{mr:.2f}" if mr is not None else "—"
        print(
            f"{wf:<26} {s['median_time_to_demo_min']:>10.2f} {mrs:>12} "
            f"{s['mean_instant_demo_ok']:>8.2f} {s['mean_final_robust_ok']:>8.2f} {s['mean_llm_rounds']:>9.2f}"
        )
    print("* robust median only over final_robust_ok==1\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Simulate strategy evaluation trials (tidy CSV + manifest).")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs", type=int, default=3, help="Repeats per task × workflow.")
    parser.add_argument("--tasks", type=int, default=20, help="Number of tasks N01..Nxx.")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent / "data" / "strategy_trials_simulated.csv",
        help="Output CSV path.",
    )
    parser.add_argument("--env-noise", type=float, default=0.25, help="Std dev (min) of Gaussian clock noise per trial.")
    args = parser.parse_args(argv)

    params = SimulationParams(seed=args.seed, n_tasks=args.tasks, n_runs=args.runs, env_noise_sigma_min=args.env_noise)
    rng = np.random.default_rng(args.seed)
    df = simulate_trials(rng=rng, params=params)

    args.out = args.out.resolve()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False, encoding="utf-8-sig")

    manifest = {
        "params": asdict(params),
        "output_csv": str(args.out).replace("\\", "/"),
        "summary": summarize(df),
    }
    man_path = args.out.with_name("simulation_manifest.json")
    man_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    summ = manifest["summary"]
    print_summary_table(summ)

    w1 = summ["W1_hand_only"]["median_time_to_demo_min"]
    w6d = summ["W6_gen_react"]["median_time_to_demo_min"]
    w6r = summ["W6_gen_react"]["median_time_to_robust_min_if_ok"]
    w1r = summ["W1_hand_only"]["median_time_to_robust_min_if_ok"]
    w2d = summ["W2_hand_chat"]["median_time_to_demo_min"]
    w3d = summ["W3_gen_chat"]["median_time_to_demo_min"]
    print("Interpretation (simulation, not proof):")
    if w1 and w6d:
        print(
            f"  - Median time-to-demo: W6 (Generator+ReAct) ~ {w6d:.2f} min vs W1 (hand only) ~ {w1:.2f} min "
            f"({w1 / max(w6d, 1e-6):.1f}x)."
        )
    if w2d and w3d:
        print(
            f"  - Plain LLM chat: median demo hand ~ {w2d:.2f} min vs generator ~ {w3d:.2f} min "
            f"(generator surface saves ~{max(0.0, w2d - w3d):.2f} min in this draw)."
        )
    if w6r and w1r:
        print(f"  - Median time-to-robust (successes): W6 ~ {w6r:.2f} min vs W1 ~ {w1r:.2f} min.")
    print(
        f"  - W6 mean pass@1: {summ['W6_gen_react']['mean_instant_demo_ok']:.2f}; "
        f"final robust: {summ['W6_gen_react']['mean_final_robust_ok']:.2f}"
    )
    print(f"\nWrote: {args.out}")
    print(f"Wrote: {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
