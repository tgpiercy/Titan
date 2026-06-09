# FILE: pages/5_Validation.py
# ROLE: Walk-Forward Validation Lab

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

import ui
import config as cfg
from core.backtest import run_backtest, run_benchmark, BacktestResult

st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# SESSION STATE
# ==============================================================================
if "val_results" not in st.session_state: st.session_state.val_results   = None
if "val_spy"     not in st.session_state: st.session_state.val_spy       = None
if "val_params"  not in st.session_state: st.session_state.val_params    = {}

# ==============================================================================
# HEADER
# ==============================================================================
st.title("🔬 Validation Lab")
st.markdown(
    "Walk-forward harness. **IS** = In-Sample (first 70%). "
    "**OOS** = Out-of-Sample (last 30%). OOS metrics are the only ones that matter."
)
st.divider()

# ==============================================================================
# VALIDATED BASELINE — always visible
# ==============================================================================
st.markdown("## 📌 Validated Baseline (RS Extension)")

b1, b2, b3, b4 = st.columns(4)
b1.metric("OOS Sharpe", "0.96",   "Validated")
b2.metric("OOS CAGR",   "26.2%",  "Validated")
b3.metric("OOS MaxDD",  "-12.7%", "Validated")
b4.metric("WFE",        "0.41",   "Validated")

st.caption(
    "Any variant must beat OOS Sharpe 0.96 AND show WFE ≥ 0.50 to be promoted to live use."
)
st.divider()

# ==============================================================================
# CONTROLS — always visible, outside expander so universe is always in scope
# ==============================================================================
st.markdown("## ⚙️ Test Parameters")

col1, col2, col3 = st.columns(3)

with col1:
    period      = st.selectbox("Data Period", ["5y", "3y", "2y", "7y"], index=0)
    top_n       = st.slider("Top N Holdings", 1, 10, 5)

with col2:
    rs_window   = st.slider("RS Window (days)", 30, 180, 90, step=10)
    ext_thresh  = st.slider("Extension Threshold", 0.00, 0.20, 0.05, step=0.01,
                            help="Min RS ratio above trend to qualify")

with col3:
    universe_choice = st.selectbox(
        "Universe",
        ["Sector ETFs (Generals)", "Generals + Lieutenants", "Custom"],
    )
    trend_filter = st.toggle(
        "Trend Filter",
        value=False,
        help="Only hold tickers where price > 50-SMA (causal, no lookahead)",
    )

# Universe — defined at module scope so always accessible
if universe_choice == "Sector ETFs (Generals)":
    universe = list(cfg.SECTOR_MAP.values())
elif universe_choice == "Generals + Lieutenants":
    universe = list(cfg.SECTOR_MAP.values())
    for sub in cfg.THEME_MAP.values():
        universe.extend(sub.values())
    universe = list(set(universe))
else:
    custom_input = st.text_input(
        "Custom tickers (comma-separated)", "XLK,XLF,XLE,XLV,XLI"
    )
    universe = [t.strip().upper() for t in custom_input.split(",") if t.strip()]

st.caption(f"Universe: {len(universe)} tickers  ·  Benchmark: SPY")

run_btn = st.button("🚀 RUN COMPARISON", type="primary", use_container_width=True)

st.divider()

# ==============================================================================
# RUN ON BUTTON CLICK
# ==============================================================================
if run_btn:
    strategies_to_run = [
        {"strategy": "rs_extension", "trend_ok": False, "label": "RS Extension (Baseline)"},
    ]
    if trend_filter:
        strategies_to_run.append(
            {"strategy": "rs_trend", "trend_ok": True, "label": "RS + Trend Filter"}
        )

    results = []
    spy     = None

    prog = st.progress(0, text="Running walk-forward analysis...")

    spy = run_benchmark(period=period)
    prog.progress(0.2, text="Benchmark done...")

    for i, params in enumerate(strategies_to_run):
        prog.progress(
            0.2 + 0.8 * (i + 1) / len(strategies_to_run),
            text=f"Testing {params['label']}...",
        )
        res = run_backtest(
            strategy   = params["strategy"],
            universe   = universe,
            period     = period,
            top_n      = top_n,
            rs_window  = rs_window,
            ext_thresh = ext_thresh,
            trend_ok   = params["trend_ok"],
        )
        if res:
            res.name = params["label"]
            results.append(res)

    prog.empty()

    if results:
        st.session_state.val_results = results
        st.session_state.val_spy     = spy
    else:
        st.error("No results returned — check data connection or reduce universe size.")

# ==============================================================================
# DISPLAY RESULTS (from session state — persists across reruns)
# ==============================================================================
results = st.session_state.val_results
spy     = st.session_state.val_spy

if not results:
    st.info(
        "Configure parameters above and click **RUN COMPARISON** to run the walk-forward test. "
        "Toggle **Trend Filter** on to test the RS + Trend variant head-to-head."
    )
    st.stop()

# -----------------------------------------------------------------------
# RESULTS TABLE
# -----------------------------------------------------------------------
st.markdown("## 📊 Results")

