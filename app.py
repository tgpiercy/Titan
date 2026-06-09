# FILE: app.py
# ROLE: Entry point — page config, sidebar, global session state
# SYSTEM: APEX Trading Command System

import streamlit as st
from datetime import datetime

import ui
from core.regime   import get_regime
from core.data     import get_latest_price

# ==============================================================================
# PAGE CONFIG (must be first Streamlit call)
# ==============================================================================
st.set_page_config(
    page_title  = "APEX",
    page_icon   = "⚡",
    layout      = "wide",
    initial_sidebar_state = "expanded",
)
st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# GLOBAL SESSION STATE
# ==============================================================================
defaults = {
    "active_ticker":       "SPY",
    "audit_ticker":        "SPY",
    "scan_results":        None,
    "scan_mode":           "TRAP",
    "rrg_selected_general": None,
    "rrg_scope":           "SECTORS",
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ==============================================================================
# SIDEBAR
# ==============================================================================
with st.sidebar:
    st.markdown("## ⚡ APEX")
    st.caption("Unified Trading Command System")
    st.divider()

    # -- Risk Controls --
    st.markdown("### 🛡️ Risk Config")
    balance  = st.number_input("Capital ($)", value=10_000, step=1_000, min_value=1_000)
    risk_pct = st.slider("Risk per Trade (%)", 0.25, 2.0, 1.0, step=0.25)
    st.divider()

    # -- Regime Snapshot --
    st.markdown("### 🌦️ Regime")
    regime = get_regime()
    if regime:
        st.markdown(
            f"<div style='padding:10px; border-radius:6px; border:2px solid {regime.color}; "
            f"background:{regime.color}22; text-align:center;'>"
            f"<b style='color:{regime.color}; font-size:16px;'>{regime.status}</b><br>"
            f"<span style='color:#CCC; font-size:13px;'>{regime.action}</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.caption(f"Score: {regime.score:.1f}/10 · Fails: {regime.fail_count}/3")
        if regime.size_scalar < 1.0:
            st.warning(f"🐻 Bear Protocol: {int(regime.size_scalar*100)}% position size")
    else:
        st.warning("Weather offline")

    st.divider()

    # -- Active Focus --
    st.markdown("### 🎯 Active Focus")
    active = st.text_input(
        "Ticker",
        value=st.session_state.active_ticker,
        key="sidebar_ticker",
        label_visibility="collapsed",
    ).upper()
    if active != st.session_state.active_ticker:
        st.session_state.active_ticker = active
        st.session_state.audit_ticker  = active
        st.rerun()

    price = get_latest_price(st.session_state.active_ticker)
    if price:
        st.metric(st.session_state.active_ticker, f"${price:.2f}")

    st.divider()

    # -- Position Sizer (quick calc) --
    st.markdown("### 📐 Quick Sizer")
    qs_entry = st.number_input("Entry", value=price or 100.0, format="%.2f", step=0.01)
    qs_stop  = st.number_input("Stop",  value=(price or 100.0) * 0.95, format="%.2f", step=0.01)

    if qs_entry > qs_stop > 0:
        risk_amt   = balance * (risk_pct / 100)
        risk_share = qs_entry - qs_stop
        raw_shares = int(risk_amt / risk_share)
        scalar     = regime.size_scalar if regime else 1.0
        shares     = int(raw_shares * scalar)
        cost       = shares * qs_entry
        actual_risk = shares * risk_share

        st.metric("Shares", shares)
        col1, col2 = st.columns(2)
        col1.metric("Cost",   f"${cost:,.0f}")
        col2.metric("Risk $", f"${actual_risk:,.0f}")
        if scalar < 1.0:
            st.caption(f"⚠️ Bear Protocol applied ({int(scalar*100)}%)")
    else:
        st.caption("Set entry above stop to size.")

    st.divider()
    st.caption(f"APEX · {datetime.now().strftime('%H:%M %Z')}")

# ==============================================================================
# LANDING PAGE (shown when no sub-page is selected)
# ==============================================================================
st.title("⚡ APEX")
st.markdown("### Unified Trading Command System")
st.markdown(
    "Use the **sidebar pages** to navigate:\n\n"
    "- **1 Command** — Market regime, watchlist, scanner\n"
    "- **2 Rotation** — RRG sector & macro compass\n"
    "- **3 Hunter** — Per-ticker VSA, flow, signal\n"
    "- **4 Portfolio** — Positions, P&L, decision engine\n"
    "- **5 Validation** — Walk-forward backtest\n"
)

if regime:
    st.markdown(
        ui.regime_banner(
            regime.status, regime.action, regime.color,
            datetime.now().strftime("%H:%M")
        ),
        unsafe_allow_html=True,
    )

