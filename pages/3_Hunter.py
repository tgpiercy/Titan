# FILE: pages/3_Hunter.py
# ROLE: Per-ticker deep analysis — VSA chart, Flow intel, Unified signal, ATR stop

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import ui
import config as cfg
from core.data    import get_ohlcv
from core.vsa     import analyse as vsa_analyse
from core.flow    import get_flow
from core.signals import synthesise
from core.rrg     import get_generals_rrg, get_latest_snapshot

st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# SESSION STATE
# ==============================================================================
if "active_ticker" not in st.session_state: st.session_state.active_ticker = "SPY"
if "audit_ticker"  not in st.session_state: st.session_state.audit_ticker  = "SPY"

# ==============================================================================
# HEADER + TICKER INPUT
# ==============================================================================
st.title("🦅 Hunter")

c_inp, c_btn = st.columns([4, 1])
with c_inp:
    def _on_ticker_change():
        st.session_state.active_ticker = st.session_state.hunter_input.upper()

    ticker = st.text_input(
        "Ticker",
        value=st.session_state.active_ticker,
        key="hunter_input",
        on_change=_on_ticker_change,
        label_visibility="collapsed",
        placeholder="Enter ticker...",
    ).upper()

with c_btn:
    is_etf = st.toggle("ETF", value=True, help="ETF vs Stock changes flow weighting")

if ticker != st.session_state.active_ticker:
    st.session_state.active_ticker = ticker
    st.session_state.audit_ticker  = ticker

# ==============================================================================
# DATA LOAD
# ==============================================================================
with st.spinner(f"Analysing {ticker}..."):
    df_ohlcv = get_ohlcv(ticker, period="6mo")

if df_ohlcv.empty:
    st.error(f"No data for {ticker}. Check ticker and try again.")
    st.stop()

# VSA
vsa_result = vsa_analyse(df_ohlcv)
if vsa_result is None:
    st.warning("Insufficient price history for VSA (need 20+ bars).")
    st.stop()

# RRG context (generals only — lightweight)
df_rrg    = get_generals_rrg()
snap_rrg  = get_latest_snapshot(df_rrg)
quadrant  = "UNTRACKED"
velocity  = 0.0
accel     = 0.0
rrg_alpha = 0.0

if not snap_rrg.empty and ticker in snap_rrg["Ticker"].values:
    row      = snap_rrg[snap_rrg["Ticker"] == ticker].iloc[0]
    quadrant = row.get("Quadrant", "UNTRACKED")
    velocity = float(row.get("Velocity",     0.0))
    accel    = float(row.get("Acceleration", 0.0))
    rrg_alpha = float(row.get("Alpha",       0.0))

# Flow (CBOE — may be None for tickers without listed options)
with st.spinner("Fetching options flow..."):
    flow_result = get_flow(ticker, df_ohlcv)

flow_score = flow_result.score if flow_result else None

# Unified signal
sig_result = synthesise(
    vsa_signal = vsa_result.signal,
    quadrant   = quadrant,
    velocity   = velocity,
    flow_score = flow_score,
    is_etf     = is_etf,
)

# ATR stop
def _atr_stop(df: pd.DataFrame, mult: float = cfg.ATR_MULTIPLIER_ETF) -> tuple[float, float]:
    try:
        high, low, close = df["High"], df["Low"], df["Close"]
        prev_close = close.shift()
        tr  = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
        atr = float(tr.rolling(cfg.ATR_PERIOD).mean().iloc[-1])
        stop = float(close.iloc[-1]) - atr * mult
        return stop, atr
    except Exception:
        return 0.0, 0.0

mult      = cfg.ATR_MULTIPLIER_ETF if is_etf else cfg.ATR_MULTIPLIER_STK
stop_price, atr_val = _atr_stop(df_ohlcv, mult)
current_price       = float(df_ohlcv["Close"].iloc[-1])
downside_pct        = (current_price - stop_price) / current_price * 100 if current_price > 0 else 0

# ==============================================================================
# COMMAND CARD
# ==============================================================================
st.markdown(
    ui.command_card(sig_result.label, sig_result.color),
    unsafe_allow_html=True,
)

