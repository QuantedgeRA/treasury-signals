"""
dashboard.py
-------------
Treasury Purchase Signal Intelligence - Live Web Dashboard
Run with: streamlit run dashboard.py
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

load_dotenv()
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ============================================
# PAGE CONFIG
# ============================================
st.set_page_config(
    page_title="Treasury Signal Intelligence",
    page_icon="🔶",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================
# CUSTOM CSS
# ============================================
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #E67E22;
        margin-bottom: 0;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #95A5A6;
        margin-top: 0;
    }
    .signal-card-high {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-left: 4px solid #E74C3C;
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
    }
    .signal-card-medium {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border-left: 4px solid #F39C12;
        padding: 15px;
        border-radius: 8px;
        margin: 10px 0;
    }
    .metric-box {
        background: #1a1a2e;
        padding: 20px;
        border-radius: 10px;
        text-align: center;
    }
    .stMetric label {
        color: #95A5A6 !important;
    }
</style>
""", unsafe_allow_html=True)


# ============================================
# DATA LOADING FUNCTIONS
# ============================================
@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_all_tweets():
    """Load all tweets from Supabase."""
    try:
        result = supabase.table("tweets").select("*").order("inserted_at", desc=True).limit(1000).execute()
        return result.data if result.data else []
    except Exception as e:
        st.error(f"Database error: {e}")
        return []


@st.cache_data(ttl=300)
def load_signals():
    """Load only signal tweets."""
    try:
        result = (
            supabase.table("tweets")
            .select("*")
            .eq("is_signal", True)
            .order("inserted_at", desc=True)
            .limit(100)
            .execute()
        )
        return result.data if result.data else []
    except:
        return []


@st.cache_data(ttl=600)
def load_strc_data():
    """Load STRC price and volume history."""
    try:
        strc = yf.Ticker("STRC")
        hist = strc.history(period="3mo")
        return hist
    except:
        return pd.DataFrame()


@st.cache_data(ttl=600)
def load_btc_price():
    """Load recent BTC price."""
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
        return 0
    except:
        return 0


@st.cache_data(ttl=600)
def load_mstr_price():
    """Load recent MSTR price."""
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        if not hist.empty:
            return round(float(hist["Close"].iloc[-1]), 2)
        return 0
    except:
        return 0


# ============================================
# LOAD DATA
# ============================================
tweets = load_all_tweets()
signals = load_signals()
strc_hist = load_strc_data()
btc_price = load_btc_price()
mstr_price = load_mstr_price()

# Calculate stats
total_tweets = len(tweets)
total_signals = len(signals)
high_signals = len([s for s in signals if s.get("confidence_score", 0) >= 60])
accounts_tracked = len(set(t.get("author_username", "") for t in tweets))

# STRC latest
strc_price = round(float(strc_hist["Close"].iloc[-1]), 2) if not strc_hist.empty else 0
strc_volume = int(strc_hist["Volume"].iloc[-1]) if not strc_hist.empty else 0
strc_avg_volume = int(strc_hist["Volume"].tail(20).mean()) if not strc_hist.empty else 0
strc_ratio = round(strc_volume / strc_avg_volume, 2) if strc_avg_volume > 0 else 0


# ============================================
# SIDEBAR
# ============================================
with st.sidebar:
    st.image("https://img.icons8.com/color/96/bitcoin--v1.png", width=60)
    st.markdown("## Treasury Signal Intelligence")
    st.markdown("*Real-time Bitcoin purchase signal detection*")
    st.markdown("---")
    
    st.markdown("### 📊 System Status")
    st.markdown(f"🟢 **Scanner:** Active")
    st.markdown(f"📡 **Accounts:** {accounts_tracked}")
    st.markdown(f"🗄️ **Tweets in DB:** {total_tweets}")
    st.markdown(f"🚨 **Signals detected:** {total_signals}")
    
    st.markdown("---")
    st.markdown("### ⏱️ Data Sources")
    st.markdown("✅ Twitter/X Executive Feeds")
    st.markdown("✅ STRC Volume (Yahoo Finance)")
    st.markdown("✅ SEC EDGAR 8-K Filings")
    
    st.markdown("---")
    st.markdown("### 🔓 Upgrade to PRO")
    st.markdown("Get instant alerts for all accounts")
    st.markdown("[Subscribe →](https://your-stripe-link-here)")
    
    st.markdown("---")
    st.markdown(f"*Last updated: {datetime.now().strftime('%H:%M:%S')}*")
    if st.button("🔄 Refresh Data"):
        st.cache_data.clear()
        st.rerun()


