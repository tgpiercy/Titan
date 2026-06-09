# FILE: pages/4_Portfolio.py
# ROLE: The Vault — open positions, decision engine, trade terminal, service record

import streamlit as st
import pandas as pd
from datetime import datetime

import ui
import config as cfg
from core.data      import get_ohlcv, get_latest_price
from core.vsa       import get_vsa_verdict
from core.signals   import synthesise
from core.regime    import get_regime
from core.portfolio import (
    get_portfolio, get_history, enrich_portfolio, performance_summary,
    get_decision, execute_trade, close_position, update_stop,
    delete_record, add_to_watchlist,
)

st.markdown(ui.get_styles(), unsafe_allow_html=True)

# ==============================================================================
# SESSION STATE
# ==============================================================================
if "active_ticker" not in st.session_state:
    st.session_state.active_ticker = "SPY"

# ==============================================================================
# LOAD DATA
# ==============================================================================
regime   = get_regime()
port_df  = get_portfolio()
hist_df  = get_history()

# Fetch live prices for all held positions
tickers = port_df["Ticker"].tolist() if not port_df.empty else []
prices  = {}
if tickers:
    for t in tickers:
        p = get_latest_price(t)
        if p:
            prices[t] = p

port_enriched   = enrich_portfolio(port_df, prices) if not port_df.empty else pd.DataFrame()
total_value     = float(port_enriched["Value"].sum())         if not port_enriched.empty else 0.0
total_open_pnl  = float(port_enriched["Unrealized PnL"].sum()) if not port_enriched.empty else 0.0
perf            = performance_summary(hist_df)

# ==============================================================================
# HEADER METRICS
# ==============================================================================
st.title("🏦 Portfolio")

m1, m2, m3, m4 = st.columns(4)
m1.metric("Total Equity",    f"${total_value:,.2f}")
m2.metric("Open P&L",        f"${total_open_pnl:,.2f}",
          delta_color="normal" if total_open_pnl >= 0 else "inverse")
m3.metric("Positions",       len(port_enriched) if not port_enriched.empty else 0)
m4.metric("Win Rate",        f"{perf['win_rate']}%", f"{perf['total_trades']} closed trades")

st.divider()

# ==============================================================================
# OPEN POSITIONS TABLE
# ==============================================================================
st.markdown("## 📊 Open Positions")

if not port_enriched.empty:
    display_cols = [
        "Ticker", "Shares", "Entry Price", "Current",
        "Stop Loss", "PnL %", "Unrealized PnL", "Risk Buffer %",
    ]
    display_cols = [c for c in display_cols if c in port_enriched.columns]

    evt_port = st.dataframe(
        port_enriched[display_cols],
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Ticker":        st.column_config.TextColumn("Ticker",      width=70),
            "Shares":        st.column_config.NumberColumn("Size",      width=60),
            "Entry Price":   st.column_config.NumberColumn("Entry",     format="$%.2f"),
            "Current":       st.column_config.NumberColumn("Price",     format="$%.2f"),
            "Stop Loss":     st.column_config.NumberColumn("Stop",      format="$%.2f"),
            "PnL %":         st.column_config.NumberColumn("P&L %",     format="%.2f%%"),
            "Unrealized PnL":st.column_config.NumberColumn("P&L $",     format="$%.2f"),
            "Risk Buffer %": st.column_config.ProgressColumn(
                "Risk Buffer", min_value=-10, max_value=25, format="%.1f%%"
            ),
        },
    )

    # Row selection → set focus
    if evt_port.selection.rows:
        selected_ticker = port_enriched.iloc[evt_port.selection.rows[0]]["Ticker"]
        st.session_state.active_ticker = selected_ticker

else:
    st.info("The Vault is empty. Execute your first trade below.")

st.divider()

# ==============================================================================
# DECISION ENGINE PANEL
# ==============================================================================
st.markdown("## 🧠 Decision Engine")