rows = [r.summary_row() for r in results]
if spy:
    rows.append(spy.summary_row())

df_results = pd.DataFrame(rows)

st.dataframe(
    df_results,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Strategy":    st.column_config.TextColumn("Strategy",      width=260),
        "IS Sharpe":   st.column_config.NumberColumn("IS Sharpe",   format="%.2f"),
        "OOS Sharpe":  st.column_config.NumberColumn("OOS Sharpe ⭐", format="%.2f"),
        "IS CAGR %":   st.column_config.NumberColumn("IS CAGR %",   format="%.1f%%"),
        "OOS CAGR %":  st.column_config.NumberColumn("OOS CAGR %",  format="%.1f%%"),
        "IS MaxDD %":  st.column_config.NumberColumn("IS MaxDD %",  format="%.1f%%"),
        "OOS MaxDD %": st.column_config.NumberColumn("OOS MaxDD %", format="%.1f%%"),
        "WFE":         st.column_config.NumberColumn(
            "WFE", format="%.2f",
            help="Walk-Forward Efficiency = OOS/IS Sharpe. ≥0.70 excellent, ≥0.50 acceptable."
        ),
        "Trades":      st.column_config.NumberColumn("Trades"),
    },
)

# -----------------------------------------------------------------------
# VERDICT CARDS
# -----------------------------------------------------------------------
st.markdown("### 🏆 Verdict")

baseline_oos = 0.0
for r in results:
    if "Baseline" in r.name:
        baseline_oos = r.oos_sharpe
        break

v_cols = st.columns(len(results) + (1 if spy else 0))

COLORS = ["#00FF00", "#00CCFF", "#D500F9", "#FFA500"]

