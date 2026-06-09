# FILE: core/flow.py
# ROLE: Options flow analysis — CBOE data, directional score -10..+10
#
# SIGNALS synthesised:
#   1. Price/Volume trend (from OHLCV)
#   2. Options premium bias (calls vs puts net premium)
#   3. DEX tilt — Dealer delta exposure direction
#   4. New positioning — vol > OI (fresh conviction vs rolling)
#   5. Gamma regime — net gamma sign drives dealer hedging behaviour
#
# OUTPUT: FlowResult dataclass with score, regime, key levels, read.
#         Score drives the walk-forward backtest.
#         Named signal drives the Hunter UI.
#
# NOTE: CBOE data is 15-min delayed. For ETFs the flow signal is
#       directionally reliable; for individual stocks treat as
#       confirmation layer, not primary entry trigger.

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from core.data import get_options_chain, get_ohlcv


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================
@dataclass
class FlowResult:
    # Composite score
    score:   float   # -10.0 .. +10.0  (positive = bullish flow)
    regime:  str     # "STRONG BULL" | "BULL" | "NEUTRAL" | "BEAR" | "STRONG BEAR"
    color:   str     # hex for UI

    # Component scores (-2..+2 each)
    score_pv:     float   # price/volume trend
    score_premium: float  # call/put premium bias
    score_dex:    float   # dealer delta exposure tilt
    score_new:    float   # new positioning (vol > OI)
    score_gamma:  float   # gamma regime

    # Key levels
    call_wall:  float | None   # strike with highest call OI
    put_wall:   float | None   # strike with highest put OI
    gamma_flip: float | None   # estimated zero-gamma level

    # Plain-language
    read:   str    # e.g. "Dealers short gamma — amplified moves likely"
    detail: str    # component breakdown string

    # Raw option metrics
    total_call_premium: float
    total_put_premium:  float
    put_call_ratio:     float
    net_dex:            float


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def get_flow(ticker: str, df_ohlcv: pd.DataFrame | None = None) -> FlowResult | None:
    """
    Full flow analysis for a ticker.
    df_ohlcv can be pre-fetched; if None, will fetch internally.
    Returns None if options data unavailable.
    """
    # 1. Fetch options chain from CBOE
    chain, spot = get_options_chain(ticker)
    if chain is None or spot is None or spot <= 0:
        return None

    calls = chain.get("calls", [])
    puts  = chain.get("puts",  [])
    if not calls and not puts:
        return None

    # 2. OHLCV for price/volume component
    if df_ohlcv is None or df_ohlcv.empty:
        df_ohlcv = get_ohlcv(ticker, period="3mo")

    # ------------------------------------------------------------------
    # COMPONENT 1: Price / Volume Trend (-2 .. +2)
    # ------------------------------------------------------------------
    score_pv = _score_price_volume(df_ohlcv)

    # ------------------------------------------------------------------
    # COMPONENT 2: Options Premium Bias (-2 .. +2)
    # ------------------------------------------------------------------
    score_premium, call_prem, put_prem, pcr = _score_premium(calls, puts)

    # ------------------------------------------------------------------
    # COMPONENT 3: DEX Tilt (-2 .. +2)
    # ------------------------------------------------------------------
    score_dex, net_dex = _score_dex(calls, puts, spot)

    # ------------------------------------------------------------------
    # COMPONENT 4: New Positioning / Vol > OI (-2 .. +2)
    # ------------------------------------------------------------------
    score_new = _score_new_positioning(calls, puts)

    # ------------------------------------------------------------------
    # COMPONENT 5: Gamma Regime (-2 .. +2)
    # ------------------------------------------------------------------
    score_gamma, call_wall, put_wall, gamma_flip = _score_gamma(calls, puts, spot)

    # ------------------------------------------------------------------
    # COMPOSITE SCORE
    # ------------------------------------------------------------------
    raw = score_pv + score_premium + score_dex + score_new + score_gamma
    score = float(np.clip(raw, -10, 10))

    # ------------------------------------------------------------------
    # REGIME LABEL
    # ------------------------------------------------------------------
    if score >= 6:
        regime, color = "STRONG BULL", "#00FF00"
    elif score >= 2:
        regime, color = "BULL",        "#00CC44"
    elif score <= -6:
        regime, color = "STRONG BEAR", "#FF2222"
    elif score <= -2:
        regime, color = "BEAR",        "#FF6644"
    else:
        regime, color = "NEUTRAL",     "#888888"

    # ------------------------------------------------------------------
    # PLAIN-LANGUAGE READ
    # ------------------------------------------------------------------
    read   = _build_read(score, score_gamma, score_dex, score_premium, net_dex, gamma_flip, spot)
    detail = (
        f"PV:{score_pv:+.1f}  "
        f"Prem:{score_premium:+.1f}  "
        f"DEX:{score_dex:+.1f}  "
        f"New:{score_new:+.1f}  "
        f"Gamma:{score_gamma:+.1f}"
    )

    return FlowResult(
        score              = score,
        regime             = regime,
        color              = color,
        score_pv           = score_pv,
        score_premium      = score_premium,
        score_dex          = score_dex,
        score_new          = score_new,
        score_gamma        = score_gamma,
        call_wall          = call_wall,
        put_wall           = put_wall,
        gamma_flip         = gamma_flip,
        read               = read,
        detail             = detail,
        total_call_premium = call_prem,
        total_put_premium  = put_prem,
        put_call_ratio     = pcr,
        net_dex            = net_dex,
    )


