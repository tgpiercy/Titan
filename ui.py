# FILE: ui.py
# ROLE: Global visual styling — TITAN aesthetic, APEX refinements
# Apply once in app.py via: st.markdown(get_styles(), unsafe_allow_html=True)

def get_styles() -> str:
    return """
    <style>
        /* ================================================================
           GLOBAL
        ================================================================ */
        html, body, [class*="css"] {
            font-family: 'Roboto Mono', monospace;
            font-size: 17px;
        }

        /* ================================================================
           TYPOGRAPHY HIERARCHY
        ================================================================ */
        h1 {
            font-size: 52px !important;
            font-weight: 900 !important;
            text-transform: uppercase;
            padding-bottom: 16px !important;
            letter-spacing: 2px;
        }

        h2 {
            font-size: 38px !important;
            font-weight: 800 !important;
            color: #FFFFFF !important;
            border-bottom: 3px solid #333;
            padding-top: 28px !important;
            padding-bottom: 10px !important;
            margin-bottom: 18px !important;
            text-transform: uppercase;
            letter-spacing: 1px;
        }

        h3 {
            font-size: 24px !important;
            font-weight: 700 !important;
            color: #E0E0E0 !important;
            margin-top: 0px !important;
            margin-bottom: 8px !important;
        }

        /* ================================================================
           REGIME BANNER  (used in Command page)
        ================================================================ */
        .regime-banner {
            border-radius: 12px;
            padding: 28px 20px;
            text-align: center;
            margin-bottom: 28px;
        }
        .regime-title {
            font-size: 46px;
            font-weight: 900;
            line-height: 1.2;
            text-shadow: 0px 0px 12px rgba(0,0,0,0.6);
            margin: 0;
        }
        .regime-action {
            font-size: 22px;
            font-weight: bold;
            letter-spacing: 1px;
            margin: 10px 0 0 0;
            color: #DDD;
        }

        /* ================================================================
           MARKET CARDS  (VIX / Breadth / Credit / Dollar)
        ================================================================ */
        .market-card {
            border: 1px solid #444;
            border-radius: 8px;
            padding: 16px;
            text-align: center;
            margin-bottom: 10px;
            transition: border-color 0.2s;
        }
        .market-card:hover { border-color: #888; }
        .market-label {
            font-size: 20px;
            font-weight: 700;
            color: #EEEEEE;
            text-transform: uppercase;
            margin-bottom: 6px;
        }
        .market-value {
            font-size: 30px;
            font-weight: 800;
            color: #FFFFFF;
        }
        .market-note {
            font-size: 14px;
            color: #BBBBBB;
            margin-top: 6px;
            font-weight: 500;
        }

        /* ================================================================
           COMMAND CARD  (Hunter signal box)
        ================================================================ */
        .command-card {
            border-radius: 8px;
            padding: 16px 20px;
            text-align: center;
            margin-bottom: 20px;
        }
        .command-title {
            font-size: 28px;
            font-weight: 900;
            margin: 0;
            padding: 0;
        }

        /* ================================================================
           SIGNAL PILL  (inline label badges)
        ================================================================ */
        .signal-pill {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 4px;
            font-size: 13px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        /* ================================================================
           METRICS
        ================================================================ */
        div[data-testid="stMetricValue"] {
            font-size: 30px !important;
            font-weight: 700 !important;
            color: #FFFFFF !important;
        }
        div[data-testid="stMetricLabel"] {
            font-size: 20px !important;
            color: #AAAAAA !important;
            text-transform: uppercase;
            font-weight: 600 !important;
        }
        div[data-testid="stMetricDelta"] {
            font-size: 15px !important;
        }

        /* ================================================================
           TABLES
        ================================================================ */
        div[data-testid="stDataFrame"] {
            zoom: 1.12;
            width: 100% !important;
        }

        /* ================================================================
           CHARTS
        ================================================================ */
        .js-plotly-plot {
            margin-top: 0px !important;
            margin-bottom: 0px !important;
        }

        /* ================================================================
           ALERTS & BUTTONS
        ================================================================ */
        .stAlert { font-size: 18px !important; }

        button {
            font-size: 18px !important;
            font-weight: 700 !important;
        }

        /* ================================================================
           SIDEBAR
        ================================================================ */
        [data-testid="stSidebar"] {
            background-color: #0D1117;
            border-right: 1px solid #222;
        }

        /* ================================================================
           DIVIDER
        ================================================================ */
        hr {
            border-color: #2A2A2A !important;
            margin: 24px 0 !important;
        }
    </style>
    """


# ==============================================================================
# HELPER RENDERERS — reusable HTML components
# ==============================================================================

def regime_banner(status: str, action: str, color: str, timestamp: str) -> str:
    """Full-width regime status banner."""
    return f"""
    <div class="regime-banner" style="border: 4px solid {color}; background-color: {color}22;">
        <p class="regime-title" style="color: {color};">{status}</p>
        <p class="regime-action">AUTHORIZATION: {action}
            <span style="font-size:16px; color:#BBB; margin-left:14px; font-weight:normal;">
                ({timestamp})
            </span>
        </p>
    </div>
    """


def market_card(label: str, value: str, note: str, state: str = "neutral") -> str:
    """Individual market condition card (VIX, Breadth, Credit, Dollar)."""
    if state == "good":
        bg = "rgba(0,120,0,0.25)"; border = "#00FF00"
    elif state == "bad":
        bg = "rgba(120,0,0,0.25)"; border = "#FF4444"
    elif state == "warn":
        bg = "rgba(180,100,0,0.25)"; border = "#FFA500"
    else:
        bg = "rgba(255,255,255,0.04)"; border = "#444"

    return f"""
    <div class="market-card" style="background-color:{bg}; border-color:{border};">
        <div class="market-label">{label}</div>
        <div class="market-value">{value}</div>
        <div class="market-note">{note}</div>
    </div>
    """


def command_card(order: str, color: str) -> str:
    """Hunter command decision box."""
    return f"""
    <div class="command-card" style="border: 2px solid {color}; background-color:{color}1A;">
        <p class="command-title" style="color:{color};">COMMAND: {order}</p>
    </div>
    """


def signal_pill(text: str, color: str) -> str:
    """Inline coloured signal label."""
    return f'<span class="signal-pill" style="background-color:{color}33; color:{color}; border:1px solid {color}55;">{text}</span>'


# ==============================================================================
# QUADRANT COLOUR MAP  (shared across RRG and tables)
# ==============================================================================
QUAD_COLORS = {
    "Leading":   "#00FF00",
    "Improving": "#00CCFF",
    "Weakening": "#FFFF00",
    "Lagging":   "#FF4444",
    "UNTRACKED": "#888888",
}

def quad_color(quadrant: str) -> str:
    return QUAD_COLORS.get(quadrant, "#888888")

