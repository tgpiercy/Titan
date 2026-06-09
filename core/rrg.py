# FILE: core/rrg.py
# ROLE: Relative Rotation Graph — single canonical implementation
#
# DESIGN DECISIONS vs source systems:
#   - One method only: JdK-style z-score normalisation (StratFlow approach,
#     more mathematically stable than TITAN's simple deviation).
#   - Physics layer from TITAN: velocity, acceleration, heading.
#   - Tactical state labels from TITAN's RRG display.
#   - Supports three modes: MACRO (indices vs IEF), GENERALS (sectors vs SPY),
#     LIEUTENANTS (sub-sectors vs their General).
#   - Cached at the data layer (get_close_batch). This function itself is
#     @st.cache_data so repeated calls within a session are free.
#
# OUTPUT: DataFrame with columns:
#   Date, Ticker, Ratio, Momentum, Quadrant, Velocity, Acceleration,
#   Heading, Tactical, Thrust, Type

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

import config as cfg
from core.data import get_close_batch


# ==============================================================================
# PUBLIC: Main RRG calculation
# ==============================================================================
@st.cache_data(ttl=3600)
def get_rrg_data(
    tickers:   list[str],
    benchmark: str = "SPY",
    period:    str = "2y",
) -> pd.DataFrame:
    """
    Calculates RRG coordinates for a list of tickers vs a benchmark.

    Returns a long-format DataFrame (one row per ticker per date),
    filtered to the display window defined in config.RRG_DISPLAY_DAYS.
    Empty DataFrame on failure.
    """
    if not tickers:
        return pd.DataFrame()

    all_tickers = list(set(tickers + [benchmark]))
    closes = get_close_batch(all_tickers, period=period)

    if closes.empty or benchmark not in closes.columns:
        return pd.DataFrame()

    bench = closes[benchmark]
    frames: list[pd.DataFrame] = []

    for ticker in tickers:
        if ticker == benchmark or ticker not in closes.columns:
            continue

        df = _calc_single(closes[ticker], bench, ticker)
        if df is not None and not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)

    # Trim to display window
    if not combined.empty:
        cutoff = combined["Date"].max() - pd.Timedelta(
            days=cfg.RRG_DISPLAY_DAYS * 3
        )
        combined = combined[combined["Date"] >= cutoff]

    return combined.reset_index(drop=True)


# ==============================================================================
# PUBLIC: Convenience loaders for each mode
# ==============================================================================
@st.cache_data(ttl=3600)
def get_macro_rrg() -> pd.DataFrame:
    """Indices vs IEF (bonds). Macro Compass mode."""
    return get_rrg_data(
        tickers   = cfg.MACRO_TICKERS,
        benchmark = cfg.MACRO_BENCHMARK,
        period    = "1y",
    )


@st.cache_data(ttl=3600)
def get_generals_rrg() -> pd.DataFrame:
    """Sector ETFs vs SPY."""
    tickers = list(cfg.SECTOR_MAP.values())
    return get_rrg_data(tickers=tickers, benchmark="SPY", period="2y")


@st.cache_data(ttl=3600)
def get_lieutenants_rrg(general_ticker: str) -> pd.DataFrame:
    """
    Sub-sector ETFs for one General, benchmarked vs that General.
    """
    # Find which sector this general belongs to
    sector_name = None
    for name, etf in cfg.SECTOR_MAP.items():
        if etf == general_ticker:
            sector_name = name
            break

    if sector_name is None or sector_name not in cfg.THEME_MAP:
        return pd.DataFrame()

    lieuts = list(cfg.THEME_MAP[sector_name].values())
    return get_rrg_data(
        tickers   = lieuts,
        benchmark = general_ticker,
        period    = "1y",
    )


# ==============================================================================
# PUBLIC: Latest snapshot (one row per ticker)
# ==============================================================================
def get_latest_snapshot(df_rrg: pd.DataFrame) -> pd.DataFrame:
    """
    Returns one row per ticker — the most recent date.
    Adds 'Alpha' column = Ratio - 100.
    """
    if df_rrg.empty:
        return pd.DataFrame()

    snap = (
        df_rrg.sort_values("Date")
        .groupby("Ticker")
        .last()
        .reset_index()
    )
    snap["Alpha"] = snap["Ratio"] - 100.0
    return snap