if not port_enriched.empty:
    decisions = []

    for _, pos_row in port_enriched.iterrows():
        ticker_d      = pos_row["Ticker"]
        current_price = float(pos_row.get("Current", pos_row["Entry Price"]))

        # Get signal for this position
        try:
            df_t        = get_ohlcv(ticker_d, period="3mo")
            vsa_txt, _, _ = get_vsa_verdict(df_t) if not df_t.empty else ("NEUTRAL", "#888", "")
            rrg_state   = pos_row.get("RRG_State", "UNTRACKED")
            sig_result  = synthesise(vsa_txt, rrg_state, flow_score=None)
            decision    = get_decision(pos_row.to_dict(), current_price, sig_result, regime)
        except Exception:
            from core.signals import SignalResult
            sig_result = SignalResult("HOLD", "#888", "", "D", 0.0, "HOLD")
            decision   = get_decision(pos_row.to_dict(), current_price, sig_result, regime)

        decisions.append({
            "Ticker":    ticker_d,
            "Price":     f"${current_price:.2f}",
            "P&L %":     f"{pos_row.get('PnL %', 0):.1f}%",
            "Action":    decision.action,
            "Rationale": decision.rationale,
            "_color":    decision.color,
            "_stop_tgt": decision.stop_target,
        })

    # Render decision cards
    for dec in decisions:
        col_action, col_ticker, col_price, col_pnl, col_reason = st.columns([1.5, 1, 1, 1, 5])

        action_html = (
            f"<div style='background:{dec['_color']}22; border:1px solid {dec['_color']}; "
            f"border-radius:5px; padding:6px 10px; text-align:center; "
            f"font-weight:700; color:{dec['_color']}; font-size:15px;'>"
            f"{dec['Action']}</div>"
        )
        col_action.markdown(action_html, unsafe_allow_html=True)
        col_ticker.markdown(f"**{dec['Ticker']}**")
        col_price.markdown(dec["Price"])
        col_pnl.markdown(dec["P&L %"])
        col_reason.caption(dec["Rationale"])

        # Auto-apply stop raise
        if dec["Action"] == "RAISE STOP" and dec["_stop_tgt"]:
            if st.button(f"Apply Stop → ${dec['_stop_tgt']:.2f}", key=f"stop_{dec['Ticker']}"):
                update_stop(dec["Ticker"], dec["_stop_tgt"])
                st.toast(f"Stop updated for {dec['Ticker']}", icon="🛡️")
                st.rerun()

else:
    st.info("No positions to evaluate.")

st.divider()

# ==============================================================================
# TRADE TERMINAL (sidebar-style tabs)
# ==============================================================================
st.markdown("## ⚡ Trade Terminal")

tab_trade, tab_manage, tab_watch = st.tabs(["🟢 EXECUTE", "💼 MANAGE", "🎯 WATCHLIST"])

