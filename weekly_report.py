"""
weekly_report.py — v2.0
------------------------
CEO-Grade Weekly PDF Report

Board-ready, printable, shareable.
Professional design with cover page, executive summary,
clean tables, and polished layout.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch, cm
from reportlab.lib.colors import HexColor, Color
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether, Frame, PageTemplate
)
from reportlab.pdfgen import canvas as pdfcanvas

load_dotenv()

# ============================================
# BRAND COLORS
# ============================================
BRAND_ORANGE = HexColor("#E67E22")
BRAND_DARK_ORANGE = HexColor("#D35400")
DARK_BG = HexColor("#1A1A2E")
CARD_BG = HexColor("#F8FAFC")
LIGHT_GRAY = HexColor("#F1F5F9")
BORDER_GRAY = HexColor("#E2E8F0")
TEXT_BLACK = HexColor("#1E293B")
TEXT_DARK = HexColor("#334155")
TEXT_MEDIUM = HexColor("#64748B")
TEXT_LIGHT = HexColor("#94A3B8")
GREEN = HexColor("#059669")
GREEN_LIGHT = HexColor("#ECFDF5")
RED = HexColor("#DC2626")
RED_LIGHT = HexColor("#FEF2F2")
YELLOW = HexColor("#D97706")
YELLOW_LIGHT = HexColor("#FFFBEB")
BLUE = HexColor("#2563EB")
BLUE_LIGHT = HexColor("#EFF6FF")
WHITE = HexColor("#FFFFFF")


def create_styles():
    """Professional paragraph styles."""
    styles = {}

    styles["title"] = ParagraphStyle(
        "title", fontName="Helvetica-Bold", fontSize=28,
        textColor=TEXT_BLACK, spaceAfter=4, leading=34,
    )
    styles["subtitle"] = ParagraphStyle(
        "subtitle", fontName="Helvetica", fontSize=13,
        textColor=TEXT_MEDIUM, spaceAfter=20, leading=18,
    )
    styles["section"] = ParagraphStyle(
        "section", fontName="Helvetica-Bold", fontSize=15,
        textColor=TEXT_BLACK, spaceBefore=24, spaceAfter=8, leading=20,
    )
    styles["subsection"] = ParagraphStyle(
        "subsection", fontName="Helvetica-Bold", fontSize=11,
        textColor=TEXT_DARK, spaceBefore=12, spaceAfter=6, leading=15,
    )
    styles["body"] = ParagraphStyle(
        "body", fontName="Helvetica", fontSize=9.5,
        textColor=TEXT_DARK, spaceAfter=5, leading=13.5,
        alignment=TA_JUSTIFY,
    )
    styles["body_small"] = ParagraphStyle(
        "body_small", fontName="Helvetica", fontSize=8.5,
        textColor=TEXT_MEDIUM, spaceAfter=3, leading=12,
    )
    styles["caption"] = ParagraphStyle(
        "caption", fontName="Helvetica", fontSize=7.5,
        textColor=TEXT_LIGHT, spaceAfter=4, leading=10,
    )
    styles["metric_value"] = ParagraphStyle(
        "metric_value", fontName="Helvetica-Bold", fontSize=22,
        textColor=TEXT_BLACK, alignment=TA_CENTER, spaceAfter=2,
    )
    styles["metric_label"] = ParagraphStyle(
        "metric_label", fontName="Helvetica", fontSize=7.5,
        textColor=TEXT_MEDIUM, alignment=TA_CENTER, leading=10,
    )
    styles["action_signal"] = ParagraphStyle(
        "action_signal", fontName="Helvetica-Bold", fontSize=20,
        textColor=BRAND_ORANGE, alignment=TA_LEFT, spaceAfter=4,
    )
    styles["action_body"] = ParagraphStyle(
        "action_body", fontName="Helvetica", fontSize=10,
        textColor=TEXT_DARK, spaceAfter=4, leading=14,
        alignment=TA_JUSTIFY,
    )
    styles["quote"] = ParagraphStyle(
        "quote", fontName="Helvetica-Oblique", fontSize=9,
        textColor=TEXT_MEDIUM, leftIndent=15, spaceAfter=4, leading=12.5,
    )
    styles["footer"] = ParagraphStyle(
        "footer", fontName="Helvetica", fontSize=7,
        textColor=TEXT_LIGHT, alignment=TA_CENTER, leading=9,
    )
    styles["toc_item"] = ParagraphStyle(
        "toc_item", fontName="Helvetica", fontSize=10,
        textColor=TEXT_DARK, spaceAfter=6, leading=14,
    )

    return styles


def add_header_footer(canvas, doc):
    """Professional header and footer."""
    canvas.saveState()
    w, h = letter

    # Top line
    canvas.setStrokeColor(BRAND_ORANGE)
    canvas.setLineWidth(3)
    canvas.line(40, h - 30, w - 40, h - 30)

    # Header text
    canvas.setFont("Helvetica-Bold", 7)
    canvas.setFillColor(BRAND_ORANGE)
    canvas.drawString(42, h - 26, "TREASURY SIGNAL INTELLIGENCE™")

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(TEXT_LIGHT)
    canvas.drawRightString(w - 42, h - 26, "CONFIDENTIAL — EXECUTIVE WEEKLY REPORT")

    # Footer line
    canvas.setStrokeColor(BORDER_GRAY)
    canvas.setLineWidth(0.5)
    canvas.line(40, 35, w - 40, 35)

    # Footer text
    canvas.setFont("Helvetica", 6.5)
    canvas.setFillColor(TEXT_LIGHT)
    canvas.drawString(42, 24, f"© 2026 Treasury Signal Intelligence. Not financial advice. Data: CoinGecko · SEC EDGAR · Yahoo Finance")
    canvas.drawRightString(w - 42, 24, f"Page {doc.page}")

    # Bottom accent
    canvas.setStrokeColor(BRAND_ORANGE)
    canvas.setLineWidth(2)
    canvas.line(40, 18, w - 40, 18)

    canvas.restoreState()


def make_metric_box(value, label, color=TEXT_BLACK):
    """Create a metric display box."""
    styles = create_styles()
    val_style = ParagraphStyle("mv", fontName="Helvetica-Bold", fontSize=20, textColor=color, alignment=TA_CENTER, spaceAfter=1)
    lab_style = ParagraphStyle("ml", fontName="Helvetica", fontSize=7, textColor=TEXT_MEDIUM, alignment=TA_CENTER)
    return [[Paragraph(str(value), val_style)], [Paragraph(label, lab_style)]]


def section_divider():
    """Orange section divider."""
    return HRFlowable(width="100%", thickness=1.5, color=BRAND_ORANGE, spaceAfter=6, spaceBefore=2)


def generate_weekly_report(output_path="weekly_report.pdf"):
    """Generate the CEO-grade weekly PDF report."""
    print("  Generating CEO-Grade Weekly PDF Report v2.0...")

    # ============================================
    # GATHER ALL DATA
    # ============================================
    from strc_tracker import get_strc_volume_data
    from treasury_leaderboard import get_leaderboard_with_live_price
    from regulatory_tracker import get_summary_stats as get_reg_stats, get_all_items_combined, get_all_statements_combined
    from purchase_tracker import get_recent_purchases, get_purchase_stats
    from correlation_engine import CorrelationEngine
    from market_intelligence import generate_action_signal, get_risk_dashboard, get_week_ahead, get_overnight_changes, get_peer_activity
    from supabase import create_client
    import yfinance as yf

    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Market
    btc_price = btc_change = mstr_price = mstr_change = 0
    try:
        btc = yf.Ticker("BTC-USD")
        hist = btc.history(period="5d")
        if not hist.empty:
            btc_price = round(float(hist["Close"].iloc[-1]), 2)
            btc_prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else btc_price
            btc_change = round(((btc_price - btc_prev) / btc_prev) * 100, 2)
    except:
        pass
    try:
        mstr = yf.Ticker("MSTR")
        hist = mstr.history(period="5d")
        if not hist.empty:
            mstr_price = round(float(hist["Close"].iloc[-1]), 2)
            mstr_prev = round(float(hist["Close"].iloc[-2]), 2) if len(hist) > 1 else mstr_price
            mstr_change = round(((mstr_price - mstr_prev) / mstr_prev) * 100, 2)
    except:
        pass

    strc_data = get_strc_volume_data()
    strc_ratio = strc_data["volume_ratio"] if strc_data else 0
    strc_price = strc_data["price"] if strc_data else 0
    strc_vol_m = strc_data["dollar_volume_m"] if strc_data else 0

    leaderboard, lb_summary = get_leaderboard_with_live_price(btc_price)
    risk = get_risk_dashboard()

    try:
        sig_result = supabase.table("tweets").select("*").eq("is_signal", True).order("inserted_at", desc=True).limit(20).execute()
        all_signals = sig_result.data if sig_result.data else []
    except:
        all_signals = []

    action = generate_action_signal(0, 0, strc_ratio, all_signals[:10], btc_change, risk["fear_greed_value"])

    purchases = get_recent_purchases(10)
    purchase_stats = get_purchase_stats()
    reg_stats = get_reg_stats()
    reg_items = get_all_items_combined()
    statements = get_all_statements_combined()
    week_ahead = get_week_ahead()
    changes = get_overnight_changes(btc_price, mstr_price, strc_ratio, len(all_signals), lb_summary["total_btc"], reg_stats["total_items"])
    peers = get_peer_activity()

    try:
        pred_result = supabase.table("predictions").select("*").execute()
        purch_result = supabase.table("confirmed_purchases").select("*").execute()
        total_predictions = len(pred_result.data) if pred_result.data else 0
        total_confirmed = len(purch_result.data) if purch_result.data else 0
        predicted_correct = len([p for p in (purch_result.data or []) if p.get("was_predicted")])
        hit_rate = round(predicted_correct / total_confirmed * 100, 1) if total_confirmed > 0 else 0
    except:
        total_predictions = total_confirmed = 0
        hit_rate = 0

    total_signals = len(all_signals)
    high_signals = len([s for s in all_signals if s.get("confidence_score", 0) >= 60])

    # ============================================
    # BUILD PDF
    # ============================================
    styles = create_styles()
    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        leftMargin=42, rightMargin=42,
        topMargin=44, bottomMargin=44,
    )
    story = []

    # ============================================
    # PAGE 1: COVER
    # ============================================
    story.append(Spacer(1, 100))

    # Brand mark
    cover_brand = ParagraphStyle("cb", fontName="Helvetica-Bold", fontSize=11, textColor=BRAND_ORANGE, alignment=TA_CENTER, spaceAfter=12, letterSpacing=3)
    story.append(Paragraph("TREASURY SIGNAL INTELLIGENCE", cover_brand))

    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="40%", thickness=2, color=BRAND_ORANGE, spaceAfter=20, hAlign="CENTER"))

    cover_title = ParagraphStyle("ct", fontName="Helvetica-Bold", fontSize=32, textColor=TEXT_BLACK, alignment=TA_CENTER, spaceAfter=8, leading=38)
    story.append(Paragraph("Executive Weekly Report", cover_title))

    cover_date = ParagraphStyle("cd", fontName="Helvetica", fontSize=14, textColor=TEXT_MEDIUM, alignment=TA_CENTER, spaceAfter=40)
    story.append(Paragraph(datetime.now().strftime("%B %d, %Y"), cover_date))

    story.append(HRFlowable(width="40%", thickness=1, color=BORDER_GRAY, spaceAfter=30, hAlign="CENTER"))

    # Cover metrics
    btc_arrow = "▲" if btc_change >= 0 else "▼"
    mstr_arrow = "▲" if mstr_change >= 0 else "▼"
    btc_color = GREEN if btc_change >= 0 else RED
    mstr_color = GREEN if mstr_change >= 0 else RED

    cover_metrics = [
        [
            Paragraph(f"${btc_price:,.0f}", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=18, textColor=TEXT_BLACK, alignment=TA_CENTER)),
            Paragraph(f"${mstr_price:,.2f}", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=18, textColor=TEXT_BLACK, alignment=TA_CENTER)),
            Paragraph(str(risk["fear_greed_value"]), ParagraphStyle("", fontName="Helvetica-Bold", fontSize=18, textColor=YELLOW if risk["fear_greed_value"] <= 40 else GREEN, alignment=TA_CENTER)),
            Paragraph(action["action"].replace("🟢 ", "").replace("🔵 ", "").replace("🟡 ", "").replace("🔴 ", "").replace("⚪ ", ""), ParagraphStyle("", fontName="Helvetica-Bold", fontSize=14, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
        ],
        [
            Paragraph(f"Bitcoin ({btc_arrow}{btc_change:+.1f}%)", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph(f"MSTR ({mstr_arrow}{mstr_change:+.1f}%)", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph(f"Fear & Greed ({risk['fear_greed_label']})", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph(f"Action Signal ({action['score']}/100)", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
        ],
    ]
    cm_table = Table(cover_metrics, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    cm_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 1, BORDER_GRAY),
        ('LINEBEFORE', (1, 0), (1, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (2, 0), (2, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (3, 0), (3, -1), 0.5, BORDER_GRAY),
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
    ]))
    story.append(cm_table)

    story.append(Spacer(1, 40))

    # Cover summary
    cover_summary = ParagraphStyle("cs", fontName="Helvetica", fontSize=10, textColor=TEXT_MEDIUM, alignment=TA_CENTER, leading=14.5)
    story.append(Paragraph(
        f"Tracking {lb_summary.get('corporate_count', 148)} companies and {lb_summary.get('sovereign_count', 7)} governments holding "
        f"{lb_summary['total_btc']:,} BTC (${lb_summary['total_value_b']:.1f}B) · "
        f"{reg_stats['total_items']} regulatory items across {reg_stats['regions_tracked']} regions · "
        f"{total_signals} signals detected · {total_predictions} predictions logged",
        cover_summary
    ))

    story.append(Spacer(1, 60))

    # Confidentiality
    conf_style = ParagraphStyle("conf", fontName="Helvetica", fontSize=7.5, textColor=TEXT_LIGHT, alignment=TA_CENTER, leading=10)
    story.append(Paragraph("CONFIDENTIAL — For authorized recipients only", conf_style))
    story.append(Paragraph("Treasury Signal Intelligence™ · Data: CoinGecko · SEC EDGAR · Yahoo Finance · BitcoinTreasuries.net", conf_style))

    # ============================================
    # PAGE 2: TABLE OF CONTENTS
    # ============================================
    story.append(PageBreak())
    story.append(Paragraph("Table of Contents", styles["title"]))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BRAND_ORANGE, spaceAfter=20))

    toc_items = [
        ("1", "Action Signal & Risk Assessment", "Buy/Hold/Wait recommendation with confidence score"),
        ("2", "Market Overview", "Bitcoin, MSTR, STRC prices, volatility, and Fear & Greed"),
        ("3", "What Changed This Week", "Key developments and overnight changes"),
        ("4", "BTC Treasury Leaderboard", f"Top 20 holders from {lb_summary['total_companies']} entities"),
        ("5", "Recent BTC Purchases", f"{purchase_stats['total_purchases']} confirmed purchases tracked"),
        ("6", "Signal Activity & Accuracy", f"{total_signals} signals, {hit_rate}% hit rate"),
        ("7", "Global Regulatory Landscape", f"{reg_stats['total_items']} items across {reg_stats['regions_tracked']} regions"),
        ("8", "Notable Statements", f"{reg_stats['total_statements']} from world leaders and CEOs"),
        ("9", "Week Ahead", "Upcoming events that could move markets"),
    ]

    toc_data = []
    for num, title, desc in toc_items:
        toc_data.append([
            Paragraph(f"<b>{num}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=12, textColor=BRAND_ORANGE)),
            Paragraph(f"<b>{title}</b><br/><font size=8 color='#94A3B8'>{desc}</font>", ParagraphStyle("", fontName="Helvetica", fontSize=10.5, textColor=TEXT_BLACK, leading=15)),
        ])

    toc_table = Table(toc_data, colWidths=[0.5 * inch, 5.3 * inch])
    toc_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, BORDER_GRAY),
    ]))
    story.append(toc_table)

    # ============================================
    # SECTION 1: ACTION SIGNAL
    # ============================================
    story.append(PageBreak())
    story.append(Paragraph("1 — Action Signal & Risk Assessment", styles["section"]))
    story.append(section_divider())

    # Action box
    action_label = action["action"].replace("🟢 ", "").replace("🔵 ", "").replace("🟡 ", "").replace("🔴 ", "").replace("⚪ ", "")
    if "BUY" in action_label:
        box_color = GREEN
        box_bg = GREEN_LIGHT
    elif "ACCUMULATE" in action_label:
        box_color = BLUE
        box_bg = BLUE_LIGHT
    elif "WAIT" in action_label:
        box_color = YELLOW
        box_bg = YELLOW_LIGHT
    elif "CAUTION" in action_label:
        box_color = RED
        box_bg = RED_LIGHT
    else:
        box_color = TEXT_MEDIUM
        box_bg = CARD_BG

    action_data = [
        [
            Paragraph(f"<b>{action_label}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=22, textColor=box_color)),
            Paragraph(f"<b>{action['score']}</b><font size=10 color='#94A3B8'>/100</font>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=28, textColor=box_color, alignment=TA_RIGHT)),
        ],
        [
            Paragraph(action["summary"], ParagraphStyle("", fontName="Helvetica", fontSize=10, textColor=TEXT_DARK, leading=14)),
            "",
        ],
    ]
    act_table = Table(action_data, colWidths=[4.2 * inch, 1.8 * inch])
    act_table.setStyle(TableStyle([
        ('SPAN', (0, 1), (1, 1)),
        ('BACKGROUND', (0, 0), (-1, -1), box_bg),
        ('BOX', (0, 0), (-1, -1), 2, box_color),
        ('TOPPADDING', (0, 0), (-1, -1), 14),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 14),
        ('LEFTPADDING', (0, 0), (-1, -1), 16),
        ('RIGHTPADDING', (0, 0), (-1, -1), 16),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(act_table)
    story.append(Spacer(1, 6))

    # Action reasons
    if action.get("reasons"):
        for r in action["reasons"]:
            story.append(Paragraph(f"• {r}", styles["body_small"]))

    # Risk Dashboard
    story.append(Spacer(1, 12))
    story.append(Paragraph("Risk Dashboard", styles["subsection"]))

    fg_color = RED if risk["fear_greed_value"] <= 25 else YELLOW if risk["fear_greed_value"] <= 40 else GREEN if risk["fear_greed_value"] <= 60 else YELLOW
    vol_color = RED if risk["volatility_30d"] >= 60 else YELLOW if risk["volatility_30d"] >= 40 else GREEN
    risk_table_color = RED if "HIGH" in risk["risk_level"] else YELLOW if "ELEVATED" in risk["risk_level"] else GREEN

    risk_data = [
        [
            Paragraph(f"<b>{risk['fear_greed_value']}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=24, textColor=fg_color, alignment=TA_CENTER)),
            Paragraph(f"<b>{risk['volatility_30d']}%</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=24, textColor=vol_color, alignment=TA_CENTER)),
            Paragraph(f"<b>{risk['drawdown_from_ath']}%</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=24, textColor=RED, alignment=TA_CENTER)),
            Paragraph(f"<b>{risk['risk_level']}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=14, textColor=risk_table_color, alignment=TA_CENTER)),
        ],
        [
            Paragraph(f"Fear & Greed<br/><font size=7 color='#94A3B8'>{risk['fear_greed_label']}</font>", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER, leading=11)),
            Paragraph("30D Volatility", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph(f"From ATH<br/><font size=7 color='#94A3B8'>(${risk['ath_price']:,.0f})</font>", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER, leading=11)),
            Paragraph("Overall Risk", ParagraphStyle("", fontName="Helvetica", fontSize=8, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
        ],
    ]
    r_table = Table(risk_data, colWidths=[1.5 * inch, 1.5 * inch, 1.5 * inch, 1.5 * inch])
    r_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (1, 0), (1, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (2, 0), (2, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (3, 0), (3, -1), 0.5, BORDER_GRAY),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
    ]))
    story.append(r_table)

    # ============================================
    # SECTION 2: MARKET OVERVIEW
    # ============================================
    story.append(Spacer(1, 16))
    story.append(Paragraph("2 — Market Overview", styles["section"]))
    story.append(section_divider())

    market_data = [
        ["", "Price", "Change", "", "Price / Value", "Status"],
        ["Bitcoin", f"${btc_price:,.0f}", f"{btc_arrow} {btc_change:+.2f}%", "STRC", f"${strc_price:.2f}", f"{strc_ratio}x volume"],
        ["MSTR", f"${mstr_price:,.2f}", f"{mstr_arrow} {mstr_change:+.2f}%", "STRC Vol", f"${strc_vol_m}M", "ELEVATED" if strc_ratio >= 1.5 else "NORMAL"],
    ]
    m_table = Table(market_data, colWidths=[0.8 * inch, 1.1 * inch, 1 * inch, 0.8 * inch, 1.1 * inch, 1 * inch])
    m_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (3, 1), (3, -1), 'Helvetica-Bold'),
        ('TEXTCOLOR', (0, 0), (-1, 0), TEXT_MEDIUM),
        ('TEXTCOLOR', (0, 1), (0, -1), TEXT_DARK),
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT_GRAY),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 7),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(m_table)

    # ============================================
    # SECTION 3: WHAT CHANGED
    # ============================================
    story.append(Spacer(1, 8))
    story.append(Paragraph("3 — What Changed This Week", styles["section"]))
    story.append(section_divider())
    for c in changes:
        story.append(Paragraph(f"{c.get('icon', '📊')}  {c.get('text', '')}", styles["body"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("Peer Activity", styles["subsection"]))
    for p in peers[:5]:
        story.append(Paragraph(f"{p.get('icon', '📊')}  <b>{p.get('company', '')}</b> — {p.get('text', '')}", styles["body_small"]))

    # ============================================
    # SECTION 4: LEADERBOARD
    # ============================================
    story.append(PageBreak())
    story.append(Paragraph("4 — BTC Treasury Leaderboard", styles["section"]))
    story.append(section_divider())
    story.append(Paragraph(
        f"{lb_summary.get('corporate_count', 0)} companies + {lb_summary.get('sovereign_count', 0)} governments · "
        f"{lb_summary['total_btc']:,} BTC (${lb_summary['total_value_b']:.1f}B) · "
        f"Source: CoinGecko (LIVE) + BitcoinTreasuries.net",
        styles["caption"]
    ))

    lb_header = ["#", "Entity", "Type", "BTC Holdings", "Value ($B)", "P&L"]
    lb_rows = [lb_header]
    for c in leaderboard[:20]:
        if c["btc_holdings"] > 0:
            etype = "GOV" if c.get("is_government") else "CORP"
            pnl = f"{c['unrealized_pnl_pct']:+.1f}%" if c.get("unrealized_pnl_pct") else "—"
            lb_rows.append([
                str(c["rank"]), c["company"][:26], etype,
                f"{c['btc_holdings']:,}", f"${c['btc_value_b']:.2f}", pnl,
            ])

    lb_table = Table(lb_rows, colWidths=[0.35 * inch, 2.2 * inch, 0.5 * inch, 1.1 * inch, 0.85 * inch, 0.7 * inch])
    lb_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_ORANGE),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (3, 0), (5, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, CARD_BG]),
    ]))
    story.append(lb_table)

    # ============================================
    # SECTION 5: PURCHASES
    # ============================================
    story.append(Spacer(1, 12))
    story.append(Paragraph("5 — Recent BTC Purchases", styles["section"]))
    story.append(section_divider())
    story.append(Paragraph(
        f"{purchase_stats['total_purchases']} purchases · {purchase_stats['total_btc']:,} BTC · "
        f"${purchase_stats['total_usd'] / 1_000_000_000:.1f}B · Sources: SEC EDGAR · Press Releases · Auto-Detection",
        styles["caption"]
    ))

    p_header = ["Date", "Entity", "BTC Amount", "USD", "Source"]
    p_rows = [p_header]
    for p in purchases[:10]:
        usd_m = p.get("usd_amount", 0) / 1_000_000
        source = p.get("source", "")
        if len(source) > 22:
            source = source[:22] + "..."
        p_rows.append([
            p.get("filing_date", "")[:10], p.get("company", "")[:22],
            f"{p.get('btc_amount', 0):,}", f"${usd_m:,.0f}M", source,
        ])

    p_table = Table(p_rows, colWidths=[0.85 * inch, 1.7 * inch, 0.9 * inch, 0.85 * inch, 1.5 * inch])
    p_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), BRAND_ORANGE),
        ('TEXTCOLOR', (0, 0), (-1, 0), WHITE),
        ('GRID', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('ALIGN', (2, 0), (3, -1), 'RIGHT'),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [WHITE, CARD_BG]),
    ]))
    story.append(p_table)

    # ============================================
    # SECTION 6: SIGNALS & ACCURACY
    # ============================================
    story.append(PageBreak())
    story.append(Paragraph("6 — Signal Activity & Accuracy", styles["section"]))
    story.append(section_divider())

    acc_metrics = [
        [
            Paragraph(f"<b>{total_signals}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
            Paragraph(f"<b>{high_signals}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
            Paragraph(f"<b>{total_predictions}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
            Paragraph(f"<b>{hit_rate}%</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
            Paragraph(f"<b>{total_confirmed}</b>", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=20, textColor=BRAND_ORANGE, alignment=TA_CENTER)),
        ],
        [
            Paragraph("Total Signals", ParagraphStyle("", fontName="Helvetica", fontSize=7.5, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph("High Confidence", ParagraphStyle("", fontName="Helvetica", fontSize=7.5, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph("Predictions", ParagraphStyle("", fontName="Helvetica", fontSize=7.5, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph("Hit Rate", ParagraphStyle("", fontName="Helvetica", fontSize=7.5, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
            Paragraph("Confirmed", ParagraphStyle("", fontName="Helvetica", fontSize=7.5, textColor=TEXT_MEDIUM, alignment=TA_CENTER)),
        ],
    ]
    acc_table = Table(acc_metrics, colWidths=[1.16 * inch] * 5)
    acc_table.setStyle(TableStyle([
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, -1), CARD_BG),
        ('BOX', (0, 0), (-1, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (1, 0), (1, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (2, 0), (2, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (3, 0), (3, -1), 0.5, BORDER_GRAY),
        ('LINEBEFORE', (4, 0), (4, -1), 0.5, BORDER_GRAY),
    ]))
    story.append(acc_table)

    if all_signals[:5]:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Recent Signals", styles["subsection"]))
        for sig in all_signals[:5]:
            score = sig.get("confidence_score", 0)
            author = sig.get("author_username", "")
            text = sig.get("tweet_text", "")[:100]
            color_tag = "red" if score >= 60 else "orange" if score >= 40 else "gray"
            story.append(Paragraph(
                f"<font color='{color_tag}'><b>{score}/100</b></font> — @{author}: {text}...",
                styles["body_small"]
            ))

    # ============================================
    # SECTION 7: REGULATORY
    # ============================================
    story.append(Spacer(1, 12))
    story.append(Paragraph("7 — Global Regulatory Landscape", styles["section"]))
    story.append(section_divider())
    story.append(Paragraph(
        f"{reg_stats['total_items']} items · {reg_stats['regions_tracked']} regions · "
        f"{reg_stats['active_passed']} active · {reg_stats['pending']} pending · "
        f"{reg_stats['bullish']} bullish · Auto-updated via Google News",
        styles["caption"]
    ))

    categories = ["US Federal", "US State", "Europe", "Asia-Pacific", "Latin America", "Middle East & Africa", "Global"]
    for cat in categories:
        cat_items = [r for r in reg_items if r.get("category") == cat][:3]
        if cat_items:
            story.append(Paragraph(f"<b>{cat}</b>", styles["body"]))
            for item in cat_items:
                status_icon = "✅" if item.get("status_color") == "green" else "🟡" if item.get("status_color") == "yellow" else "❌"
                title = item.get("title", "")[:70]
                impact = item.get("btc_impact", "")
                story.append(Paragraph(f"  {status_icon} {title} [{impact}]", styles["body_small"]))

    # ============================================
    # SECTION 8: STATEMENTS
    # ============================================
    story.append(PageBreak())
    story.append(Paragraph("8 — Notable Statements — Leaders & CEOs", styles["section"]))
    story.append(section_divider())
    story.append(Paragraph(
        f"{reg_stats['total_statements']} statements · {reg_stats['bullish_statements']} bullish · "
        f"{reg_stats['bearish_statements']} bearish · Auto-updated via Google News",
        styles["caption"]
    ))

    for s in statements[:10]:
        person = s.get("person", "")
        title = s.get("title", "")
        date = s.get("date", "")
        statement = s.get("statement", "")[:150]
        impact = s.get("impact", "")
        cat_icon = "🏛️" if s.get("category") == "Government" else "💼"

        story.append(Paragraph(f"<b>{cat_icon} {person}</b> — {title} <font size=7 color='#94A3B8'>({date})</font>", styles["body"]))
        story.append(Paragraph(f'"{statement}..."', styles["quote"]))
        story.append(Paragraph(f"Impact: {impact}", styles["body_small"]))
        story.append(Spacer(1, 4))

    # ============================================
    # SECTION 9: WEEK AHEAD
    # ============================================
    story.append(Spacer(1, 8))
    story.append(Paragraph("9 — Week Ahead", styles["section"]))
    story.append(section_divider())

    for e in week_ahead:
        impact_text = f"[{e['impact']}]"
        story.append(Paragraph(
            f"<b>{e['timing']}</b> — {e['event']} <font size=8 color='#D97706'>{impact_text}</font>",
            styles["body"]
        ))
        story.append(Paragraph(e['description'][:200], styles["body_small"]))
        story.append(Spacer(1, 4))

    # ============================================
    # FINAL PAGE: DISCLAIMER
    # ============================================
    story.append(Spacer(1, 40))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_ORANGE, spaceAfter=12))
    story.append(Paragraph("TREASURY SIGNAL INTELLIGENCE™", ParagraphStyle("", fontName="Helvetica-Bold", fontSize=9, textColor=BRAND_ORANGE, alignment=TA_CENTER, spaceAfter=4)))
    story.append(Paragraph(
        "Multi-Signal Correlation Engine™ · BTC Treasury Leaderboard™ · Global Regulatory Tracker™",
        styles["footer"]
    ))
    story.append(Paragraph(
        "Data Sources: CoinGecko · BitcoinTreasuries.net · Yahoo Finance · SEC EDGAR · TwitterAPI.io · Google News RSS · alternative.me",
        styles["footer"]
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        "DISCLAIMER: This report is for informational purposes only and does not constitute financial, investment, legal, or tax advice. "
        "Past performance of signals and predictions does not guarantee future results. Bitcoin and cryptocurrency investments carry significant risk. "
        "Always conduct your own research and consult with qualified financial advisors before making investment decisions.",
        ParagraphStyle("", fontName="Helvetica", fontSize=7, textColor=TEXT_LIGHT, alignment=TA_JUSTIFY, leading=9.5)
    ))
    story.append(Spacer(1, 8))
    story.append(Paragraph(
        f"Report generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · Dashboard: treasury-signals-jqyywcwr8l8pbtv66rvbbg.streamlit.app",
        styles["footer"]
    ))

    # BUILD
    doc.build(story, onFirstPage=add_header_footer, onLaterPages=add_header_footer)
    print(f"  ✅ CEO-Grade Weekly Report saved: {output_path}")
    return output_path


if __name__ == "__main__":
    print("\nWeekly PDF Report Generator v2.0 — CEO-Grade\n")
    print("=" * 60)
    path = generate_weekly_report("weekly_report.pdf")
    print(f"\n  Open {path} to view the report!")