# ==============================================================================
# VSA CHART
# ==============================================================================
display_len = 65
df_chart    = df_ohlcv.iloc[-display_len:]
vol_ma      = df_ohlcv["Volume"].rolling(20).mean()
sma20       = df_ohlcv["Close"].rolling(20).mean()
sma50       = df_ohlcv["Close"].rolling(50).mean()

# Volume colour: purple for climax bars, grey otherwise
vol_ma_chart = vol_ma.iloc[-display_len:]
vol_colors   = [
    "#D500F9" if v > (a * 1.5) else "#2A2A2A"
    for v, a in zip(df_chart["Volume"], vol_ma_chart)
]

fig = make_subplots(
    rows=2, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.04,
    row_heights=[0.72, 0.28],
)

# Volume bars (background layer)
fig.add_trace(go.Bar(
    x=df_chart.index, y=df_chart["Volume"],
    marker_color=vol_colors,
    name="Volume", opacity=0.55,
), row=2, col=1)

# Candlesticks
fig.add_trace(go.Candlestick(
    x=df_chart.index,
    open=df_chart["Open"], high=df_chart["High"],
    low=df_chart["Low"],   close=df_chart["Close"],
    increasing_line_color="#00FF00",
    decreasing_line_color="#FF4444",
    name="Price",
), row=1, col=1)

# SMA lines
fig.add_trace(go.Scatter(
    x=df_chart.index, y=sma20.iloc[-display_len:],
    mode="lines", line=dict(color="#FFFF00", width=1.5),
    name="SMA 20",
), row=1, col=1)

if len(df_ohlcv) >= 50:
    fig.add_trace(go.Scatter(
        x=df_chart.index, y=sma50.iloc[-display_len:],
        mode="lines", line=dict(color="#FF8800", width=1.5),
        name="SMA 50",
    ), row=1, col=1)

# Stop level
if stop_price > 0:
    fig.add_hline(
        y=stop_price, row=1, col=1,
        line_color="#FF4444", line_dash="dash", line_width=1.5,
        annotation_text=f"Stop ${stop_price:.2f}",
        annotation_font_color="#FF4444",
        annotation_position="bottom right",
    )

# Key flow levels
if flow_result:
    if flow_result.call_wall:
        fig.add_hline(
            y=flow_result.call_wall, row=1, col=1,
            line_color="#00FF00", line_dash="dot", line_width=1,
            annotation_text=f"Call Wall ${flow_result.call_wall:.0f}",
            annotation_font_color="#00FF00",
            annotation_position="top right",
        )
    if flow_result.put_wall:
        fig.add_hline(
            y=flow_result.put_wall, row=1, col=1,
            line_color="#FF4444", line_dash="dot", line_width=1,
            annotation_text=f"Put Wall ${flow_result.put_wall:.0f}",
            annotation_font_color="#FF4444",
            annotation_position="bottom right",
        )

fig.update_layout(
    height=820,
    title=dict(
        text=f"{ticker}  ·  {sig_result.label}  ·  Grade {sig_result.grade}",
        font=dict(size=20, color="white", family="Roboto Mono"),
    ),
    margin=dict(l=50, r=50, t=60, b=40),
    paper_bgcolor="#161B22",
    plot_bgcolor="#161B22",
    font=dict(color="#C5C5C5", family="Roboto Mono"),
    xaxis_rangeslider_visible=False,
    showlegend=False,
    hovermode="x unified",
    yaxis=dict(showgrid=True, gridcolor="rgba(128,128,128,0.15)"),
    yaxis2=dict(showgrid=False),
)
st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# INTEL GRID  (4 columns)
# ==============================================================================
st.divider()
c1, c2, c3, c4 = st.columns(4)

# --- COL 1: VSA Intel ---
with c1:
    st.markdown(
        f"### 🔍 VSA INTEL\n"
        f"<span style='color:{vsa_result.color}; font-size:18px; font-weight:700;'>"
        f"{vsa_result.signal}</span>",
        unsafe_allow_html=True,
    )
    st.metric("Volume",        vsa_result.vol_state,    f"{vsa_result.vol_ratio:.1f}× avg")
    st.metric("Range / Spread", vsa_result.spread_state)
    st.metric("Close Location", vsa_result.close_state,
              f"{vsa_result.close_loc*100:.0f}% of range")
    st.caption(f"_{vsa_result.note}_")

