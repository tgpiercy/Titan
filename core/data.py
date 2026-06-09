# FILE: core/data.py
# ROLE: Unified data layer — ALL external data calls go through here.
#       Nothing else in APEX calls yfinance or requests directly.
#
# SOURCES (in priority order):
#   1. yfinance  — primary OHLCV + multi-ticker batch
#   2. Stooq CSV — fallback for OHLCV when Yahoo returns 401/crumb errors
#   3. CBOE      — options chains + spot price (15-min delayed)
#
# RULE: Every public function returns a clean DataFrame or scalar.
#       On failure it returns an empty DataFrame / None — never raises.

import io
import time
import warnings
import requests
import pandas as pd
import numpy as np
import yfinance as yf
import streamlit as st

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------
_STOOQ_URL   = "https://stooq.com/q/d/l/?s={ticker}&i=d"
_CBOE_CHAIN  = "https://cdn.cboe.com/api/global/delayed_quotes/options/{ticker}.json"
_CBOE_SPOT   = "https://cdn.cboe.com/api/global/delayed_quotes/quotes/{ticker}.json"
_YF_TIMEOUT  = 10   # seconds
_HTTP_HEADERS = {"User-Agent": "Mozilla/5.0"}


# ==============================================================================
# PUBLIC: OHLCV — single ticker
# ==============================================================================
def get_ohlcv(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """
    Fetch OHLCV for a single ticker.
    Tries yfinance first; falls back to Stooq on any error.
    Returns columns: Open, High, Low, Close, Volume (DatetimeIndex).
    """
    df = _yf_single(ticker, period, interval)
    if df is not None and not df.empty:
        return df

    # Stooq fallback (daily only — no intraday)
    if interval == "1d":
        df = _stooq_single(ticker, period)
        if df is not None and not df.empty:
            return df

    return pd.DataFrame()


# ==============================================================================
# PUBLIC: OHLCV — multi-ticker batch (Close only for RRG / breadth work)
# ==============================================================================
@st.cache_data(ttl=3600)
def get_close_batch(tickers: list, period: str = "2y") -> pd.DataFrame:
    """
    Fetch closing prices for a list of tickers.
    Returns a DataFrame with tickers as columns, DatetimeIndex.
    Cached for 1 hour.
    """
    if not tickers:
        return pd.DataFrame()

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
            raise ValueError("Empty response")

        # Flatten MultiIndex
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", level=0, axis=1)
        else:
            closes = raw[["Close"]] if "Close" in raw.columns else raw

        closes = closes.ffill().dropna(how="all")

        # If only one ticker yfinance returns a Series
        if isinstance(closes, pd.Series):
            closes = closes.to_frame(name=tickers[0])

        return closes

    except Exception:
        # Stooq batch fallback — fetch individually and concat
        frames = {}
        for t in tickers:
            df = _stooq_single(t, period)
            if df is not None and not df.empty:
                frames[t] = df["Close"]
        if frames:
            return pd.DataFrame(frames).ffill().dropna(how="all")
        return pd.DataFrame()


# ==============================================================================
# PUBLIC: OHLCV batch with all columns (for scanner)
# ==============================================================================
def get_ohlcv_batch(tickers: list, period: str = "6mo") -> dict:
    """
    Returns dict of DataFrames keyed by ticker, each with full OHLCV.
    Used by the scanner which needs Volume etc, not just Close.
    No cache — scanner is always fresh.
    """
    if not tickers:
        return {}

    result = {}
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
            raise ValueError("Empty")

        if isinstance(raw.columns, pd.MultiIndex):
            for t in tickers:
                try:
                    df = raw.xs(t, level=1, axis=1).dropna()
                    if not df.empty:
                        result[t] = df
                except Exception:
                    pass
        else:
            # Single ticker
            if len(tickers) == 1:
                result[tickers[0]] = raw.dropna()

    except Exception:
        pass

    # Stooq fallback for any missing tickers
    missing = [t for t in tickers if t not in result]
    for t in missing:
        df = _stooq_single(t, period)
        if df is not None and not df.empty:
            result[t] = df

    return result


# ==============================================================================
# PUBLIC: Latest price (single ticker, fast)
# ==============================================================================
def get_latest_price(ticker: str) -> float | None:
    """Returns the most recent closing price, or None on failure."""
    try:
        raw = yf.download(ticker, period="2d", interval="1d", progress=False, auto_adjust=True)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if not raw.empty:
            return float(raw["Close"].iloc[-1])
    except Exception:
        pass

    df = _stooq_single(ticker, "5d")
    if df is not None and not df.empty:
        return float(df["Close"].iloc[-1])

    return None


# ==============================================================================
# PUBLIC: Options chain (CBOE, 15-min delayed)
# ==============================================================================
def get_options_chain(ticker: str) -> tuple[dict | None, float | None]:
    """
    Fetches options chain and spot price from CBOE.
    Returns (chain_dict, spot_price).
    chain_dict keys: 'calls', 'puts' — each a list of option dicts.
    Returns (None, None) on failure.
    """
    try:
        # Spot price from CBOE (more accurate for options math than yfinance)
        spot = _cboe_spot(ticker)

        url = _CBOE_CHAIN.format(ticker=ticker.upper())
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=_YF_TIMEOUT)
        r.raise_for_status()
        raw = r.json()

        data = raw.get("data", {})
        options = data.get("options", [])

        calls = [o for o in options if o.get("option_type") == "C"]
        puts  = [o for o in options if o.get("option_type") == "P"]

        # Use CBOE spot if yf spot failed
        if spot is None:
            spot = data.get("current_price") or data.get("last_trade_price")

        return {"calls": calls, "puts": puts, "raw": data}, spot

    except Exception:
        return None, None


