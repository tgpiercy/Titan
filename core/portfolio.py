# FILE: core/portfolio.py
# ROLE: Portfolio persistence, trade execution, watchlist, decision engine
#
# PERSISTENCE HIERARCHY:
#   1. Google Sheets (gspread + google-auth via st.secrets) — primary
#   2. Local JSON                                           — fallback
#
# SHEETS STRUCTURE:
#   One spreadsheet, three tabs:
#     apex_portfolio  — open positions
#     apex_trade_log  — closed trade archive
#     apex_watchlist  — ticker watchlist
#
# DECISION ENGINE:
#   Reuses SignalResult from core/signals to produce portfolio actions:
#   HOLD / ADD / TRIM / REDUCE / EXIT / RAISE STOP
#   Mirrors StratFlow's balanced decision engine logic.

from __future__ import annotations

import json
import os
from datetime import datetime
from dataclasses import dataclass

import pandas as pd
import streamlit as st

import config as cfg


# ==============================================================================
# PORTFOLIO COLUMNS
# ==============================================================================
PORT_COLS = [
    "Ticker", "Entry Price", "Shares", "Stop Loss", "Entry Date",
    "Currency", "Market_Condition", "VSA_Signal", "RRG_State",
    "Flow_Score", "User_Note",
]

HISTORY_COLS = [
    "Ticker", "Entry Price", "Exit Price", "Shares", "PnL", "Return_Pct",
    "Entry Date", "Exit Date", "Currency",
    "Market_Condition", "VSA_Signal", "RRG_State", "User_Note",
]

WATCHLIST_COLS = ["Ticker", "Added"]


