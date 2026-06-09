# FILE: config.py
# ROLE: Single source of truth for all configuration constants
# SYSTEM: APEX — Unified Trading Command System

# ==============================================================================
# SECTOR MAP — "The Generals" (Broad Sector ETFs vs SPY)
# ==============================================================================
SECTOR_MAP = {
    "Technology":     "XLK",
    "Communications": "XLC",
    "Consumer Disc":  "XLY",
    "Financials":     "XLF",
    "Healthcare":     "XLV",
    "Industrials":    "XLI",
    "Energy":         "XLE",
    "Materials":      "XLB",
    "Real Estate":    "XLRE",
    "Utilities":      "XLU",
    "Staples":        "XLP",
    "Commodities":    "DBC",
}

# ==============================================================================
# THEME MAP — "The Lieutenants" (Sub-Sector ETFs vs their General)
# ==============================================================================
THEME_MAP = {
    "Technology": {
        "Semiconductors":   "SMH",
        "Software":         "IGV",
        "Cybersecurity":    "CIBR",
        "Cloud Computing":  "SKYY",
        "AI & Robotics":    "BOTZ",
    },
    "Communications": {
        "Social Media":       "SOCL",
        "Video Games":        "HERO",
        "Internet Giants":    "FDN",
        "Telecom":            "IYZ",
        "Media":              "PBS",
    },
    "Consumer Disc": {
        "Homebuilders":   "XHB",
        "Retail":         "XRT",
        "Travel/Leisure": "PEJ",
        "Automotive/EV":  "DRIV",
        "Online Retail":  "IBUY",
    },
    "Financials": {
        "Regional Banks":   "KRE",
        "Capital Markets":  "KCE",
        "Insurance":        "KIE",
        "Fintech":          "FINX",
        "Broker-Dealers":   "IAI",
    },
    "Healthcare": {
        "Biotech":              "XBI",
        "Medical Devices":      "IHI",
        "Pharmaceuticals":      "PJP",
        "Healthcare Providers": "IHF",
        "Genomics":             "ARKG",
    },
    "Industrials": {
        "Aerospace/Defense": "PPA",
        "Transportation":    "IYT",
        "Infrastructure":    "PAVE",
        "Water Resources":   "PHO",
        "Global Jets":       "JETS",
    },
    "Energy": {
        "Oil & Gas Equip":  "XES",
        "Exploration":      "XOP",
        "Oil Services":     "OIH",
        "Clean Energy":     "ICLN",
        "Uranium":          "URNM",
    },
    "Materials": {
        "Gold Miners":    "GDX",
        "Rare Earths":    "REMX",
        "Steel":          "SLX",
        "Lithium/Battery":"LIT",
        "Copper Miners":  "COPX",
    },
    "Real Estate": {
        "Residential":      "REZ",
        "Data Center REITs":"SRVR",
        "Mortgage REITs":   "REM",
        "International RE": "VNQI",
        "Industrial RE":    "INDS",
    },
    "Utilities": {
        "Clean Power": "QCLN",
        "Water":       "CGW",
        "Nuclear":     "NLR",
        "Solar":       "TAN",
        "Wind":        "FAN",
    },
    "Staples": {
        "Food & Beverage":  "PBJ",
        "Household Goods":  "IYK",
        "Agribusiness":     "MOO",
        "Emerging Consumer":"ECON",
    },
    "Commodities": {
        "Gold":        "GLD",
        "Silver":      "SLV",
        "Crude Oil":   "USO",
        "Natural Gas": "UNG",
        "Copper":      "CPER",
        "Agriculture": "DBA",
        "Uranium":     "URNM",
    },
}

# ==============================================================================
# MACRO COMPASS — Indices vs Bonds (IEF benchmark)
# ==============================================================================
MACRO_TICKERS = ["SPY", "QQQ", "IWM", "DIA", "GLD", "SLV", "HYG", "TLT", "UUP"]
MACRO_BENCHMARK = "IEF"

# ==============================================================================
# MARKET REGIME — Weather Engine Tickers
# ==============================================================================
WEATHER_TICKERS = ["SPY", "^VIX", "RSP", "HYG", "IEI", "UUP"]

# ==============================================================================
# SCANNER UNIVERSE — ETF-only, no individual stocks
# ==============================================================================
SCAN_UNIVERSE_EXTRA = [
    "SMH", "IGV", "CIBR", "KRE", "IAI", "IBB", "IHI",
    "OIH", "URA", "TAN", "ITA", "JETS", "PAVE",
    "XHB", "XRT", "PEJ", "GDX", "SIL", "LIT",
    "COPX", "VNQ", "TLT", "UUP", "GLD", "USO",
]

# ==============================================================================
# RRG SETTINGS
# ==============================================================================
RRG_LOOKBACK_DAYS   = 252   # 1 trading year of data fetched
RRG_RATIO_WINDOW    = 65    # RS-Ratio smoothing (JdK standard)
RRG_MOM_WINDOW      = 10    # RS-Momentum window
RRG_TAIL_DAYS       = 7     # Comet tail length on chart
RRG_DISPLAY_DAYS    = 20    # Lookback for display filter

# ==============================================================================
# RISK / SIZING
# ==============================================================================
RISK_FREE_RATE      = 0.04   # 4.0% — used in Sharpe calculation
ATR_PERIOD          = 14
ATR_MULTIPLIER_ETF  = 2.0    # Stop distance for ETFs (Generals)
ATR_MULTIPLIER_STK  = 2.5    # Stop distance for individual stocks
BEAR_SIZE_SCALAR    = 0.5    # Position size cut in bear/risk-off regime

# ==============================================================================
# PERSISTENCE
# ==============================================================================
PORTFOLIO_SHEET     = "apex_portfolio"   # Google Sheets tab name
HISTORY_SHEET       = "apex_trade_log"
WATCHLIST_SHEET     = "apex_watchlist"
LOCAL_PORTFOLIO_JSON = "apex_portfolio.json"
LOCAL_HISTORY_JSON   = "apex_history.json"
LOCAL_WATCHLIST_JSON = "apex_watchlist.json"

# ==============================================================================
# DEFAULT WATCHLIST (first run only)
# ==============================================================================
DEFAULT_WATCHLIST = ["NVDA", "AMD", "PLTR", "COIN", "TSLA", "SMH", "GLD"]

