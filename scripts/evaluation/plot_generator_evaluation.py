"""
Ryven Node Generator — multi-workflow evaluation figures (Thesis Ch. §8.2.2 / §8.2.4).

Uses Plotly (+ Kaleido) for high-clarity static exports (PDF/PNG). Workflows can include:
  manual, generator-only GUI, AI single-turn without validation, AI single-turn with checks,
  and ReAct-style loops with validation until the package imports cleanly.

CSV inputs (default under scripts/evaluation/data/):
  - generator_task_times.csv
  - generator_loc.csv

Replace placeholder rows with your study data before submission.

Usage:
  pip install -r scripts/evaluation/requirements-figures.txt
  python scripts/evaluation/plot_generator_evaluation.py
  python scripts/evaluation/plot_generator_evaluation.py --out-dir build/figures
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots

try:
    from scipy.stats import kruskal, mannwhitneyu
except ImportError:
    kruskal = None
    mannwhitneyu = None


# --- Workflow catalogue (order = bottom-to-top on horizontal charts) ---
_WORKFLOW_ORDER: tuple[str, ...] = (
    "manual",
    "generator_gui",
    "ai_1shot_no_check",
    "ai_1shot_validated",
    "ai_react_validated",
)

_DISPLAY: dict[str, str] = {
    "manual": "① Hand-written package",
    "generator_gui": "② Generator (templates only)",
    "ai_1shot_no_check": "③ AI 1-shot · no validation gate",
    "ai_1shot_validated": "④ AI 1-shot · AST/JSON validated",
    "ai_react_validated": "⑤ ReAct + validation · until import succeeds",
}

# Cohesive categorical palette (color-blind–friendly-ish, distinct steps)
_PALETTE: dict[str, str] = {
    "manual": "#4E79A7",
    "generator_gui": "#59A14F",
    "ai_1shot_no_check": "#EDC948",
    "ai_1shot_validated": "#F28E2B",
    "ai_react_validated": "#E15759",
}

_infer_validation_loop: dict[str, tuple[bool, str]] = {
    "manual": (False, "none"),
    "generator_gui": (False, "none"),
    "ai_1shot_no_check": (False, "single"),
    "ai_1shot_validated": (True, "single"),
    "ai_react_validated": (True, "react"),
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _apply_plotly_defaults() -> None:
    pio.templates["thesis"] = go.layout.Template(
        layout=go.Layout(
            font=dict(family="Segoe UI, Arial, Helvetica, sans-serif", size=13, color="#1f2933"),
            title=dict(font=dict(size=16), x=0.0, xanchor="left"),
            paper_bgcolor="#FFFFFF",
            plot_bgcolor="#F7F8FA",
            colorway=list(_PALETTE.values()),
            xaxis=dict(showline=True, linewidth=1, linecolor="#CFD8DC", gridcolor="#ECEFF1", zeroline=False),
            yaxis=dict(showline=True, linewidth=1, linecolor="#CFD8DC", gridcolor="#ECEFF1", zeroline=False),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(255,255,255,0.85)"),
            margin=dict(l=72, r=48, t=96, b=80),
        )
    )


def _write_static(fig: go.Figure, base: Path, *, width: int = 1280, height: int = 720) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(base.with_suffix(".pdf"), width=width, height=height, scale=2)
    fig.write_image(base.with_suffix(".png"), width=width, height=height, scale=2)


def _parse_bool_series(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s

    def _one(v: object) -> bool:
        if pd.isna(v):
            return False
        t = str(v).strip().lower()
        if t in {"", "nan"}:
            return False
        return t in {"1", "true", "yes", "y"}

    return s.map(_one)


def load_times(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if "minutes" not in df.columns:
        raise ValueError(f"{csv_path} must contain column 'minutes'")

    if "workflow" in df.columns:
        df = df.rename(columns={"workflow": "workflow_key"})
    elif "condition" in df.columns:
        df = df.rename(columns={"condition": "workflow_key"})
    else:
        raise ValueError(f"{csv_path}: need column 'workflow' (or legacy 'condition')")

    df["workflow_key"] = df["workflow_key"].astype(str).str.strip()
    _aliases = {
        "generator": "generator_gui",
        "tool": "generator_gui",
        "hand": "manual",
    }
    df["workflow_key"] = df["workflow_key"].str.lower().map(lambda k: _aliases.get(k, k))

    if "validation" not in df.columns:
        df["validation"] = np.nan
    if "loop_mode" not in df.columns:
        df["loop_mode"] = np.nan

    for col in ("validation", "loop_mode"):
        mask = df[col].isna() | (df[col].astype(str).str.strip() == "")
        if mask.any():
            for i in df.index[mask]:
                key = df.at[i, "workflow_key"]
                if key in _infer_validation_loop:
                    v, lm = _infer_validation_loop[key]
                    if col == "validation":
                        df.at[i, "validation"] = v
                    else:
                        df.at[i, "loop_mode"] = lm

    df["validation_flag"] = _parse_bool_series(df["validation"])
    df["loop_mode"] = df["loop_mode"].astype(str).str.strip()

    if "success" not in df.columns:
        df["success"] = True
    df["success_flag"] = _parse_bool_series(df["success"])

    for opt in ("llm_rounds", "tool_calls"):
        if opt not in df.columns:
            df[opt] = np.nan
        else:
            df[opt] = pd.to_numeric(df[opt], errors="coerce")

    known = set(_WORKFLOW_ORDER)
    unknown = sorted(set(df["workflow_key"].unique()) - known)
    if unknown:
        raise ValueError(
            f"Unknown workflow keys {unknown}. Extend _WORKFLOW_ORDER / _DISPLAY in plot_generator_evaluation.py."
        )

    df["workflow_label"] = df["workflow_key"].map(_DISPLAY).fillna(df["workflow_key"])
    df["minutes"] = pd.to_numeric(df["minutes"], errors="coerce")
    df = df.dropna(subset=["minutes"])
    return df


def load_loc(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    for c in ("boilerplate_lines", "custom_logic_lines", "total_lines"):
        if c not in df.columns:
            raise ValueError(f"{csv_path} missing column: {c}")
    key_col = "workflow_key" if "workflow_key" in df.columns else "series"
    if key_col not in df.columns:
        raise ValueError(f"{csv_path} needs 'workflow_key' or legacy 'series' column")
    if key_col == "series":
        df = df.rename(columns={"series": "workflow_key"})
    label_col = "label" if "label" in df.columns else "series"
    if label_col not in df.columns:
        df["label"] = df["workflow_key"].map(_DISPLAY).fillna(df["workflow_key"])
    return df


def _ordered_labels(df: pd.DataFrame) -> list[str]:
    keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    return [ _DISPLAY[k] for k in keys ]


def _median_iqr(s: pd.Series) -> tuple[float, float, float]:
    s = s.dropna().astype(float)
    if s.empty:
        return float("nan"), float("nan"), float("nan")
    med = float(s.median())
    q1, q3 = float(s.quantile(0.25)), float(s.quantile(0.75))
    return med, med - q1, q3 - med


def fig_workflow_distribution(df: pd.DataFrame, task_note: str) -> go.Figure:
    labels = _ordered_labels(df)
    cat_keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    df_plot = df.copy()
    df_plot["workflow_label"] = pd.Categorical(df_plot["workflow_label"], categories=labels, ordered=True)

    fig = go.Figure()
    for key in cat_keys:
        sub = df_plot.loc[df_plot["workflow_key"] == key]
        if sub.empty:
            continue
        fig.add_trace(
            go.Box(
                x=sub["minutes"],
                y=[_DISPLAY[key]] * len(sub),
                marker_color=_PALETTE[key],
                line=dict(color="#263238"),
                fillcolor=_PALETTE[key],
                opacity=0.55,
                boxmean="sd",
                quartilemethod="linear",
                pointpos=0,
                jitter=0.35,
                boxpoints="all",
                marker=dict(size=8, opacity=0.75, color=_PALETTE[key], line=dict(width=0.6, color="white")),
                orientation="h",
                showlegend=False,
            )
        )

    fig.update_layout(
        template="thesis",
        title="Completion time by authoring workflow <sup>(box + jittered trials)</sup>",
        xaxis_title="Wall-clock time (minutes)",
        yaxis_title="",
        boxmode="overlay",
        height=520,
        width=1100,
    )
    fig.update_yaxes(categoryorder="array", categoryarray=labels)
    annotation = (
        f"<b>Task</b>: {task_note}<br>"
        f"<b>Note</b>: replace CSV with measured data; success/failure flags affect secondary charts."
    )
    fig.add_annotation(
        text=annotation,
        xref="paper",
        yref="paper",
        x=0,
        y=-0.22,
        showarrow=False,
        align="left",
        font=dict(size=11, color="#37474F"),
        bordercolor="#CFD8DC",
        borderwidth=1,
        borderpad=8,
        bgcolor="rgba(255,255,255,0.9)",
    )
    return fig


def fig_median_ranking(df: pd.DataFrame) -> go.Figure:
    rows = []
    err_lo, err_hi = [], []
    keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    for key in keys:
        med, el, eh = _median_iqr(df.loc[df["workflow_key"] == key, "minutes"])
        rows.append((_DISPLAY[key], med, key))
        err_lo.append(el)
        err_hi.append(eh)
    rows.sort(key=lambda t: t[1])
    labels_sorted = [t[0] for t in rows]
    vals = [t[1] for t in rows]
    colors = [_PALETTE[t[2]] for t in rows]

    fig = go.Figure(
        go.Bar(
            x=vals,
            y=labels_sorted,
            orientation="h",
            marker=dict(color=colors, line=dict(color="#263238", width=0.6)),
            error_x=dict(type="data", symmetric=False, array=err_hi, arrayminus=err_lo, thickness=1.6, color="#455A64"),
            text=[f"{v:.2f} min" for v in vals],
            textposition="outside",
        )
    )
    fig.update_layout(
        template="thesis",
        title="Median completion time (IQR asymmetric error bars)",
        xaxis_title="Minutes",
        yaxis_title="",
        height=480,
        width=1000,
        showlegend=False,
    )
    return fig


def fig_success_and_load(df: pd.DataFrame) -> go.Figure:
    keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    labels = [_DISPLAY[k] for k in keys]
    rates = [df.loc[df["workflow_key"] == k, "success_flag"].mean() for k in keys]
    colors = [_PALETTE[k] for k in keys]

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=[100 * r for r in rates],
            marker=dict(color=colors, line=dict(color="#263238", width=0.6)),
            text=[f"{100 * r:.0f}%" for r in rates],
            textposition="outside",
        )
    )
    fig.update_layout(
        template="thesis",
        title="Observed success rate (trial → Ryven import OK) <sup>per protocol</sup>",
        yaxis_title="Success (%)",
        xaxis_title="",
        height=460,
        width=1100,
        yaxis_range=[0, min(115, 100 * max(rates) * 1.25 + 5) if rates else 100],
    )
    fig.update_xaxes(tickangle=-20)
    return fig


def fig_react_overhead(df: pd.DataFrame) -> go.Figure:
    sub = df.loc[df["workflow_key"] == "ai_react_validated"].copy()
    if sub.empty or sub["llm_rounds"].isna().all():
        fig = go.Figure()
        fig.update_layout(template="thesis", title="ReAct diagnostics — no rounds/tool_calls in CSV", height=400, width=900)
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=sub["llm_rounds"],
            y=sub["minutes"],
            mode="markers+text",
            marker=dict(size=sub["tool_calls"].fillna(4) * 1.2 + 6, color=_PALETTE["ai_react_validated"], opacity=0.75, line=dict(width=0.6, color="white")),
            text=sub["trial_id"].astype(str),
            textposition="top center",
            name="trials",
        )
    )
    fig.update_layout(
        template="thesis",
        title="ReAct workload vs wall-clock (marker size ≈ tool calls)",
        xaxis_title="LLM rounds (logged)",
        yaxis_title="Minutes",
        height=520,
        width=900,
        showlegend=False,
    )
    return fig


def fig_design_grid(df: pd.DataFrame) -> go.Figure:
    """Heatmap: validation × loop_mode → median minutes (aggregated)."""
    d = df.copy()
    d["validation_txt"] = np.where(d["validation_flag"], "validation on", "validation off")
    d["loop_txt"] = d["loop_mode"].replace({"none": "none (no LLM loop)", "single": "single-turn", "react": "react loop"})

    g = d.groupby(["validation_txt", "loop_txt"], dropna=False)["minutes"].median().reset_index()
    if g.empty:
        return go.Figure()
    piv = g.pivot(index="validation_txt", columns="loop_txt", values="minutes")

    fig = go.Figure(
        data=go.Heatmap(
            z=piv.values,
            x=list(piv.columns),
            y=list(piv.index),
            colorscale="Blues",
            reversescale=True,
            colorbar=dict(title="Median min"),
            text=np.round(piv.values, 2),
            texttemplate="%{text}",
            hovertemplate="Validation: %{y}<br>Loop: %{x}<br>Median: %{z:.2f} min<extra></extra>",
        )
    )
    fig.update_layout(
        template="thesis",
        title="Median time by experimental factors (validation × loop mode)",
        height=460,
        width=840,
        xaxis_title="Loop mode",
        yaxis_title="Validation",
    )
    return fig


def fig_loc_stacked(df_loc: pd.DataFrame) -> go.Figure:
    df = df_loc.copy()
    order_keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    df = df.set_index("workflow_key").reindex(order_keys).reset_index()
    df["boilerplate_lines"] = pd.to_numeric(df["boilerplate_lines"], errors="coerce").fillna(0)
    df["custom_logic_lines"] = pd.to_numeric(df["custom_logic_lines"], errors="coerce").fillna(0)
    df["label"] = df["workflow_key"].map(_DISPLAY).fillna(df["workflow_key"].astype(str))

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            y=df["label"],
            x=df["boilerplate_lines"],
            name="Boilerplate / Ryven glue",
            orientation="h",
            marker=dict(color="#90CAF9", line=dict(color="#263238", width=0.5)),
        )
    )
    fig.add_trace(
        go.Bar(
            y=df["label"],
            x=df["custom_logic_lines"],
            name="Matched task logic",
            orientation="h",
            marker=dict(color="#A5D6A7", line=dict(color="#263238", width=0.5)),
        )
    )
    fig.update_layout(
        template="thesis",
        barmode="stack",
        title="Code volume (nodes.py + gui.py) — same logical task across workflows",
        xaxis_title="Lines of code",
        yaxis_title="",
        height=520,
        width=1040,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, xanchor="left"),
    )
    return fig


def fig_dashboard(
    df: pd.DataFrame,
    df_loc: pd.DataFrame,
    task_note: str,
) -> go.Figure:
    fig = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "A. Trial distribution (horizontal box + points)",
            "B. Median ± IQR ranking",
            "C. Success rate (import OK)",
            "D. Design grid: median time (validation × loop)",
        ),
        vertical_spacing=0.14,
        horizontal_spacing=0.10,
    )

    labels = _ordered_labels(df)
    cat_keys = [k for k in _WORKFLOW_ORDER if k in set(df["workflow_key"].unique())]
    for key in cat_keys:
        sub = df.loc[df["workflow_key"] == key]
        if sub.empty:
            continue
        y_cat = [_DISPLAY[key]] * len(sub)
        fig.add_trace(
            go.Box(
                x=sub["minutes"],
                y=y_cat,
                name=_DISPLAY[key],
                marker_color=_PALETTE[key],
                opacity=0.55,
                boxpoints="all",
                jitter=0.3,
                pointpos=0,
                orientation="h",
                showlegend=False,
            ),
            row=1,
            col=1,
        )
    fig.update_yaxes(categoryorder="array", categoryarray=labels, row=1, col=1)

    keys = cat_keys
    medians = []
    for key in keys:
        med, _, _ = _median_iqr(df.loc[df["workflow_key"] == key, "minutes"])
        medians.append((key, _DISPLAY[key], med))
    medians.sort(key=lambda t: t[2])
    fig.add_trace(
        go.Bar(
            x=[t[2] for t in medians],
            y=[t[1] for t in medians],
            orientation="h",
            marker=dict(color=[_PALETTE[t[0]] for t in medians]),
            showlegend=False,
        ),
        row=1,
        col=2,
    )

    rates = [df.loc[df["workflow_key"] == k, "success_flag"].mean() for k in keys]
    fig.add_trace(
        go.Bar(
            x=[_DISPLAY[k] for k in keys],
            y=[100 * r for r in rates],
            marker=dict(color=[_PALETTE[k] for k in keys]),
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    grid = fig_design_grid(df)
    if grid.data:
        fig.add_trace(grid.data[0], row=2, col=2)

    fig.update_xaxes(title_text="Minutes", row=1, col=1)
    fig.update_xaxes(title_text="Median minutes", row=1, col=2)
    fig.update_yaxes(title_text="Success %", row=2, col=1)
    fig.update_xaxes(tickangle=-25, row=2, col=1)

    fig.update_layout(
        template="thesis",
        title=dict(text=f"<b>Generator evaluation — multi-workflow</b><br><sup>{task_note}</sup>", x=0, xanchor="left"),
        height=980,
        width=1320,
        margin=dict(t=120),
    )
    return fig


def _kruskal_sentence(df: pd.DataFrame) -> str:
    if kruskal is None:
        return "Kruskal–Wallis: scipy not available."
    groups = [df.loc[df["workflow_key"] == k, "minutes"].to_numpy(float) for k in _WORKFLOW_ORDER if k in df["workflow_key"].unique()]
    groups = [g for g in groups if g.size]
    if len(groups) < 2:
        return "Kruskal–Wallis: not enough groups."
    stat, p = kruskal(*groups)
    return f"Kruskal–Wallis across workflows: H={stat:.3g}, p={p:.3g}"


def fig_stat_inset_card(df: pd.DataFrame) -> go.Figure:
    """Small summary card figure for thesis margin / appendix."""
    manual = df.loc[df["workflow_key"] == "manual", "minutes"].to_numpy(float)
    gen = df.loc[df["workflow_key"] == "generator_gui", "minutes"].to_numpy(float)
    lines = [_kruskal_sentence(df)]
    if manual.size and gen.size and mannwhitneyu is not None:
        try:
            _, p = mannwhitneyu(manual, gen, alternative="two-sided")
            lines.append(f"Mann–Whitney (manual vs generator): p={p:.3g}")
        except ValueError:
            lines.append("Mann–Whitney: could not compute.")
    summary = "<br>".join(lines)
    fig = go.Figure(
        layout=go.Layout(
            annotations=[
                dict(
                    xref="paper",
                    yref="paper",
                    x=0,
                    y=0.5,
                    showarrow=False,
                    align="left",
                    text=f"<b>Nonparametric tests</b><br>{summary}",
                    font=dict(size=14),
                )
            ]
        )
    )
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(template="thesis", height=220, width=880, margin=dict(l=40, r=40, t=40, b=40))
    return fig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plot multi-workflow generator evaluation (Plotly).")
    parser.add_argument("--data-dir", type=Path, default=Path(__file__).resolve().parent / "data")
    parser.add_argument("--out-dir", type=Path, default=_repo_root() / "build" / "figures")
    parser.add_argument(
        "--task-note",
        type=str,
        default=(
            "single new node (2 data in, 1 data out) until Ryven loads it without structural repair; "
            "AI arms differ by validation gate & loop policy"
        ),
    )
    args = parser.parse_args(argv)

    times_path = args.data_dir / "generator_task_times.csv"
    loc_path = args.data_dir / "generator_loc.csv"
    if not times_path.is_file():
        print(f"Missing {times_path}", file=sys.stderr)
        return 2
    if not loc_path.is_file():
        print(f"Missing {loc_path}", file=sys.stderr)
        return 2

    _apply_plotly_defaults()
    pio.templates.default = "thesis"

    df = load_times(times_path)
    df_loc = load_loc(loc_path)

    stems: list[str] = []

    f1 = fig_workflow_distribution(df, args.task_note)
    _write_static(f1, args.out_dir / "fig-08-02-workflow-times", width=1200, height=640)
    stems.append("fig-08-02-workflow-times")

    f2 = fig_median_ranking(df)
    _write_static(f2, args.out_dir / "fig-08-02b-median-ranking", width=1100, height=560)
    stems.append("fig-08-02b-median-ranking")

    f3 = fig_success_and_load(df)
    _write_static(f3, args.out_dir / "fig-08-02c-success-rate", width=1200, height=560)
    stems.append("fig-08-02c-success-rate")

    f4 = fig_react_overhead(df)
    _write_static(f4, args.out_dir / "fig-08-02d-react-scatter", width=960, height=600)
    stems.append("fig-08-02d-react-scatter")

    f5 = fig_design_grid(df)
    if f5.data:
        _write_static(f5, args.out_dir / "fig-08-04-design-heatmap", width=900, height=520)
        stems.append("fig-08-04-design-heatmap")

    f6 = fig_loc_stacked(df_loc)
    _write_static(f6, args.out_dir / "fig-08-03-loc-stacked", width=1150, height=620)
    stems.append("fig-08-03-loc-stacked")

    fd = fig_dashboard(df, df_loc, args.task_note)
    _write_static(fd, args.out_dir / "fig-08-generator-evaluation-dashboard", width=1400, height=1020)
    stems.append("fig-08-generator-evaluation-dashboard")

    fstats = fig_stat_inset_card(df)
    _write_static(fstats, args.out_dir / "fig-08-02e-nonparametric-summary", width=960, height=260)
    stems.append("fig-08-02e-nonparametric-summary")

    print("Wrote:")
    for stem in stems:
        for suffix in (".pdf", ".png"):
            print(" ", args.out_dir / f"{stem}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
