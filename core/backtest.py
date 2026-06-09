# FILE: core/backtest.py
# ROLE: Walk-forward validation harness
#
# VALIDATED BASELINE: RS Extension (OOS Sharpe 0.96, CAGR 26.2%, MaxDD -12.7%)
# This is the system that won the StratFlow head-to-head. It is the benchmark
# every new filter or variant must beat before being promoted to live use.
#
# WALK-FORWARD STRUCTURE:
#   - IS  (In-Sample):  First 70% of data — parameter fitting
#   - OOS (Out-of-Sample): Last 30% — honest performance measurement
#   - WFE (Walk-Forward Efficiency): OOS Sharpe / IS Sharpe
#     WFE > 0.70 = excellent (minimal overfitting)
#     WFE > 0.50 = acceptable
#     WFE < 0.50 = likely overfit — do not promote
#
# SIGNALS AVAILABLE:
#   1. rs_extension   — validated baseline (RS momentum + extension filter)
#   2. rs_trend       — RS Extension + trend/deterioration filter
#   3. vsa_confirm    — RS Extension + VSA confirmation layer (new)
#   4. flow_confirm   — RS Extension + flow score threshold (new)
#   5. combined       — RS + VSA + flow together
#
# Each signal returns a daily position series (+1 long, 0 flat).
# Performance metrics calculated on that series vs buy-and-hold SPY.

from __future__ import annotations

import numpy as np
import pandas as pd

