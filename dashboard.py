"""
dashboard.py - Treasury Signal Intelligence
Landing Page + Live Dashboard
"""

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
from supabase import create_client
import yfinance as yf
import pandas as pd
from treasury_leaderboard import get_leaderboard_with_live_price, TREASURY_COMPANIES
from regulatory_tracker import get_all_regulatory_items, get_summary_stats as get_reg_stats, get_by_category, get_all_items_combined, get_all_statements_combined
from purchase_tracker import get_recent_purchases, get_purchase_stats
from logger import get_logger
from freshness_tracker import FreshnessTracker
from auth import require_auth, show_login_page, login_user, logout

logger = get_logger(__name__)

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Treasury Signal Intelligence | BTC Treasury Monitoring", page_icon="🔶", layout="wide", initial_sidebar_state="expanded")

# ============================================
# CUSTOM CSS
# ============================================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap');

    /* Global overrides */
    .stApp { background-color: #0a0e17; }
    .main .block-container { padding-top: 2rem; max-width: 1200px; }
    html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }
    h1, h2, h3 { font-family: 'DM Sans', sans-serif !important; }

    /* Sidebar styling */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0d1117 0%, #0a0e17 100%);
        border-right: 1px solid #1a1f2e;
    }
    section[data-testid="stSidebar"] .stRadio label {
        font-family: 'DM Sans', sans-serif;
        font-weight: 500;
        padding: 8px 12px;
        border-radius: 8px;
        transition: all 0.2s ease;
    }
    section[data-testid="stSidebar"] .stRadio label:hover {
        background: rgba(230, 126, 34, 0.1);
    }

    /* Metric cards */
    [data-testid="stMetric"] {
        background: linear-gradient(135deg, #111827 0%, #0d1117 100%);
        border: 1px solid #1e2a3a;
        border-radius: 12px;
        padding: 16px 20px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    [data-testid="stMetric"] label {
        color: #6b7280 !important;
        font-size: 0.8rem !important;
        font-weight: 500 !important;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    [data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #f0f0f0 !important;
        font-family: 'JetBrains Mono', monospace !important;
        font-weight: 600 !important;
    }

    /* Headers */
    .main-header {
        font-size: 2.8rem;
        font-weight: 700;
        background: linear-gradient(135deg, #E67E22 0%, #F39C12 50%, #E67E22 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin-top: 20px;
        letter-spacing: -0.02em;
    }
    .hero-sub {
        font-size: 1.15rem;
        color: #6b7280;
        text-align: center;
        margin-bottom: 30px;
        font-weight: 400;
        letter-spacing: 0.01em;
    }

    /* Feature boxes */
    .feature-box {
        background: linear-gradient(135deg, #111827 0%, #0d1420 100%);
        padding: 22px;
        border-radius: 12px;
        border: 1px solid #1e2a3a;
        margin: 5px 0;
        box-shadow: 0 4px 16px rgba(0,0,0,0.2);
        transition: all 0.3s ease;
    }
    .feature-box:hover {
        border-color: #E67E22;
        box-shadow: 0 4px 24px rgba(230, 126, 34, 0.15);
        transform: translateY(-2px);
    }
    .feature-title {
        color: #E67E22;
        font-size: 1.05rem;
        font-weight: 700;
        margin-bottom: 8px;
        letter-spacing: -0.01em;
    }

    /* Stats */
    .stat-huge {
        font-size: 2.8rem;
        font-weight: 700;
        font-family: 'JetBrains Mono', monospace;
        background: linear-gradient(135deg, #E67E22 0%, #F39C12 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        text-align: center;
        margin: 0;
    }
    .stat-label {
        font-size: 0.85rem;
        color: #4b5563;
        text-align: center;
        margin: 4px 0 0 0;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        font-weight: 500;
    }

    /* Proof bar */
    .proof-bar {
        background: linear-gradient(135deg, #1a0f00 0%, #1a1000 100%);
        padding: 18px 24px;
        border-radius: 12px;
        text-align: center;
        border: 1px solid rgba(230, 126, 34, 0.3);
        margin: 20px 0;
        box-shadow: 0 0 30px rgba(230, 126, 34, 0.08);
    }

    /* Signal cards */
    .signal-card {
        border-left: 3px solid;
        padding: 14px 16px;
        margin: 8px 0;
        background: linear-gradient(135deg, #111827 0%, #0d1420 100%);
        border-radius: 0 10px 10px 0;
        box-shadow: 0 2px 12px rgba(0,0,0,0.2);
        transition: all 0.2s ease;
    }
    .signal-card:hover {
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        transform: translateX(4px);
    }

    /* Pricing cards */
    .pricing-free {
        background: linear-gradient(135deg, #111827 0%, #0d1420 100%);
        padding: 28px;
        border-radius: 16px;
        border: 1px solid #1e2a3a;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
    }
    .pricing-pro {
        background: linear-gradient(135deg, #1a0f00 0%, #111827 100%);
        padding: 28px;
        border-radius: 16px;
        border: 2px solid #E67E22;
        box-shadow: 0 0 40px rgba(230, 126, 34, 0.12);
        position: relative;
    }

    /* Dataframe styling */
    .stDataFrame { border-radius: 12px; overflow: hidden; }

    /* Tabs and dividers */
    hr { border-color: #1e2a3a !important; }

    /* Links */
    a { color: #E67E22 !important; text-decoration: none !important; font-weight: 600; }
    a:hover { color: #F39C12 !important; }

    /* Plotly chart backgrounds */
    .js-plotly-plot { border-radius: 12px; overflow: hidden; }

    /* Button styling */
    .stButton button {
        background: linear-gradient(135deg, #E67E22 0%, #d35400 100%);
        color: white;
        border: none;
        border-radius: 8px;
        font-weight: 600;
        font-family: 'DM Sans', sans-serif;
        padding: 8px 24px;
        transition: all 0.2s ease;
    }
    .stButton button:hover {
        box-shadow: 0 4px 16px rgba(230, 126, 34, 0.4);
        transform: translateY(-1px);
    }

    /* Hide Streamlit branding */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header { visibility: hidden; }

    /* Badge styling for PRO label */
    .pro-badge {
        background: linear-gradient(135deg, #E67E22, #d35400);
        color: white;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.7rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.1em;
        display: inline-block;
        margin-left: 8px;
    }

    /* Custom scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0a0e17; }
    ::-webkit-scrollbar-thumb { background: #1e2a3a; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #E67E22; }

    /* Expander styling */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, #111827 0%, #0d1420 100%) !important;
        border: 1px solid #1e2a3a !important;
        border-radius: 10px !important;
        font-weight: 600 !important;
        color: #d1d5db !important;
    }
    .streamlit-expanderContent {
        border: 1px solid #1e2a3a !important;
        border-top: none !important;
        border-radius: 0 0 10px 10px !important;
        background: rgba(17, 24, 39, 0.5) !important;
    }

    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background: #111827;
        border-radius: 10px;
        padding: 4px;
    }
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 8px 20px;
        font-family: 'DM Sans', sans-serif;
        font-weight: 500;
    }
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #E67E22 0%, #d35400 100%) !important;
    }

    /* Selectbox and input styling */
    .stSelectbox > div > div,
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input {
        background: #111827 !important;
        border: 1px solid #1e2a3a !important;
        border-radius: 8px !important;
        color: #f0f0f0 !important;
    }

    /* Download button */
    .stDownloadButton button {
        background: linear-gradient(135deg, #10B981 0%, #059669 100%) !important;
    }
    .stDownloadButton button:hover {
        box-shadow: 0 4px 16px rgba(16, 185, 129, 0.4) !important;
    }

    /* Smooth page transitions */
    .main .block-container {
        animation: fadeIn 0.3s ease-in;
    }
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(8px); }
        to { opacity: 1; transform: translateY(0); }
    }

    /* Mobile responsive */
    @media (max-width: 768px) {
        .main .block-container { padding: 1rem 0.5rem; }
        .main-header { font-size: 1.8rem; }
        .hero-sub { font-size: 0.95rem; }
        .stat-huge { font-size: 1.8rem; }
        .feature-box { padding: 14px; }
        .signal-card { padding: 10px 12px; }
        .proof-bar { padding: 12px 16px; }
        [data-testid="stMetric"] { padding: 10px 12px; }
    }
</style>
""", unsafe_allow_html=True)


# ============================================
# DATA LOADING
# ============================================
@st.cache_data(ttl=300)
def load_all_tweets():
    try:
        result = supabase.table("tweets").select("*").order("inserted_at", desc=True).limit(1000).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to load tweets for dashboard: {e}")
        return []

@st.cache_data(ttl=300)
def load_signals():
    try:
        result = supabase.table("tweets").select("*").eq("is_signal", True).order("inserted_at", desc=True).limit(100).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Failed to load signals for dashboard: {e}")
        return []

@st.cache_data(ttl=600)
def load_strc_data():
    try:
        strc = yf.Ticker("STRC")
        hist = strc.history(period="3mo")
        if hist.empty:
            return yf.download("STRC", period="3mo", progress=False)
        return hist
    except Exception as e:
        logger.warning(f"Failed to load STRC data for dashboard: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_btc_price():
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else 0
    except Exception as e:
        logger.warning(f"Failed to load BTC price for dashboard: {e}")
        return 0

@st.cache_data(ttl=600)
def load_mstr_price():
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else 0
    except Exception as e:
        logger.warning(f"Failed to load MSTR price for dashboard: {e}")
        return 0

@st.cache_data(ttl=300)
def load_accuracy_stats():
    try:
        purchases = supabase.table("confirmed_purchases").select("*").execute()
        predictions = supabase.table("predictions").select("*").execute()
        all_purchases = purchases.data if purchases.data else []
        all_predictions = predictions.data if predictions.data else []
        total = len(all_purchases)
        predicted = len([p for p in all_purchases if p.get("was_predicted")])
        hit_rate = round(predicted / total * 100, 1) if total > 0 else 0
        return {"total": total, "predicted": predicted, "hit_rate": hit_rate, "predictions": len(all_predictions)}
    except Exception as e:
        logger.error(f"Failed to load accuracy stats for dashboard: {e}")
        return {"total": 0, "predicted": 0, "hit_rate": 0, "predictions": 0}

# Load data
tweets = load_all_tweets()
signals = load_signals()
strc_hist = load_strc_data()
btc_price = load_btc_price()
mstr_price = load_mstr_price()
accuracy = load_accuracy_stats()

total_tweets = len(tweets)
total_signals = len(signals)
high_signals = len([s for s in signals if s.get("confidence_score", 0) >= 60])
accounts_tracked = len(set(t.get("author_username", "") for t in tweets))

strc_price = round(float(strc_hist["Close"].iloc[-1]), 2) if not strc_hist.empty else 0
strc_volume = int(strc_hist["Volume"].iloc[-1]) if not strc_hist.empty else 0
strc_avg = int(strc_hist["Volume"].tail(20).mean()) if not strc_hist.empty else 0
strc_ratio = round(strc_volume / strc_avg, 2) if strc_avg > 0 else 0

# ============================================
# SIDEBAR
# ============================================

# Check auth state
_current_user = require_auth()

with st.sidebar:
    st.image("https://img.icons8.com/color/96/bitcoin--v1.png", width=60)
    st.markdown("## Treasury Signal Intelligence")
    st.markdown("*Multi-source Bitcoin purchase detection*")
    st.markdown("---")

    # Auth-aware navigation
    if _current_user:
        page = st.radio("Navigate", ["🏠 Home", "📊 Live Dashboard", "🏆 BTC Leaderboard", "💰 Recent Purchases", "🏛️ Regulatory Tracker", "📈 Accuracy", "🏢 My Company", "📐 What-If Calculator"], label_visibility="collapsed")
    else:
        page = st.radio("Navigate", ["🏠 Home", "🔑 Sign In"], label_visibility="collapsed")

    st.markdown("---")

    # User info or sign-in prompt
    if _current_user:
        st.markdown(f"### 👤 {_current_user['name']}")
        st.markdown(f"*{_current_user.get('company_name', '')}*")
        if _current_user.get("plan"):
            plan_badge = "🟢 PRO" if _current_user["plan"] == "pro" else "⚪ FREE"
            st.markdown(f"Plan: **{plan_badge}**")
        st.markdown("---")
        if st.button("🚪 Sign Out"):
            logout()
            st.rerun()
    else:
        st.markdown("### 🔒 Sign in for full access")
        st.markdown("Get personalized intelligence, watchlist alerts, and scenario modeling.")

    st.markdown("---")
    st.markdown("### System Status")

    # Load freshness data from Supabase
    _freshness_loader = FreshnessTracker()
    _freshness_data = _freshness_loader.load_from_supabase(supabase)
    if _freshness_data:
        _health = _freshness_data.get("overall_health", "unknown")
        _live = _freshness_data.get("live_count", 0)
        _stale = _freshness_data.get("stale_count", 0)
        _down = _freshness_data.get("unavailable_count", 0)
        if _health == "healthy":
            st.markdown(f"🟢 **Data Sources:** All {_live} live")
        elif _health == "degraded":
            st.markdown(f"🟡 **Data Sources:** {_live} live, {_stale} stale, {_down} down")
        else:
            st.markdown(f"🔴 **Data Sources:** {_live} live, {_stale} stale, {_down} down")

        with st.expander("View data source details"):
            sources = _freshness_data.get("sources", [])
            for src in sources:
                if src.get("status") == "unknown":
                    continue
                _emoji = src.get("emoji", "⚪")
                _label = src.get("label", src.get("source", ""))
                _age = src.get("age_text", "?")
                st.markdown(f"{_emoji} **{_label}**: {_age}")
    else:
        st.markdown(f"⚪ **Scanner:** Waiting for first scan")

    st.markdown(f"📡 **Accounts:** {accounts_tracked}")
    st.markdown(f"🗄️ **Tweets:** {total_tweets}")
    st.markdown(f"🚨 **Signals:** {total_signals}")
    st.markdown("---")
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()


# ============================================
# PAGE: HOME / LANDING
# ============================================
if page == "🏠 Home":
    st.markdown('<p class="main-header">🔶 Treasury Signal Intelligence</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Know when Bitcoin treasury companies are about to buy — before the market does.</p>', unsafe_allow_html=True)
    
    # Stats bar
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown('<p class="stat-huge">4</p><p class="stat-label">Data Streams</p>', unsafe_allow_html=True)
    with c2:
        st.markdown('<p class="stat-huge">24/7</p><p class="stat-label">Monitoring</p>', unsafe_allow_html=True)
    with c3:
        st.markdown(f'<p class="stat-huge">{accounts_tracked}+</p><p class="stat-label">Accounts Tracked</p>', unsafe_allow_html=True)
    with c4:
        st.markdown('<p class="stat-huge">60min</p><p class="stat-label">Scan Cycle</p>', unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Executive Summary with tooltips
    st.markdown("### 📋 Executive Summary")
    
    # Get live data for summary
    from regulatory_tracker import get_summary_stats as get_reg_summary
    reg_summary = get_reg_summary()
    
    st.markdown("""
    <style>
        .exec-item {
            display: flex;
            align-items: flex-start;
            padding: 10px 16px;
            margin: 4px 0;
            background: linear-gradient(135deg, #111827 0%, #0d1420 100%);
            border-radius: 10px;
            border: 1px solid #1e2a3a;
            position: relative;
            transition: all 0.2s ease;
        }
        .exec-item:hover {
            border-color: #E67E22;
            box-shadow: 0 2px 16px rgba(230, 126, 34, 0.1);
        }
        .exec-icon {
            font-size: 1.2rem;
            margin-right: 12px;
            margin-top: 2px;
            flex-shrink: 0;
        }
        .exec-text {
            color: #d1d5db;
            font-size: 0.95rem;
            line-height: 1.5;
            flex-grow: 1;
        }
        .info-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 18px;
            height: 18px;
            border-radius: 50%;
            background: rgba(230, 126, 34, 0.15);
            border: 1px solid rgba(230, 126, 34, 0.3);
            color: #E67E22;
            font-size: 11px;
            font-weight: 700;
            cursor: help;
            margin-left: 8px;
            flex-shrink: 0;
            position: relative;
        }
        .info-badge:hover .tooltip-popup {
            display: block;
        }
        .tooltip-popup {
            display: none;
            position: absolute;
            bottom: 28px;
            right: -10px;
            width: 300px;
            background: #1a1f2e;
            border: 1px solid #E67E22;
            border-radius: 10px;
            padding: 14px 16px;
            color: #d1d5db;
            font-size: 12px;
            font-weight: 400;
            line-height: 1.6;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
            z-index: 1000;
        }
        .tooltip-popup::after {
            content: '';
            position: absolute;
            bottom: -8px;
            right: 16px;
            width: 14px;
            height: 14px;
            background: #1a1f2e;
            border-right: 1px solid #E67E22;
            border-bottom: 1px solid #E67E22;
            transform: rotate(45deg);
        }
        .tooltip-title {
            color: #E67E22;
            font-weight: 700;
            font-size: 12px;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
    </style>
    """, unsafe_allow_html=True)
    
    # Determine signal status
    signal_count = len([s for s in signals if s.get("confidence_score", 0) >= 40])
    high_signal_count = len([s for s in signals if s.get("confidence_score", 0) >= 60])
    
    if high_signal_count > 0:
        top_sig = max(signals, key=lambda x: x.get("confidence_score", 0))
        signal_text = f"<span style='color: #F59E0B;'>{signal_count} purchase signal(s) detected</span> — highest: {top_sig.get('confidence_score', 0)}/100 from @{top_sig.get('author_username', '')}"
        signal_icon = "⚡"
    elif signal_count > 0:
        signal_text = f"<span style='color: #F59E0B;'>{signal_count} low-confidence signal(s)</span> detected — monitoring closely"
        signal_icon = "🟡"
    else:
        signal_text = "<span style='color: #10B981;'>No purchase signals in the last 24 hours</span> — market is quiet"
        signal_icon = "✅"
    
    if strc_ratio >= 1.5:
        strc_text = f"<span style='color: #EF4444;'>STRC volume is {strc_ratio}x normal</span> — capital raise activity elevated"
        strc_icon = "🔴"
    elif strc_ratio >= 1.2:
        strc_text = f"<span style='color: #F59E0B;'>STRC volume is {strc_ratio}x normal</span> — slightly above average"
        strc_icon = "🟡"
    else:
        strc_text = f"<span style='color: #10B981;'>STRC volume is {strc_ratio}x normal</span> — no unusual capital raise activity"
        strc_icon = "🟢"
    
    exec_items = [
        {
            "icon": signal_icon,
            "text": signal_text,
            "tooltip_title": "Purchase Signals",
            "tooltip": "Our AI monitors 24+ executive accounts on X/Twitter every hour, scoring each tweet 0-100 for Bitcoin purchase intent. Signals above 60 are HIGH confidence — historically preceding confirmed purchases within 24-72 hours. When Saylor posts cryptic hints like 'Stretch the Orange Dots', our system catches it instantly.",
        },
        {
            "icon": strc_icon,
            "text": strc_text,
            "tooltip_title": "STRC Capital Raise Monitor",
            "tooltip": "STRC is Strategy's Variable Rate Preferred Stock used to raise capital specifically for Bitcoin purchases. When STRC trading volume spikes above the 20-day average, it signals that Strategy is actively raising capital — and a Bitcoin purchase typically follows within days. A ratio above 1.5x is elevated; above 2.0x is very high.",
        },
        {
            "icon": "🔗",
            "text": f"<span style='color: #9ca3af;'>Correlation Engine: 0/100</span> — baseline, no multi-stream convergence" if high_signals == 0 else f"<span style='color: #F59E0B;'>Correlation Engine active</span> — multiple streams detecting signals",
            "tooltip_title": "Multi-Signal Correlation Engine™",
            "tooltip": "Our proprietary engine monitors 4 independent data streams: executive tweets, STRC volume, SEC EDGAR filings, and timing patterns. When a single stream fires, confidence is ~35%. When 2 streams converge, it jumps to ~72%. When 3+ streams fire simultaneously, confidence hits 99%. This multi-source confirmation is what no competitor offers.",
        },
        {
            "icon": "📋",
            "text": f"<span style='color: #9ca3af;'>SEC EDGAR:</span> Monitoring 11 treasury companies for 8-K filings",
            "tooltip_title": "SEC EDGAR 8-K Monitor",
            "tooltip": "We monitor SEC EDGAR for 8-K filings from 11 major Bitcoin treasury companies including Strategy (MSTR), MARA, Riot, Tesla, GameStop, and more. 8-K filings are used to disclose material events — including Bitcoin purchases. When a company files an 8-K with Bitcoin-related keywords, our system detects it instantly and alerts subscribers.",
        },
        {
            "icon": "🏆",
            "text": f"<span style='color: #E67E22;'>{len([c for c in strc_hist.index]) if not strc_hist.empty else 148} companies</span> on live BTC Treasury Leaderboard — {btc_price:,.0f} BTC price" if btc_price else "BTC Treasury Leaderboard tracking 148+ companies",
            "tooltip_title": "BTC Treasury Leaderboard",
            "tooltip": "A live ranking of every publicly traded company holding Bitcoin on their balance sheet — pulled from CoinGecko in real-time. Currently tracking 148 companies across 25+ countries. Shows BTC holdings, USD value, unrealized P&L, and company details. Updated every scan cycle.",
        },
        {
            "icon": "🏛️",
            "text": f"<span style='color: #3B82F6;'>Regulatory:</span> {reg_summary['total_items']} items tracked across {reg_summary['regions_tracked']} regions — {reg_summary['bullish']} bullish for BTC",
            "tooltip_title": "Global Regulatory Tracker",
            "tooltip": "Tracks Bitcoin legislation, regulations, and policy developments worldwide across 6 regions: US Federal, US State, Europe, Asia-Pacific, Latin America, and Middle East & Africa. Auto-scans Google News every hour for new developments. Also tracks notable statements from world leaders and CEOs about Bitcoin. Currently monitoring 50+ items and 15+ notable statements.",
        },
        {
            "icon": "📈",
            "text": f"<span style='color: #9ca3af;'>Accuracy:</span> {accuracy['predictions']} predictions logged — building track record",
            "tooltip_title": "Accuracy & Prediction Tracking",
            "tooltip": "Every signal our system detects is logged as a prediction with a timestamp and confidence score. When a company confirms a Bitcoin purchase via 8-K filing, we match it against prior predictions. If we predicted it within 72 hours, it counts as a correct prediction. This builds a transparent, verifiable track record — our hit rate and average lead time are displayed publicly.",
        },
    ]
    
    for item in exec_items:
        st.markdown(f"""
        <div class="exec-item">
            <span class="exec-icon">{item['icon']}</span>
            <span class="exec-text">{item['text']}</span>
            <span class="info-badge">ℹ
                <div class="tooltip-popup">
                    <div class="tooltip-title">{item['tooltip_title']}</div>
                    {item['tooltip']}
                </div>
            </span>
        </div>
        """, unsafe_allow_html=True)
    
    st.markdown("")


    # Real signal proof
    st.markdown("""
    <div class="proof-bar">
        <strong>🔴 REAL SIGNAL — March 15, 2026:</strong> @saylor posted "Stretch the Orange Dots" → Our system scored it 90/100 instantly → 
        Strategy filed 8-K confirming Bitcoin purchase the next day.
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown("---")
    
    # How it works
    st.markdown("### How the Multi-Signal Correlation Engine™ Works")
    st.markdown("Four independent data streams. When they converge, confidence compounds exponentially.")
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown("""<div class="feature-box">
            <p class="feature-title">📡 Executive Signals</p>
            <p style="color: #BDC3C7; font-size: 0.9rem;">AI monitors 24+ executive accounts for cryptic purchase hints like Saylor's "orange dot" posts.</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="feature-box">
            <p class="feature-title">💰 STRC Volume</p>
            <p style="color: #BDC3C7; font-size: 0.9rem;">Tracks Strategy's preferred stock issuance. Volume spikes = capital being raised to buy Bitcoin.</p>
        </div>""", unsafe_allow_html=True)
    with c3:
        st.markdown("""<div class="feature-box">
            <p class="feature-title">📋 SEC EDGAR</p>
            <p style="color: #BDC3C7; font-size: 0.9rem;">Monitors 8-K filings from 11 treasury companies for Bitcoin purchase confirmations.</p>
        </div>""", unsafe_allow_html=True)
    with c4:
        st.markdown("""<div class="feature-box">
            <p class="feature-title">🔗 Correlation</p>
            <p style="color: #BDC3C7; font-size: 0.9rem;">Multiple streams firing together = exponential confidence. 1 stream: 35%. 3 streams: 99%.</p>
        </div>""", unsafe_allow_html=True)
    
    st.markdown("---")
    
    # Correlation visualization
    st.markdown("### Signal Correlation in Action")
    
    fig = go.Figure()
    scenarios = ["No Signal", "Tweet Only", "Tweet +\nSTRC Spike", "Tweet + STRC\n+ SEC Filing", "All 4\nStreams"]
    scores = [0, 35, 72, 99, 99]
    colors = ["#2C3E50", "#3498DB", "#F39C12", "#E74C3C", "#E74C3C"]
    
    fig.add_trace(go.Bar(
        x=scenarios, y=scores,
        marker_color=colors,
        text=[f"{s}%" for s in scores],
        textposition="outside",
        textfont=dict(size=16, color="white"),
    ))
    fig.update_layout(
        template="plotly_dark",
        height=350,
        yaxis_title="Confidence Score",
        yaxis_range=[0, 110],
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Pricing
    st.markdown("### Pricing")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("""<div class="pricing-free">
            <h3 style="color: white;">Free</h3>
            <p style="font-size: 2rem; font-weight: 800; color: white;">$0<span style="font-size: 1rem; color: #95A5A6;">/month</span></p>
            <p>✅ Saylor-only signals</p>
            <p>✅ 1-hour delayed alerts</p>
            <p>✅ Basic dashboard</p>
            <p style="color: #7F8C8D;">❌ STRC volume alerts</p>
            <p style="color: #7F8C8D;">❌ SEC EDGAR alerts</p>
            <p style="color: #7F8C8D;">❌ Correlation Engine</p>
            <p style="color: #7F8C8D;">❌ Instant delivery</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        st.markdown("""<div class="pricing-pro">
            <h3 style="color: #E67E22;">PRO ⭐</h3>
            <p style="font-size: 2rem; font-weight: 800; color: #E67E22;">$19<span style="font-size: 1rem; color: #95A5A6;">/month</span></p>
            <p>✅ All 24+ executive accounts</p>
            <p>✅ Instant real-time alerts</p>
            <p>✅ STRC volume spike alerts</p>
            <p>✅ SEC EDGAR 8-K alerts</p>
            <p>✅ Multi-Signal Correlation Engine™</p>
            <p>✅ Full dashboard access</p>
            <p>✅ Accuracy tracking</p>
            <p style="color: #E67E22; font-weight: 700;">🎁 3-day free trial</p>
        </div>""", unsafe_allow_html=True)
    
    st.markdown("")
    if not _current_user:
        st.markdown("""<div class="proof-bar">
            <span style="color: #E67E22; font-size: 1.1rem; font-weight: 700;">Ready to get started?</span>
            <br><span style="color: #9ca3af; font-size: 0.95rem;">Sign in or create an account to access the full platform.</span>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="proof-bar">
            <span style="color: #E67E22; font-size: 1.1rem; font-weight: 700;">Welcome back, {_current_user['name']}</span>
            <br><span style="color: #9ca3af; font-size: 0.95rem;">Use the sidebar to navigate to your personalized dashboard.</span>
        </div>""", unsafe_allow_html=True)
    
    # Navigation cards
    st.markdown("---")
    st.markdown("### Explore the Full Platform")
    st.markdown("Use the sidebar to navigate between all sections:")
    
    nav1, nav2, nav3 = st.columns(3)
    with nav1:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">📊</p>
            <p class="feature-title">Live Dashboard</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Real-time signals, STRC volume charts, market prices, and score distribution</p>
        </div>""", unsafe_allow_html=True)
    with nav2:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">🏆</p>
            <p class="feature-title">BTC Leaderboard</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">148 companies ranked by BTC holdings with P&L, charts, and market share</p>
        </div>""", unsafe_allow_html=True)
    with nav3:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">💰</p>
            <p class="feature-title">Recent Purchases</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Auto-detected BTC purchases with monthly charts and company breakdowns</p>
        </div>""", unsafe_allow_html=True)
    
    nav4, nav5, nav6 = st.columns(3)
    with nav4:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">🏛️</p>
            <p class="feature-title">Regulatory Tracker</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Global regulatory items across 6 regions with auto-detected news and statements</p>
        </div>""", unsafe_allow_html=True)
    with nav5:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">🏢</p>
            <p class="feature-title">My Company</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Your company profile, leaderboard position, watchlist, and board report download</p>
        </div>""", unsafe_allow_html=True)
    with nav6:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">📐</p>
            <p class="feature-title">What-If Calculator</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Model hypothetical BTC purchases and see the impact on rank, P&L, and projections</p>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown(f"""<p style="text-align: center; color: #7F8C8D; font-size: 0.85rem;">
        Treasury Signal Intelligence™ — Independent research tool. Not financial advice.<br>
        Data: TwitterAPI.io • Yahoo Finance • SEC EDGAR • © {datetime.now().year} All rights reserved.
    </p>""", unsafe_allow_html=True)


# ============================================
# PAGE: SIGN IN
# ============================================
elif page == "🔑 Sign In":
    show_login_page()


# ============================================
# PAGE: LIVE DASHBOARD (PROTECTED)
# ============================================
elif page == "📊 Live Dashboard":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">📊 Live Dashboard</p>', unsafe_allow_html=True)

    # Data provenance bar
    _prov_data_dash = None
    try:
        _ft_dash = FreshnessTracker()
        _prov_data_dash = _ft_dash.load_from_supabase(supabase)
    except Exception:
        pass

    if _prov_data_dash and _prov_data_dash.get("provenance"):
        _all_prov = _prov_data_dash["provenance"]
        _badges_html = ""
        _prov_items = [
            ("btc_price", "BTC Price"),
            ("mstr_price", "MSTR Price"),
            ("leaderboard_corporate", "Leaderboard"),
            ("leaderboard_sovereign", "Sovereign"),
        ]
        _badge_colors_d = {"live": ("#10B981", "rgba(16,185,129,0.08)"), "cached": ("#F59E0B", "rgba(245,158,11,0.08)"), "fallback": ("#EF4444", "rgba(239,68,68,0.08)")}
        _icons_d = {"live": "🟢", "cached": "🟡", "fallback": "🔴"}

        for key, label in _prov_items:
            prov = _all_prov.get(key, {})
            ptype = prov.get("source_type", "unknown") if prov else "unknown"
            if ptype == "unknown":
                continue
            _c, _bg = _badge_colors_d.get(ptype, ("#6B7280", "rgba(107,114,128,0.08)"))
            _i = _icons_d.get(ptype, "⚪")
            _badges_html += f'<span style="background:{_bg};color:{_c};padding:3px 10px;border-radius:5px;font-size:10px;font-weight:700;border:1px solid {_c}25;margin-right:8px;">{_i} {label}: {ptype.upper()}</span>'

        if _badges_html:
            st.markdown(f'<div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:4px;">{_badges_html}</div>', unsafe_allow_html=True)

    st.markdown("")

    # Risk Dashboard with tooltips
    from market_intelligence import get_risk_dashboard, generate_action_signal, get_week_ahead
    risk = get_risk_dashboard()
    action = generate_action_signal(
        correlation_score=0, active_streams=0, strc_ratio=strc_ratio,
        signals_24h=signals, btc_change=0, fear_greed_value=risk["fear_greed_value"],
        subscriber=_current_user,
    )

    # Action Signal Banner
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #111827 0%, #0d1420 100%); border: 2px solid {action['action_color']}; border-radius: 14px; padding: 20px 28px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Today's Action Signal</span>
            <br><span style="color: {action['action_color']}; font-size: 1.8rem; font-weight: 800;">{action['action']}</span>
            <br><span style="color: #9ca3af; font-size: 0.85rem;">{action['summary'][:200]}</span>
        </div>
        <div style="text-align: right;">
            <span style="color: {action['action_color']}; font-size: 2.5rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;">{action['score']}</span>
            <br><span style="color: #4b5563; font-size: 0.75rem;">/100</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # Confidence Breakdown
    _breakdown = action.get("confidence_breakdown", [])
    if _breakdown:
        _breakdown_html = ""
        for stream in _breakdown:
            pct = (stream["contribution"] / stream["max"] * 100) if stream["max"] > 0 else 0
            bar_color = "#10B981" if pct >= 60 else "#F59E0B" if pct >= 30 else "#374151"
            _breakdown_html += f"""<div style="display: flex; align-items: center; margin: 3px 0;">
                <span style="color: #6b7280; font-size: 10px; width: 130px;">{stream['icon']} {stream['stream']}</span>
                <div style="flex: 1; height: 6px; background: #1e2a3a; border-radius: 3px; margin: 0 8px;">
                    <div style="width: {min(pct, 100)}%; height: 100%; background: {bar_color}; border-radius: 3px;"></div>
                </div>
                <span style="color: #9ca3af; font-size: 10px; font-family: 'JetBrains Mono', monospace; width: 40px; text-align: right;">{stream['contribution']}/{stream['max']}</span>
            </div>"""
        st.markdown(f"""<div style="background: #111827; border-radius: 10px; padding: 12px 16px; margin-bottom: 16px;">
            <span style="color: #4b5563; font-size: 9px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">Confidence Breakdown</span>
            {_breakdown_html}
        </div>""", unsafe_allow_html=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Bitcoin", f"${btc_price:,.0f}")
    with c2:
        st.metric("MSTR", f"${mstr_price:,.2f}")
    with c3:
        st.metric("STRC", f"${strc_price:.2f}")
    with c4:
        st.metric("STRC Vol Ratio", f"{strc_ratio}x")
    with c5:
        st.metric("Active Signals", f"{high_signals}")

    # Risk Dashboard with tooltip icons
    st.markdown("### Risk Dashboard")
    r1, r2, r3, r4 = st.columns(4)
    with r1:
        st.markdown(f"""<div class="exec-item" style="text-align: center; padding: 16px;">
            <span style="color: {'#EF4444' if risk['fear_greed_value'] <= 25 else '#F59E0B' if risk['fear_greed_value'] <= 40 else '#10B981' if risk['fear_greed_value'] <= 60 else '#F59E0B'}; font-size: 2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;">{risk['fear_greed_value']}</span>
            <br><span style="color: #6b7280; font-size: 0.8rem;">Fear & Greed</span>
            <span class="info-badge">ℹ
                <div class="tooltip-popup">
                    <div class="tooltip-title">Fear & Greed Index</div>
                    Measures market sentiment from 0 (Extreme Fear) to 100 (Extreme Greed). Extreme Fear (0-25) historically signals buying opportunities — the market is oversold and prices are depressed. Extreme Greed (75-100) signals caution — the market may be overbought. Currently at {risk['fear_greed_value']} ({risk['fear_greed_label']}). Source: alternative.me
                </div>
            </span>
            <br><span style="color: #9ca3af; font-size: 0.75rem;">{risk['fear_greed_label']}</span>
        </div>""", unsafe_allow_html=True)
    with r2:
        st.markdown(f"""<div class="exec-item" style="text-align: center; padding: 16px;">
            <span style="color: {'#EF4444' if risk['volatility_30d'] >= 60 else '#F59E0B' if risk['volatility_30d'] >= 40 else '#10B981'}; font-size: 2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;">{risk['volatility_30d']}%</span>
            <br><span style="color: #6b7280; font-size: 0.8rem;">30D Volatility</span>
            <span class="info-badge">ℹ
                <div class="tooltip-popup">
                    <div class="tooltip-title">30-Day Annualized Volatility</div>
                    Measures how much Bitcoin's price fluctuates daily, annualized over 30 days. Below 40% = low volatility (stable, good for large purchases). 40-60% = moderate (normal market conditions). Above 60% = high volatility (rapid price swings, consider scaling into positions rather than lump-sum buying).
                </div>
            </span>
        </div>""", unsafe_allow_html=True)
    with r3:
        st.markdown(f"""<div class="exec-item" style="text-align: center; padding: 16px;">
            <span style="color: #EF4444; font-size: 2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;">{risk['drawdown_from_ath']}%</span>
            <br><span style="color: #6b7280; font-size: 0.8rem;">From ATH</span>
            <span class="info-badge">ℹ
                <div class="tooltip-popup">
                    <div class="tooltip-title">Drawdown from All-Time High</div>
                    Shows how far Bitcoin has fallen from its highest recorded price (${risk['ath_price']:,.0f}). A -20% drawdown means BTC is 20% below its peak. Larger drawdowns (30%+) can signal strong buying opportunities for long-term holders. Smaller drawdowns indicate strength near all-time highs.
                </div>
            </span>
        </div>""", unsafe_allow_html=True)
    with r4:
        st.markdown(f"""<div class="exec-item" style="text-align: center; padding: 16px; border: 1px solid {risk['risk_color']};">
            <span style="color: {risk['risk_color']}; font-size: 1.4rem; font-weight: 800;">{risk['risk_level']}</span>
            <br><span style="color: #6b7280; font-size: 0.8rem;">Risk Level</span>
            <span class="info-badge">ℹ
                <div class="tooltip-popup">
                    <div class="tooltip-title">Overall Risk Assessment</div>
                    Combines Fear & Greed, Volatility, and Drawdown into one assessment. MODERATE (green) = favorable conditions for accumulation. ELEVATED (yellow) = proceed with caution, consider smaller position sizes. HIGH (red) = significant risk environment, consider pausing new purchases until conditions improve.
                </div>
            </span>
        </div>""", unsafe_allow_html=True)

    # Week Ahead
    week_events = get_week_ahead()
    if week_events:
        st.markdown("### 📅 Week Ahead")
        for e in week_events[:4]:
            impact_color = "#EF4444" if e["impact"] == "VERY HIGH" else "#F59E0B" if e["impact"] == "HIGH" else "#3B82F6"
            st.markdown(f"""<div class="signal-card" style="border-left-color: {impact_color};">
                <span style="background: {impact_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 700;">{e['timing']}</span>
                <span style="color: #6b7280; font-size: 0.8rem; margin-left: 6px;">{e['category']}</span>
                <br><strong style="color: #e0e0e0; font-size: 0.95rem;">{e['event']}</strong>
                <br><span style="color: #9ca3af; font-size: 0.85rem;">{e['description'][:200]}</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    
    st.markdown("### 📋 Recent Tweets")
    if tweets:
        df_data = [{"Date": t.get("created_at", "")[:19], "Author": f"@{t.get('author_username', '')}", "Company": t.get("company", ""), "Tweet": t.get("tweet_text", "")[:100] + "...", "Signal": "🚨" if t.get("is_signal") else "", "Score": t.get("confidence_score", 0)} for t in tweets[:50]]
        st.dataframe(pd.DataFrame(df_data), use_container_width=True, height=400, column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})

    st.markdown("---")
    if st.button("📄 Download Board Report (PDF)"):
        try:
            from pdf_report import generate_board_report
            pdf_buffer = generate_board_report(_current_user, btc_price)
            if pdf_buffer:
                _company = _current_user.get("company_name", "Report").replace(" ", "_")
                st.download_button(
                    label="⬇️ Download PDF",
                    data=pdf_buffer,
                    file_name=f"Treasury_Intelligence_{_company}_{datetime.now().strftime('%Y%m%d')}.pdf",
                    mime="application/pdf",
                )
        except Exception as e:
            st.error(f"PDF generation error: {e}")

# ============================================
# PAGE: BTC LEADERBOARD
# ============================================
elif page == "🏆 BTC Leaderboard":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">🏆 BTC Treasury Leaderboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Every publicly traded company holding Bitcoin on their balance sheet</p>', unsafe_allow_html=True)
    
    companies, summary = get_leaderboard_with_live_price(btc_price)

    # Show data provenance badge
    _prov_data = None
    try:
        _ft = FreshnessTracker()
        _prov_data = _ft.load_from_supabase(supabase)
    except Exception:
        pass

    if _prov_data and _prov_data.get("provenance"):
        _corp_prov = _prov_data["provenance"].get("leaderboard_corporate", {})
        _sov_prov = _prov_data["provenance"].get("leaderboard_sovereign", {})
        _corp_type = _corp_prov.get("source_type", "unknown") if _corp_prov else "unknown"
        _sov_type = _sov_prov.get("source_type", "unknown") if _sov_prov else "unknown"
        _corp_name = _corp_prov.get("source_name", "Unknown") if _corp_prov else "Unknown"
        _sov_name = _sov_prov.get("source_name", "Unknown") if _sov_prov else "Unknown"

        _badge_colors = {"live": ("#10B981", "rgba(16,185,129,0.1)"), "cached": ("#F59E0B", "rgba(245,158,11,0.1)"), "fallback": ("#EF4444", "rgba(239,68,68,0.1)")}
        _corp_c, _corp_bg = _badge_colors.get(_corp_type, ("#6B7280", "rgba(107,114,128,0.1)"))
        _sov_c, _sov_bg = _badge_colors.get(_sov_type, ("#6B7280", "rgba(107,114,128,0.1)"))
        _corp_icon = {"live": "🟢", "cached": "🟡", "fallback": "🔴"}.get(_corp_type, "⚪")
        _sov_icon = {"live": "🟢", "cached": "🟡", "fallback": "🔴"}.get(_sov_type, "⚪")

        st.markdown(f"""<div style="display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap;">
            <span style="background: {_corp_bg}; color: {_corp_c}; padding: 4px 12px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid {_corp_c}30;">
                {_corp_icon} CORPORATE: {_corp_type.upper()} — {_corp_name}
            </span>
            <span style="background: {_sov_bg}; color: {_sov_c}; padding: 4px 12px; border-radius: 6px; font-size: 11px; font-weight: 700; border: 1px solid {_sov_c}30;">
                {_sov_icon} SOVEREIGN: {_sov_type.upper()} — {_sov_name}
            </span>
        </div>""", unsafe_allow_html=True)
    
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Companies", summary["total_companies"])
    with c2:
        st.metric("Total BTC Held", f"{summary['total_btc']:,}")
    with c3:
        st.metric("Total Value", f"${summary['total_value_b']:.1f}B")
    with c4:
        st.metric("BTC Price", f"${btc_price:,.0f}")
    
    st.markdown("---")
    
    # Top 10 Bar Chart
    st.markdown("### Top 10 Bitcoin Holders (Corporate + Sovereign)")
    top10 = [c for c in companies if c["btc_holdings"] > 0][:10]
    
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=[c["company"].replace(" (MicroStrategy)", "").replace(" Digital (MARA)", "").replace(" Platforms", "").replace(" Global", "").replace(" (Square)", "").replace(" Mining", "") for c in top10],
        y=[c["btc_holdings"] for c in top10],
        marker_color=["#E67E22" if c["rank"] == 1 else "#F39C12" if c["rank"] <= 3 else "#3498DB" for c in top10],
        text=[f'{c["btc_holdings"]:,}' for c in top10],
        textposition="outside",
        textfont=dict(color="white", size=11),
    ))
    fig.update_layout(
        template="plotly_dark",
        height=450,
        yaxis_title="BTC Holdings",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Value chart (in billions)
    st.markdown("### Treasury Value ($B)")
    top10_value = [c for c in companies if c["btc_value_b"] > 0][:10]
    
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=[c["company"].replace(" (MicroStrategy)", "").replace(" Digital (MARA)", "").replace(" Platforms", "").replace(" Global", "").replace(" (Square)", "").replace(" Mining", "") for c in top10_value],
        y=[c["btc_value_b"] for c in top10_value],
        marker_color=["#2ECC71" if c.get("unrealized_pnl_pct", 0) > 0 else "#E74C3C" if c.get("unrealized_pnl_pct", 0) < 0 else "#3498DB" for c in top10_value],
        text=[f'${c["btc_value_b"]:.2f}B' for c in top10_value],
        textposition="outside",
        textfont=dict(color="white", size=11),
    ))
    fig2.update_layout(
        template="plotly_dark",
        height=400,
        yaxis_title="Value (Billions USD)",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.caption("🟢 Unrealized profit | 🔴 Unrealized loss | 🔵 Cost basis unknown")
    
    st.markdown("---")
    
    # Full table
    st.markdown("### Full Leaderboard")
    st.markdown(f"*{summary.get('corporate_count', 0)} companies + {summary.get('sovereign_count', 0)} governments · Source: [CoinGecko](https://www.coingecko.com/en/public-companies-bitcoin) + [BitcoinTreasuries.net](https://bitcointreasuries.net)*")
    df_data = []
    for c in companies:
        if c["btc_holdings"] > 0:
            pnl_str = f"{c['unrealized_pnl_pct']:+.1f}%" if c.get("unrealized_pnl_pct") else "N/A"
            entity_type = "🏛️ Gov" if c.get("is_government") else "🏢 Corp"
            df_data.append({
                "Rank": c["rank"],
                "Entity": c["company"],
                "Type": entity_type,
                "Ticker": c.get("ticker", ""),
                "BTC Holdings": c["btc_holdings"],
                "Value ($B)": c["btc_value_b"],
                "P&L": pnl_str,
                "Country": c.get("country", "N/A"),
                "Sector": c.get("sector", "N/A"),
            })
    
    df = pd.DataFrame(df_data)
    st.dataframe(df, use_container_width=True, height=500, column_config={
        "BTC Holdings": st.column_config.NumberColumn("BTC Holdings", format="%d"),
    })
    
    st.markdown("---")
    
    # Dominance pie chart
    st.markdown("### Market Share — Corporate vs Sovereign")
    
    corporate_btc = summary.get("total_corporate_btc", 0)
    sovereign_btc = summary.get("total_sovereign_btc", 0)
    
    col_pie1, col_pie2 = st.columns(2)
    
    with col_pie1:
        st.markdown("**By Type**")
        fig_type = go.Figure(go.Pie(
            labels=["Corporate", "Sovereign/Gov"],
            values=[corporate_btc, sovereign_btc],
            marker=dict(colors=["#E67E22", "#3B82F6"]),
            textinfo="label+percent",
            hole=0.4,
        ))
        fig_type.update_layout(template="plotly_dark", height=350, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig_type, use_container_width=True)
    
    with col_pie2:
        st.markdown("**Top Holders**")
        top5 = [c for c in companies if c["btc_holdings"] > 0][:5]
        others_btc = summary["total_btc"] - sum(c["btc_holdings"] for c in top5)

        labels = [c["company"].replace(" (MicroStrategy)", "")[:20] for c in top5] + ["Others"]
        values = [c["btc_holdings"] for c in top5] + [others_btc]
        colors = ["#E67E22", "#F39C12", "#3498DB", "#2ECC71", "#9B59B6", "#7F8C8D"]

    
    fig3 = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors),
        textinfo="label+percent",
        hole=0.4,
    ))
    fig3.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig3, use_container_width=True)

# ============================================
# PAGE: RECENT PURCHASES
# ============================================
elif page == "💰 Recent Purchases":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">💰 Recent BTC Purchases</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Confirmed Bitcoin purchases by treasury companies</p>', unsafe_allow_html=True)

    # Provenance badge for purchases
    _prov_purch = None
    try:
        _ft_purch = FreshnessTracker()
        _prov_purch = _ft_purch.load_from_supabase(supabase)
    except Exception:
        pass
    if _prov_purch and _prov_purch.get("sources"):
        _news_src = next((s for s in _prov_purch["sources"] if s.get("source") == "google_news_purchases"), None)
        if _news_src and _news_src.get("status") != "unknown":
            _s = _news_src["status"]
            _c_map = {"live": "#10B981", "stale": "#F59E0B", "unavailable": "#EF4444"}
            _bg_map = {"live": "rgba(16,185,129,0.08)", "stale": "rgba(245,158,11,0.08)", "unavailable": "rgba(239,68,68,0.08)"}
            _c = _c_map.get(_s, "#6B7280")
            _bg = _bg_map.get(_s, "rgba(107,114,128,0.08)")
            st.markdown(f'<div style="margin-bottom:12px;"><span style="background:{_bg};color:{_c};padding:3px 10px;border-radius:5px;font-size:10px;font-weight:700;border:1px solid {_c}25;">{_news_src.get("emoji", "⚪")} News Scanner: {_news_src.get("age_text", "?")}</span> <span style="background:rgba(16,185,129,0.08);color:#10B981;padding:3px 10px;border-radius:5px;font-size:10px;font-weight:700;border:1px solid #10B98125;">🟢 Database: LIVE</span></div>', unsafe_allow_html=True)

    stats = get_purchase_stats()

    # Load leaderboard summary for this page
    _lb_companies, _lb_summary = get_leaderboard_with_live_price(btc_price)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Companies", _lb_summary.get("corporate_count", _lb_summary["total_companies"]))
    with c2:
        st.metric("Governments", _lb_summary.get("sovereign_count", 0))
    with c3:
        st.metric("Total BTC Held", f"{_lb_summary['total_btc']:,}")
    with c4:
        st.metric("Total Value", f"${_lb_summary['total_value_b']:.1f}B")
    with c5:
        st.metric("BTC Price", f"${btc_price:,.0f}")

    st.markdown("---")

    # Monthly purchase chart
    st.markdown("### Monthly BTC Purchases")
    months = list(reversed(list(stats["by_month"].keys())))
    month_btc = [stats["by_month"][m]["btc"] for m in months]
    month_usd = [stats["by_month"][m]["usd"] / 1_000_000_000 for m in months]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=months, y=month_btc,
        marker_color="#E67E22",
        text=[f"{b:,}" for b in month_btc],
        textposition="outside",
        textfont=dict(color="white", size=11),
        name="BTC Purchased",
    ))
    fig.update_layout(
        template="plotly_dark",
        height=400,
        yaxis_title="BTC Purchased",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Purchases by company
    st.markdown("### Purchases by Company")
    company_names = [c["company"].replace(" (MicroStrategy)", "") for c in stats["by_company"]]
    company_btc = [c["total_btc"] for c in stats["by_company"]]

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=company_names, y=company_btc,
        marker_color=["#E67E22" if i == 0 else "#F39C12" if i <= 2 else "#3498DB" for i in range(len(company_names))],
        text=[f"{b:,}" for b in company_btc],
        textposition="outside",
        textfont=dict(color="white", size=11),
    ))
    fig2.update_layout(
        template="plotly_dark",
        height=400,
        yaxis_title="Total BTC Purchased",
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.markdown("---")

    # Purchase feed
    st.markdown("### All Confirmed Purchases")
    purchases = get_recent_purchases(20)

    for p in purchases:
        usd_m = p["usd_amount"] / 1_000_000
        if usd_m >= 1000:
            size_color = "#E74C3C"
            size_label = "MEGA"
        elif usd_m >= 500:
            size_color = "#F39C12"
            size_label = "LARGE"
        elif usd_m >= 100:
            size_color = "#F1C40F"
            size_label = "MEDIUM"
        else:
            size_color = "#3498DB"
            size_label = "SMALL"

        company_short = p["company"].replace(" (MicroStrategy)", "")
        # Escape HTML characters in data fields to prevent broken rendering
        import html as _html_mod
        _source_safe = _html_mod.escape(str(p.get("source", "") or ""))[:120]
        _notes_safe = _html_mod.escape(str(p.get("notes", "") or ""))[:200]
        notes_html = f'<br><span style="color: #7F8C8D; font-size: 0.8em;">📝 {_notes_safe}</span>' if _notes_safe else ""

        st.markdown(f"""<div class="signal-card" style="border-left-color: {size_color};"><span style="background: {size_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700;">{size_label}</span> <strong style="color: #ECF0F1; margin-left: 8px;">{_html_mod.escape(company_short)}</strong> <span style="color: #7F8C8D;">({_html_mod.escape(p['ticker'])})</span><br><span style="color: #E67E22; font-size: 1.1em; font-weight: 700;">₿ {p['btc_amount']:,} BTC</span> <span style="color: #BDC3C7;"> — ${usd_m:,.0f}M at ${p['price_per_btc']:,.0f}/BTC</span><br><span style="color: #7F8C8D; font-size: 0.85em;">📅 {p['filing_date']} | 📄 {_source_safe}</span>{notes_html}</div>""", unsafe_allow_html=True)
        st.markdown("")

# ============================================
# PAGE: REGULATORY TRACKER
# ============================================
# ============================================
# PAGE: REGULATORY TRACKER
# ============================================
elif page == "🏛️ Regulatory Tracker":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">🏛️ Global Regulatory Tracker</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Legislative and regulatory developments affecting Bitcoin worldwide</p>', unsafe_allow_html=True)

    # Provenance badges
    _prov_reg = None
    try:
        _ft_reg = FreshnessTracker()
        _prov_reg = _ft_reg.load_from_supabase(supabase)
    except Exception:
        pass
    if _prov_reg and _prov_reg.get("provenance"):
        _reg_prov = _prov_reg["provenance"].get("regulatory", {})
        _stmt_prov = _prov_reg["provenance"].get("statements", {})
        _badges_reg = ""
        for prov, label in [(_reg_prov, "Regulatory"), (_stmt_prov, "Statements")]:
            if prov:
                ptype = prov.get("source_type", "unknown")
                pname = prov.get("source_name", "Unknown")
                _c_map = {"live": "#10B981", "cached": "#F59E0B", "fallback": "#EF4444"}
                _bg_map = {"live": "rgba(16,185,129,0.08)", "cached": "rgba(245,158,11,0.08)", "fallback": "rgba(239,68,68,0.08)"}
                _i_map = {"live": "🟢", "cached": "🟡", "fallback": "🔴"}
                _c = _c_map.get(ptype, "#6B7280")
                _bg = _bg_map.get(ptype, "rgba(107,114,128,0.08)")
                _i = _i_map.get(ptype, "⚪")
                _badges_reg += f'<span style="background:{_bg};color:{_c};padding:3px 10px;border-radius:5px;font-size:10px;font-weight:700;border:1px solid {_c}25;margin-right:8px;">{_i} {label}: {ptype.upper()}</span>'
        if _badges_reg:
            st.markdown(f'<div style="margin-bottom:12px;display:flex;flex-wrap:wrap;gap:4px;">{_badges_reg}</div>', unsafe_allow_html=True)

    from regulatory_tracker import get_all_statements_combined, get_all_items_combined

    reg_stats = get_reg_stats()

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total Items", reg_stats["total_items"])
    with c2:
        st.metric("Regions Tracked", reg_stats["regions_tracked"])
    with c3:
        st.metric("Active / Passed", reg_stats["active_passed"])
    with c4:
        st.metric("Pending", reg_stats["pending"])
    with c5:
        st.metric("Notable Statements", reg_stats["total_statements"])

    st.markdown("---")

    # Regional overview chart
    st.markdown("### Regulatory Items by Region")
    regions = ["US Federal", "US State", "Europe", "Asia-Pacific", "Latin America", "Middle East & Africa"]
    region_counts = [reg_stats.get("us_federal", 0), reg_stats.get("us_state", 0), reg_stats.get("europe", 0), reg_stats.get("asia_pacific", 0), reg_stats.get("latin_america", 0), reg_stats.get("middle_east_africa", 0)]
    region_colors = ["#E67E22", "#F39C12", "#3498DB", "#2ECC71", "#9B59B6", "#E74C3C"]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=regions, y=region_counts,
        marker_color=region_colors,
        text=region_counts,
        textposition="outside",
        textfont=dict(color="white", size=14),
    ))
    fig.update_layout(template="plotly_dark", height=350, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Items Tracked")
    st.plotly_chart(fig, use_container_width=True)

    # Sentiment pie chart
    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### Regulatory Sentiment")
        fig2 = go.Figure(go.Pie(
            labels=["Bullish", "Pending/Neutral", "Bearish"],
            values=[reg_stats["bullish"], reg_stats["pending"], reg_stats.get("failed", 0)],
            marker=dict(colors=["#2ECC71", "#F1C40F", "#E74C3C"]),
            hole=0.4,
        ))
        fig2.update_layout(template="plotly_dark", height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig2, use_container_width=True)

    with col_right:
        st.markdown("### Statement Sentiment")
        fig3 = go.Figure(go.Pie(
            labels=["Bullish", "Bearish"],
            values=[reg_stats["bullish_statements"], reg_stats["bearish_statements"]],
            marker=dict(colors=["#2ECC71", "#E74C3C"]),
            hole=0.4,
        ))
        fig3.update_layout(template="plotly_dark", height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # Notable Statements
    st.markdown("### 📣 Notable Statements from World Leaders & CEOs")

    statements = get_all_statements_combined()
    for s in statements:
        if "EXTREMELY" in s["impact"]:
            s_color = "#E74C3C"
        elif "VERY" in s["impact"]:
            s_color = "#F39C12"
        elif "BULLISH" in s["impact"]:
            s_color = "#2ECC71"
        elif "BEARISH" in s["impact"]:
            s_color = "#E74C3C"
        else:
            s_color = "#7F8C8D"

        cat_emoji = "🏛️" if s["category"] == "Government" else "💼"

        st.markdown(f"""<div class="feature-box">
            <p style="color: #7F8C8D; font-size: 0.8rem; margin: 0;">{cat_emoji} {s['category']} | {s['date']}</p>
            <p class="feature-title">{s['person']} — {s['title']}</p>
            <p style="color: #BDC3C7; font-size: 0.9rem; font-style: italic; margin: 5px 0;">"{s['statement']}"</p>
            <p style="color: {s_color}; font-size: 0.85rem; margin: 5px 0;"><strong>Impact:</strong> {s['impact']}</p>
        </div>""", unsafe_allow_html=True)
        st.markdown("")

    st.markdown("---")

    # Regulatory items by region
    all_combined = get_all_items_combined()

    region_display = [
        ("🇺🇸 US Federal", "US Federal"),
        ("🏛️ US State-Level", "US State"),
        ("🇪🇺 Europe & UK", "Europe"),
        ("🌏 Asia-Pacific", "Asia-Pacific"),
        ("🌎 Latin America", "Latin America"),
        ("🌍 Middle East & Africa", "Middle East & Africa"),
        ("🌐 Global / Other", "Global"),
    ]

    for display_name, category_key in region_display:
        items = [r for r in all_combined if r.get("category") == category_key]
        if items:
            st.markdown(f"### {display_name}")
            for item in items:
                status_emoji = "✅" if item["status_color"] == "green" else "🟡" if item["status_color"] == "yellow" else "❌"
                impact_color = "#E74C3C" if "EXTREMELY" in item["btc_impact"] or "VERY" in item["btc_impact"] else "#F39C12" if "BULLISH" in item["btc_impact"] else "#7F8C8D"

                st.markdown(f"""<div class="feature-box">
                    <p class="feature-title">{status_emoji} {item['title']}</p>
                    <p style="color: #BDC3C7; font-size: 0.9rem; margin: 5px 0;"><strong>Status:</strong> {item['status']} | <strong>Type:</strong> {item['type']} | <strong>Updated:</strong> {item['date_updated']}</p>
                    <p style="color: #BDC3C7; font-size: 0.9rem; margin: 5px 0;">{item['summary']}</p>
                    <p style="color: {impact_color}; font-size: 0.85rem; margin: 5px 0;"><strong>BTC Impact:</strong> {item['btc_impact']} — {item['impact']}</p>
                </div>""", unsafe_allow_html=True)
                st.markdown("")
            st.markdown("---")


# ============================================
# PAGE: ACCURACY
# ============================================
elif page == "📈 Accuracy":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">📈 Accuracy Tracking</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Transparent, verifiable prediction accuracy</p>', unsafe_allow_html=True)
    
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Confirmed Purchases", accuracy["total"])
    with c2:
        st.metric("Predicted in Advance", accuracy["predicted"])
    with c3:
        st.metric("Hit Rate", f"{accuracy['hit_rate']}%")
    
    st.markdown("---")
    
    if accuracy["total"] > 0:
        st.markdown("### Purchase History")
        try:
            purchases = supabase.table("confirmed_purchases").select("*").order("filing_date", desc=True).execute()
            if purchases.data:
                df = pd.DataFrame([{
                    "Date": p["filing_date"],
                    "Company": p["company"],
                    "BTC": p.get("btc_amount", 0),
                    "USD": f"${p.get('usd_amount', 0):,.0f}",
                    "Predicted?": "✅ Yes" if p.get("was_predicted") else "❌ No",
                    "Lead Time": f"{p.get('prediction_lead_time_hours', 0):.0f}h" if p.get("was_predicted") else "-",
                } for p in purchases.data])
                st.dataframe(df, use_container_width=True)
        except Exception as e:
            logger.error(f"Failed to load purchase history for accuracy page: {e}")
    else:
        st.info("Accuracy data will populate as the system runs and matches predictions against confirmed purchases. Check back after a few days of operation.")
        
        st.markdown("### How Accuracy Tracking Works")
        st.markdown("""
        1. **Signal Detected** → Our system logs a prediction with timestamp and confidence score
        2. **Purchase Confirmed** → When an 8-K filing confirms a BTC purchase, we log it
        3. **Match & Verify** → If a prediction came within 72 hours before the purchase, it's marked as correct
        4. **Public Stats** → Hit rate, accuracy %, and average lead time are calculated and displayed here
        
        This is fully transparent — every prediction and every purchase is logged with timestamps.
        """)

# ============================================
# PAGE: MY COMPANY
# ============================================
elif page == "🏢 My Company":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">🏢 My Company Profile</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Your personalized treasury intelligence hub</p>', unsafe_allow_html=True)

    from subscriber_manager import subscribers as sub_mgr

    # Use authenticated user profile directly
    profile = _current_user
    p_name = profile.get("name", "")
    p_company = profile.get("company_name", "")
    p_ticker = profile.get("ticker", "")
    p_btc = float(profile.get("btc_holdings", 0))
    p_avg_price = float(profile.get("avg_purchase_price", 0))
    p_total_cost = float(profile.get("total_invested_usd", 0))

    # Header with company info
    st.markdown(f"""<div class="feature-box" style="border-left: 3px solid #E67E22;">
        <span style="color: #E67E22; font-size: 1.2rem; font-weight: 700;">{p_company}</span>
        {f'<span style="color: #6b7280; margin-left: 8px;">({p_ticker})</span>' if p_ticker else ''}
        <br><span style="color: #9ca3af; font-size: 0.9rem;">Welcome back, {p_name}</span>
        {f'<span style="color: #4b5563; margin-left: 8px;"> · {profile.get("role", "")}</span>' if profile.get("role") else ''}
    </div>""", unsafe_allow_html=True)

    st.markdown("")

    # Position metrics
    if p_btc > 0:
        btc_value = p_btc * btc_price
        btc_value_m = btc_value / 1_000_000

        position = sub_mgr.get_leaderboard_position(profile["email"], btc_price)

        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Your BTC Holdings", f"{p_btc:,.0f}")
        with c2:
            st.metric("Current Value", f"${btc_value_m:,.1f}M")
        with c3:
            if p_total_cost > 0:
                pnl = btc_value - p_total_cost
                pnl_pct = (pnl / p_total_cost) * 100
                st.metric("Unrealized P&L", f"{pnl_pct:+.1f}%", delta=f"${pnl/1_000_000:+,.1f}M")
            else:
                st.metric("Avg Price", f"${p_avg_price:,.0f}" if p_avg_price > 0 else "—")
        with c4:
            if position:
                st.metric("Leaderboard Rank", f"#{position['rank']}", delta=f"of {position['total_companies']}")
            else:
                st.metric("Leaderboard Rank", "—")

        st.markdown("---")

        # Leaderboard context
        if position:
            st.markdown("### 📍 Your Position on the Leaderboard")

            # Show closest competitors
            closest = position.get("closest_competitors", [])
            if closest:
                for c in closest:
                    c_btc = c.get("btc_holdings", 0)
                    is_you = (p_ticker and c.get("ticker", "") == p_ticker) or abs(c_btc - p_btc) < 1
                    c_name = c.get("company", "")[:35]
                    c_rank = c.get("rank", "?")

                    if is_you:
                        st.markdown(f"""<div class="signal-card" style="border-left-color: #E67E22; background: linear-gradient(135deg, #1a0f00 0%, #111827 100%);">
                            <strong style="color: #E67E22;">#{c_rank} {c_name} (YOU)</strong>
                            <span style="color: #f0f0f0; float: right; font-family: 'JetBrains Mono', monospace;">{c_btc:,} BTC</span>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div class="signal-card" style="border-left-color: #1e2a3a;">
                            <span style="color: #9ca3af;">#{c_rank}</span>
                            <strong style="color: #d1d5db; margin-left: 8px;">{c_name}</strong>
                            <span style="color: #6b7280; float: right; font-family: 'JetBrains Mono', monospace;">{c_btc:,} BTC</span>
                        </div>""", unsafe_allow_html=True)

            st.markdown("")

            # Gap to next rank
            gap = position.get("next_rank_gap", 0)
            if gap > 0 and position["rank"] > 1:
                gap_cost = gap * btc_price
                st.markdown(f"""<div class="proof-bar">
                    <span style="color: #E67E22; font-size: 1.1rem; font-weight: 700;">🎯 Buy {gap:,.0f} BTC (${gap_cost/1_000_000:,.1f}M) to move to #{position['rank']-1}</span>
                </div>""", unsafe_allow_html=True)

        st.markdown("---")

    else:
        st.info(f"Add your BTC holdings below to see your leaderboard position, P&L, and personalized insights.")
        st.markdown("---")

    # ============================================
    # WATCHLIST SECTION
    # ============================================
    st.markdown("### 👁️ Your Watchlist")
    st.markdown("Track specific companies and get priority alerts when they make moves.")

    from watchlist_manager import get_watchlist_activity, TRACKABLE_COMPANIES, format_watchlist_telegram

    current_watchlist = profile.get("watchlist", [])
    if isinstance(current_watchlist, str):
        try:
            import json as _json
            current_watchlist = _json.loads(current_watchlist)
        except Exception:
            current_watchlist = []

    if current_watchlist:
        # Show current watchlist with activity
        st.markdown(f"**Tracking {len(current_watchlist)} companies:** {', '.join(current_watchlist)}")
        st.markdown("")

        # Get watchlist activity
        try:
            from purchase_tracker import get_recent_purchases as _get_purchases
            from email_briefing import get_recent_signals as _get_signals
            _w_purchases = _get_purchases(20)
            _w_signals = _get_signals(hours=48)
            _w_companies, _ = get_leaderboard_with_live_price(btc_price)

            w_activity = get_watchlist_activity(
                watchlist=current_watchlist,
                signals=_w_signals,
                purchases=_w_purchases,
                leaderboard=_w_companies,
            )

            if w_activity:
                high_activity = [a for a in w_activity if a["priority"] in ("high", "medium")]
                info_activity = [a for a in w_activity if a["priority"] == "info"]

                if high_activity:
                    st.markdown("#### Recent Activity")
                    for a in high_activity[:8]:
                        priority_color = {"high": "#EF4444", "medium": "#F59E0B"}[a["priority"]]
                        st.markdown(f"""<div class="signal-card" style="border-left-color: {priority_color};">
                            <span style="font-size: 14px;">{a['icon']}</span>
                            <strong style="color: #d1d5db; margin-left: 4px;">{a['company'][:30]}</strong>
                            <span style="color: #4b5563;"> ({a['ticker']})</span>
                            <span style="background: {priority_color}20; color: {priority_color}; padding: 1px 6px; border-radius: 3px; font-size: 9px; font-weight: 700; margin-left: 8px; text-transform: uppercase;">{a['priority']}</span>
                            <br><span style="color: #9ca3af; font-size: 0.9rem;">{a['headline']}</span>
                            {'<br><span style="color: #6b7280; font-size: 0.85rem;">' + a["detail"][:100] + '</span>' if a.get("detail") and a["type"] != "holding" else ""}
                        </div>""", unsafe_allow_html=True)
                else:
                    st.markdown("_No notable activity from your watched companies in the last 48 hours._")

                if info_activity:
                    with st.expander(f"Current holdings of watched companies ({len(info_activity)})"):
                        for a in info_activity:
                            st.markdown(f"**{a['company']}** ({a['ticker']}): {a['detail']}")
        except Exception as _e:
            st.markdown(f"_Could not load watchlist activity: {_e}_")

        st.markdown("")

    # Add/remove companies
    with st.expander("Edit Watchlist"):
        available = [c for c in TRACKABLE_COMPANIES if c["ticker"] not in current_watchlist]

        # Add
        if available:
            add_options = [f"{c['ticker']} — {c['name']} ({c['category']})" for c in available]
            selected_add = st.multiselect("Add companies to watchlist:", add_options, key="watchlist_add")

            if st.button("➕ Add Selected") and selected_add:
                new_tickers = [opt.split(" — ")[0] for opt in selected_add]
                updated = current_watchlist + new_tickers
                sub_mgr.update_watchlist(profile["email"], updated)
                login_user(sub_mgr.get_by_email(profile["email"]))
                st.success(f"Added {', '.join(new_tickers)} to watchlist!")
                st.rerun()

        # Remove
        if current_watchlist:
            st.markdown("---")
            remove_options = current_watchlist
            selected_remove = st.multiselect("Remove from watchlist:", remove_options, key="watchlist_remove")

            if st.button("🗑️ Remove Selected") and selected_remove:
                updated = [t for t in current_watchlist if t not in selected_remove]
                sub_mgr.update_watchlist(profile["email"], updated)
                login_user(sub_mgr.get_by_email(profile["email"]))
                st.success(f"Removed {', '.join(selected_remove)} from watchlist!")
                st.rerun()

        # Custom ticker
        st.markdown("---")
        custom_ticker = st.text_input("Add a custom ticker (not in the list above):", placeholder="e.g., HOOD", key="custom_ticker")
        if st.button("➕ Add Custom Ticker") and custom_ticker:
            updated = current_watchlist + [custom_ticker.upper().strip()]
            sub_mgr.update_watchlist(profile["email"], updated)
            login_user(sub_mgr.get_by_email(profile["email"]))
            st.success(f"Added {custom_ticker.upper()} to watchlist!")
            st.rerun()

    st.markdown("---")

    # PDF Board Report
    st.markdown("### 📄 Board Report")
    st.markdown("Generate a professional PDF report to share with your board of directors.")
    if st.button("📄 Generate Board Report PDF", type="primary"):
        try:
            from pdf_report import generate_board_report
            pdf_buffer = generate_board_report(profile, btc_price)
            if pdf_buffer:
                report_filename = f"Treasury_Intelligence_{p_company.replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
                st.download_button(
                    label="⬇️ Download PDF Report",
                    data=pdf_buffer,
                    file_name=report_filename,
                    mime="application/pdf",
                )
                st.success("Report generated! Click the download button above.")
            else:
                st.error("Failed to generate report.")
        except Exception as e:
            st.error(f"Report generation error: {e}")

    st.markdown("---")

    # Edit profile section
    st.markdown("### ⚙️ Update Profile")
    with st.expander("Edit company details and holdings"):
        e1, e2 = st.columns(2)
        with e1:
            edit_btc = st.number_input("BTC Holdings", value=p_btc, min_value=0.0, step=1.0, key="edit_btc")
            edit_avg = st.number_input("Avg Purchase Price ($)", value=p_avg_price, min_value=0.0, step=100.0, key="edit_avg")
        with e2:
            edit_cost = st.number_input("Total Invested ($)", value=p_total_cost, min_value=0.0, step=10000.0, key="edit_cost")
            edit_sector = st.text_input("Sector", value=profile.get("sector", ""), key="edit_sector")

        if st.button("💾 Save Changes"):
            sub_mgr.update_holdings(profile["email"], edit_btc, edit_avg, edit_cost)
            if edit_sector != profile.get("sector", ""):
                sub_mgr.update_profile(profile["email"], sector=edit_sector)
            updated_profile = sub_mgr.get_by_email(profile["email"])
            login_user(updated_profile)
            st.success("Profile updated!")
            st.rerun()

# ============================================
# PAGE: WHAT-IF CALCULATOR (PROTECTED)
# ============================================
elif page == "📐 What-If Calculator":
    if not _current_user:
        show_login_page()
        st.stop()

    st.markdown('<p class="main-header">📐 What-If Scenario Calculator</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Model a hypothetical BTC purchase and see the impact on your position</p>', unsafe_allow_html=True)

    from scenario_calculator import calculate_scenario
    from subscriber_manager import subscribers as sub_mgr

    # Use authenticated user profile
    profile = _current_user

    # Scenario inputs
    st.markdown("### 🎯 Model Your Purchase")

    col_input1, col_input2 = st.columns(2)
    with col_input1:
        btc_to_buy = st.number_input(
            "BTC to Buy",
            min_value=1.0, max_value=100000.0, value=100.0, step=10.0,
            help="How many Bitcoin would you purchase?"
        )
    with col_input2:
        buy_price = st.number_input(
            "Purchase Price ($/BTC)",
            min_value=1000.0, max_value=1000000.0, value=float(btc_price), step=1000.0,
            help="Price per Bitcoin for this hypothetical purchase"
        )

    purchase_cost = btc_to_buy * buy_price

    st.markdown(f"""<div class="proof-bar">
        <span style="color: #E67E22; font-size: 1rem;">
            Scenario: Buy <strong>{btc_to_buy:,.0f} BTC</strong> at <strong>${buy_price:,.0f}</strong>/BTC
            = <strong>${purchase_cost/1_000_000:,.1f}M</strong> total cost
        </span>
    </div>""", unsafe_allow_html=True)

    if st.button("🔮 Calculate Scenario", type="primary"):
        companies, summary = get_leaderboard_with_live_price(btc_price)

        result = calculate_scenario(
            subscriber_email=profile.get("email", ""),
            btc_to_buy=btc_to_buy,
            buy_price=buy_price,
            current_btc_price=btc_price,
            leaderboard_companies=companies,
            subscriber_profile=profile,
        )

        if result:
            st.markdown("---")

            # Before vs After comparison
            st.markdown("### 📊 Before vs After")

            col_b, col_arrow, col_a = st.columns([5, 1, 5])

            with col_b:
                st.markdown(f"""<div class="feature-box">
                    <p style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">BEFORE</p>
                    <p style="color: #f0f0f0; font-size: 2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; margin: 8px 0;">{result['before']['btc_holdings']:,.0f} <span style="color: #6b7280; font-size: 0.9rem;">BTC</span></p>
                    <p style="color: #9ca3af; font-size: 0.9rem;">Value: ${result['before']['value_m']:,.1f}M</p>
                    <p style="color: #9ca3af; font-size: 0.9rem;">Rank: <strong style="color: #f0f0f0;">#{result['before']['rank']}</strong> of {result['total_companies']}</p>
                    {'<p style="color: ' + ('#10B981' if result['before']['pnl_pct'] >= 0 else '#EF4444') + '; font-size: 0.9rem;">P&L: ' + f"{result['before']['pnl_pct']:+.1f}%" + '</p>' if result['before']['total_cost'] > 0 else ''}
                </div>""", unsafe_allow_html=True)

            with col_arrow:
                st.markdown(f"""<div style="text-align: center; padding-top: 60px;">
                    <span style="color: #E67E22; font-size: 2rem;">→</span>
                </div>""", unsafe_allow_html=True)

            with col_a:
                rank_color = "#10B981" if result['ranks_gained'] > 0 else "#f0f0f0"
                st.markdown(f"""<div class="feature-box" style="border: 1px solid #E67E2240;">
                    <p style="color: #E67E22; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em;">AFTER PURCHASE</p>
                    <p style="color: #f0f0f0; font-size: 2rem; font-weight: 800; font-family: 'JetBrains Mono', monospace; margin: 8px 0;">{result['after']['btc_holdings']:,.0f} <span style="color: #6b7280; font-size: 0.9rem;">BTC</span></p>
                    <p style="color: #9ca3af; font-size: 0.9rem;">Value: ${result['after']['value_m']:,.1f}M</p>
                    <p style="color: {rank_color}; font-size: 0.9rem;">Rank: <strong>#{result['after']['rank']}</strong> of {result['total_companies']} {'<span style="color: #10B981;">(↑' + str(result['ranks_gained']) + ' ranks)</span>' if result['ranks_gained'] > 0 else ''}</p>
                    {'<p style="color: ' + ('#10B981' if result['after']['pnl_pct'] >= 0 else '#EF4444') + '; font-size: 0.9rem;">P&L: ' + f"{result['after']['pnl_pct']:+.1f}%" + '</p>' if result['after']['total_cost'] > 0 else ''}
                </div>""", unsafe_allow_html=True)

            # Key metrics row
            st.markdown("")
            m1, m2, m3, m4 = st.columns(4)
            with m1:
                st.metric("Purchase Cost", f"${result['purchase_cost_m']}M")
            with m2:
                st.metric("New Avg Price", f"${result['after']['avg_price']:,.0f}")
            with m3:
                st.metric("Break-Even Price", f"${result['break_even_price']:,.0f}")
            with m4:
                st.metric("Ranks Gained", f"+{result['ranks_gained']}" if result['ranks_gained'] > 0 else "0")

            st.markdown("---")

            # Companies overtaken
            if result['companies_overtaken']:
                st.markdown("### 🏆 Companies You'd Overtake")
                for c in result['companies_overtaken']:
                    st.markdown(f"""<div class="signal-card" style="border-left-color: #10B981;">
                        <span style="color: #10B981;">✅</span>
                        <strong style="color: #d1d5db; margin-left: 8px;">{c['company']}</strong>
                        <span style="color: #6b7280;"> ({c.get('ticker', '')})</span>
                        <span style="color: #9ca3af; float: right; font-family: 'JetBrains Mono', monospace;">{c['btc_holdings']:,} BTC</span>
                    </div>""", unsafe_allow_html=True)
                st.markdown("")

            # Still ahead
            if result['still_ahead']:
                st.markdown("### ⬆️ Still Ahead of You")
                for c in result['still_ahead']:
                    gap_cost = c['gap'] * btc_price
                    st.markdown(f"""<div class="signal-card" style="border-left-color: #F59E0B;">
                        <strong style="color: #d1d5db;">{c['company']}</strong>
                        <span style="color: #6b7280;"> ({c.get('ticker', '')})</span>
                        <span style="color: #9ca3af; float: right; font-family: 'JetBrains Mono', monospace;">{c['btc_holdings']:,} BTC</span>
                        <br><span style="color: #F59E0B; font-size: 0.85rem;">Gap: {c['gap']:,} BTC (${gap_cost/1_000_000:,.1f}M to overtake)</span>
                    </div>""", unsafe_allow_html=True)
                st.markdown("")

            # Next rank after purchase
            if result['next_rank_gap'] > 0 and result['after']['rank'] > 1:
                next_cost = result['next_rank_gap'] * btc_price
                st.markdown(f"""<div class="proof-bar">
                    <span style="color: #E67E22; font-size: 1rem;">
                        🎯 After this purchase, you'd need <strong>{result['next_rank_gap']:,} more BTC</strong>
                        (${next_cost/1_000_000:,.1f}M) to reach <strong>#{result['after']['rank'] - 1}</strong>
                    </span>
                </div>""", unsafe_allow_html=True)

            st.markdown("---")

            # P&L Projections
            st.markdown("### 📈 P&L Projections at Different BTC Prices")

            import plotly.graph_objects as go

            proj = result['projections']
            fig = go.Figure()

            colors = []
            for p in proj:
                if p['pnl_pct'] >= 0:
                    colors.append("#10B981")
                else:
                    colors.append("#EF4444")

            fig.add_trace(go.Bar(
                x=[p['label'] for p in proj],
                y=[p['pnl_pct'] for p in proj],
                marker_color=colors,
                text=[f"{p['pnl_pct']:+.1f}%" for p in proj],
                textposition="outside",
                textfont=dict(color="white", size=12),
            ))

            fig.add_hline(y=0, line_dash="dash", line_color="#4b5563", line_width=1)

            fig.update_layout(
                template="plotly_dark",
                height=400,
                yaxis_title="Return (%)",
                margin=dict(l=0, r=0, t=10, b=0),
                showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Projections table
            st.markdown("")
            for p in proj:
                pnl_color = "#10B981" if p['pnl_pct'] >= 0 else "#EF4444"
                pnl_icon = "📈" if p['pnl_pct'] >= 0 else "📉"
                is_current = "Current Price" in p['label']
                border = "border: 1px solid #E67E2240;" if is_current else ""

                st.markdown(f"""<div class="feature-box" style="padding: 12px 18px; margin: 4px 0; {border}">
                    <table width="100%"><tr>
                        <td width="35%"><span style="color: #d1d5db; font-size: 0.9rem;">{'<strong>' if is_current else ''}{p['label']}{'</strong>' if is_current else ''}</span></td>
                        <td width="20%" style="text-align: center;"><span style="color: #9ca3af; font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;">${p['btc_price']:,}</span></td>
                        <td width="25%" style="text-align: center;"><span style="color: #f0f0f0; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem;">${p['portfolio_value']/1_000_000:,.1f}M</span></td>
                        <td width="20%" style="text-align: right;"><span style="color: {pnl_color}; font-weight: 700; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem;">{pnl_icon} {p['pnl_pct']:+.1f}%</span></td>
                    </tr></table>
                </div>""", unsafe_allow_html=True)

            st.markdown("---")
            st.markdown(f"""<p style="color: #4b5563; font-size: 0.8rem; text-align: center;">
                This is a hypothetical scenario only — not financial advice.
                Based on current leaderboard data and BTC price of ${btc_price:,.0f}.
            </p>""", unsafe_allow_html=True)

        else:
            st.error("Could not calculate scenario. Check your profile data.")

# Footer
st.markdown("---")
st.markdown(f"""<div style="display: flex; justify-content: space-between; align-items: center; padding: 0 4px; flex-wrap: wrap; gap: 8px;">
    <span style="color: #4b5563; font-size: 0.8rem;"><strong style="color: #6b7280;">Treasury Signal Intelligence</strong> v3.0</span>
    <span style="color: #374151; font-size: 0.75rem;">TwitterAPI.io • Yahoo Finance • SEC EDGAR • CoinGecko • BitcoinTreasuries.net</span>
    <span style="color: #374151; font-size: 0.75rem;">Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')} • © {datetime.now().year}</span>
</div>""", unsafe_allow_html=True)