# ==============================================================================
# PRIVATE: Component scorers
# ==============================================================================

def _score_price_volume(df: pd.DataFrame) -> float:
    """
    Trend score from OHLCV: SMA alignment + volume confirmation.
    Range: -2 .. +2
    """
    if df.empty or len(df) < 50:
        return 0.0

    close  = df["Close"]
    volume = df["Volume"]

    sma20 = close.rolling(20).mean()
    sma50 = close.rolling(50).mean()
    vol_ma = volume.rolling(20).mean()

    price_now = close.iloc[-1]
    v20 = sma20.iloc[-1]
    v50 = sma50.iloc[-1]
    vol_now  = volume.iloc[-1]
    vol_avg  = vol_ma.iloc[-1]

    score = 0.0

    # Price vs SMAs
    if price_now > v20 and price_now > v50:
        score += 1.0
    elif price_now < v20 and price_now < v50:
        score -= 1.0

    # SMA alignment
    if v20 > v50:
        score += 0.5
    elif v20 < v50:
        score -= 0.5

    # Volume confirmation
    vol_ratio = vol_now / vol_avg if vol_avg > 0 else 1.0
    recent_up = close.iloc[-1] > close.iloc[-2]

    if vol_ratio > 1.2 and recent_up:
        score += 0.5
    elif vol_ratio > 1.2 and not recent_up:
        score -= 0.5

    return float(np.clip(score, -2, 2))


def _score_premium(calls: list, puts: list) -> tuple[float, float, float, float]:
    """
    Net premium bias: calls premium vs puts premium.
    Returns (score, call_prem_total, put_prem_total, put_call_ratio)
    """
    def _prem(opts: list) -> float:
        total = 0.0
        for o in opts:
            try:
                mid = (float(o.get("ask", 0)) + float(o.get("bid", 0))) / 2
                vol = float(o.get("volume", 0) or 0)
                total += mid * vol * 100
            except Exception:
                pass
        return total

    call_prem = _prem(calls)
    put_prem  = _prem(puts)
    total     = call_prem + put_prem

    if total == 0:
        return 0.0, 0.0, 0.0, 1.0

    pcr = put_prem / call_prem if call_prem > 0 else 9.99
    call_pct = call_prem / total

    if call_pct > 0.65:   score = 2.0
    elif call_pct > 0.55: score = 1.0
    elif call_pct < 0.35: score = -2.0
    elif call_pct < 0.45: score = -1.0
    else:                  score = 0.0

    return float(score), call_prem, put_prem, pcr


def _score_dex(calls: list, puts: list, spot: float) -> tuple[float, float]:
    """
    Dealer Delta Exposure (DEX) tilt.
    Dealers are short calls → positive delta exposure from their perspective
    means they must buy the underlying as price rises (amplifying effect).
    Returns (score, net_dex)
    """
    def _dex(opts: list, sign: float) -> float:
        total = 0.0
        for o in opts:
            try:
                delta = float(o.get("delta", 0) or 0)
                oi    = float(o.get("open_interest", 0) or 0)
                total += sign * delta * oi * 100
            except Exception:
                pass
        return total

    call_dex = _dex(calls, -1.0)   # dealers short calls → negative delta
    put_dex  = _dex(puts,   1.0)   # dealers short puts  → positive delta
    net_dex  = call_dex + put_dex

    # Normalise to score
    if net_dex > 0:
        score = min(2.0, net_dex / max(abs(net_dex), 1) * 2)
    elif net_dex < 0:
        score = max(-2.0, net_dex / max(abs(net_dex), 1) * 2)
    else:
        score = 0.0

    return float(np.clip(score, -2, 2)), float(net_dex)


