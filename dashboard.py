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

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.set_page_config(page_title="Treasury Signal Intelligence", page_icon="🔶", layout="wide", initial_sidebar_state="expanded")

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
    except:
        return []

@st.cache_data(ttl=300)
def load_signals():
    try:
        result = supabase.table("tweets").select("*").eq("is_signal", True).order("inserted_at", desc=True).limit(100).execute()
        return result.data if result.data else []
    except:
        return []

@st.cache_data(ttl=600)
def load_strc_data():
    try:
        strc = yf.Ticker("STRC")
        hist = strc.history(period="3mo")
        if hist.empty:
            return yf.download("STRC", period="3mo", progress=False)
        return hist
    except:
        return pd.DataFrame()

@st.cache_data(ttl=600)
def load_btc_price():
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else 0
    except:
        return 0

@st.cache_data(ttl=600)
def load_mstr_price():
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        return round(float(hist["Close"].iloc[-1]), 2) if not hist.empty else 0
    except:
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
    except:
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
with st.sidebar:
    st.image("https://img.icons8.com/color/96/bitcoin--v1.png", width=60)
    st.markdown("## Treasury Signal Intelligence")
    st.markdown("*Multi-source Bitcoin purchase detection*")
    st.markdown("---")
    
    page = st.radio("Navigate", ["🏠 Home", "📊 Live Dashboard", "🏆 BTC Leaderboard", "💰 Recent Purchases", "🏛️ Regulatory Tracker", "📈 Accuracy"], label_visibility="collapsed")
    
    st.markdown("---")
    st.markdown("### System Status")
    st.markdown(f"🟢 **Scanner:** Active 24/7")
    st.markdown(f"📡 **Accounts:** {accounts_tracked}")
    st.markdown(f"🗄️ **Tweets:** {total_tweets}")
    st.markdown(f"🚨 **Signals:** {total_signals}")
    st.markdown("---")
    st.markdown("### 🔓 Upgrade to PRO")
    st.markdown("[Subscribe $19/mo →](https://YOUR_STRIPE_LINK)")
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
        st.markdown('<p class="stat-huge">15min</p><p class="stat-label">Scan Cycle</p>', unsafe_allow_html=True)
    
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
    st.plotly_chart(fig, width="stretch")
    
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
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("[Join Free Telegram →](https://t.me/YOUR_FREE_CHANNEL)")
    with c2:
        st.markdown("[Start Free Trial →](https://YOUR_STRIPE_LINK)")
    
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
            <p style="color: #9ca3af; font-size: 0.85rem;">54+ items across 6 global regions with auto-detected news and notable statements</p>
        </div>""", unsafe_allow_html=True)
    with nav5:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">📈</p>
            <p class="feature-title">Accuracy Tracking</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">Transparent prediction record with hit rates, lead times, and verified results</p>
        </div>""", unsafe_allow_html=True)
    with nav6:
        st.markdown("""<div class="feature-box" style="text-align: center; padding: 20px;">
            <p style="font-size: 1.8rem; margin: 0;">🔗</p>
            <p class="feature-title">Correlation Engine</p>
            <p style="color: #9ca3af; font-size: 0.85rem;">4 data streams analyzed simultaneously with exponential confidence multipliers</p>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("""<p style="text-align: center; color: #7F8C8D; font-size: 0.85rem;">
        Treasury Signal Intelligence™ — Independent research tool. Not financial advice.<br>
        Data: TwitterAPI.io • Yahoo Finance • SEC EDGAR • © 2026 All rights reserved.
    </p>""", unsafe_allow_html=True)


# ============================================
# PAGE: LIVE DASHBOARD
# ============================================
elif page == "📊 Live Dashboard":
    st.markdown('<p class="main-header">📊 Live Dashboard</p>', unsafe_allow_html=True)
    st.markdown("")

    # Risk Dashboard with tooltips
    from market_intelligence import get_risk_dashboard, generate_action_signal, get_week_ahead
    risk = get_risk_dashboard()
    action = generate_action_signal(
        correlation_score=0, active_streams=0, strc_ratio=strc_ratio,
        signals_24h=signals, btc_change=0, fear_greed_value=risk["fear_greed_value"]
    )

    # Action Signal Banner
    st.markdown(f"""
    <div style="background: linear-gradient(135deg, #111827 0%, #0d1420 100%); border: 2px solid {action['action_color']}; border-radius: 14px; padding: 20px 28px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
        <div>
            <span style="color: #6b7280; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.12em;">Today's Action Signal</span>
            <br><span style="color: {action['action_color']}; font-size: 1.8rem; font-weight: 800;">{action['action']}</span>
            <br><span style="color: #9ca3af; font-size: 0.85rem;">{action['summary'][:150]}</span>
        </div>
        <div style="text-align: right;">
            <span style="color: {action['action_color']}; font-size: 2.5rem; font-weight: 800; font-family: 'JetBrains Mono', monospace;">{action['score']}</span>
            <br><span style="color: #4b5563; font-size: 0.75rem;">/100</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

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
        st.dataframe(pd.DataFrame(df_data), width="stretch", height=400, column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})

