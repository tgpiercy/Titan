# FILE: pages/2_Rotation.py
# ROLE: Sector Command — RRG Battlemap with Macro Compass + 2-level drill-down

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go

import ui
import config as cfg
from core.rrg import (
    get_macro_rrg,
    get_generals_rrg,
    get_lieutenants_rrg,
    get_latest_snapshot,
)

st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# SESSION STATE
# ==============================================================================
if "rrg_scope"            not in st.session_state: st.session_state.rrg_scope            = "SECTORS"
if "rrg_selected_general" not in st.session_state: st.session_state.rrg_selected_general = None
if "active_ticker"        not in st.session_state: st.session_state.active_ticker        = "SPY"

def _set_focus(ticker: str):
    st.session_state.active_ticker = ticker
    st.session_state.audit_ticker  = ticker

# ==============================================================================
# HEADER & SCOPE SELECTOR
# ==============================================================================
st.title("🚀 Rotation")

scope = st.radio(
    "Mission Scope",
    ["🌍 MACRO (Indices vs Bonds)", "⚔️ SECTORS (Generals vs SPY)"],
    horizontal=True,
    label_visibility="collapsed",
    key="rrg_scope_radio",
)

# Detect scope switch — clear general selection
new_scope = "MACRO" if "MACRO" in scope else "SECTORS"
if st.session_state.rrg_scope != new_scope:
    st.session_state.rrg_scope            = new_scope
    st.session_state.rrg_selected_general = None
    st.rerun()

st.divider()

# ==============================================================================
# DATA LOAD
# ==============================================================================
with st.spinner("Calculating rotation..."):
    if new_scope == "MACRO":
        df_parents = get_macro_rrg()
        parent_label = "MACRO COMPASS (Indices vs Bonds/IEF)"
        bench_label  = "IEF"
    else:
        df_parents = get_generals_rrg()
        parent_label = "SECTOR GENERALS (vs SPY)"
        bench_label  = "SPY"

    # Auto-select first general in Sectors mode
    if new_scope == "SECTORS" and st.session_state.rrg_selected_general is None:
        generals = list(cfg.SECTOR_MAP.values())
        if generals:
            st.session_state.rrg_selected_general = generals[0]

    # Lieutenant data
    df_children = pd.DataFrame()
    selected_general = st.session_state.rrg_selected_general
    if new_scope == "SECTORS" and selected_general:
        df_children = get_lieutenants_rrg(selected_general)

# Active plot data: prefer lieutenants when available
plot_df     = df_children if not df_children.empty else df_parents
snap_plot   = get_latest_snapshot(plot_df)
snap_parents = get_latest_snapshot(df_parents)

if new_scope == "MACRO":
    chart_title = "RRG: MACRO COMPASS (Risk vs Bonds)"
elif df_children.empty:
    chart_title = "RRG: SECTOR ROTATION (Generals vs SPY)"
else:
    chart_title = f"RRG: DRILL-DOWN — {selected_general} Lieutenants"

