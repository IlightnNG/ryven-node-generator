"""
Generate synthetic trial data aligned with `strategy/GENERATOR_EVALUATION_STRATEGY.md`
and export high-clarity figures (Plotly + Kaleido).

The synthetic dataset is *illustrative only* — replace CSV with measured trials before thesis submission.

Usage:
  pip install -r scripts/evaluation/requirements-figures.txt
  python scripts/evaluation/plot_strategy_results.py
  python scripts/evaluation/plot_strategy_results.py --csv scripts/evaluation/data/strategy_trials_synthetic.csv
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

try:
    from scipy.stats import mannwhitneyu
except ImportError:
    mannwhitneyu = None


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


_WORKFLOWS: tuple[str, ...] = (
    "W1_manual",
    "W2_chat",
    "W3_single_agent",
    "W4_three_stage",
    "W5_react",
)

_LABELS: dict[str, str] = {
    "W1_manual": "W1 Manual (no LLM)",
    "W2_chat": "W2 Manual + plain LLM chat",
    "W3_single_agent": "W3 Single-turn agent",
    "W4_three_stage": "W4 3-stage pipeline",
    "W5_react": "W5 ReAct tool loop",
}

_COLORS: dict[str, str] = {
    "W1_manual": "#4E79A7",
    "W2_chat": "#EDC948",
    "W3_single_agent": "#59A14F",
    "W4_three_stage": "#B279A2",
    "W5_react": "#E15759",
}


def _apply_template() -> None:
    pio.templates["strategy"] = go.layout.Template(
        layout=go.Layout(
            font=dict(family="Segoe UI, Microsoft YaHei, Arial, sans-serif", size=13, color="#1f2933"),
            # Center the title above the plot.
            title=dict(font=dict(size=17, color="#111827"), x=0.5, xanchor="center"),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#F8FAFC",
            xaxis=dict(
                showline=True,
                linewidth=1,
                linecolor="#CBD5E1",
                gridcolor="#E2E8F0",
                zeroline=False,
                tickfont=dict(size=12),
            ),
            yaxis=dict(
                showline=True,
                linewidth=1,
                linecolor="#CBD5E1",
                gridcolor="#E2E8F0",
                zeroline=False,
                tickfont=dict(size=12),
            ),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                # Put legend above plotting area AND above title block.
                # (Mitigates title/legend overlap when exporting static images.)
                y=1.18,
                xanchor="left",
                x=0,
                bgcolor="rgba(255,255,255,0.86)",
                bordercolor="#E5E7EB",
                borderwidth=1,
            ),
            # More top margin to avoid title/legend overlap.
            margin=dict(l=200, r=200, t=250, b=100),
        )
    )
    pio.templates.default = "strategy"


def _task_band(task_id: str) -> str:
    n = int(task_id.replace("N", ""))
    if n <= 8:
        return "L1"
    if n <= 16:
        return "L2"
    return "L3"


def _wilson_ci(p: float, n: int, z: float = 1.96) -> tuple[float, float]:
    if n <= 0:
        return (float("nan"), float("nan"))
    phat = min(max(p, 0.0), 1.0)
    denom = 1 + z**2 / n
    center = (phat + z**2 / (2 * n)) / denom
    half = (z / denom) * math.sqrt(phat * (1 - phat) / n + z**2 / (4 * n * n))
    return max(0.0, center - half), min(1.0, center + half)


def generate_synthetic_trials(*, seed: int, n_runs: int = 2) -> pd.DataFrame:
    """Produce a plausible *tidy* trial table (20 tasks × workflows × runs).

    Narrative baked in (not real measurements):
    - Manual slowest; chat modest help but brittle;
    - Single agent faster; 3-stage improves first-shot;
    - ReAct: highest pass@1, moderate wall-clock, more tool calls / rounds.
    """
    rng = np.random.default_rng(seed)
    task_ids = [f"N{i:02d}" for i in range(1, 21)]
    rows: list[dict] = []

    # Difficulty raises baseline minutes for a "good" implementation pathway.
    base_demo = {"L1": 11.0, "L2": 19.0, "L3": 31.0}

    wf_meta = {
        "W1_manual": {
            "time_mult": 1.95,
            "time_jitter": 3.6,
            "p_instant": 0.60,
            "p_instant_dl": {"L1": 0.0, "L2": -0.06, "L3": -0.10},
            "p_final": 0.86,
            "p_final_dl": {"L1": 0.05, "L2": -0.03, "L3": -0.08},
            "validation_on": False,
            "loop_mode": "none",
            "rounds": (0, 0),
            "tools": (0, 0),
        },
        "W2_chat": {
            "time_mult": 1.55,
            "time_jitter": 3.2,
            "p_instant": 0.52,
            "p_instant_dl": {"L1": 0.0, "L2": -0.07, "L3": -0.12},
            "p_final": 0.78,
            "p_final_dl": {"L1": 0.04, "L2": -0.06, "L3": -0.11},
            "validation_on": False,
            "loop_mode": "none",
            "rounds": (0, 0),
            "tools": (0, 0),
        },
        "W3_single_agent": {
            "time_mult": 0.58,
            "time_jitter": 2.4,
            "p_instant": 0.72,
            "p_instant_dl": {"L1": 0.0, "L2": -0.05, "L3": -0.09},
            "p_final": 0.90,
            "p_final_dl": {"L1": 0.03, "L2": -0.02, "L3": -0.06},
            "validation_on": True,
            "loop_mode": "single",
            "rounds": (1, 1),
            "tools": (3, 9),
        },
        "W4_three_stage": {
            "time_mult": 0.48,
            "time_jitter": 2.0,
            "p_instant": 0.80,
            "p_instant_dl": {"L1": 0.0, "L2": -0.04, "L3": -0.07},
            "p_final": 0.94,
            "p_final_dl": {"L1": 0.02, "L2": -0.02, "L3": -0.05},
            "validation_on": True,
            "loop_mode": "3stage",
            "rounds": (3, 3),
            "tools": (9, 18),
        },
        "W5_react": {
            "time_mult": 0.54,
            "time_jitter": 2.6,
            "p_instant": 0.88,
            "p_instant_dl": {"L1": 0.0, "L2": -0.03, "L3": -0.05},
            "p_final": 0.97,
            "p_final_dl": {"L1": 0.01, "L2": -0.01, "L3": -0.03},
            "validation_on": True,
            "loop_mode": "react",
            "rounds": (2, 7),
            "tools": (12, 38),
        },
    }

    err_pool = ["stub_mismatch", "syntax_error", "validation_error", "off_by_one_ports", "none"]

    for task_id in task_ids:
        band = _task_band(task_id)
        b0 = float(base_demo[band])
        for wf in _WORKFLOWS:
            meta = wf_meta[wf]
            for run_id in range(1, n_runs + 1):
                p_inst = float(np.clip(meta["p_instant"] + meta["p_instant_dl"][band] + rng.normal(0, 0.02), 0.05, 0.98))
                p_fin = float(np.clip(meta["p_final"] + meta["p_final_dl"][band] + rng.normal(0, 0.02), 0.05, 0.995))

                # wall clock to demo (minutes): log-normal-ish positive
                med = max(3.0, b0 * meta["time_mult"])
                sigma = meta["time_jitter"] * (1.15 if band == "L3" else 1.0)
                t_demo = float(rng.normal(med, sigma))
                t_demo = float(max(2.5, t_demo))

                instant_ok = bool(rng.random() < p_inst)

                rounds_lo, rounds_hi = meta["rounds"]
                tools_lo, tools_hi = meta["tools"]
                llm_rounds = int(rng.integers(rounds_lo, rounds_hi + 1)) if rounds_hi > 0 else 0
                tool_calls = int(rng.integers(tools_lo, tools_hi + 1)) if tools_hi > 0 else 0
                if wf == "W5_react":
                    # correlate time slightly with rounds (more debugging on harder tasks)
                    t_demo += 0.9 * max(0, llm_rounds - 3)
                    tool_calls = int(max(tools_lo, tool_calls + 2 * max(0, llm_rounds - 3)))

                # rework for first-shot failures
                if not instant_ok:
                    t_demo += float(rng.uniform(4.0, 14.0) * (1.25 if band == "L3" else 1.0))
                    err = str(rng.choice(err_pool[:-1]))  # not none
                else:
                    err = "none"

                instant_flag = 1 if instant_ok else 0

                final_ok = bool(rng.random() < p_fin)
                if not final_ok:
                    t_rob = float("nan")
                    err_top = str(rng.choice(["stub_mismatch", "robust_case_fail", "timeout"]))
                else:
                    # reaching robust: extra work beyond demo, larger when demo wasn't instant
                    extra = rng.uniform(3.0, 10.0)
                    if not instant_ok:
                        extra += rng.uniform(8.0, 22.0) * (1.35 if wf in {"W1_manual", "W2_chat"} else 1.0)
                    if band == "L3":
                        extra *= 1.18
                    t_rob = float(max(t_demo + extra, t_demo + 2.0))
                    err_top = "none"

                rows.append(
                    {
                        "task_id": task_id,
                        "task_band": band,
                        "workflow": wf,
                        "workflow_label": _LABELS[wf],
                        "run_id": run_id,
                        "operator": "synthetic_operator_A",
                        "time_to_demo_min": round(t_demo, 2),
                        "instant_demo_ok": instant_flag,
                        "time_to_robust_min": (round(t_rob, 2) if final_ok and not math.isnan(t_rob) else ""),
                        "final_robust_ok": int(final_ok),
                        "validation_on": int(bool(meta["validation_on"])),
                        "loop_mode": meta["loop_mode"],
                        "llm_rounds": llm_rounds,
                        "tool_calls": tool_calls,
                        "errors_top": err_top,
                        "notes": "SYNTHETIC — replace with measured trials before submission",
                    }
                )

    df = pd.DataFrame(rows)
    # stable sort for reproducible diffs
    return df.sort_values(["workflow", "task_id", "run_id"], kind="mergesort").reset_index(drop=True)


def _workflow_cat(df: pd.DataFrame, col: str = "workflow_label") -> pd.Categorical:
    order = [_LABELS[w] for w in _WORKFLOWS]
    return pd.Categorical(df[col], categories=order, ordered=True)


def fig_times_two_panel(df: pd.DataFrame) -> go.Figure:
    df = df.copy()
    df["workflow_label"] = _workflow_cat(df, "workflow_label")

    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=(
            "M1: Time-to-Demo (minutes)",
            "M3: Time-to-Robust (minutes, successful trials only)",
        ),
        horizontal_spacing=0.09,
    )

    for wf in _WORKFLOWS:
        sub = df.loc[df["workflow"] == wf]
        lbl = _LABELS[wf]
        fig.add_trace(
            go.Box(
                x=sub["time_to_demo_min"],
                y=[lbl] * len(sub),
                name=lbl,
                marker_color=_COLORS[wf],
                line=dict(color="#0F172A", width=1),
                fillcolor=_COLORS[wf],
                opacity=0.55,
                boxpoints="all",
                jitter=0.28,
                pointpos=0,
                orientation="h",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        sub_ok = sub.loc[sub["final_robust_ok"] == 1].copy()
        sub_ok["tro"] = pd.to_numeric(sub_ok["time_to_robust_min"], errors="coerce")
        sub_ok = sub_ok.dropna(subset=["tro"])
        if sub_ok.empty:
            continue
        fig.add_trace(
            go.Box(
                x=sub_ok["tro"],
                y=[lbl] * len(sub_ok),
                name=lbl,
                marker_color=_COLORS[wf],
                line=dict(color="#0F172A", width=1),
                fillcolor=_COLORS[wf],
                opacity=0.55,
                boxpoints="all",
                jitter=0.28,
                pointpos=0,
                orientation="h",
                showlegend=False,
            ),
            row=1,
            col=2,
        )

    fig.update_xaxes(title_text="Minutes", row=1, col=1, automargin=True)
    fig.update_xaxes(title_text="Minutes", row=1, col=2, automargin=True)
    fig.update_yaxes(categoryorder="array", categoryarray=[_LABELS[w] for w in _WORKFLOWS], row=1, col=1)
    fig.update_yaxes(categoryorder="array", categoryarray=[_LABELS[w] for w in _WORKFLOWS], row=1, col=2)

    fig.update_layout(
        title=dict(
            text="<b>Main results: time distributions</b><br>"
            "<sup>Box = quartiles; dots = individual trials. Robust time includes only final_robust_ok=1.</sup>",
            x=0.5,
            xanchor="center",
        ),
        height=560,
        width=1280,
        margin=dict(l=200, r=200, t=250, b=100),
    )
    return fig


def fig_success_rates(df: pd.DataFrame) -> go.Figure:
    rows = [df.loc[df["workflow"] == wf] for wf in _WORKFLOWS]
    labels = [_LABELS[w] for w in _WORKFLOWS]
    p_inst = [r["instant_demo_ok"].mean() for r in rows]
    p_fin = [r["final_robust_ok"].mean() for r in rows]
    n = [len(r) for r in rows]

    inst_lo = [_wilson_ci(p_inst[i], n[i])[0] for i in range(len(rows))]
    inst_hi = [_wilson_ci(p_inst[i], n[i])[1] for i in range(len(rows))]
    fin_lo = [_wilson_ci(p_fin[i], n[i])[0] for i in range(len(rows))]
    fin_hi = [_wilson_ci(p_fin[i], n[i])[1] for i in range(len(rows))]

    fig = go.Figure()
    x = np.arange(len(labels))
    w = 0.34
    fig.add_trace(
        go.Bar(
            name="M2 pass@1 (instant demo)",
            x=x - w / 2,
            y=p_inst,
            width=w,
            marker=dict(color="#2563EB", line=dict(color="#0F172A", width=1)),
            text=[f"{v*100:.1f}%" for v in p_inst],
            textposition="auto",
            error_y=dict(type="data", symmetric=False, array=[hi - pi for hi, pi in zip(inst_hi, p_inst, strict=True)], arrayminus=[pi - lo for pi, lo in zip(p_inst, inst_lo, strict=True)], visible=True, thickness=1.8, color="#64748B"),
        )
    )
    fig.add_trace(
        go.Bar(
            name="Final robust success rate",
            x=x + w / 2,
            y=p_fin,
            width=w,
            marker=dict(color="#16A34A", line=dict(color="#0F172A", width=1)),
            text=[f"{v*100:.1f}%" for v in p_fin],
            textposition="auto",
            error_y=dict(type="data", symmetric=False, array=[hi - pf for hi, pf in zip(fin_hi, p_fin, strict=True)], arrayminus=[pf - lo for pf, lo in zip(p_fin, fin_lo, strict=True)], visible=True, thickness=1.8, color="#64748B"),
        )
    )

    fig.update_xaxes(tickvals=x, ticktext=labels, tickangle=-18, automargin=True)
    fig.update_yaxes(title_text="Rate (0–1)", range=[0, 1.08], tickformat=".0%")
    fig.update_layout(
        title=dict(
            text="<b>Correctness rates (with Wilson 95% intervals)</b><br>"
            "<sup>Aggregated across trials; error bars approximate 95% confidence intervals.</sup>",
            x=0.5,
            xanchor="center",
        ),
        barmode="overlay",
        bargap=0.22,
        height=560,
        width=1180,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            # Move legend downward a bit (reduces legend height/overlap on static exports).
            y=1.10,
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(l=200, r=200, t=250, b=100),
    )
    return fig


def fig_median_summary(df: pd.DataFrame) -> go.Figure:
    meds_demo, meds_rob = [], []
    for wf in _WORKFLOWS:
        sub = df.loc[df["workflow"] == wf]
        meds_demo.append(float(np.median(sub["time_to_demo_min"])))
        sub_ok = sub.loc[sub["final_robust_ok"] == 1].copy()
        tro = pd.to_numeric(sub_ok["time_to_robust_min"], errors="coerce").dropna()
        meds_rob.append(float(np.median(tro)) if len(tro) else float("nan"))

    labels = [_LABELS[wj] for wj in _WORKFLOWS]
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            name="median(time_to_demo)",
            x=labels,
            y=meds_demo,
            marker=dict(color=[_COLORS[w] for w in _WORKFLOWS], line=dict(color="#0F172A", width=1)),
            text=[f"{v:.1f}" for v in meds_demo],
            textposition="auto",
        )
    )
    fig.add_trace(
        go.Bar(
            name="median(time_to_robust | success)",
            x=labels,
            y=meds_rob,
            marker=dict(color=[_COLORS[w] for w in _WORKFLOWS], line=dict(color="#0F172A", width=1), opacity=0.55, pattern_shape="/"),
            text=[("" if math.isnan(v) else f"{v:.1f}") for v in meds_rob],
            textposition="auto",
        )
    )
    fig.update_layout(
        title=dict(
            text="<b>Median time summary (minutes)</b><br><sup>Robust column uses successful trials only: final_robust_ok=1</sup>",
            x=0.5,
            xanchor="center",
        ),
        barmode="group",
        height=560,
        width=1180,
        yaxis_title="Minutes",
        legend=dict(
            orientation="h",
            y=1.10,
            yanchor="bottom",
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(l=200, r=200, t=250, b=100),
    )
    return fig


def fig_react_diagnostic(df: pd.DataFrame) -> go.Figure:
    sub = df.loc[df["workflow"] == "W5_react"].copy()
    sub["band"] = sub["task_id"].map(_task_band)
    palette = {"L1": "#22C55E", "L2": "#F59E0B", "L3": "#EF4444"}
    fig = go.Figure()
    for band in ("L1", "L2", "L3"):
        s = sub.loc[sub["band"] == band]
        fig.add_trace(
            go.Scatter(
                x=s["llm_rounds"],
                y=s["time_to_demo_min"],
                mode="markers",
                name=f"{band} difficulty",
                marker=dict(size=np.clip(s["tool_calls"] / 2.2 + 6, 8, 26), color=palette[band], opacity=0.75, line=dict(width=1, color="white")),
                text=s["task_id"] + "<br>run=" + s["run_id"].astype(str),
                hovertemplate="%{text}<br>rounds=%{x}<br>demo_min=%{y}<extra></extra>",
            )
        )
    fig.update_layout(
        title=dict(
            text="<b>W5 (ReAct) diagnostics: rounds × time-to-demo</b><br><sup>Bubble size ≈ tool_calls (proxy for loop workload)</sup>",
            x=0.5,
            xanchor="center",
        ),
        xaxis_title="LLM rounds (logged)",
        yaxis_title="time_to_demo_min",
        height=560,
        width=980,
        legend=dict(
            orientation="h",
            y=1.10,
            yanchor="bottom",
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(l=200, r=200, t=250, b=100),
    )
    return fig


def fig_failure_mix(df: pd.DataFrame) -> go.Figure:
    sub = df.loc[df["instant_demo_ok"] == 0].copy()
    if sub.empty:
        return go.Figure(
            layout=go.Layout(title="No instant failures in dataset", height=420, width=900)
        )

    g = (
        sub.assign(errors_top=sub["errors_top"].fillna("unknown"))
        .groupby(["workflow_label", "errors_top"], observed=True)
        .size()
        .reset_index(name="count")
    )
    workflows = [_LABELS[w] for w in _WORKFLOWS]
    pivot = g.pivot(index="workflow_label", columns="errors_top", values="count").reindex(workflows).fillna(0)

    fig = go.Figure()
    for col in list(pivot.columns):
        fig.add_trace(
            go.Bar(name=str(col), x=pivot.index.astype(str), y=pivot[col].to_numpy(float), marker=dict(line=dict(width=1, color="#0F172A")))
        )
    fig.update_layout(
        title=dict(
            text="<b>Instant-demo failure reasons (instant_demo_ok=0)</b><br><sup>Stacked counts: highlights brittleness patterns</sup>",
            x=0.5,
            xanchor="center",
        ),
        barmode="stack",
        height=560,
        width=1200,
        xaxis=dict(tickangle=-18),
        yaxis_title="Trial count",
        legend=dict(
            orientation="h",
            y=1.12,
            yanchor="bottom",
            x=0,
            xanchor="left",
            font=dict(size=11),
        ),
        margin=dict(l=200, r=200, t=250, b=100),
    )
    return fig


def fig_dashboard(df: pd.DataFrame) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "Time-to-demo distribution",
            "Success rates + 95% intervals",
            "Median time (grouped bars)",
            "W5 diagnostic scatter",
        ),
        specs=[[{"type": "box"}, {"type": "bar"}], [{"type": "bar"}, {"type": "scatter"}]],
        vertical_spacing=0.15,
        horizontal_spacing=0.11,
    )

    # Panel A: demo times (mini box per wf - use violin simplified as bar? use box traces)
    for wf in _WORKFLOWS:
        sub = df.loc[df["workflow"] == wf]
        lbl = _LABELS[wf]
        fig.add_trace(
            go.Box(
                x=sub["time_to_demo_min"],
                y=[lbl] * len(sub),
                marker_color=_COLORS[wf],
                line=dict(color="#0F172A", width=1),
                fillcolor=_COLORS[wf],
                opacity=0.55,
                orientation="h",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

    # Panel B: instant + final as grouped bars (simplified: two series)
    rows_wf = [df.loc[df["workflow"] == wf] for wf in _WORKFLOWS]
    labels = [_LABELS[w] for w in _WORKFLOWS]
    p_inst = [r["instant_demo_ok"].mean() for r in rows_wf]
    p_fin = [r["final_robust_ok"].mean() for r in rows_wf]
    n = [len(r) for r in rows_wf]
    inst_err_plus = [_wilson_ci(p_inst[i], n[i])[1] - p_inst[i] for i in range(5)]
    inst_err_minus = [p_inst[i] - _wilson_ci(p_inst[i], n[i])[0] for i in range(5)]
    fin_err_plus = [_wilson_ci(p_fin[i], n[i])[1] - p_fin[i] for i in range(5)]
    fin_err_minus = [p_fin[i] - _wilson_ci(p_fin[i], n[i])[0] for i in range(5)]

    x = np.arange(5)
    w = 0.35
    fig.add_trace(
        go.Bar(
            name="Instant demo",
            x=x - w / 2,
            y=p_inst,
            width=w,
            marker=dict(color="#2563EB"),
            error_y=dict(type="data", symmetric=False, array=inst_err_plus, arrayminus=inst_err_minus, thickness=2, color="#64748B"),
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.add_trace(
        go.Bar(
            name="Final robust",
            x=x + w / 2,
            y=p_fin,
            width=w,
            marker=dict(color="#16A34A"),
            error_y=dict(type="data", symmetric=False, array=fin_err_plus, arrayminus=fin_err_minus, thickness=2, color="#64748B"),
            showlegend=False,
        ),
        row=1,
        col=2,
    )
    fig.update_xaxes(tickvals=x, ticktext=labels, tickangle=-22, row=1, col=2)

    # Panel C: median demo bars
    meds = [float(np.median(df.loc[df["workflow"] == wf, "time_to_demo_min"])) for wf in _WORKFLOWS]
    fig.add_trace(
        go.Bar(
            x=labels,
            y=meds,
            marker=dict(color=[_COLORS[w] for w in _WORKFLOWS], line=dict(color="#0F172A", width=1)),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    # Panel D: react
    rdf = df.loc[df["workflow"] == "W5_react"]
    fig.add_trace(
        go.Scatter(
            x=rdf["llm_rounds"],
            y=rdf["time_to_demo_min"],
            mode="markers",
            marker=dict(size=12, color=_COLORS["W5_react"], opacity=0.75, line=dict(width=1, color="white")),
            showlegend=False,
        ),
        row=2,
        col=2,
    )

    fig.update_layout(
        title=dict(
            text="<b>Synthetic evaluation dashboard (layout preview)</b><br><sup>Illustrative only — replace with measured CSV before thesis submission.</sup>",
            x=0.5,
            xanchor="center",
        ),
        height=1060,
        width=1360,
        margin=dict(l=200, r=200, t=250, b=100),
    )
    fig.update_yaxes(title_text="Rate", row=1, col=2)
    fig.update_yaxes(title_text="Minutes", row=2, col=1)
    fig.update_xaxes(title_text="LLM rounds", row=2, col=2)
    fig.update_yaxes(title_text="demo_min", row=2, col=2)
    return fig


def _mannwhitney_manual_vs_best(df: pd.DataFrame) -> str:
    if mannwhitneyu is None:
        return "Mann–Whitney: scipy not installed (optional)."
    m = df.loc[df["workflow"] == "W1_manual", "time_to_demo_min"].to_numpy(float)
    # compare to W5 as "system condition"
    g = df.loc[df["workflow"] == "W5_react", "time_to_demo_min"].to_numpy(float)
    if m.size == 0 or g.size == 0:
        return "Mann–Whitney: insufficient samples."
    try:
        _, p = mannwhitneyu(m, g, alternative="two-sided")
        return f"Mann–Whitney (W1 vs W5, time-to-demo, two-sided): p={p:.3g}"
    except ValueError:
        return "Mann–Whitney: could not compute (possibly all equal)."


def _write_static(fig: go.Figure, base: Path, *, width: int, height: int) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(base.with_suffix(".pdf"), width=width, height=height, scale=2)
    fig.write_image(base.with_suffix(".png"), width=width, height=height, scale=2)


def _write_html(fig: go.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(
        str(base.with_suffix(".html")),
        full_html=True,
        include_plotlyjs="cdn",
        config={"responsive": True, "displaylogo": False},
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot strategy evaluation figures from CSV (or synthesize).")
    parser.add_argument("--csv", type=Path, default=None, help="Input tidy trials CSV (optional).")
    parser.add_argument("--out-dir", type=Path, default=_repo_root() / "build" / "figures" / "strategy")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--runs", type=int, default=2, help="Runs per task×workflow when synthesizing.")
    parser.add_argument(
        "--write-csv",
        type=Path,
        default=_repo_root() / "scripts" / "evaluation" / "data" / "strategy_trials_synthetic.csv",
        help="Where to write synthesized CSV.",
    )
    parser.add_argument("--no-synth", action="store_true", help="Require --csv; do not synthesize.")
    args = parser.parse_args(argv)

    _apply_template()

    if args.csv and args.csv.is_file():
        df = pd.read_csv(args.csv)
    elif args.no_synth:
        print("Missing --csv or file not found.", file=sys.stderr)
        return 2
    else:
        df = generate_synthetic_trials(seed=args.seed, n_runs=args.runs)
        args.write_csv.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.write_csv, index=False, encoding="utf-8-sig")
        print("Wrote synthetic CSV:", args.write_csv)

    required = {
        "task_id",
        "workflow",
        "run_id",
        "time_to_demo_min",
        "instant_demo_ok",
        "time_to_robust_min",
        "final_robust_ok",
    }
    missing = required - set(df.columns)
    if missing:
        print(f"CSV missing columns: {sorted(missing)}", file=sys.stderr)
        return 2

    f1 = fig_times_two_panel(df)
    _write_static(f1, args.out_dir / "fig-strategy-01-times-demo-robust", width=1460, height=760)
    _write_html(f1, args.out_dir / "fig-strategy-01-times-demo-robust")

    f2 = fig_success_rates(df)
    _write_static(f2, args.out_dir / "fig-strategy-02-success-rates", width=1360, height=760)
    _write_html(f2, args.out_dir / "fig-strategy-02-success-rates")

    f3 = fig_median_summary(df)
    _write_static(f3, args.out_dir / "fig-strategy-03-median-summary", width=1360, height=760)
    _write_html(f3, args.out_dir / "fig-strategy-03-median-summary")

    f4 = fig_react_diagnostic(df)
    _write_static(f4, args.out_dir / "fig-strategy-04-react-diagnostic", width=1160, height=760)
    _write_html(f4, args.out_dir / "fig-strategy-04-react-diagnostic")

    f5 = fig_failure_mix(df)
    _write_static(f5, args.out_dir / "fig-strategy-05-failure-mix", width=1420, height=780)
    _write_html(f5, args.out_dir / "fig-strategy-05-failure-mix")

    fd = fig_dashboard(df)
    _write_static(fd, args.out_dir / "fig-strategy-00-dashboard", width=1560, height=1260)
    _write_html(fd, args.out_dir / "fig-strategy-00-dashboard")

    stems = [
        "fig-strategy-00-dashboard",
        "fig-strategy-01-times-demo-robust",
        "fig-strategy-02-success-rates",
        "fig-strategy-03-median-summary",
        "fig-strategy-04-react-diagnostic",
        "fig-strategy-05-failure-mix",
    ]
    print("Wrote:")
    for stem in stems:
        for suf in (".pdf", ".png", ".html"):
            print(" ", args.out_dir / f"{stem}{suf}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
