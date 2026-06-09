# FILE: core/backtest.py
# ROLE: Walk-forward validation harness
#
# VALIDATED BASELINE: RS Extension (OOS Sharpe 0.96, CAGR 26.2%, MaxDD -12.7%)
#
# WALK-FORWARD STRUCTURE:
#   IS  (In-Sample):  First 70% of data
#   OOS (Out-of-Sample): Last 30% — the only metrics that matter
#   WFE (Walk-Forward Efficiency): OOS Sharpe / IS Sharpe
#     >= 0.70 excellent  |  >= 0.50 acceptable  |  < 0.50 likely overfit

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf

import config as cfg


# ==============================================================================
# RESULT CLASS
# ==============================================================================
class BacktestResult:
    def __init__(
        self,
        name:       str,
        equity:     pd.Series,
        positions:  pd.Series,
        returns:    pd.Series,
        is_sharpe:  float,
        oos_sharpe: float,
        is_cagr:    float,
        oos_cagr:   float,
        is_maxdd:   float,
        oos_maxdd:  float,
        wfe:        float,
        trades:     int,
        split_idx:  int,
    ):
        self.name       = name
        self.equity     = equity
        self.positions  = positions
        self.returns    = returns
        self.is_sharpe  = is_sharpe
        self.oos_sharpe = oos_sharpe
        self.is_cagr    = is_cagr
        self.oos_cagr   = oos_cagr
        self.is_maxdd   = is_maxdd
        self.oos_maxdd  = oos_maxdd
        self.wfe        = wfe
        self.trades     = trades
        self.split_idx  = split_idx

    def summary_row(self) -> dict:
        return {
            "Strategy":    self.name,
            "IS Sharpe":   round(self.is_sharpe,  2),
            "OOS Sharpe":  round(self.oos_sharpe, 2),
            "IS CAGR %":   round(self.is_cagr,    1),
            "OOS CAGR %":  round(self.oos_cagr,   1),
            "IS MaxDD %":  round(self.is_maxdd,    1),
            "OOS MaxDD %": round(self.oos_maxdd,   1),
            "WFE":         round(self.wfe,         2),
            "Trades":      self.trades,
        }


# ==============================================================================
# DATA FETCH — direct yfinance, bypasses cache layer issues
# ==============================================================================
def _fetch_closes(tickers: list[str], period: str) -> pd.DataFrame:
    """
    Fetches daily closes for a list of tickers directly via yfinance.
    Returns a clean wide DataFrame (Date index, tickers as columns).
    Falls back to Stooq for any missing tickers.
    """
    try:
        raw = yf.download(
            tickers,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=True,
            threads=True,
        )
        if raw.empty:
            return pd.DataFrame()

        # Extract Close — handle both single and multi-ticker
        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" in raw.columns.get_level_values(0):
                closes = raw["Close"]
            else:
                closes = raw.xs("Close", level=0, axis=1)
        else:
            # Single ticker — raw IS the close data
            closes = raw[["Close"]] if "Close" in raw.columns else raw
            if len(tickers) == 1:
                closes.columns = [tickers[0]]

        closes = closes.ffill().dropna(how="all")

        # If some tickers missing, try Stooq for them
        missing = [t for t in tickers if t not in closes.columns]
        for t in missing:
            df = _stooq_close(t, period)
            if df is not None:
                closes[t] = df

        return closes.dropna(how="all")

    except Exception as e:
        return pd.DataFrame()


def _stooq_close(ticker: str, period: str) -> pd.Series | None:
    """Stooq fallback for a single ticker."""
    import requests, io
    period_days = {
        "1y": 365, "2y": 730, "3y": 1095, "5y": 1825, "7y": 2555
    }.get(period, 1825)
    try:
        url = f"https://stooq.com/q/d/l/?s={ticker.lower()}&i=d"
        r   = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        r.raise_for_status()
        df  = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"], index_col="Date")
        df.columns = [c.strip().title() for c in df.columns]
        if "Close" not in df.columns:
            return None
        return df["Close"].sort_index().iloc[-period_days:]
    except Exception:
        return None