# ============================================
# MAIN DASHBOARD
# ============================================
st.markdown('<p class="main-header">🔶 Treasury Signal Intelligence</p>', unsafe_allow_html=True)
st.markdown('<p class="sub-header">Real-time detection of Bitcoin treasury purchase signals across executive social media, capital markets, and SEC filings</p>', unsafe_allow_html=True)
st.markdown("")

# ---- TOP METRICS ----
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Bitcoin Price", f"${btc_price:,.0f}", help="Current BTC/USD price")

with col2:
    st.metric("MSTR Price", f"${mstr_price:,.2f}", help="Strategy stock price")

with col3:
    st.metric("STRC Price", f"${strc_price:.2f}", help="STRC preferred stock price")

with col4:
    st.metric("STRC Volume Ratio", f"{strc_ratio}x", help="Today's volume vs 20-day average")

with col5:
    st.metric("Active Signals", f"{high_signals}", help="HIGH+ confidence signals detected")

st.markdown("---")

# ---- TWO COLUMN LAYOUT ----
left_col, right_col = st.columns([2, 1])

with left_col:
    # ---- STRC VOLUME CHART ----
    st.markdown("### 📈 STRC Daily Volume (3 Months)")
    
    if not strc_hist.empty:
        fig_vol = go.Figure()
        
        # Calculate average for color coding
        avg_vol = strc_hist["Volume"].rolling(20).mean()
        
        colors = ["#E74C3C" if v > avg * 1.5 else "#F39C12" if v > avg * 1.2 else "#2ECC71" 
                  for v, avg in zip(strc_hist["Volume"], avg_vol.fillna(strc_hist["Volume"].mean()))]
        
        fig_vol.add_trace(go.Bar(
            x=strc_hist.index,
            y=strc_hist["Volume"],
            marker_color=colors,
            name="Daily Volume",
            hovertemplate="Date: %{x}<br>Volume: %{y:,.0f}<extra></extra>"
        ))
        
        fig_vol.add_trace(go.Scatter(
            x=strc_hist.index,
            y=avg_vol,
            mode="lines",
            line=dict(color="#3498DB", width=2, dash="dash"),
            name="20-Day Average"
        ))
        
        fig_vol.update_layout(
            template="plotly_dark",
            height=400,
            margin=dict(l=0, r=0, t=10, b=0),
            legend=dict(orientation="h", y=1.1),
            yaxis_title="Shares Traded",
            xaxis_title="",
        )
        
        st.plotly_chart(fig_vol, use_container_width=True)
        
        st.caption("🔴 Red bars = volume 1.5x+ above average (likely capital raise) | 🟠 Orange = elevated | 🟢 Green = normal")
    else:
        st.info("STRC data unavailable")
    
    # ---- STRC PRICE CHART ----
    st.markdown("### 💵 STRC Price History")
    
    if not strc_hist.empty:
        fig_price = go.Figure()
        
        fig_price.add_trace(go.Scatter(
            x=strc_hist.index,
            y=strc_hist["Close"],
            mode="lines",
            line=dict(color="#E67E22", width=2),
            fill="tozeroy",
            fillcolor="rgba(230, 126, 34, 0.1)",
            name="STRC Price"
        ))
        
        # Add $100 par value reference line
        fig_price.add_hline(y=100, line_dash="dash", line_color="#95A5A6", 
                           annotation_text="$100 Par Value")
        
        fig_price.update_layout(
            template="plotly_dark",
            height=300,
            margin=dict(l=0, r=0, t=10, b=0),
            yaxis_title="Price ($)",
            xaxis_title="",
        )
        
        st.plotly_chart(fig_price, use_container_width=True)


