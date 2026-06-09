# FILE: core/vsa.py
# ROLE: Volume Spread Analysis — Smart Money footprint detection
#
# PATTERNS (7 named + 4 default states + 2 contextual overlays):
#   Named:   Stopping Volume, No Demand, Shakeout, Upthrust,
#            Churn/Squat, Buy Climax, Sell Climax, Successful Test
#   Default: Strength, Weakness, Drift Up, Drift Down
#   Context: Float on Support, Test of Support  (anchor-bar memory)
#
# RETURNS: VSAResult dataclass with signal, color, note, bias, and
#          the raw metrics for display in Hunter's Intel panel.

from __future__ import annotations
from dataclasses import dataclass
import pandas as pd
import numpy as np


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================
@dataclass
class VSAResult:
    signal:    str    # e.g. "🛑 STOPPING VOLUME"
    color:     str    # hex
    note:      str    # plain-language description
    bias:      str    # "BULLISH" | "BEARISH" | "CAUTION" | "NEUTRAL"

    # Raw metrics (for Hunter display)
    vol_ratio:    float   # current vol / 20-day avg
    vol_state:    str     # "Climax" | "High" | "Average" | "Low"
    spread_state: str     # "Wide" | "Average" | "Narrow"
    close_loc:    float   # 0.0 = closed at low, 1.0 = closed at high
    close_state:  str     # "Strong" | "Indecision" | "Weak"


# ==============================================================================
# MAIN ENGINE
# ==============================================================================
def get_vsa_verdict(df: pd.DataFrame) -> tuple[str, str, str]:
    """
    Lightweight entry point for scanner/signal calls.
    Returns (signal_text, color, note) — same signature as TITAN's pillar_action.
    """
    result = analyse(df)
    if result is None:
        return "INSUFFICIENT DATA", "#888888", "Need 20+ bars"
    return result.signal, result.color, result.note


def analyse(df: pd.DataFrame) -> VSAResult | None:
    """
    Full analysis — returns VSAResult with all metrics.
    Used by Hunter page for the detailed Intel panel.
    """
    if df.empty or len(df) < 20:
        return None

    # ------------------------------------------------------------------
    # 1. CURRENT BAR METRICS
    # ------------------------------------------------------------------
    curr = df.iloc[-1]
    prev = df.iloc[-2]

    vol_ma    = df["Volume"].rolling(20).mean().iloc[-1]
    vol_ratio = float(curr["Volume"] / vol_ma) if vol_ma > 0 else 1.0

    spread     = curr["High"] - curr["Low"]
    avg_spread = (df["High"] - df["Low"]).rolling(20).mean().iloc[-1]
    is_wide    = spread > avg_spread * 1.10
    is_narrow  = spread < avg_spread * 0.80

    rng     = curr["High"] - curr["Low"]
    close_loc = float((curr["Close"] - curr["Low"]) / rng) if rng > 0 else 0.5

    up_close   = curr["Close"] >= prev["Close"]
    down_close = curr["Close"] <  prev["Close"]

    # ------------------------------------------------------------------
    # 2. NAMED PATTERN RECOGNITION
    # ------------------------------------------------------------------
    signal = color = note = None

    # A. Stopping Volume — supply absorbed on a down bar closing mid-high
    if down_close and vol_ratio > 1.5 and close_loc > 0.40:
        signal, color, note = "🛑 STOPPING VOLUME", "#00FF00", "Smart Money Absorbing Supply"

    # B. No Demand — weak up bar on low volume (supply still overhead)
    elif up_close and vol_ratio < 0.80 and is_narrow:
        signal, color, note = "⛔ NO DEMAND", "#FF4444", "Price Up, Vol Down — Supply Overhead"

    # C. Shakeout — runs stops below prev low then reverses above prev high
    elif (curr["Low"] < prev["Low"]
          and curr["Close"] > prev["High"]
          and is_wide):
        signal, color, note = "🎢 SHAKEOUT", "#00CCFF", "Bear Trap — Stops Run & Reversed"

    # D. Upthrust — breakout above prev high but closes in lower third (rejection)
    elif curr["High"] > prev["High"] and close_loc < 0.30 and is_wide:
        signal, color, note = "🔨 UPTHRUST", "#FF4444", "Breakout Failed — Supply Rejected"

    # E. Churn / Squat — high volume, narrow range (effort without result)
    elif vol_ratio > 1.50 and is_narrow:
        signal, color, note = "⚖️ CHURN (SQUAT)", "#FFFF00", "High Vol, Price Stuck — Transfer"

    # F. Climax Action — extreme volume on wide range
    elif vol_ratio > 2.50 and is_wide:
        if up_close:
            signal, color, note = "🔥 BUY CLIMAX",  "#FF8800", "Retail Chasing Top?"
        else:
            signal, color, note = "💧 SELL CLIMAX", "#00FF00", "Panic Selling — Possible Bottom"

    # G. Successful Test — probes below prev low, closes up on low volume
    elif (curr["Low"] < prev["Low"]
          and up_close
          and vol_ratio < 0.80):
        signal, color, note = "🧪 SUCCESSFUL TEST", "#00FF00", "Supply Exhausted"

    # ------------------------------------------------------------------
    # 3. DEFAULT STATES (no named pattern matched)
    # ------------------------------------------------------------------
    if signal is None:
        if up_close:
            if vol_ratio > 1.0:
                signal, color, note = "💪 STRENGTH",  "#00FF00", "Rising on Volume"
            else:
                signal, color, note = "🌤️ DRIFT UP",  "#CCCCCC", "Rising on Weak Volume"
        else:
            if vol_ratio > 1.0:
                signal, color, note = "📉 WEAKNESS",   "#FF4444", "Falling on Volume"
            else:
                signal, color, note = "☁️ DRIFT DOWN", "#CCCCCC", "Falling on Weak Volume"

    # ------------------------------------------------------------------
    # 4. CONTEXTUAL MEMORY — Anchor Bar Override
    #    If we have a weak signal, scan last 12 bars for high-volume
    #    up-closes (anchor bars). If current price holds above an anchor,
    #    upgrade the read.
    # ------------------------------------------------------------------
    weak_signals = {"NO DEMAND", "DRIFT UP", "DRIFT DOWN", "WEAKNESS", "NEUTRAL"}
    if any(s in signal for s in weak_signals):
        signal, color, note = _anchor_override(df, signal, color, note, curr, vol_ma)

    # ------------------------------------------------------------------
    # 5. BIAS CLASSIFICATION
    # ------------------------------------------------------------------
    bias = _classify_bias(signal)

    # ------------------------------------------------------------------
    # 6. DISPLAY METRICS
    # ------------------------------------------------------------------
    if vol_ratio > 2.0:    vol_state = "🔴 Climax"
    elif vol_ratio > 1.20: vol_state = "🟠 High"
    elif vol_ratio < 0.80: vol_state = "⚪ Low"
    else:                  vol_state = "🔵 Average"

    if is_wide:    spread_state = "Wide Range"
    elif is_narrow: spread_state = "Narrow Range"
    else:           spread_state = "Average Range"

    if close_loc > 0.70:   close_state = "Strong (Top)"
    elif close_loc < 0.30: close_state = "Weak (Bottom)"
    else:                  close_state = "Indecision (Mid)"

    return VSAResult(
        signal       = signal,
        color        = color,
        note         = note,
        bias         = bias,
        vol_ratio    = vol_ratio,
        vol_state    = vol_state,
        spread_state = spread_state,
        close_loc    = close_loc,
        close_state  = close_state,
    )


