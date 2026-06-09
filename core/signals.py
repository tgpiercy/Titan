# FILE: core/signals.py
# ROLE: Unified signal synthesiser
#
# LOGIC:
#   Takes the three analysis layers and produces one actionable output:
#     • RRG quadrant + physics  → structural context (macro)
#     • VSA bias                → tape reading (micro)
#     • Flow score (optional)   → institutional intent
#
#   The RRG × VSA matrix is TITAN's trigger engine, refined.
#   Flow score acts as a confirmation multiplier:
#     +ve flow upgrades neutral reads; -ve flow downgrades bullish reads.
#
#   Asset type weighting:
#     ETFs:   RRG + VSA primary,  flow secondary
#     Stocks: flow primary,       VSA confirmation,  RRG context
#
# OUTPUT: SignalResult dataclass with named label + score + sizing recommendation.

from __future__ import annotations
from dataclasses import dataclass
import config as cfg


# ==============================================================================
# RESULT DATACLASS
# ==============================================================================
@dataclass
class SignalResult:
    label:       str    # e.g. "🎯 EXECUTE (PULLBACK)"
    color:       str    # hex
    description: str    # one-line rationale
    grade:       str    # "A" | "B" | "C" | "D"
    score:       float  # -10..+10 (for backtest harness)
    action:      str    # "EXECUTE" | "RIDE" | "STALK" | "HOLD" | "EXIT" | "AVOID"


# ==============================================================================
# MAIN SYNTHESISER
# ==============================================================================
def get_trigger_signal(
    vsa_signal:  str,
    quadrant:    str,
    velocity:    float = 0.0,
    flow_score:  float | None = None,
    is_etf:      bool  = True,
) -> tuple[str, str, str]:
    """
    Lightweight entry point for scanner / watchlist calls.
    Returns (label, color, description) — compatible with TITAN's trigger signature.
    """
    result = synthesise(vsa_signal, quadrant, velocity, flow_score, is_etf)
    return result.label, result.color, result.description


def synthesise(
    vsa_signal:  str,
    quadrant:    str,
    velocity:    float = 0.0,
    flow_score:  float | None = None,
    is_etf:      bool  = True,
) -> SignalResult:
    """
    Full synthesis — returns SignalResult with all metadata.
    Used by Hunter page and portfolio decision engine.
    """
    vsa_bias = _classify_vsa(vsa_signal)

    # Base signal from RRG × VSA matrix
    label, color, description = _rrg_vsa_matrix(vsa_signal, vsa_bias, quadrant, velocity)

    # Flow adjustment (optional — only if CBOE data available)
    if flow_score is not None:
        label, color, description = _apply_flow(
            label, color, description, vsa_bias, flow_score, is_etf
        )

    # Grade
    grade = _grade(label)

    # Numeric score for backtest
    score = _numeric_score(label, quadrant, flow_score)

    # Action
    action = _action_code(label)

    return SignalResult(
        label       = label,
        color       = color,
        description = description,
        grade       = grade,
        score       = score,
        action      = action,
    )


# ==============================================================================
# PRIVATE: VSA bias classifier
# ==============================================================================
def _classify_vsa(signal: str) -> str:
    bullish = {"STOPPING", "SHAKEOUT", "TEST", "STRENGTH", "FLOAT", "SUPPORT", "SELL CLIMAX"}
    bearish = {"NO DEMAND", "UPTHRUST", "WEAKNESS", "BUY CLIMAX"}
    caution = {"CHURN", "SQUAT"}

    if any(k in signal for k in bullish): return "BULLISH"
    if any(k in signal for k in bearish): return "BEARISH"
    if any(k in signal for k in caution): return "CAUTION"
    return "NEUTRAL"


# ==============================================================================
# PRIVATE: RRG × VSA matrix (TITAN's trigger engine, refined)
# ==============================================================================
def _rrg_vsa_matrix(
    vsa_signal: str,
    vsa_bias:   str,
    quadrant:   str,
    velocity:   float,
) -> tuple[str, str, str]:

    # --- LEADING: trend confirmed, look for entries and continuation ---
    if quadrant == "Leading":
        if vsa_bias == "BULLISH":
            if "TEST" in vsa_signal:
                return "🎯 EXECUTE (PULLBACK)", "#00FF00", "Trend Up + Supply Exhausted — Perfect Entry"
            if "STOPPING" in vsa_signal:
                return "🎯 EXECUTE (RELOAD)",   "#00FF00", "Trend Up + Absorption Confirmed"
            if "FLOAT" in vsa_signal or "SUPPORT" in vsa_signal:
                return "🚀 RIDE (ANCHORED)",    "#00CCFF", "Trend Strong, Supported by Anchor Bar"
            return "🚀 RIDE THE WAVE", "#00CCFF", "Trend Strong, Volume Supportive"

        if vsa_bias == "BEARISH":
            if "UPTHRUST" in vsa_signal:
                return "⚠️ CAUTION (TRAP)",  "#FF4444", "Trend Up but Breakout Failed — Upthrust"
            if "BUY CLIMAX" in vsa_signal:
                return "🛑 TAKE PROFITS",    "#FF4444", "Volume Climax into Highs — Distribution"
            return "⚠️ STALLING", "#FFFF00", "Price Drifting Up on Low Volume"

        # Neutral / Caution in Leading
        return "🛡️ HOLD CORE", "#CCCCCC", "Trend Intact, Momentum Paused"

    # --- IMPROVING: turnaround in progress — best risk/reward zone ---
    if quadrant == "Improving":
        if vsa_bias == "BULLISH":
            if "STOPPING" in vsa_signal:
                return "⚡ IGNITION STRIKE",    "#D500F9", "Momentum Turning + Smart Money Buying"
            if "SHAKEOUT" in vsa_signal:
                return "⚡ AGGRESSIVE ENTRY",   "#D500F9", "Bear Trap Spring + Momentum Turn"
            if "FLOAT" in vsa_signal:
                return "👀 STALK (BASE)",       "#00CCFF", "Constructive Basing Detected"
            return "👀 STALK (READY)", "#00CCFF", "Structure Improving — Await Trigger"

        if vsa_bias == "BEARISH":
            return "⛔ FALSE START", "#FF4444", "Momentum Improved but Supply Hit — Abort"

        return "👀 WATCHLIST", "#FFFF00", "Improving — Awaiting Volume Confirmation"

    # --- WEAKENING: profit-taking territory, tighten stops ---
    if quadrant == "Weakening":
        if vsa_bias == "BEARISH":
            return "🔻 EXIT / HEDGE",    "#FF4444", "Momentum Fading + Supply Entering"
        if vsa_bias == "BULLISH":
            return "🤔 POSSIBLE RELOAD", "#FFFF00", "Pullback Finding Support (Risky)"
        return "🛡️ TIGHTEN STOPS", "#FFA500", "Momentum Fading — Protect Profits"

    # --- LAGGING: dead money, avoid or short ---
    if vsa_bias == "BULLISH" and any(k in vsa_signal for k in {"STOPPING", "SUPPORT", "TEST"}):
        return "👀 BOTTOM FISHING?", "#888888", "Lagging but Hitting Anchor Support — Small Size Only"

    return "💤 AVOID / SHORT", "#444444", "Dead Money — No Edge"


