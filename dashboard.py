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
    .main-header { font-size: 2.8rem; font-weight: 800; color: #E67E22; text-align: center; margin-top: 20px; }
    .hero-sub { font-size: 1.3rem; color: #BDC3C7; text-align: center; margin-bottom: 30px; }
    .feature-box { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 20px; border-radius: 12px; border: 1px solid #2C3E50; margin: 5px 0; }
    .feature-title { color: #E67E22; font-size: 1.1rem; font-weight: 700; margin-bottom: 8px; }
    .stat-huge { font-size: 2.5rem; font-weight: 800; color: #E67E22; text-align: center; margin: 0; }
    .stat-label { font-size: 0.9rem; color: #95A5A6; text-align: center; margin: 0; }
    .proof-bar { background: #1a1a2e; padding: 15px; border-radius: 8px; text-align: center; border: 1px solid #E67E22; margin: 20px 0; }
    .signal-card { border-left: 3px solid; padding: 10px; margin: 8px 0; background: rgba(26,26,46,0.5); border-radius: 5px; }
    .pricing-free { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 25px; border-radius: 12px; border: 1px solid #2C3E50; }
    .pricing-pro { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%); padding: 25px; border-radius: 12px; border: 2px solid #E67E22; }
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
    
    page = st.radio("Navigate", ["🏠 Home", "📊 Live Dashboard", "📈 Accuracy"], label_visibility="collapsed")
    
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
    
    st.markdown("---")
    
    left, right = st.columns([2, 1])
    
    with left:
        st.markdown("### 📈 STRC Daily Volume (3 Months)")
        if not strc_hist.empty:
            avg_vol = strc_hist["Volume"].rolling(20).mean()
            colors = ["#E74C3C" if v > a * 1.5 else "#F39C12" if v > a * 1.2 else "#2ECC71"
                      for v, a in zip(strc_hist["Volume"], avg_vol.fillna(strc_hist["Volume"].mean()))]
            
            fig = go.Figure()
            fig.add_trace(go.Bar(x=strc_hist.index, y=strc_hist["Volume"], marker_color=colors, name="Volume"))
            fig.add_trace(go.Scatter(x=strc_hist.index, y=avg_vol, mode="lines", line=dict(color="#3498DB", width=2, dash="dash"), name="20-Day Avg"))
            fig.update_layout(template="plotly_dark", height=400, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Shares", legend=dict(orientation="h", y=1.1))
            st.plotly_chart(fig, width="stretch")
            st.caption("🔴 1.5x+ avg (capital raise) | 🟠 Elevated | 🟢 Normal")
        else:
            st.info("STRC data unavailable")
        
        st.markdown("### 💵 STRC Price")
        if not strc_hist.empty:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=strc_hist.index, y=strc_hist["Close"], mode="lines", line=dict(color="#E67E22", width=2), fill="tozeroy", fillcolor="rgba(230,126,34,0.1)"))
            fig2.add_hline(y=100, line_dash="dash", line_color="#95A5A6", annotation_text="$100 Par")
            fig2.update_layout(template="plotly_dark", height=300, margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Price ($)")
            st.plotly_chart(fig2, width="stretch")
    
    with right:
        st.markdown("### 🚨 Recent Signals")
        if signals:
            for sig in signals[:10]:
                score = sig.get("confidence_score", 0)
                author = sig.get("author_username", "")
                text = sig.get("tweet_text", "")[:120]
                company = sig.get("company", "")
                date = sig.get("created_at", "")[:16]
                color = "#E74C3C" if score >= 60 else "#F39C12" if score >= 40 else "#F1C40F"
                emoji = "🔴" if score >= 60 else "🟠" if score >= 40 else "🟡"
                st.markdown(f"""<div class="signal-card" style="border-left-color: {color};">
                    <strong>{emoji} {score}/100</strong> — @{author} ({company})<br>
                    <span style="color: #BDC3C7; font-size: 0.85em;">{text}...</span><br>
                    <span style="color: #7F8C8D; font-size: 0.75em;">{date}</span>
                </div>""", unsafe_allow_html=True)
        else:
            st.info("No signals detected yet.")
        
        st.markdown("### 📊 Score Distribution")
        if signals:
            scores = [s.get("confidence_score", 0) for s in signals]
            fig3 = go.Figure(go.Histogram(x=scores, nbinsx=10, marker_color="#E67E22", opacity=0.8))
            fig3.update_layout(template="plotly_dark", height=250, margin=dict(l=0, r=0, t=10, b=0), xaxis_title="Score", yaxis_title="Count")
            st.plotly_chart(fig3, width="stretch")
    
    st.markdown("---")
    st.markdown("### 📋 Recent Tweets")
    if tweets:
        df_data = [{"Date": t.get("created_at", "")[:19], "Author": f"@{t.get('author_username', '')}", "Company": t.get("company", ""), "Tweet": t.get("tweet_text", "")[:100] + "...", "Signal": "🚨" if t.get("is_signal") else "", "Score": t.get("confidence_score", 0)} for t in tweets[:50]]
        st.dataframe(pd.DataFrame(df_data), width="stretch", height=400, column_config={"Score": st.column_config.ProgressColumn("Score", min_value=0, max_value=100, format="%d")})


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