# --- COL 2: Signal & Structure ---
with c2:
    st.markdown(
        f"### 🎯 SIGNAL\n"
        f"<span style='color:{sig_result.color}; font-size:18px; font-weight:700;'>"
        f"{sig_result.label}</span>",
        unsafe_allow_html=True,
    )
    st.metric("Grade",      f"{sig_result.grade} — {sig_result.action}")
    st.metric("Score",      f"{sig_result.score:+.1f} / 10")
    st.metric("RRG State",  quadrant)
    st.caption(f"_{sig_result.description}_")

# --- COL 3: Flow (CBOE) ---
with c3:
    st.markdown("### 📡 FLOW (CBOE)")
    if flow_result:
        st.markdown(
            f"<span style='color:{flow_result.color}; font-size:18px; font-weight:700;'>"
            f"{flow_result.regime}</span>",
            unsafe_allow_html=True,
        )
        st.metric("Flow Score",   f"{flow_result.score:+.1f} / 10")
        st.metric("P/C Ratio",    f"{flow_result.put_call_ratio:.2f}")
        st.metric("Net DEX",      f"{flow_result.net_dex:,.0f}")
        st.caption(f"_{flow_result.read}_")
        st.caption(f"Components: {flow_result.detail}")
    else:
        st.info("No CBOE options data.\nETF or no listed options.")
        st.metric("Flow Score", "N/A")

# --- COL 4: Risk ---
with c4:
    st.markdown("### ⚖️ RISK")
    st.markdown(
        f"<span style='color:#FF4444; font-size:18px; font-weight:700;'>"
        f"Stop ${stop_price:.2f}</span>",
        unsafe_allow_html=True,
    )
    st.metric("Current Price",  f"${current_price:.2f}")
    st.metric("Hard Stop",      f"${stop_price:.2f}")
    st.metric("Downside Risk",  f"-{downside_pct:.1f}%")
    st.metric("ATR (14)",       f"${atr_val:.2f}")
    if flow_result and flow_result.call_wall and flow_result.put_wall:
        st.metric("Call Wall", f"${flow_result.call_wall:.0f}")
        st.metric("Put Wall",  f"${flow_result.put_wall:.0f}")

st.divider()

# ==============================================================================
# RRG CONTEXT STRIP
# ==============================================================================
st.markdown("### 📍 RRG Context")
rc1, rc2, rc3, rc4 = st.columns(4)
quad_col = ui.quad_color(quadrant)

rc1.markdown(
    f"**Quadrant**<br>"
    f"<span style='color:{quad_col}; font-size:22px; font-weight:700;'>{quadrant}</span>",
    unsafe_allow_html=True,
)
rc2.metric("RRG Alpha",    f"{rrg_alpha:+.2f}")
rc3.metric("Velocity",     f"{velocity:.2f}")
rc4.metric("Acceleration", f"{accel:+.2f}")

# Quadrant context note
quad_notes = {
    "Leading":   "✅ Strong trend vs benchmark. Ride or reload on pullbacks.",
    "Improving": "⚡ Momentum turning bullish. Best risk/reward entry zone.",
    "Weakening": "⚠️ Momentum fading. Tighten stops, no new longs.",
    "Lagging":   "🛑 Underperforming benchmark. Avoid or short.",
    "UNTRACKED": "ℹ️ Not tracked in RRG universe. Flow + VSA only.",
}
st.caption(quad_notes.get(quadrant, ""))

st.divider()

# ==============================================================================
# WATCHLIST BUTTON
# ==============================================================================
try:
    from core.portfolio import add_to_watchlist
    if st.button(f"➕ Add {ticker} to Trap", use_container_width=False):
        add_to_watchlist(ticker)
        st.success(f"{ticker} added to The Trap.")
except Exception:
    pass