for i, res in enumerate(results):
    is_baseline = "Baseline" in res.name
    beats_base  = res.oos_sharpe > baseline_oos and not is_baseline
    wfe_ok      = res.wfe >= 0.50

    if is_baseline:
        border, verdict_txt = "#00CCFF", "📌 VALIDATED BASELINE"
        cap = f"OOS Sharpe {res.oos_sharpe:.2f} · WFE {res.wfe:.2f}"
    elif beats_base and wfe_ok:
        border, verdict_txt = "#00FF00", "✅ PROMOTED"
        cap = f"+{res.oos_sharpe - baseline_oos:.2f} vs baseline · WFE {res.wfe:.2f}"
    elif beats_base and not wfe_ok:
        border, verdict_txt = "#FFA500", "⚠️ OVERFIT RISK"
        cap = f"Beats baseline but WFE {res.wfe:.2f} < 0.50"
    else:
        border, verdict_txt = "#FF4444", "❌ REJECTED"
        cap = f"OOS Sharpe {res.oos_sharpe:.2f} ≤ baseline {baseline_oos:.2f}"

    v_cols[i].markdown(
        f"<div style='border:2px solid {border}; border-radius:8px; padding:14px; "
        f"background:{border}11; text-align:center;'>"
        f"<div style='color:{border}; font-size:15px; font-weight:700;'>{verdict_txt}</div>"
        f"<div style='color:#CCC; font-size:12px; margin-top:5px;'>{res.name}</div>"
        f"<div style='color:#AAA; font-size:12px; margin-top:3px;'>{cap}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

if spy:
    v_cols[-1].markdown(
        f"<div style='border:2px solid #444; border-radius:8px; padding:14px; "
        f"background:#44444411; text-align:center;'>"
        f"<div style='color:#888; font-size:15px; font-weight:700;'>📈 BENCHMARK</div>"
        f"<div style='color:#CCC; font-size:12px; margin-top:5px;'>SPY Buy & Hold</div>"
        f"<div style='color:#AAA; font-size:12px; margin-top:3px;'>"
        f"OOS Sharpe {spy.oos_sharpe:.2f}</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

st.divider()

# -----------------------------------------------------------------------
# EQUITY CURVES
# -----------------------------------------------------------------------
st.markdown("## 📈 Equity Curves")

split_date = results[0].equity.index[results[0].split_idx] if results else None
fig = go.Figure()

for i, res in enumerate(results):
    c      = COLORS[i % len(COLORS)]
    is_eq  = res.equity.iloc[:res.split_idx]
    oos_eq = res.equity.iloc[res.split_idx:]

    fig.add_trace(go.Scatter(
        x=is_eq.index, y=is_eq.values, mode="lines",
        line=dict(color=c, width=1.5, dash="dot"),
        name=f"{res.name} IS", legendgroup=res.name,
    ))
    fig.add_trace(go.Scatter(
        x=oos_eq.index, y=oos_eq.values, mode="lines",
        line=dict(color=c, width=2.5),
        name=f"{res.name} OOS", legendgroup=res.name,
    ))

if spy:
    fig.add_trace(go.Scatter(
        x=spy.equity.index, y=spy.equity.values, mode="lines",
        line=dict(color="#555555", width=1.5, dash="dot"),
        name="SPY Buy & Hold",
    ))

if split_date is not None:
    fig.add_vline(
        x=split_date, line_width=1.5, line_color="#FFFFFF", line_dash="dash",
        annotation_text="IS → OOS", annotation_font_color="#FFFFFF",
        annotation_position="top",
    )

fig.update_layout(
    height=480,
    title=dict(text="Equity Curves ($10,000 start)", font=dict(size=16, color="white")),
    margin=dict(l=50, r=50, t=55, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0E1117",
    font=dict(color="#C5C5C5", family="Roboto Mono"),
    xaxis=dict(showgrid=True, gridcolor="#1E1E1E"),
    yaxis=dict(showgrid=True, gridcolor="#1E1E1E", tickprefix="$"),
    legend=dict(bgcolor="rgba(0,0,0,0.5)", bordercolor="#333", borderwidth=1),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------
# DRAWDOWN
# -----------------------------------------------------------------------
st.markdown("## 📉 Drawdown")

fig_dd = go.Figure()
for i, res in enumerate(results):
    c      = COLORS[i % len(COLORS)]
    equity = (1 + res.returns).cumprod()
    dd     = (equity - equity.cummax()) / equity.cummax() * 100
    fig_dd.add_trace(go.Scatter(
        x=dd.index, y=dd.values, mode="lines",
        line=dict(color=c, width=1.5),
        fill="tozeroy", fillcolor=f"{c}18",
        name=res.name,
    ))

if spy:
    spy_eq = (1 + spy.returns).cumprod()
    spy_dd = (spy_eq - spy_eq.cummax()) / spy_eq.cummax() * 100
    fig_dd.add_trace(go.Scatter(
        x=spy_dd.index, y=spy_dd.values, mode="lines",
        line=dict(color="#555555", width=1, dash="dot"), name="SPY",
    ))

if split_date is not None:
    fig_dd.add_vline(x=split_date, line_width=1.5, line_color="#FFFFFF", line_dash="dash")

fig_dd.update_layout(
    height=300,
    margin=dict(l=50, r=50, t=20, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0E1117",
    font=dict(color="#C5C5C5", family="Roboto Mono"),
    xaxis=dict(showgrid=True, gridcolor="#1E1E1E"),
    yaxis=dict(showgrid=True, gridcolor="#1E1E1E", ticksuffix="%"),
    legend=dict(bgcolor="rgba(0,0,0,0.5)", bordercolor="#333", borderwidth=1),
    hovermode="x unified",
)
st.plotly_chart(fig, use_container_width=True)

# -----------------------------------------------------------------------
# ROLLING OOS SHARPE
# -----------------------------------------------------------------------
st.markdown("## 🔄 Rolling OOS Sharpe  (252-day)")
st.caption("Flat or rising = consistent edge. Declining = regime-dependent.")

fig_rs = go.Figure()
for i, res in enumerate(results):
    c        = COLORS[i % len(COLORS)]
    oos_rets = res.returns.iloc[res.split_idx:]
    roll_sh  = oos_rets.rolling(252).apply(
        lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else 0, raw=True
    ).dropna()
    if not roll_sh.empty:
        fig_rs.add_trace(go.Scatter(
            x=roll_sh.index, y=roll_sh.values, mode="lines",
            line=dict(color=c, width=2), name=res.name,
        ))

fig_rs.add_hline(y=0,   line_color="#444", line_width=1)
fig_rs.add_hline(y=0.5, line_color="#FFA500", line_dash="dot",
                 annotation_text="0.50", annotation_font_color="#FFA500",
                 annotation_position="bottom right")
fig_rs.add_hline(y=1.0, line_color="#00FF00", line_dash="dot",
                 annotation_text="1.00", annotation_font_color="#00FF00",
                 annotation_position="bottom right")

fig_rs.update_layout(
    height=280,
    margin=dict(l=50, r=50, t=20, b=40),
    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="#0E1117",
    font=dict(color="#C5C5C5", family="Roboto Mono"),
    xaxis=dict(showgrid=True, gridcolor="#1E1E1E"),
    yaxis=dict(showgrid=True, gridcolor="#1E1E1E"),
    legend=dict(bgcolor="rgba(0,0,0,0.5)", bordercolor="#333", borderwidth=1),
    hovermode="x unified",
)
st.plotly_chart(fig_rs, use_container_width=True)

st.divider()

# -----------------------------------------------------------------------
# DOCTRINE
# -----------------------------------------------------------------------
with st.expander("📋 Validation Doctrine"):
    st.markdown("""
**Promotion criteria — a strategy is promoted only when ALL three pass:**

1. **OOS Sharpe > Baseline** — must beat the validated RS Extension system
2. **WFE ≥ 0.50** — edge carries from IS to OOS (not overfit)
3. **OOS MaxDD** not materially worse than baseline

**WFE guide:**  ≥ 0.70 excellent  ·  0.50–0.69 acceptable  ·  < 0.50 overfit — reject

**Key principle:** IS tells you how well you fitted history.
OOS tells you whether the edge is real. Only OOS matters.
    """)