# ==============================================================================
# GOOGLE SHEETS CONNECTOR
# ==============================================================================
def _get_sheet(tab_name: str):
    """Returns a gspread worksheet or None if unavailable."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds      = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc         = gspread.authorize(creds)
        spreadsheet_id = st.secrets.get("spreadsheet_id", "")
        sh = gc.open_by_key(spreadsheet_id)

        try:
            return sh.worksheet(tab_name)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title=tab_name, rows=500, cols=20)
            return ws

    except Exception:
        return None


def _sheet_to_df(tab_name: str, columns: list) -> pd.DataFrame:
    ws = _get_sheet(tab_name)
    if ws is None:
        return _local_load(tab_name, columns)
    try:
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=columns)
        df = pd.DataFrame(records)
        for col in columns:
            if col not in df.columns:
                df[col] = ""
        return df[columns]
    except Exception:
        return _local_load(tab_name, columns)


def _df_to_sheet(tab_name: str, df: pd.DataFrame) -> bool:
    """Write full DataFrame to sheet. Returns True on success."""
    ws = _get_sheet(tab_name)
    if ws is None:
        _local_save(tab_name, df)
        return False
    try:
        ws.clear()
        ws.update([df.columns.tolist()] + df.fillna("").values.tolist())
        _local_save(tab_name, df)   # keep local in sync as backup
        return True
    except Exception:
        _local_save(tab_name, df)
        return False


# ==============================================================================
# LOCAL JSON FALLBACK
# ==============================================================================
_JSON_MAP = {
    cfg.PORTFOLIO_SHEET:  cfg.LOCAL_PORTFOLIO_JSON,
    cfg.HISTORY_SHEET:    cfg.LOCAL_HISTORY_JSON,
    cfg.WATCHLIST_SHEET:  cfg.LOCAL_WATCHLIST_JSON,
}

def _local_save(tab_name: str, df: pd.DataFrame):
    path = _JSON_MAP.get(tab_name)
    if path:
        try:
            df.to_json(path, orient="records", date_format="iso")
        except Exception:
            pass

def _local_load(tab_name: str, columns: list) -> pd.DataFrame:
    path = _JSON_MAP.get(tab_name)
    if path and os.path.exists(path):
        try:
            df = pd.read_json(path, orient="records")
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
            return df[columns]
        except Exception:
            pass
    return pd.DataFrame(columns=columns)


# ==============================================================================
# PUBLIC: PORTFOLIO
# ==============================================================================
def get_portfolio() -> pd.DataFrame:
    return _sheet_to_df(cfg.PORTFOLIO_SHEET, PORT_COLS)


def get_position(ticker: str) -> dict | None:
    """Returns position dict or None if not held."""
    df = get_portfolio()
    row = df[df["Ticker"] == ticker]
    if row.empty:
        return None
    return row.iloc[0].to_dict()


def execute_trade(
    ticker:     str,
    price:      float,
    shares:     int,
    stop:       float,
    market:     str = "",
    vsa:        str = "",
    rrg:        str = "",
    flow_score: float = 0.0,
    note:       str = "",
    currency:   str = "USD",
    entry_date: datetime | None = None,
) -> bool:
    """
    Opens or overwrites a position.
    Positive shares = long, negative = short.
    """
    df = get_portfolio()
    date_str = (entry_date or datetime.now()).strftime("%Y-%m-%d")

    # Remove existing position for this ticker (overwrite mode)
    df = df[df["Ticker"] != ticker]

    new_row = pd.DataFrame([{
        "Ticker":           ticker,
        "Entry Price":      price,
        "Shares":           shares,
        "Stop Loss":        stop,
        "Entry Date":       date_str,
        "Currency":         currency,
        "Market_Condition": market,
        "VSA_Signal":       vsa,
        "RRG_State":        rrg,
        "Flow_Score":       flow_score,
        "User_Note":        note,
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    return _df_to_sheet(cfg.PORTFOLIO_SHEET, df)


def close_position(ticker: str, exit_price: float) -> bool:
    """Closes position and archives to trade log."""
    df_port = get_portfolio()
    row     = df_port[df_port["Ticker"] == ticker]
    if row.empty:
        return False

    pos         = row.iloc[0]
    entry_price = float(pos["Entry Price"])
    shares      = float(pos["Shares"])
    pnl         = (exit_price - entry_price) * shares
    ret_pct     = ((exit_price - entry_price) / entry_price) * 100 if shares > 0 \
                  else ((entry_price - exit_price) / entry_price) * 100

    # Archive
    df_hist = get_history()
    new_log = pd.DataFrame([{
        "Ticker":           ticker,
        "Entry Price":      entry_price,
        "Exit Price":       exit_price,
        "Shares":           shares,
        "PnL":              round(pnl, 2),
        "Return_Pct":       round(ret_pct, 2),
        "Entry Date":       pos.get("Entry Date", ""),
        "Exit Date":        datetime.now().strftime("%Y-%m-%d"),
        "Currency":         pos.get("Currency", "USD"),
        "Market_Condition": pos.get("Market_Condition", ""),
        "VSA_Signal":       pos.get("VSA_Signal", ""),
        "RRG_State":        pos.get("RRG_State", ""),
        "User_Note":        pos.get("User_Note", ""),
    }])
    df_hist = pd.concat([df_hist, new_log], ignore_index=True)
    _df_to_sheet(cfg.HISTORY_SHEET, df_hist)

    # Remove from portfolio
    df_port = df_port[df_port["Ticker"] != ticker]
    return _df_to_sheet(cfg.PORTFOLIO_SHEET, df_port)


def update_stop(ticker: str, new_stop: float) -> bool:
    df = get_portfolio()
    if ticker not in df["Ticker"].values:
        return False
    df.loc[df["Ticker"] == ticker, "Stop Loss"] = new_stop
    return _df_to_sheet(cfg.PORTFOLIO_SHEET, df)


def delete_record(ticker: str) -> bool:
    """Admin delete — no cash credit, no archive. Fix typos only."""
    df = get_portfolio()
    df = df[df["Ticker"] != ticker]
    return _df_to_sheet(cfg.PORTFOLIO_SHEET, df)


# ==============================================================================
# PUBLIC: TRADE HISTORY
# ==============================================================================
def get_history() -> pd.DataFrame:
    return _sheet_to_df(cfg.HISTORY_SHEET, HISTORY_COLS)


# ==============================================================================
# PUBLIC: WATCHLIST
# ==============================================================================
def get_watchlist(regime=None) -> pd.DataFrame:
    """
    Returns watchlist enriched with Sector State + Signal + VSA.
    regime: RegimeResult (used for market veto interlock).
    """
    df = _sheet_to_df(cfg.WATCHLIST_SHEET, WATCHLIST_COLS)

    if df.empty:
        _seed_watchlist()
        df = _sheet_to_df(cfg.WATCHLIST_SHEET, WATCHLIST_COLS)

    if df.empty:
        return pd.DataFrame(columns=["Ticker", "Added", "Sector State", "Signal", "VSA"])

    is_locked = regime is not None and regime.is_risk_off

    # Enrich with live signals
    from core.data    import get_ohlcv
    from core.vsa     import get_vsa_verdict
    from core.rrg     import get_generals_rrg, get_latest_snapshot
    from core.signals import get_trigger_signal

    df_rrg   = get_generals_rrg()
    snap_rrg = get_latest_snapshot(df_rrg)

    sector_states, signals, vsas = [], [], []

    for ticker in df["Ticker"]:
        try:
            # RRG state
            quad, vel = "UNTRACKED", 0.0
            sec_state = "⚪ UNTRACKED"
            if not snap_rrg.empty and ticker in snap_rrg["Ticker"].values:
                row   = snap_rrg[snap_rrg["Ticker"] == ticker].iloc[0]
                quad  = row.get("Quadrant", "UNTRACKED")
                vel   = float(row.get("Velocity", 0.0))
                accel = float(row.get("Acceleration", 0.0))
                tactical = row.get("Tactical", "")
                thrust   = row.get("Thrust", "")
                sec_state = f"{tactical} | {thrust}"

            # VSA
            df_t = get_ohlcv(ticker, period="1mo")
            if df_t.empty:
                vsas.append("NO DATA")
                signals.append("⚠️ CHECK")
                sector_states.append(sec_state)
                continue

            vsa_txt, _, _ = get_vsa_verdict(df_t)

            # Signal (with market veto)
            if is_locked:
                sig = "⛔ MARKET VETO"
            else:
                sig, _, _ = get_trigger_signal(vsa_txt, quad, vel)

            sector_states.append(sec_state)
            signals.append(sig)
            vsas.append(vsa_txt)

        except Exception:
            sector_states.append("ERR")
            signals.append("ERR")
            vsas.append("ERR")

    df["Sector State"] = sector_states
    df["Signal"]       = signals
    df["VSA"]          = vsas

    return df[["Ticker", "Added", "Sector State", "Signal", "VSA"]]


def add_to_watchlist(ticker: str) -> bool:
    df = _sheet_to_df(cfg.WATCHLIST_SHEET, WATCHLIST_COLS)
    if ticker in df["Ticker"].astype(str).values:
        return False  # already present
    new_row = pd.DataFrame([{
        "Ticker": ticker.upper(),
        "Added":  datetime.now().strftime("%Y-%m-%d"),
    }])
    df = pd.concat([df, new_row], ignore_index=True)
    return _df_to_sheet(cfg.WATCHLIST_SHEET, df)


def remove_from_watchlist(ticker: str) -> bool:
    df = _sheet_to_df(cfg.WATCHLIST_SHEET, WATCHLIST_COLS)
    df = df[df["Ticker"] != ticker]
    return _df_to_sheet(cfg.WATCHLIST_SHEET, df)


def _seed_watchlist():
    """Populate default watchlist on first run."""
    rows = [{"Ticker": t, "Added": datetime.now().strftime("%Y-%m-%d")}
            for t in cfg.DEFAULT_WATCHLIST]
    df = pd.DataFrame(rows)
    _df_to_sheet(cfg.WATCHLIST_SHEET, df)


# ==============================================================================
# DECISION ENGINE
# ==============================================================================
@dataclass
class PortfolioDecision:
    action:      str    # HOLD | ADD | TRIM | REDUCE | EXIT | RAISE STOP
    color:       str
    rationale:   str
    stop_target: float | None = None


def get_decision(
    pos:         dict,
    current_price: float,
    sig_result,          # SignalResult from core/signals
    regime=None,         # RegimeResult from core/regime
) -> PortfolioDecision:
    """
    Produces a portfolio management decision for an open position.

    Logic hierarchy:
      1. Hard stop breach → EXIT (no override)
      2. Market regime veto → REDUCE
      3. Signal EXIT/FADE → EXIT or TRIM
      4. Signal ADD/EXECUTE + regime OK → ADD
      5. Trend intact, stop comfortable → RAISE STOP or HOLD
    """
    entry      = float(pos.get("Entry Price", current_price))
    stop       = float(pos.get("Stop Loss",   current_price * 0.92))
    shares     = float(pos.get("Shares", 0))
    is_long    = shares >= 0

    pnl_pct    = ((current_price - entry) / entry * 100) if entry > 0 else 0
    above_stop = current_price > stop if is_long else current_price < stop
    sig_action = sig_result.action if sig_result else "HOLD"
    is_risk_off = regime is not None and regime.is_risk_off

    # --- Rule 1: Hard stop breach ---
    if not above_stop:
        return PortfolioDecision(
            action    = "EXIT",
            color     = "#FF2222",
            rationale = f"Hard stop breached — price ${current_price:.2f} vs stop ${stop:.2f}",
        )

    # --- Rule 2: Market regime veto ---
    if is_risk_off and sig_action not in {"EXIT", "AVOID"}:
        return PortfolioDecision(
            action    = "REDUCE",
            color     = "#FF8800",
            rationale = f"Regime: {regime.status} — reduce exposure, protect capital",
        )

    # --- Rule 3: Exit signals ---
    if sig_action in {"EXIT", "AVOID"}:
        return PortfolioDecision(
            action    = "EXIT",
            color     = "#FF4444",
            rationale = sig_result.description,
        )

    if sig_action == "HOLD" and pnl_pct < -5:
        return PortfolioDecision(
            action    = "TRIM",
            color     = "#FFA500",
            rationale = f"Momentum stalling, position -({abs(pnl_pct):.1f}%) — trim to reduce risk",
        )

    # --- Rule 4: Add signals ---
    if sig_action == "EXECUTE" and not is_risk_off and pnl_pct > 0:
        return PortfolioDecision(
            action    = "ADD",
            color     = "#00CC44",
            rationale = sig_result.description + " — pyramid into strength",
        )

    # --- Rule 5: Stop management ---
    if pnl_pct > 15 and sig_action in {"RIDE", "HOLD"}:
        # Trail stop suggestion: 2× ATR below current (approximated)
        trail_stop = current_price * 0.93
        return PortfolioDecision(
            action     = "RAISE STOP",
            color      = "#00CCFF",
            rationale  = f"Position +{pnl_pct:.1f}% — trail stop to lock gains",
            stop_target = trail_stop,
        )

    if pnl_pct > 5 and sig_action in {"RIDE", "HOLD"}:
        be_stop = entry * 1.005   # move to break-even + 0.5%
        return PortfolioDecision(
            action     = "RAISE STOP",
            color      = "#00CCFF",
            rationale  = f"Position +{pnl_pct:.1f}% — move stop to break-even",
            stop_target = be_stop,
        )

    return PortfolioDecision(
        action    = "HOLD",
        color     = "#888888",
        rationale = "Structure intact — no action required",
    )


# ==============================================================================
# HELPERS: P&L calculations
# ==============================================================================
def enrich_portfolio(df: pd.DataFrame, prices: dict) -> pd.DataFrame:
    """
    Adds live price, value, P&L columns to a portfolio DataFrame.
    prices: {ticker: current_price}
    """
    if df.empty:
        return df

    df = df.copy()
    df["Current"]          = df["Ticker"].map(prices).fillna(df["Entry Price"].astype(float))
    df["Current"]          = df["Current"].astype(float)
    df["Entry Price"]      = df["Entry Price"].astype(float)
    df["Shares"]           = df["Shares"].astype(float)
    df["Stop Loss"]        = df["Stop Loss"].astype(float)

    df["Value"]            = df["Current"] * df["Shares"].abs()
    df["Cost Basis"]       = df["Entry Price"] * df["Shares"].abs()
    df["Unrealized PnL"]   = (df["Current"] - df["Entry Price"]) * df["Shares"]
    df["PnL %"]            = ((df["Current"] - df["Entry Price"]) / df["Entry Price"]) * 100
    df["Risk Buffer %"]    = ((df["Current"] - df["Stop Loss"]) / df["Current"]) * 100

    return df


def performance_summary(df_history: pd.DataFrame) -> dict:
    """Returns summary stats from closed trade log."""
    if df_history.empty:
        return {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "realized_pnl": 0.0,
            "avg_win": 0.0, "avg_loss": 0.0, "expectancy": 0.0,
        }

    pnl        = pd.to_numeric(df_history["PnL"], errors="coerce").dropna()
    wins       = pnl[pnl > 0]
    losses     = pnl[pnl < 0]
    total      = len(pnl)
    win_rate   = len(wins) / total * 100 if total > 0 else 0.0
    avg_win    = float(wins.mean())   if not wins.empty   else 0.0
    avg_loss   = float(losses.mean()) if not losses.empty else 0.0
    expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

    return {
        "total_trades": total,
        "wins":         len(wins),
        "losses":       len(losses),
        "win_rate":     round(win_rate, 1),
        "realized_pnl": round(float(pnl.sum()), 2),
        "avg_win":      round(avg_win, 2),
        "avg_loss":     round(avg_loss, 2),
        "expectancy":   round(expectancy, 2),
    }