# ==============================================================================
# RRG BATTLEMAP
# ==============================================================================
if not plot_df.empty and not snap_plot.empty:
    # --- Dynamic zoom ---
    tail_df = plot_df.groupby("Ticker").tail(cfg.RRG_TAIL_DAYS)

    x_min = min(snap_plot["Ratio"].min(), tail_df["Ratio"].min())
    x_max = max(snap_plot["Ratio"].max(), tail_df["Ratio"].max())
    y_min = min(snap_plot["Momentum"].min(), tail_df["Momentum"].min())
    y_max = max(snap_plot["Momentum"].max(), tail_df["Momentum"].max())

    x_center = (x_max + x_min) / 2
    y_center = (y_max + y_min) / 2
    span     = max(x_max - x_min, y_max - y_min) * 1.12
    if span < 4.0: span = 4.0
    half = span / 2

    x_range = [x_center - half, x_center + half]
    y_range = [y_center - half, y_center + half]

    fig = go.Figure()

    # Quadrant backgrounds
    fig.add_shape(type="rect", x0=100, y0=100, x1=x_range[1]+20, y1=y_range[1]+20,
                  fillcolor="rgba(0,255,0,0.05)",   layer="below", line_width=0)
    fig.add_shape(type="rect", x0=100, y0=y_range[0]-20, x1=x_range[1]+20, y1=100,
                  fillcolor="rgba(255,255,0,0.05)", layer="below", line_width=0)
    fig.add_shape(type="rect", x0=x_range[0]-20, y0=y_range[0]-20, x1=100, y1=100,
                  fillcolor="rgba(255,0,0,0.05)",   layer="below", line_width=0)
    fig.add_shape(type="rect", x0=x_range[0]-20, y0=100, x1=100, y1=y_range[1]+20,
                  fillcolor="rgba(0,204,255,0.05)", layer="below", line_width=0)

    # Axis lines
    fig.add_vline(x=100, line_width=1, line_color="#444")
    fig.add_hline(y=100, line_width=1, line_color="#444")

    # Quadrant labels
    pad = span * 0.05
    for txt, x, y, col in [
        ("LEADING",   x_center + half - pad, y_center + half - pad, "#00FF00"),
        ("WEAKENING", x_center + half - pad, y_center - half + pad, "#FFFF00"),
        ("LAGGING",   x_center - half + pad, y_center - half + pad, "#FF4444"),
        ("IMPROVING", x_center - half + pad, y_center + half - pad, "#00CCFF"),
    ]:
        fig.add_annotation(
            x=x, y=y, text=txt, showarrow=False,
            font=dict(color=col, size=11, family="Roboto Mono"),
            opacity=0.4,
        )

    # Comet trails + heads
    for ticker in snap_plot["Ticker"].unique():
        trail = plot_df[plot_df["Ticker"] == ticker].sort_values("Date").tail(cfg.RRG_TAIL_DAYS)
        curr  = snap_plot[snap_plot["Ticker"] == ticker]
        if curr.empty: continue
        curr  = curr.iloc[0]

        c = ui.quad_color(curr["Quadrant"])

        # Trail
        if len(trail) > 1:
            fig.add_trace(go.Scatter(
                x=trail["Ratio"], y=trail["Momentum"],
                mode="lines",
                line=dict(color=c, width=2, shape="spline"),
                opacity=0.45,
                showlegend=False,
                hoverinfo="skip",
            ))

        # Head
        fig.add_trace(go.Scatter(
            x=[curr["Ratio"]], y=[curr["Momentum"]],
            mode="markers+text",
            marker=dict(color=c, size=14, line=dict(width=2, color="white")),
            text=[ticker],
            textposition="top center",
            textfont=dict(color="white", size=11, family="Roboto Mono"),
            hovertemplate=(
                f"<b>{ticker}</b><br>"
                f"{curr.get('Tactical','')}<br>"
                f"Alpha: {curr.get('Alpha', curr['Ratio']-100):.2f}<br>"
                f"Vel: {curr.get('Velocity',0):.2f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

    fig.update_layout(
        height=720,
        title=dict(text=chart_title, font=dict(size=18, color="white", family="Roboto Mono")),
        margin=dict(l=50, r=50, t=60, b=50),
        xaxis=dict(
            title="RS-Ratio →  (Trend)",
            range=x_range,
            showgrid=True, gridcolor="#1E1E1E",
            zeroline=False,
            tickfont=dict(family="Roboto Mono"),
        ),
        yaxis=dict(
            title="RS-Momentum ↑  (Speed)",
            range=y_range,
            showgrid=True, gridcolor="#1E1E1E",
            zeroline=False,
            scaleanchor="x", scaleratio=1,
            tickfont=dict(family="Roboto Mono"),
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0E1117",
        hovermode="closest",
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("⏳ Loading rotation data...")

st.divider()

# ==============================================================================
# COMMAND TABLES
# ==============================================================================
col_generals, col_lieuts = st.columns(2)

# --- GENERALS / MACRO TABLE ---
with col_generals:
    st.markdown(f"### {'1. INDICES' if new_scope == 'MACRO' else '1. SECTOR GENERALS'}")

    if not snap_parents.empty:
        view = snap_parents.copy()
        display_cols = ["Ticker", "Tactical", "Alpha", "Thrust", "Velocity", "Acceleration"]
        display_cols = [c for c in display_cols if c in view.columns]
        view_sorted  = view[display_cols].sort_values("Alpha", ascending=False)

        evt_gen = st.dataframe(
            view_sorted,
            use_container_width=True,
            hide_index=True,
            selection_mode="single-row",
            on_select="rerun",
            key="table_generals",
            column_config={
                "Ticker":       st.column_config.TextColumn("Asset",   width=65),
                "Tactical":     st.column_config.TextColumn("State",   width=100),
                "Alpha":        st.column_config.NumberColumn("Alpha",  format="%.2f"),
                "Thrust":       st.column_config.TextColumn("Thrust",  width=70),
                "Velocity":     st.column_config.NumberColumn("Vel",   format="%.2f"),
                "Acceleration": st.column_config.NumberColumn("Acc",   format="%.2f"),
            },
        )

        if evt_gen.selection.rows:
            idx     = evt_gen.selection.rows[0]
            new_sel = view_sorted.iloc[idx]["Ticker"]

            # Update VSA focus
            if new_sel != st.session_state.active_ticker:
                _set_focus(new_sel)

            # Update lieutenant drill-down (sectors mode only)
            if new_scope == "SECTORS":
                if new_sel != st.session_state.rrg_selected_general:
                    st.session_state.rrg_selected_general = new_sel
                    st.rerun()
    else:
        st.info("Loading generals data...")

# --- LIEUTENANTS TABLE ---
with col_lieuts:
    if new_scope == "SECTORS":
        gen_lbl = st.session_state.rrg_selected_general or "—"
        st.markdown(f"### 2. LIEUTENANTS  (vs {gen_lbl})")

        if not df_children.empty:
            snap_c = get_latest_snapshot(df_children)
            display_cols = ["Ticker", "Tactical", "Alpha", "Thrust", "Velocity", "Acceleration"]
            display_cols = [c for c in display_cols if c in snap_c.columns]
            view_c_sorted = snap_c[display_cols].sort_values("Alpha", ascending=False)

            evt_lieut = st.dataframe(
                view_c_sorted,
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun",
                key="table_lieutenants",
                column_config={
                    "Ticker":       st.column_config.TextColumn("Asset",  width=65),
                    "Tactical":     st.column_config.TextColumn("State",  width=100),
                    "Alpha":        st.column_config.NumberColumn("Alpha", format="%.2f"),
                    "Thrust":       st.column_config.TextColumn("Thrust", width=70),
                    "Velocity":     st.column_config.NumberColumn("Vel",  format="%.2f"),
                    "Acceleration": st.column_config.NumberColumn("Acc",  format="%.2f"),
                },
            )

            if evt_lieut.selection.rows:
                idx_l  = evt_lieut.selection.rows[0]
                target = view_c_sorted.iloc[idx_l]["Ticker"]
                if target != st.session_state.active_ticker:
                    _set_focus(target)
                    st.rerun()
        else:
            st.info(f"Select a General to drill into its Lieutenants.")
    else:
        st.info("Switch to SECTORS mode to view Lieutenants.")

st.divider()

# ==============================================================================
# ROTATION SUMMARY STRIP
# ==============================================================================
st.markdown("### 📊 Rotation Summary")

if not snap_parents.empty and "Quadrant" in snap_parents.columns:
    counts = snap_parents["Quadrant"].value_counts()
    total  = len(snap_parents)

    c1, c2, c3, c4 = st.columns(4)
    for col, quad, emoji in [
        (c1, "Leading",   "🟢"),
        (c2, "Improving", "🔵"),
        (c3, "Weakening", "🟡"),
        (c4, "Lagging",   "🔴"),
    ]:
        n   = counts.get(quad, 0)
        pct = int(n / total * 100) if total > 0 else 0
        col.metric(f"{emoji} {quad}", f"{n}", f"{pct}% of universe")

    # Market breadth read
    leading_pct = int(counts.get("Leading", 0) / total * 100) if total > 0 else 0
    improving_pct = int(counts.get("Improving", 0) / total * 100) if total > 0 else 0
    bullish_pct = leading_pct + improving_pct

    if bullish_pct >= 60:
        st.success(f"✅ Broad participation: {bullish_pct}% of sectors Leading or Improving — risk-on conditions.")
    elif bullish_pct >= 40:
        st.warning(f"⚠️ Mixed rotation: {bullish_pct}% Leading or Improving — selective exposure only.")
    else:
        st.error(f"🛑 Narrow market: only {bullish_pct}% Leading or Improving — defensive posture.")