# -----------------------------------------------------------------------
# TAB 1: EXECUTE
# -----------------------------------------------------------------------
with tab_trade:
    col_l, col_r = st.columns([1, 1])

    with col_l:
        sb_ticker = st.text_input("Ticker", key="term_ticker").upper()

    with col_r:
        side = st.radio("Side", ["🟢 LONG", "🔴 SHORT"], horizontal=True)
        is_long = "LONG" in side

    if sb_ticker:
        curr_price = get_latest_price(sb_ticker) or 0.0

        # ATR for auto-stop
        try:
            df_live = get_ohlcv(sb_ticker, period="3mo")
            if not df_live.empty:
                hl       = df_live["High"] - df_live["Low"]
                atr_live = float(hl.rolling(14).mean().iloc[-1])
            else:
                atr_live = curr_price * 0.02
        except Exception:
            atr_live = curr_price * 0.02

        default_stop = (
            curr_price - 2.0 * atr_live if is_long
            else curr_price + 2.0 * atr_live
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("Live Price", f"${curr_price:.2f}")
        c2.metric("ATR (14)",   f"${atr_live:.2f}")
        regime_status = regime.status if regime else "OFFLINE"
        c3.metric("Regime",     regime_status)

        st.markdown("---")

        col_e, col_s = st.columns(2)
        with col_e:
            entry = st.number_input("Entry Price", value=float(curr_price), format="%.2f", step=0.01)
        with col_s:
            stop  = st.number_input("Hard Stop",   value=float(default_stop), format="%.2f", step=0.01)

        trade_date = st.date_input("Trade Date", value=datetime.now())

        # Position sizing
        sidebar_balance  = st.session_state.get("sidebar_balance",  10_000)
        sidebar_risk_pct = st.session_state.get("sidebar_risk_pct", 1.0)
        balance  = st.number_input("Capital ($)", value=sidebar_balance,  step=1000, min_value=100)
        risk_pct = st.slider("Risk %", 0.25, 2.0, sidebar_risk_pct, step=0.25)

        valid = (is_long and entry > stop > 0) or (not is_long and entry < stop)
        suggested_shares = 0
        scalar = regime.size_scalar if regime else 1.0

        if valid and entry > 0:
            risk_amt     = balance * (risk_pct / 100)
            risk_per_sh  = abs(entry - stop)
            raw          = risk_amt / risk_per_sh
            suggested_shares = max(1, int(raw * scalar))

        safe_shares = max(1, suggested_shares)
        shares_input = st.number_input("Shares", value=safe_shares, min_value=1, step=1)

        final_cost = shares_input * entry
        final_risk = shares_input * abs(entry - stop)

        if final_cost > balance:
            st.error(f"❌ Insufficient capital. Cost: ${final_cost:,.2f}")
        else:
            if scalar < 1.0:
                st.caption(f"🐻 Bear Protocol active — {int(scalar*100)}% size")
            st.caption(f"Cost: ${final_cost:,.2f}  ·  Risk: ${final_risk:,.2f}")

            note = st.text_area("Trade Thesis", height=60, placeholder="Why are you entering?")

            btn_text = f"{'BUY' if is_long else 'SHORT'} {shares_input} {sb_ticker}"
            if st.button(btn_text, type="primary", use_container_width=True):
                final_shares = shares_input if is_long else -shares_input
                vsa_ctx = ""
                try:
                    df_ctx = get_ohlcv(sb_ticker, period="1mo")
                    vsa_ctx, _, _ = get_vsa_verdict(df_ctx)
                except Exception:
                    pass

                execute_trade(
                    ticker     = sb_ticker,
                    price      = entry,
                    shares     = final_shares,
                    stop       = stop,
                    market     = regime.status if regime else "",
                    vsa        = vsa_ctx,
                    rrg        = "UNTRACKED",
                    flow_score = 0.0,
                    note       = note,
                    entry_date = datetime.combine(trade_date, datetime.min.time()),
                )
                st.toast(f"✅ {btn_text} @ ${entry:.2f}", icon="⚡")
                st.rerun()

# -----------------------------------------------------------------------
# TAB 2: MANAGE
# -----------------------------------------------------------------------
with tab_manage:
    if not port_enriched.empty:
        manage_tickers = port_enriched["Ticker"].tolist()
        target = st.selectbox("Position", manage_tickers)

        pos_row = port_enriched[port_enriched["Ticker"] == target]
        if not pos_row.empty:
            pos      = pos_row.iloc[0]
            p_entry  = float(pos["Entry Price"])
            p_stop   = float(pos["Stop Loss"])
            p_shares = float(pos["Shares"])
            p_curr   = float(pos.get("Current", p_entry))
            p_pnl    = float(pos.get("Unrealized PnL", 0))

            direction = "LONG" if p_shares > 0 else "SHORT"
            pnl_col   = "normal" if p_pnl >= 0 else "inverse"

            ma, mb = st.columns(2)
            ma.metric("Open P&L", f"${p_pnl:.2f}", delta_color=pnl_col)
            mb.metric("Direction", direction)
            st.caption(f"Entry: ${p_entry:.2f}  ·  Stop: ${p_stop:.2f}  ·  Size: {abs(p_shares):.0f}")

            st.markdown("---")
            mgmt_action = st.radio(
                "Action",
                ["Adjust Stop", "Liquidate", "Admin Delete"],
                horizontal=True,
            )

            if mgmt_action == "Adjust Stop":
                new_stop = st.number_input("New Stop Price", value=float(p_stop), format="%.2f", step=0.01)
                if st.button("Update Stop", type="primary"):
                    update_stop(target, new_stop)
                    st.success(f"Stop updated to ${new_stop:.2f}")
                    st.rerun()

            elif mgmt_action == "Liquidate":
                exit_price = st.number_input("Exit Price", value=float(p_curr), format="%.2f", step=0.01)
                est_pnl    = (exit_price - p_entry) * p_shares
                st.metric("Est. P&L", f"${est_pnl:.2f}", delta_color="normal" if est_pnl >= 0 else "inverse")
                if st.button("🛑 CLOSE POSITION", type="primary"):
                    close_position(target, exit_price)
                    st.toast(f"{target} closed @ ${exit_price:.2f}", icon="💰")
                    st.rerun()

            elif mgmt_action == "Admin Delete":
                st.warning("⚠️ No archive entry. Use only to fix data entry errors.")
                if st.button("🗑️ Delete Record"):
                    delete_record(target)
                    st.rerun()
    else:
        st.info("No open positions to manage.")

# -----------------------------------------------------------------------
# TAB 3: WATCHLIST MANAGEMENT
# -----------------------------------------------------------------------
with tab_watch:
    wl_df = _sheet_to_df_local = None
    try:
        from core.portfolio import _sheet_to_df, WATCHLIST_COLS
        wl_df = _sheet_to_df(cfg.WATCHLIST_SHEET, WATCHLIST_COLS)
    except Exception:
        wl_df = pd.DataFrame(columns=["Ticker", "Added"])

    if wl_df is not None and not wl_df.empty:
        st.dataframe(wl_df, use_container_width=True, hide_index=True)

    wc1, wc2 = st.columns([3, 1])
    with wc1:
        new_watch = st.text_input("Add ticker", label_visibility="collapsed",
                                  placeholder="Ticker to add...").upper()
    with wc2:
        if st.button("➕ Add", use_container_width=True) and new_watch:
            add_to_watchlist(new_watch)
            st.rerun()

    if wl_df is not None and not wl_df.empty:
        remove_ticker = st.selectbox("Remove ticker", ["—"] + wl_df["Ticker"].tolist())
        if remove_ticker != "—":
            if st.button(f"🗑️ Remove {remove_ticker}"):
                from core.portfolio import remove_from_watchlist
                remove_from_watchlist(remove_ticker)
                st.rerun()

st.divider()

# ==============================================================================
# SERVICE RECORD (Closed Trades)
# ==============================================================================
st.markdown("## 🎖️ Service Record")

s1, s2, s3, s4 = st.columns(4)
s1.metric("Realized P&L",   f"${perf['realized_pnl']:,.2f}")
s2.metric("Win Rate",        f"{perf['win_rate']}%",
          f"{perf['wins']}W / {perf['losses']}L")
s3.metric("Avg Win",         f"${perf['avg_win']:,.2f}")
s4.metric("Expectancy",      f"${perf['expectancy']:,.2f} / trade")

if not hist_df.empty:
    view_hist = hist_df.copy()
    display_h = ["Exit Date", "Ticker", "Entry Price", "Exit Price",
                 "PnL", "Return_Pct", "User_Note"]
    display_h = [c for c in display_h if c in view_hist.columns]
    view_hist = view_hist[display_h].sort_values("Exit Date", ascending=False).head(20)

    st.dataframe(
        view_hist,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Exit Date":   st.column_config.DateColumn("Closed"),
            "Ticker":      st.column_config.TextColumn("Asset",   width=70),
            "Entry Price": st.column_config.NumberColumn("Entry", format="$%.2f"),
            "Exit Price":  st.column_config.NumberColumn("Exit",  format="$%.2f"),
            "PnL":         st.column_config.NumberColumn("P&L $", format="$%.2f"),
            "Return_Pct":  st.column_config.NumberColumn("Ret %", format="%.2f%%"),
            "User_Note":   st.column_config.TextColumn("Thesis", width=350),
        },
    )
else:
    st.info("No closed trades yet. History will appear here after your first exit.")