# ==============================================================================
# PRIVATE: Anchor bar contextual memory
# ==============================================================================
def _anchor_override(
    df: pd.DataFrame,
    signal: str,
    color:  str,
    note:   str,
    curr:   pd.Series,
    vol_ma: float,
) -> tuple[str, str, str]:
    """
    Scans the last 12 bars for anchor bars (vol > 1.8× avg, up close).
    If the current price holds above the most recent anchor's low,
    upgrades a weak signal to 'Float on Support' or 'Test of Support'.
    """
    history = df.iloc[-13:-1]
    anchors = []

    for i in range(len(history)):
        bar = history.iloc[i]
        bar_vol_ratio = bar["Volume"] / vol_ma if vol_ma > 0 else 1.0
        if bar_vol_ratio > 1.80 and bar["Close"] > bar["Open"]:
            anchors.append(bar)

    if not anchors:
        return signal, color, note

    last_anchor = anchors[-1]

    if curr["Close"] > last_anchor["Low"]:
        if any(s in signal for s in {"DRIFT UP", "NO DEMAND"}):
            return (
                "⚓ FLOAT ON SUPPORT", "#00CCFF",
                "Rising on Low Vol — Anchored by Smart Money Bar"
            )
        elif any(s in signal for s in {"DRIFT DOWN", "WEAKNESS"}):
            return (
                "⚓ TEST OF SUPPORT", "#00FF00",
                "Drifting Into High-Vol Anchor — Potential Buy Zone"
            )

    return signal, color, note


# ==============================================================================
# PRIVATE: Bias classifier
# ==============================================================================
def _classify_bias(signal: str) -> str:
    bullish_keys = {"STOPPING", "SHAKEOUT", "TEST", "STRENGTH", "FLOAT", "SUPPORT", "SELL CLIMAX"}
    bearish_keys = {"NO DEMAND", "UPTHRUST", "WEAKNESS", "BUY CLIMAX"}
    caution_keys = {"CHURN", "SQUAT"}

    if any(k in signal for k in bullish_keys): return "BULLISH"
    if any(k in signal for k in bearish_keys): return "BEARISH"
    if any(k in signal for k in caution_keys): return "CAUTION"
    return "NEUTRAL"