# ==============================================================================
# PRIVATE: Flow score adjustment
# ==============================================================================
def _apply_flow(
    label:       str,
    color:       str,
    description: str,
    vsa_bias:    str,
    flow_score:  float,
    is_etf:      bool,
) -> tuple[str, str, str]:
    """
    Adjusts signal based on options flow confirmation.
    ETFs: flow is confirmation (smaller weight).
    Stocks: flow can upgrade or veto a signal.
    """
    flow_weight = 0.4 if is_etf else 0.7

    strong_positive = flow_score >= 4.0
    strong_negative = flow_score <= -4.0
    mild_positive   = flow_score >= 1.5
    mild_negative   = flow_score <= -1.5

    action = _action_code(label)

    # Upgrade: bullish VSA + strong positive flow
    if action in {"STALK", "WATCHLIST"} and vsa_bias == "BULLISH" and strong_positive:
        if flow_weight >= 0.6:   # stocks only
            return (
                label.replace("STALK", "EXECUTE").replace("👀", "🎯"),
                "#00FF00",
                description + " · Flow confirms: institutional buying",
            )

    # Downgrade: bullish setup + strong negative flow — abort
    if action == "EXECUTE" and strong_negative:
        return (
            "⛔ FLOW VETO",
            "#FF4444",
            description + " · Options flow contradicts — heavy put buying",
        )

    # Add flow context note
    if strong_positive and action not in {"EXIT", "AVOID"}:
        description = description + " · ✅ Flow: strong call side"
    elif strong_negative and action not in {"AVOID"}:
        description = description + " · ⚠️ Flow: heavy put protection"
    elif mild_positive:
        description = description + " · Flow: mildly constructive"
    elif mild_negative:
        description = description + " · Flow: mildly cautious"

    return label, color, description


# ==============================================================================
# PRIVATE: Grade, score, action helpers
# ==============================================================================
def _grade(label: str) -> str:
    if any(k in label for k in {"EXECUTE", "IGNITION"}): return "A"
    if any(k in label for k in {"RIDE", "RELOAD"}):      return "B"
    if any(k in label for k in {"STALK", "WATCHLIST"}):  return "C"
    return "D"


def _numeric_score(label: str, quadrant: str, flow_score: float | None) -> float:
    """
    Numeric score for walk-forward backtest harness.
    Range: -10 .. +10
    """
    # Base from label
    base_map = {
        "EXECUTE":  8.0,
        "IGNITION": 9.0,
        "RIDE":     6.0,
        "RELOAD":   7.0,
        "STALK":    3.0,
        "HOLD":     1.0,
        "TIGHTEN":  0.0,
        "CAUTION": -2.0,
        "STALL":   -1.0,
        "EXIT":    -6.0,
        "VETO":    -7.0,
        "AVOID":   -8.0,
    }
    base = 0.0
    for k, v in base_map.items():
        if k in label.upper():
            base = v
            break

    # Quadrant modifier
    quad_mod = {
        "Leading":   1.0,
        "Improving": 0.5,
        "Weakening":-0.5,
        "Lagging":  -1.0,
    }.get(quadrant, 0.0)

    # Flow modifier (capped at ±2)
    flow_mod = 0.0
    if flow_score is not None:
        flow_mod = max(-2.0, min(2.0, flow_score * 0.2))

    return float(max(-10, min(10, base + quad_mod + flow_mod)))


def _action_code(label: str) -> str:
    label_upper = label.upper()
    if "EXECUTE" in label_upper or "IGNITION" in label_upper: return "EXECUTE"
    if "RIDE"    in label_upper or "ANCHORED" in label_upper: return "RIDE"
    if "RELOAD"  in label_upper:                              return "EXECUTE"
    if "STALK"   in label_upper or "WATCHLIST" in label_upper: return "STALK"
    if "HOLD"    in label_upper or "TIGHTEN"  in label_upper: return "HOLD"
    if "EXIT"    in label_upper or "PROFIT"   in label_upper: return "EXIT"
    if "VETO"    in label_upper or "AVOID"    in label_upper: return "AVOID"
    return "HOLD"

