# FILE: core/regime.py
# ROLE: Market Regime Engine — "The Weather"
#
# LOGIC:
#   Four pillars, equal weight (2.5pts each), max score 10.0:
#     1. VIX    — Fear gauge (< 20 = safe)
#     2. Breadth — RSP vs 50-SMA (above = expanding)
#     3. Credit  — HYG/IEI ratio vs 20-SMA (rising = risk-on)
#     4. Dollar  — UUP vs 50-SMA (below = supportive for assets)
#
#   3-Day Inertia Lock:
#     While SPY > 50-SMA, we only flip to RISK OFF if BOTH price fails
#     the 21-EMA AND the internal score < 5.0 for THREE consecutive days.
#     This prevents whipsaw exits on normal pullbacks.
#
# OUTPUT: RegimeResult dataclass consumed by UI and all signal engines.

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np
from core.data import get_weather_data


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================
@dataclass
class RegimeResult:
    # Top-level verdict
    status: str          # e.g. "🚀 REGIME: BULL"
    action: str          # e.g. "ATTACK: FOCUS LEADERS"
    color:  str          # hex colour for UI
    reason: str          # short explanation

    # Composite score (0–10)
    score: float

    # Individual pillars
    vix_val:       float
    vix_safe:      bool
    breadth_state: str   # "EXPANDING" | "CONTRACTING"
    breadth_note:  str
    credit_state:  str   # "RISK ON" | "RISK OFF"
    credit_note:   str
    dollar_state:  str   # "SUPPORTIVE" | "HEADWIND"
    dollar_note:   str

    # Inertia detail
    fail_count: int      # 0-3 days of concurrent breakdown

    # Derived flags (used by signal engines)
    is_bull:      bool
    is_caution:   bool
    is_risk_off:  bool
    size_scalar:  float  # 1.0 = full size, 0.5 = bear protocol


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def get_regime() -> RegimeResult | None:
    """
    Calculates the current market regime.
    Returns None if data is unavailable.
    """
    data = get_weather_data()
    if data.empty or len(data) < 50:
        return None

    # ------------------------------------------------------------------
    # 1. BUILD INDICATORS
    # ------------------------------------------------------------------
    vix        = data["^VIX"]
    rsp        = data["RSP"]
    hyg        = data["HYG"]
    iei        = data["IEI"]
    uup        = data["UUP"]
    spy        = data["SPY"]

    rsp_sma50  = rsp.rolling(50).mean()
    uup_sma50  = uup.rolling(50).mean()
    credit_ratio    = hyg / iei
    credit_ma20     = credit_ratio.rolling(20).mean()
    spy_ema21       = spy.ewm(span=21, adjust=False).mean()
    spy_sma50       = spy.rolling(50).mean()

    # ------------------------------------------------------------------
    # 2. SCORE HELPER (runs for any historical index)
    # ------------------------------------------------------------------
    def score_at(idx: int) -> float:
        s = 0.0
        if vix.iloc[idx] < 20:                                   s += 2.5
        if rsp.iloc[idx] > rsp_sma50.iloc[idx]:                  s += 2.5
        if credit_ratio.iloc[idx] > credit_ma20.iloc[idx]:       s += 2.5
        if uup.iloc[idx] < uup_sma50.iloc[idx]:                  s += 2.5
        return s

    def is_broken(idx: int) -> bool:
        return (spy.iloc[idx] < spy_ema21.iloc[idx]) and (score_at(idx) < 5.0)

    # ------------------------------------------------------------------
    # 3. CURRENT READINGS
    # ------------------------------------------------------------------
    score_now      = score_at(-1)
    vix_now        = float(vix.iloc[-1])
    vix_safe       = vix_now < 20.0
    breadth_safe   = bool(rsp.iloc[-1] > rsp_sma50.iloc[-1])
    credit_safe    = bool(credit_ratio.iloc[-1] > credit_ma20.iloc[-1])
    dollar_safe    = bool(uup.iloc[-1] < uup_sma50.iloc[-1])
    above_sma50    = bool(spy.iloc[-1] > spy_sma50.iloc[-1])

    # ------------------------------------------------------------------
    # 4. INERTIA COUNT (last 3 days)
    # ------------------------------------------------------------------
    fail_count = sum(is_broken(i) for i in [-1, -2, -3])

    # ------------------------------------------------------------------
    # 5. REGIME VERDICT
    # ------------------------------------------------------------------
    if above_sma50:
        if fail_count >= 3:
            verdict = dict(
                status="🛡️ RISK OFF (LOCKED)",
                action="DEFENSIVE: CASH / HEDGES",
                color="#FF4444",
                reason="3-Day Inertia Triggered",
            )
            is_bull, is_caution, is_risk_off = False, False, True
            scalar = 0.5

        elif fail_count > 0:
            verdict = dict(
                status="⚠️ CAUTION (BUFFER)",
                action="HOLD CORE — NO NEW LONGS",
                color="#FFA500",
                reason=f"Inertia Active — {fail_count}/3 days broken",
            )
            is_bull, is_caution, is_risk_off = False, True, False
            scalar = 0.75

        else:
            verdict = dict(
                status="🚀 REGIME: BULL",
                action="ATTACK — FOCUS LEADERS",
                color="#00FF00",
                reason="Structure Intact",
            )
            is_bull, is_caution, is_risk_off = True, False, False
            scalar = 1.0

    else:
        # Below 50-SMA — inertia doesn't protect here
        verdict = dict(
            status="🐻 REGIME: BEAR",
            action="CASH IS KING",
            color="#888888",
            reason="SPY Below 50-Day Anchor",
        )
        is_bull, is_caution, is_risk_off = False, False, True
        scalar = 0.5

    # ------------------------------------------------------------------
    # 6. PILLAR LABELS
    # ------------------------------------------------------------------
    breadth_state = "EXPANDING"   if breadth_safe else "CONTRACTING"
    breadth_note  = "RSP > 50-SMA" if breadth_safe else "RSP < 50-SMA"
    credit_state  = "RISK ON"     if credit_safe  else "RISK OFF"
    credit_note   = "Spreads Tight" if credit_safe else "Spreads Widening"
    dollar_state  = "SUPPORTIVE"  if dollar_safe  else "HEADWIND"
    dollar_note   = "UUP < 50-SMA" if dollar_safe else "UUP > 50-SMA"

    return RegimeResult(
        status        = verdict["status"],
        action        = verdict["action"],
        color         = verdict["color"],
        reason        = verdict["reason"],
        score         = score_now,
        vix_val       = vix_now,
        vix_safe      = vix_safe,
        breadth_state = breadth_state,
        breadth_note  = breadth_note,
        credit_state  = credit_state,
        credit_note   = credit_note,
        dollar_state  = dollar_state,
        dollar_note   = dollar_note,
        fail_count    = fail_count,
        is_bull       = is_bull,
        is_caution    = is_caution,
        is_risk_off   = is_risk_off,
        size_scalar   = scalar,
    )


# ==============================================================================
# CONVENIENCE: short status string for sidebar / terminal
# ==============================================================================
def get_regime_status() -> str:
    """Returns a short status string. Safe to call anywhere."""
    r = get_regime()
    if r is None:
        return "OFFLINE"
    return r.status