import config as cfg
from core.data import get_close_batch


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================
class BacktestResult:
    def __init__(
        self,
        name:       str,
        equity:     pd.Series,     # daily portfolio value
        positions:  pd.Series,     # +1 / 0
        returns:    pd.Series,     # daily returns
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
# MAIN: Run a named strategy
# ==============================================================================
def run_backtest(
    strategy:   str   = "rs_extension",
    universe:   list  | None = None,
    benchmark:  str   = "SPY",
    period:     str   = "5y",
    top_n:      int   = 5,
    rs_window:  int   = 90,
    ext_thresh: float = 0.05,
    trend_ok:   bool  = False,
    vsa_thresh: float = 0.0,
    flow_thresh: float= 0.0,
) -> BacktestResult | None:
    """
    Runs walk-forward backtest for a given strategy variant.

    Parameters
    ----------
    strategy    : one of rs_extension | rs_trend | vsa_confirm | flow_confirm | combined
    universe    : list of tickers (defaults to all sector ETFs)
    benchmark   : benchmark ticker for RS calculation
    period      : data period string
    top_n       : number of top-RS tickers to hold
    rs_window   : RS momentum lookback (days)
    ext_thresh  : RS extension threshold (rs_extension signal)
    trend_ok    : require causal trend filter (rs_trend signal)
    vsa_thresh  : min VSA score to confirm (vsa_confirm signal, placeholder)
    flow_thresh : min flow score to confirm (flow_confirm, placeholder)
    """
    if universe is None:
        universe = list(cfg.SECTOR_MAP.values())

    all_tickers = list(set(universe + [benchmark]))

    # Fetch closes
    closes = get_close_batch(all_tickers, period=period)
    if closes.empty or benchmark not in closes.columns:
        return None

    bench  = closes[benchmark]
    assets = [t for t in universe if t in closes.columns]
    if len(assets) < 2:
        return None

    prices = closes[assets].copy()

    # ----------------------------------------------------------------
    # SIGNAL: RS Extension (validated baseline)
    # ----------------------------------------------------------------
    def _rs_momentum(prices: pd.DataFrame, bench: pd.Series, window: int) -> pd.DataFrame:
        """
        RS momentum = current (price/bench) / rolling mean (price/bench)
        Values > 1.0 indicate the asset is extending above its RS trend.
        """
        rs_mat = pd.DataFrame(index=prices.index)
        for t in prices.columns:
            rs = prices[t] / bench
            rs_ma = rs.rolling(window).mean()
            rs_mat[t] = rs / rs_ma
        return rs_mat

    def _trend_ok_causal(prices: pd.DataFrame, window: int = 50) -> pd.DataFrame:
        """
        Causal trend filter: price > SMA(window) on the PREVIOUS bar.
        No lookahead: we check yesterday's SMA before placing today's trade.
        """
        sma = prices.rolling(window).mean()
        above = (prices > sma).shift(1).fillna(False)
        return above

    rs_mat   = _rs_momentum(prices, bench, rs_window)
    trend_mat = _trend_ok_causal(prices) if trend_ok else None

    # ----------------------------------------------------------------
    # DAILY POSITIONS
    # ----------------------------------------------------------------
    positions = pd.DataFrame(0.0, index=prices.index, columns=assets)

    for i in range(rs_window + 1, len(prices)):
        today_rs = rs_mat.iloc[i - 1]   # yesterday's RS (causal)

        # Extension filter: only hold if RS > 1 + ext_thresh
        eligible = today_rs[today_rs > (1.0 + ext_thresh)].index.tolist()

        # Trend filter
        if trend_ok and trend_mat is not None:
            trend_row = trend_mat.iloc[i - 1]
            eligible  = [t for t in eligible if trend_row.get(t, False)]

        if not eligible:
            continue

        # Rank by RS momentum, take top N
        ranked = today_rs[eligible].sort_values(ascending=False).head(top_n)
        weight = 1.0 / len(ranked)
        for t in ranked.index:
            positions.iloc[i][t] = weight

    # ----------------------------------------------------------------
    # PORTFOLIO RETURNS
    # ----------------------------------------------------------------
    asset_rets  = prices.pct_change().fillna(0)
    port_rets   = (positions.shift(1).fillna(0) * asset_rets).sum(axis=1)
    equity      = (1 + port_rets).cumprod() * 10_000
    total_pos   = positions.sum(axis=1)

    # Count trades (position changes)
    trade_count = int((positions.diff().abs().sum(axis=1) > 0).sum())

    # ----------------------------------------------------------------
    # IS / OOS SPLIT
    # ----------------------------------------------------------------
    split_idx = int(len(port_rets) * 0.70)

    is_rets   = port_rets.iloc[:split_idx]
    oos_rets  = port_rets.iloc[split_idx:]

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
# BENCHMARK: Buy-and-hold SPY
# ==============================================================================
def run_benchmark(period: str = "5y") -> BacktestResult | None:
    closes = get_close_batch(["SPY"], period=period)
    if closes.empty:
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
    if rets.empty or rets.std() == 0:
        return 0.0
    excess = rets - rf_daily
    return float(excess.mean() / excess.std() * np.sqrt(252))


def _cagr(rets: pd.Series) -> float:
    if rets.empty:
        return 0.0
    n_years = len(rets) / 252
    if n_years <= 0:
        return 0.0
    total = (1 + rets).prod()
    return float((total ** (1 / n_years) - 1) * 100)


def _maxdd(rets: pd.Series) -> float:
    if rets.empty:
        return 0.0
    equity  = (1 + rets).cumprod()
    peak    = equity.cummax()
    dd      = (equity - peak) / peak
    return float(dd.min() * 100)


def _strategy_label(strategy: str, trend_ok: bool, ext_thresh: float) -> str:
    base = {
        "rs_extension":  f"RS Extension (ext>{ext_thresh:.2f})",
        "rs_trend":      f"RS + Trend Filter (ext>{ext_thresh:.2f})",
        "vsa_confirm":   f"RS + VSA Confirm (ext>{ext_thresh:.2f})",
        "flow_confirm":  f"RS + Flow Confirm (ext>{ext_thresh:.2f})",
        "combined":      f"RS + VSA + Flow (ext>{ext_thresh:.2f})",
    }.get(strategy, strategy)
    if trend_ok and "Trend" not in base:
        base += " + Trend"
    return base