# ==============================================================================
# PRIVATE: Single-ticker RRG calculation
# ==============================================================================
def _calc_single(
    series:    pd.Series,
    benchmark: pd.Series,
    ticker:    str,
) -> pd.DataFrame | None:
    """
    JdK RS-Ratio / RS-Momentum calculation for one ticker.

    RS-Ratio:  z-score of smoothed RS over a long window → normalised to 100
    RS-Momentum: z-score of RS-Ratio change → normalised to 100
    """
    try:
        # Align on common index
        common = series.index.intersection(benchmark.index)
        if len(common) < cfg.RRG_RATIO_WINDOW + 20:
            return None

        s = series.loc[common]
        b = benchmark.loc[common]

        # Raw RS
        rs_raw = (s / b) * 10_000

        # Smooth & normalise → RS-Ratio
        rs_smooth  = rs_raw.rolling(window=cfg.RRG_MOM_WINDOW).mean()
        rs_mean_lt = rs_smooth.rolling(window=cfg.RRG_RATIO_WINDOW).mean()
        rs_std_lt  = rs_smooth.rolling(window=cfg.RRG_RATIO_WINDOW).std()

        ratio = 100 + ((rs_smooth - rs_mean_lt) / rs_std_lt.replace(0, np.nan)) * 10

        # RS-Momentum: z-score of Ratio change
        ratio_mean = ratio.rolling(window=cfg.RRG_MOM_WINDOW).mean()
        ratio_std  = ratio.rolling(window=cfg.RRG_MOM_WINDOW).std()

        momentum = 100 + ((ratio - ratio_mean) / ratio_std.replace(0, np.nan))

        df = pd.DataFrame({
            "Date":     common,
            "Ticker":   ticker,
            "Ratio":    ratio.values,
            "Momentum": momentum.values,
            "Price":    s.values,
        }).dropna()

        if df.empty:
            return None

        # Quadrant
        df["Quadrant"] = df.apply(
            lambda r: _quadrant(r["Ratio"], r["Momentum"]), axis=1
        )

        # Physics
        df = _add_physics(df)

        # Tactical labels
        df["Tactical"] = df.apply(_tactical_label, axis=1)
        df["Thrust"]   = df.apply(_thrust_label,   axis=1)

        return df

    except Exception:
        return None


# ==============================================================================
# PRIVATE: Quadrant classifier
# ==============================================================================
def _quadrant(ratio: float, momentum: float) -> str:
    if ratio >= 100 and momentum >= 100: return "Leading"
    if ratio <  100 and momentum >= 100: return "Improving"
    if ratio <  100 and momentum <  100: return "Lagging"
    return "Weakening"


# ==============================================================================
# PRIVATE: Physics layer (velocity, acceleration, heading)
# ==============================================================================
def _add_physics(df: pd.DataFrame) -> pd.DataFrame:
    dx = df["Ratio"].diff()
    dy = df["Momentum"].diff()

    df["Velocity"]     = np.sqrt(dx**2 + dy**2)
    df["Acceleration"] = df["Velocity"].diff()

    # Heading: compass angle 0=East, 90=North, 180=West, 270=South
    angles = np.degrees(np.arctan2(dy, dx))
    df["Heading"] = (angles + 360) % 360

    return df


# ==============================================================================
# PRIVATE: Tactical state label
# ==============================================================================
def _tactical_label(row: pd.Series) -> str:
    q = row["Quadrant"]
    a = row.get("Acceleration", 0)

    if q == "Leading"   and a > 0:  return "🟢 LEAD"
    if q == "Leading"   and a <= 0: return "⚠️ STALL"
    if q == "Improving" and a > 0:  return "🚀 IGNITE"
    if q == "Improving" and a <= 0: return "🔵 WAKE"
    if q == "Weakening":            return "🔻 FADE"
    if q == "Lagging"   and a > 0:  return "♻️ RECOV"
    return "🛑 DRAG"


# ==============================================================================
# PRIVATE: Thrust label (momentum strength)
# ==============================================================================
def _thrust_label(row: pd.Series) -> str:
    m = row["Momentum"]
    if m > 102: return "⚡ MAX"
    if m > 100: return "🟢 GAIN"
    if m < 98:  return "🛑 HALT"
    return "➖ FLAT"