def _score_new_positioning(calls: list, puts: list) -> float:
    """
    Fresh conviction: options where volume > open_interest signal new
    directional bets rather than rolling existing positions.
    Range: -2 .. +2
    """
    new_calls = sum(
        1 for o in calls
        if float(o.get("volume", 0) or 0) > float(o.get("open_interest", 1) or 1)
    )
    new_puts = sum(
        1 for o in puts
        if float(o.get("volume", 0) or 0) > float(o.get("open_interest", 1) or 1)
    )

    total_new = new_calls + new_puts
    if total_new == 0:
        return 0.0

    call_pct = new_calls / total_new
    if call_pct > 0.65:   return  2.0
    if call_pct > 0.55:   return  1.0
    if call_pct < 0.35:   return -2.0
    if call_pct < 0.45:   return -1.0
    return 0.0


def _score_gamma(
    calls: list,
    puts:  list,
    spot:  float,
) -> tuple[float, float | None, float | None, float | None]:
    """
    Gamma regime and key strike levels.
    Positive net gamma → dealers buy dips / sell rips (dampening).
    Negative net gamma → dealers amplify moves (trending).
    Returns (score, call_wall, put_wall, gamma_flip_level)
    """
    ATM_BAND = 0.10  # 10% around spot for gamma relevance

    call_gamma_by_strike: dict[float, float] = {}
    put_gamma_by_strike:  dict[float, float] = {}

    for o in calls:
        try:
            k = float(o.get("strike", 0) or 0)
            g = float(o.get("gamma",  0) or 0)
            oi = float(o.get("open_interest", 0) or 0)
            if k > 0:
                call_gamma_by_strike[k] = call_gamma_by_strike.get(k, 0) + g * oi * 100
        except Exception:
            pass

    for o in puts:
        try:
            k  = float(o.get("strike", 0) or 0)
            g  = float(o.get("gamma",  0) or 0)
            oi = float(o.get("open_interest", 0) or 0)
            if k > 0:
                put_gamma_by_strike[k] = put_gamma_by_strike.get(k, 0) + g * oi * 100
        except Exception:
            pass

    if not call_gamma_by_strike and not put_gamma_by_strike:
        return 0.0, None, None, None

    # Key levels
    call_wall  = max(call_gamma_by_strike, key=call_gamma_by_strike.get) if call_gamma_by_strike else None
    put_wall   = max(put_gamma_by_strike,  key=put_gamma_by_strike.get)  if put_gamma_by_strike  else None

    # Net gamma near ATM (dealers perspective: short options → flip sign)
    atm_low  = spot * (1 - ATM_BAND)
    atm_high = spot * (1 + ATM_BAND)

    net_gamma = 0.0
    for k, g in call_gamma_by_strike.items():
        if atm_low <= k <= atm_high:
            net_gamma -= g   # dealers short calls
    for k, g in put_gamma_by_strike.items():
        if atm_low <= k <= atm_high:
            net_gamma += g   # dealers short puts

    # Gamma flip: strike where net shifts sign (simplified: midpoint of walls)
    gamma_flip = None
    if call_wall and put_wall:
        gamma_flip = (call_wall + put_wall) / 2

    # Score
    if net_gamma > 0:
        score = 1.0    # positive gamma → dampening → slight bullish for trend
    elif net_gamma < 0:
        score = -1.0   # negative gamma → amplifying → volatility risk
    else:
        score = 0.0

    return float(score), call_wall, put_wall, gamma_flip


# ==============================================================================
# PRIVATE: Plain-language read builder
# ==============================================================================
def _build_read(
    score:       float,
    score_gamma: float,
    score_dex:   float,
    score_prem:  float,
    net_dex:     float,
    gamma_flip:  float | None,
    spot:        float,
) -> str:
    parts = []

    if score_gamma < 0:
        parts.append("Dealers short gamma — amplified moves likely")
    elif score_gamma > 0:
        parts.append("Dealers long gamma — mean-reverting conditions")

    if score_dex > 1:
        parts.append("Dealer delta skewed bullish — buy pressure on rallies")
    elif score_dex < -1:
        parts.append("Dealer delta skewed bearish — sell pressure on dips")

    if score_prem > 1:
        parts.append("Heavy call premium — institutional upside positioning")
    elif score_prem < -1:
        parts.append("Heavy put premium — downside protection being bought")

    if gamma_flip and spot > 0:
        dist_pct = abs(spot - gamma_flip) / spot * 100
        direction = "above" if gamma_flip < spot else "below"
        parts.append(f"Gamma flip ~${gamma_flip:.0f} ({dist_pct:.1f}% {direction} spot)")

    if not parts:
        if score > 0:
            parts.append("Mildly constructive flow — no strong conviction signal")
        elif score < 0:
            parts.append("Mildly cautious flow — no strong conviction signal")
        else:
            parts.append("Balanced flow — no directional edge")

    return " · ".join(parts)

