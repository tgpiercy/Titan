# FILE: pages/1_Command.py
# ROLE: Primary Dashboard — Market Weather, The Trap, Hot List Scanner

import streamlit as st
import pandas as pd
from datetime import datetime

import ui
from core.regime import get_regime
from core.data   import get_ohlcv_batch
import config as cfg


# ==============================================================================
# LAZY IMPORTS
# ==============================================================================
def _lazy_imports():
    from core.vsa       import get_vsa_verdict
    from core.rrg       import get_rrg_data, get_latest_snapshot
    from core.signals   import get_trigger_signal
    from core.portfolio import get_portfolio, get_watchlist, add_to_watchlist
    return get_vsa_verdict, get_rrg_data, get_latest_snapshot, get_trigger_signal, get_portfolio, get_watchlist, add_to_watchlist


# ==============================================================================
# SESSION STATE
# ==============================================================================
if "scan_results"  not in st.session_state: st.session_state.scan_results  = None
if "scan_mode"     not in st.session_state: st.session_state.scan_mode     = "TRAP"
if "active_ticker" not in st.session_state: st.session_state.active_ticker = "SPY"

def _set_focus(ticker: str):
    st.session_state.active_ticker = ticker

def _close_scan():
    st.session_state.scan_results = None


# ==============================================================================
# SCANNER ENGINE — defined first so button handler can call it
# ==============================================================================
def _run_scan(mode, regime, get_vsa_verdict, get_rrg_data, get_latest_snapshot,
              get_trigger_signal, get_portfolio, get_watchlist):
    """
    Dual-mode scanner.
    Returns dict: buys, sells, swaps, holdings DataFrames.
    """
    port_df      = get_portfolio()
    held_tickers = port_df["Ticker"].tolist() if not port_df.empty else []

    wl_df        = get_watchlist(regime) if regime else pd.DataFrame()
    watch_tickers = wl_df["Ticker"].tolist() if not wl_df.empty else []

    generals = list(cfg.SECTOR_MAP.values())
    if mode == "MARKET":
        scan_list = list(set(held_tickers + generals + cfg.SCAN_UNIVERSE_EXTRA))
    else:
        scan_list = list(set(held_tickers + generals + watch_tickers))

    if not scan_list:
        empty = pd.DataFrame()
        return {"buys": empty, "sells": empty, "swaps": empty, "holdings": empty}

    prog = st.progress(0, text="Scanning...") if mode == "MARKET" else None

    # Batch OHLCV
    ohlcv_map = get_ohlcv_batch(scan_list, period="6mo")

    # RRG snapshot
    all_tickers = list(set(scan_list + ["SPY"]))
    df_rrg      = get_rrg_data(all_tickers)
    latest_rrg  = {}
    if not df_rrg.empty:
        latest_rrg = df_rrg.sort_values("Date").groupby("Ticker").last()

    is_market_locked = regime and regime.is_risk_off

    opportunities, threats, holdings_report, weak_holdings = [], [], [], []

    for i, ticker in enumerate(scan_list):
        if prog and i % 5 == 0:
            prog.progress(i / len(scan_list), text=f"Scanning {ticker}...")
        try:
            df_t = ohlcv_map.get(ticker)
            if df_t is None or df_t.empty:
                continue

            vsa_txt, _, _ = get_vsa_verdict(df_t)

            vol_avg = df_t["Volume"].rolling(20).mean().iloc[-1]
            r_vol   = df_t["Volume"].iloc[-1] / vol_avg if vol_avg > 0 else 1.0

            quad, vel, alpha = "UNTRACKED", 0.0, 0.0
            if ticker in latest_rrg.index:
                row   = latest_rrg.loc[ticker]
                quad  = row.get("Quadrant", "UNTRACKED")
                vel   = float(row.get("Velocity", 0.0))
                alpha = float(row.get("Ratio", 100.0)) - 100.0

            if is_market_locked:
                sig = "⛔ MARKET VETO"
            else:
                sig, _, _ = get_trigger_signal(vsa_txt, quad, vel)

            packet = {
                "Ticker": ticker, "Signal": sig, "VSA": vsa_txt,
                "Alpha": alpha, "Quad": quad, "Vel": vel, "Vol": r_vol,
            }

            if ticker in held_tickers:
                holdings_report.append(packet)
                if any(k in sig for k in ["EXIT", "TAKE PROFIT", "TRAP"]):
                    packet["Reason"] = f"{sig} | {vsa_txt}"
                    threats.append(packet)
                if quad in ["Lagging", "Weakening"]:
                    weak_holdings.append(ticker)
            else:
                if mode == "MARKET":
                    if any(k in sig for k in ["EXECUTE", "IGNITION"]) and quad in ["Leading", "Improving"]:
                        opportunities.append(packet)
                else:
                    if any(k in sig for k in ["EXECUTE", "IGNITION"]):
                        opportunities.append(packet)

        except Exception:
            continue

    if prog:
        prog.empty()

    hot_buys, swaps = [], []
    for op in opportunities:
        if not weak_holdings:
            hot_buys.append(op)
        else:
            op["Funder"] = weak_holdings[0]
            swaps.append(op)

    return {
        "buys":     pd.DataFrame(hot_buys),
        "sells":    pd.DataFrame(threats),
        "swaps":    pd.DataFrame(swaps),
        "holdings": pd.DataFrame(holdings_report),
    }