with right_col:
    # ---- LIVE SIGNAL FEED ----
    st.markdown("### 🚨 Recent Signals")
    
    if signals:
        for sig in signals[:10]:
            score = sig.get("confidence_score", 0)
            author = sig.get("author_username", "unknown")
            text = sig.get("tweet_text", "")[:120]
            company = sig.get("company", "")
            date = sig.get("created_at", "")[:16]
            
            if score >= 60:
                emoji = "🔴"
                border_color = "#E74C3C"
            elif score >= 40:
                emoji = "🟠"
                border_color = "#F39C12"
            else:
                emoji = "🟡"
                border_color = "#F1C40F"
            
            st.markdown(f"""
            <div style="border-left: 3px solid {border_color}; padding: 10px; margin: 8px 0; 
                        background: rgba(26,26,46,0.5); border-radius: 5px;">
                <strong>{emoji} {score}/100</strong> — @{author} ({company})<br>
                <span style="color: #BDC3C7; font-size: 0.85em;">{text}...</span><br>
                <span style="color: #7F8C8D; font-size: 0.75em;">{date}</span>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("No signals detected yet. Signals will appear here as they are detected.")
    
    # ---- SIGNAL SCORE DISTRIBUTION ----
    st.markdown("### 📊 Signal Score Distribution")
    
    if signals:
        scores = [s.get("confidence_score", 0) for s in signals]
        
        fig_dist = go.Figure()
        fig_dist.add_trace(go.Histogram(
            x=scores,
            nbinsx=10,
            marker_color="#E67E22",
            opacity=0.8,
        ))
        fig_dist.update_layout(
            template="plotly_dark",
            height=250,
            margin=dict(l=0, r=0, t=10, b=0),
            xaxis_title="Confidence Score",
            yaxis_title="Count",
        )
        st.plotly_chart(fig_dist, use_container_width=True)


# ---- BOTTOM SECTION: RECENT TWEETS TABLE ----
st.markdown("---")
st.markdown("### 📋 Recent Tweets (All Accounts)")

if tweets:
    # Convert to dataframe for display
    df_data = []
    for t in tweets[:50]:
        df_data.append({
            "Date": t.get("created_at", "")[:19],
            "Author": f"@{t.get('author_username', '')}",
            "Company": t.get("company", ""),
            "Tweet": t.get("tweet_text", "")[:100] + "...",
            "Signal": "🚨 YES" if t.get("is_signal") else "",
            "Score": t.get("confidence_score", 0),
            "Likes": t.get("like_count", 0),
            "Views": t.get("view_count", 0),
        })
    
    df = pd.DataFrame(df_data)
    
    # Color the signal rows
    st.dataframe(
        df,
        use_container_width=True,
        height=400,
        column_config={
            "Score": st.column_config.ProgressColumn(
                "Score",
                min_value=0,
                max_value=100,
                format="%d",
            ),
            "Likes": st.column_config.NumberColumn(format="%d"),
            "Views": st.column_config.NumberColumn(format="%d"),
        }
    )
else:
    st.info("No tweets in database yet.")


# ---- FOOTER ----
st.markdown("---")
col_f1, col_f2, col_f3 = st.columns(3)
with col_f1:
    st.markdown("**Treasury Signal Intelligence** v1.0")
with col_f2:
    st.markdown("Data: TwitterAPI.io • Yahoo Finance • SEC EDGAR")
with col_f3:
    st.markdown(f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