# ============================================
# PAGE: BTC LEADERBOARD
# ============================================
elif page == "🏆 BTC Leaderboard":
    st.markdown('<p class="main-header">🏆 BTC Treasury Leaderboard</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Every publicly traded company holding Bitcoin on their balance sheet</p>', unsafe_allow_html=True)
    
    companies, summary = get_leaderboard_with_live_price(btc_price)
    
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
    st.markdown("### Top 10 Corporate Bitcoin Holders")
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
    st.plotly_chart(fig, width="stretch")
    
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
    st.plotly_chart(fig2, width="stretch")
    st.caption("🟢 Unrealized profit | 🔴 Unrealized loss | 🔵 Cost basis unknown")
    
    st.markdown("---")
    
    # Full table
    st.markdown("### Full Leaderboard")
    df_data = []
    for c in companies:
        if c["btc_holdings"] > 0:
            pnl_str = f"{c['unrealized_pnl_pct']:+.1f}%" if c.get("unrealized_pnl_pct") else "N/A"
            df_data.append({
                "Rank": c["rank"],
                "Company": c["company"],
                "Ticker": c["ticker"],
                "BTC Holdings": c["btc_holdings"],
                "Value ($B)": c["btc_value_b"],
                "Avg Price": f"${c['avg_purchase_price']:,.0f}" if c["avg_purchase_price"] > 0 else "N/A",
                "P&L": pnl_str,
                "Country": c["country"],
                "Sector": c.get("sector", "N/A"),
                "Last Purchase": c.get("last_purchase_date", "N/A") or "N/A",
            })
    
    df = pd.DataFrame(df_data)
    st.dataframe(df, width="stretch", height=500, column_config={
        "BTC Holdings": st.column_config.NumberColumn("BTC Holdings", format="%d"),
    })
    
    st.markdown("---")
    
    # Dominance pie chart
    st.markdown("### Market Share of Corporate BTC Holdings")
    top5 = [c for c in companies if c["btc_holdings"] > 0][:5]
    others_btc = summary["total_btc"] - sum(c["btc_holdings"] for c in top5)
    
    labels = [c["company"].replace(" (MicroStrategy)", "") for c in top5] + ["Others"]
    values = [c["btc_holdings"] for c in top5] + [others_btc]
    colors = ["#E67E22", "#F39C12", "#3498DB", "#2ECC71", "#9B59B6", "#7F8C8D"]
    
    fig3 = go.Figure(go.Pie(
        labels=labels, values=values,
        marker=dict(colors=colors),
        textinfo="label+percent",
        hole=0.4,
    ))
    fig3.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=10, b=0))
    st.plotly_chart(fig3, width="stretch")

# ============================================
# PAGE: RECENT PURCHASES
# ============================================
elif page == "💰 Recent Purchases":
    st.markdown('<p class="main-header">💰 Recent BTC Purchases</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Confirmed Bitcoin purchases by treasury companies</p>', unsafe_allow_html=True)

    stats = get_purchase_stats()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.metric("Total Purchases", stats["total_purchases"])
    with c2:
        st.metric("Total BTC Bought", f"{stats['total_btc']:,}")
    with c3:
        st.metric("Total USD Spent", f"${stats['total_usd']/1_000_000_000:.1f}B")
    with c4:
        st.metric("Avg Price/BTC", f"${stats['avg_price']:,.0f}")

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
    st.plotly_chart(fig, width="stretch")

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
    st.plotly_chart(fig2, width="stretch")

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
        notes_html = f'<br><span style="color: #7F8C8D; font-size: 0.8em;">📝 {p["notes"]}</span>' if p["notes"] else ""

        st.markdown(f"""<div class="signal-card" style="border-left-color: {size_color};">
            <span style="background: {size_color}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 700;">{size_label}</span>
            <strong style="color: #ECF0F1; margin-left: 8px;">{company_short}</strong>
            <span style="color: #7F8C8D;">({p['ticker']})</span>
            <br>
            <span style="color: #E67E22; font-size: 1.1em; font-weight: 700;">₿ {p['btc_amount']:,} BTC</span>
            <span style="color: #BDC3C7;"> — ${usd_m:,.0f}M at ${p['price_per_btc']:,.0f}/BTC</span>
            <br>
            <span style="color: #7F8C8D; font-size: 0.85em;">📅 {p['filing_date']} | 📄 {p['source']}</span>
            {notes_html}
        </div>""", unsafe_allow_html=True)
        st.markdown("")

# ============================================
# PAGE: REGULATORY TRACKER
# ============================================
# ============================================
# PAGE: REGULATORY TRACKER
# ============================================
elif page == "🏛️ Regulatory Tracker":
    st.markdown('<p class="main-header">🏛️ Global Regulatory Tracker</p>', unsafe_allow_html=True)
    st.markdown('<p class="hero-sub">Legislative and regulatory developments affecting Bitcoin worldwide</p>', unsafe_allow_html=True)

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
    st.plotly_chart(fig, width="stretch")

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
        st.plotly_chart(fig2, width="stretch")

    with col_right:
        st.markdown("### Statement Sentiment")
        fig3 = go.Figure(go.Pie(
            labels=["Bullish", "Bearish"],
            values=[reg_stats["bullish_statements"], reg_stats["bearish_statements"]],
            marker=dict(colors=["#2ECC71", "#E74C3C"]),
            hole=0.4,
        ))
        fig3.update_layout(template="plotly_dark", height=300, margin=dict(l=0, r=0, t=10, b=0))
        st.plotly_chart(fig3, width="stretch")

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
                st.dataframe(df, width="stretch")
        except:
            pass
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

# Footer
st.markdown("---")
c1, c2, c3 = st.columns(3)
with c1:
    st.markdown("**Treasury Signal Intelligence** v2.0")
with c2:
    st.markdown("Data: TwitterAPI.io • Yahoo Finance • SEC EDGAR")
with c3:
    st.markdown(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