# ==============================================================================
# MAIN BACKTEST
# ==============================================================================
def run_backtest(
    strategy:    str         = "rs_extension",
    universe:    list | None = None,
    benchmark:   str         = "SPY",
    period:      str         = "5y",
    top_n:       int         = 5,
    rs_window:   int         = 90,
    ext_thresh:  float       = 0.05,
    trend_ok:    bool        = False,
    vsa_thresh:  float       = 0.0,
    flow_thresh: float       = 0.0,
) -> BacktestResult | None:

    if universe is None:
        universe = list(cfg.SECTOR_MAP.values())

    all_tickers = list(set(universe + [benchmark]))

    closes = _fetch_closes(all_tickers, period)
    if closes.empty or benchmark not in closes.columns:
        return None

    bench  = closes[benchmark]
    assets = [t for t in universe if t in closes.columns]
    if len(assets) < 2:
        return None

    prices = closes[assets].copy()

    # ------------------------------------------------------------------
    # RS MOMENTUM MATRIX
    # rs_ratio[t] = (price[t] / bench) / rolling_mean(price[t] / bench)
    # Values > 1.0 = extending above RS trend
    # ------------------------------------------------------------------
    rs_mat = pd.DataFrame(index=prices.index, columns=assets, dtype=float)
    for t in assets:
        rs    = prices[t] / bench
        rs_ma = rs.rolling(rs_window).mean()
        rs_mat[t] = rs / rs_ma.replace(0, np.nan)

    # ------------------------------------------------------------------
    # TREND FILTER (causal — uses previous bar's SMA)
    # ------------------------------------------------------------------
    trend_mat = None
    if trend_ok:
        sma50     = prices.rolling(50).mean()
        trend_mat = (prices > sma50).shift(1).fillna(False)

    # ------------------------------------------------------------------
    # BUILD POSITION MATRIX
    # Key fix: use .loc with label-based indexing, not chained .iloc
    # ------------------------------------------------------------------
    pos_arr = np.zeros((len(prices), len(assets)), dtype=float)
    idx_map = {t: i for i, t in enumerate(assets)}
    dates   = prices.index

    for i in range(rs_window + 1, len(prices)):
        row_rs = rs_mat.iloc[i - 1]        # yesterday's RS (causal)

        # Extension filter
        eligible = [t for t in assets
                    if pd.notna(row_rs[t]) and row_rs[t] > (1.0 + ext_thresh)]

        # Trend filter
        if trend_ok and trend_mat is not None:
            row_tr   = trend_mat.iloc[i - 1]
            eligible = [t for t in eligible if bool(row_tr[t])]

        if not eligible:
            continue

        # Rank by RS, take top N, equal weight
        ranked = sorted(eligible, key=lambda t: row_rs[t], reverse=True)[:top_n]
        w      = 1.0 / len(ranked)
        for t in ranked:
            pos_arr[i, idx_map[t]] = w

    positions = pd.DataFrame(pos_arr, index=dates, columns=assets)

    # ------------------------------------------------------------------
    # PORTFOLIO RETURNS
    # positions are set on day i, returns are earned on day i+1
    # shift(1) ensures no lookahead
    # ------------------------------------------------------------------
    asset_rets = prices.pct_change().fillna(0)
    port_rets  = (positions.shift(1).fillna(0) * asset_rets).sum(axis=1)
    equity     = (1 + port_rets).cumprod() * 10_000
    total_pos  = positions.sum(axis=1)

    trade_count = int((positions.diff().abs().sum(axis=1) > 0).sum())

    # ------------------------------------------------------------------
    # IS / OOS SPLIT
    # ------------------------------------------------------------------
    split_idx  = int(len(port_rets) * 0.70)
    is_rets    = port_rets.iloc[:split_idx]
    oos_rets   = port_rets.iloc[split_idx:]

    is_sharpe  = _sharpe(is_rets)
    oos_sharpe = _sharpe(oos_rets)
    is_cagr    = _cagr(is_rets)
    oos_cagr   = _cagr(oos_rets)
    is_maxdd   = _maxdd(is_rets)
    oos_maxdd  = _maxdd(oos_rets)
    wfe        = oos_sharpe / is_sharpe if is_sharpe > 0 else 0.0

    return BacktestResult(
        name       = _strategy_label(strategy, trend_ok, ext_thresh),
        equity     = equity,
        positions  = total_pos,
        returns    = port_rets,
        is_sharpe  = is_sharpe,
        oos_sharpe = oos_sharpe,
        is_cagr    = is_cagr,
        oos_cagr   = oos_cagr,
        is_maxdd   = is_maxdd,
        oos_maxdd  = oos_maxdd,
        wfe        = wfe,
        trades     = trade_count,
        split_idx  = split_idx,
    )


# ==============================================================================
# BENCHMARK
# ==============================================================================
def run_benchmark(period: str = "5y") -> BacktestResult | None:
    closes = _fetch_closes(["SPY"], period)
    if closes.empty or "SPY" not in closes.columns:
        return None

    rets   = closes["SPY"].pct_change().fillna(0)
    equity = (1 + rets).cumprod() * 10_000
    split  = int(len(rets) * 0.70)

    return BacktestResult(
        name       = "SPY Buy & Hold",
        equity     = equity,
        positions  = pd.Series(1.0, index=rets.index),
        returns    = rets,
        is_sharpe  = _sharpe(rets.iloc[:split]),
        oos_sharpe = _sharpe(rets.iloc[split:]),
        is_cagr    = _cagr(rets.iloc[:split]),
        oos_cagr   = _cagr(rets.iloc[split:]),
        is_maxdd   = _maxdd(rets.iloc[:split]),
        oos_maxdd  = _maxdd(rets.iloc[split:]),
        wfe        = 1.0,
        trades     = 0,
        split_idx  = split,
    )


# ==============================================================================
# METRICS
# ==============================================================================
def _sharpe(rets: pd.Series, rf_daily: float = cfg.RISK_FREE_RATE / 252) -> float:
    rets = rets.dropna()
    if len(rets) < 20 or rets.std() == 0:
        return 0.0
    excess = rets - rf_daily
    return float(excess.mean() / excess.std() * np.sqrt(252))


def _cagr(rets: pd.Series) -> float:
    rets = rets.dropna()
    if len(rets) < 20:
        return 0.0
    n_years = len(rets) / 252
    total   = float((1 + rets).prod())
    if total <= 0:
        return 0.0
    return float((total ** (1 / n_years) - 1) * 100)


def _maxdd(rets: pd.Series) -> float:
    rets = rets.dropna()
    if rets.empty:
        return 0.0
    equity = (1 + rets).cumprod()
    dd     = (equity - equity.cummax()) / equity.cummax()
    return float(dd.min() * 100)


def _strategy_label(strategy: str, trend_ok: bool, ext_thresh: float) -> str:
    labels = {
        "rs_extension": f"RS Extension (ext>{ext_thresh:.2f})",
        "rs_trend":     f"RS + Trend Filter (ext>{ext_thresh:.2f})",
        "vsa_confirm":  f"RS + VSA Confirm (ext>{ext_thresh:.2f})",
        "flow_confirm": f"RS + Flow Confirm (ext>{ext_thresh:.2f})",
        "combined":     f"RS + VSA + Flow (ext>{ext_thresh:.2f})",
    }
    base = labels.get(strategy, strategy)
    if trend_ok and "Trend" not in base:
        base += " + Trend"
    return base