# ==============================================================================
# PAGE STYLES
# ==============================================================================
st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# LEVEL 0 — REGIME BANNER
# ==============================================================================
st.title("⚡ COMMAND")

regime = get_regime()

if regime:
    now_str = datetime.now().strftime("%H:%M")
    st.markdown(
        ui.regime_banner(regime.status, regime.action, regime.color, now_str),
        unsafe_allow_html=True,
    )

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(ui.market_card(
            "Fear (VIX)", f"{regime.vix_val:.2f}",
            "Safe" if regime.vix_safe else "Elevated",
            "good" if regime.vix_safe else "bad",
        ), unsafe_allow_html=True)
    with c2:
        st.markdown(ui.market_card(
            "Breadth (RSP)", regime.breadth_state, regime.breadth_note,
            "good" if regime.breadth_state == "EXPANDING" else "bad",
        ), unsafe_allow_html=True)
    with c3:
        st.markdown(ui.market_card(
            "Credit (HYG)", regime.credit_state, regime.credit_note,
            "good" if regime.credit_state == "RISK ON" else "bad",
        ), unsafe_allow_html=True)
    with c4:
        st.markdown(ui.market_card(
            "Dollar (UUP)", regime.dollar_state, regime.dollar_note,
            "good" if regime.dollar_state == "SUPPORTIVE" else "bad",
        ), unsafe_allow_html=True)

    if regime.fail_count > 0:
        st.warning(
            f"⚠️ Inertia Lock: {regime.fail_count}/3 days of internal breakdown. "
            f"Reason: {regime.reason}"
        )
else:
    st.error("⚠️ Weather data unavailable — check data connection.")

st.divider()

# ==============================================================================
# SCAN CONTROLS
# ==============================================================================
c_title, c_opt, c_btn = st.columns([5, 1.5, 1.2])
with c_title:
    st.markdown("## 🔥 Hot List")
with c_opt:
    scan_scope = st.selectbox(
        "Scope",
        ["TRAP (Watchlist)", "MARKET (Full Universe)"],
        label_visibility="collapsed",
    )
with c_btn:
    if st.button("🔥 RUN SCAN", use_container_width=True, type="primary"):
        mode = "MARKET" if "MARKET" in scan_scope else "TRAP"
        st.session_state.scan_mode = mode

        (get_vsa_verdict, get_rrg_data, get_latest_snapshot,
         get_trigger_signal, get_portfolio, get_watchlist, add_to_watchlist) = _lazy_imports()

        with st.spinner(f"Deploying {mode} scanner..."):
            results = _run_scan(
                mode, regime,
                get_vsa_verdict, get_rrg_data, get_latest_snapshot,
                get_trigger_signal, get_portfolio, get_watchlist,
            )
            st.session_state.scan_results = results
        st.rerun()