# ==============================================================================
# PUBLIC: Market weather tickers (VIX + regime inputs)
# ==============================================================================
@st.cache_data(ttl=900)   # 15 min — regime doesn't need to be faster
def get_weather_data() -> pd.DataFrame:
    """
    Fetches ['SPY', '^VIX', 'RSP', 'HYG', 'IEI', 'UUP'] closing prices.
    Returns wide DataFrame, 3 months of history.
    """
    tickers = ["SPY", "^VIX", "RSP", "HYG", "IEI", "UUP"]
    try:
        raw = yf.download(tickers, period="3mo", interval="1d", progress=False, auto_adjust=False)
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw.xs("Close", level=0, axis=1)
        else:
            closes = raw
        closes = closes.ffill().dropna()
        if len(closes) >= 50:
            return closes
    except Exception:
        pass
    return pd.DataFrame()


# ==============================================================================
# PRIVATE: yfinance single-ticker fetch
# ==============================================================================
def _yf_single(ticker: str, period: str, interval: str) -> pd.DataFrame | None:
    try:
        raw = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
        )
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if raw.empty:
            return None
        needed = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in raw.columns]
        return raw[needed].dropna()
    except Exception:
        return None


# ==============================================================================
# PRIVATE: Stooq CSV fallback
# ==============================================================================
def _stooq_single(ticker: str, period: str) -> pd.DataFrame | None:
    """
    Fetches daily OHLCV from Stooq public CSV.
    Stooq tickers: US stocks as-is, indices use ^ prefix (e.g. ^VIX → ^VIX).
    """
    try:
        # Stooq uses lowercase and replaces ^ with ^ (keep as-is)
        stooq_ticker = ticker.lower().replace("-", ".")

        url = _STOOQ_URL.format(ticker=stooq_ticker)
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=_YF_TIMEOUT)
        r.raise_for_status()

        df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"], index_col="Date")
        df.columns = [c.strip().title() for c in df.columns]

        # Rename Stooq columns to standard
        col_map = {"Open": "Open", "High": "High", "Low": "Low",
                   "Close": "Close", "Volume": "Volume"}
        df = df.rename(columns=col_map)
        df = df[[c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]]
        df = df.sort_index().dropna()

        if df.empty:
            return None

        # Trim to approximate period
        cutoff = _period_to_days(period)
        if cutoff:
            df = df.iloc[-cutoff:]

        return df

    except Exception:
        return None


# ==============================================================================
# PRIVATE: CBOE spot price
# ==============================================================================
def _cboe_spot(ticker: str) -> float | None:
    try:
        url = _CBOE_SPOT.format(ticker=ticker.upper())
        r = requests.get(url, headers=_HTTP_HEADERS, timeout=_YF_TIMEOUT)
        r.raise_for_status()
        data = r.json().get("data", {})
        return float(data.get("current_price") or data.get("last_trade_price") or 0) or None
    except Exception:
        return None


# ==============================================================================
# PRIVATE: Convert period string to approx calendar days
# ==============================================================================
def _period_to_days(period: str) -> int | None:
    mapping = {
        "1d": 1, "5d": 5, "1mo": 35, "2mo": 65, "3mo": 95,
        "6mo": 185, "1y": 370, "2y": 740, "5y": 1850,
    }
    return mapping.get(period.lower())