# ==============================================================================
# HOT LIST DISPLAY
# ==============================================================================
if st.session_state.scan_results:
    res      = st.session_state.scan_results
    mode_lbl = "SENTRY (Watchlist)" if st.session_state.scan_mode == "TRAP" else "SCOUT (Market)"

    hdr_col, close_col = st.columns([15, 1])
    with hdr_col:
        st.markdown(f"### Results — {mode_lbl}")
    with close_col:
        st.button("❌", on_click=_close_scan)

    # Critical Threats
    st.markdown("#### 🔴 Critical Actions")
    if not res["sells"].empty:
        st.dataframe(res["sells"].head(5), use_container_width=True, hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker", width=70),
                "Signal": st.column_config.TextColumn("Action", width=160),
                "Reason": st.column_config.TextColumn("Intel",  width=300),
                "Alpha":  st.column_config.NumberColumn("Alpha", format="%.2f"),
            })
    else:
        st.success("✅ No immediate threats in portfolio.")

    # Holdings Status
    st.markdown("#### 🏦 Holdings Status")
    if not res["holdings"].empty:
        st.dataframe(res["holdings"], use_container_width=True, hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker",   width=70),
                "Signal": st.column_config.TextColumn("Signal",   width=160),
                "Alpha":  st.column_config.NumberColumn("Alpha",  format="%.2f"),
                "Quad":   st.column_config.TextColumn("RRG",      width=100),
                "Vel":    st.column_config.NumberColumn("Vel",    format="%.2f"),
                "Vol":    st.column_config.NumberColumn("Rel Vol", format="%.1fx"),
            })
    else:
        st.info("No active holdings.")

    # Prime Entries
    st.markdown("#### 🟢 Prime Entries")
    if not res["buys"].empty:
        view_buys = res["buys"].sort_values("Alpha", ascending=False).head(10)
        evt = st.dataframe(
            view_buys, use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Ticker": st.column_config.TextColumn("Ticker",   width=70),
                "Signal": st.column_config.TextColumn("Signal",   width=160),
                "Alpha":  st.column_config.NumberColumn("Alpha",  format="%.2f"),
                "Quad":   st.column_config.TextColumn("RRG",      width=100),
                "Vel":    st.column_config.NumberColumn("Vel",    format="%.2f"),
                "Vol":    st.column_config.NumberColumn("Rel Vol", format="%.1fx"),
                "VSA":    st.column_config.TextColumn("VSA",      width=180),
            },
        )
        if evt.selection.rows:
            target = view_buys.iloc[evt.selection.rows[0]]["Ticker"]
            _set_focus(target)
            if st.session_state.scan_mode == "MARKET":
                _, _, _, _, _, _, add_to_watchlist = _lazy_imports()
                add_to_watchlist(target)
                st.toast(f"{target} added to Trap", icon="🎯")
            st.rerun()
    else:
        st.info("💤 No fresh ignition signals.")

    # Capital Swaps
    if not res["swaps"].empty:
        st.markdown("#### 🔄 Capital Swaps")
        st.dataframe(res["swaps"].head(5), use_container_width=True, hide_index=True,
            column_config={
                "Ticker": st.column_config.TextColumn("BUY",    width=70),
                "Funder": st.column_config.TextColumn("SELL",   width=70),
                "Signal": st.column_config.TextColumn("Signal", width=160),
                "Alpha":  st.column_config.NumberColumn("Alpha", format="%.2f"),
            })

st.divider()

# ==============================================================================
# THE TRAP — Persistent Watchlist
# ==============================================================================
st.markdown("## 🎯 The Trap")

try:
    _, _, _, _, _, get_watchlist, add_to_watchlist = _lazy_imports()
    watchlist_df = get_watchlist(regime)

    evt_trap = st.dataframe(
        watchlist_df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Ticker":       st.column_config.TextColumn("Ticker",  width=70),
            "Sector State": st.column_config.TextColumn("Sector",  width=130),
            "Signal":       st.column_config.TextColumn("Signal",  width=200),
            "VSA":          st.column_config.TextColumn("VSA",     width=180),
        },
    )

    if evt_trap.selection.rows and not watchlist_df.empty:
        trap_ticker = watchlist_df.iloc[evt_trap.selection.rows[0]]["Ticker"]
        if st.session_state.active_ticker != trap_ticker:
            _set_focus(trap_ticker)
            st.rerun()

    c_add, c_btn2 = st.columns([3, 1])
    with c_add:
        new_ticker = st.text_input(
            "Add to Trap", label_visibility="collapsed",
            placeholder="Enter ticker..."
        ).upper()
    with c_btn2:
        if st.button("➕ Add", use_container_width=True) and new_ticker:
            add_to_watchlist(new_ticker)
            st.rerun()

except Exception as e:
    st.warning(f"Watchlist error: {e}")

st.divider()
st.caption(f"Active focus: **{st.session_state.active_ticker}** — navigate to Hunter for deep analysis.")
