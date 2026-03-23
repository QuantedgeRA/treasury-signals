"""
pdf_report.py — Board-Ready PDF Report Generator
---------------------------------------------------
Generates a professional PDF report that a CEO can forward
to their board of directors. Includes executive summary,
company position, leaderboard, competitor analysis, P&L,
regulatory landscape, and market intelligence.

Uses reportlab for PDF generation.

Usage:
    from pdf_report import generate_board_report

    pdf_path = generate_board_report(
        subscriber=profile,
        btc_price=72000,
        output_path="report.pdf",
    )

Requirements:
    pip install reportlab
"""

import os
import io
from datetime import datetime
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from logger import get_logger

logger = get_logger(__name__)

# ============================================
# BRAND COLORS
# ============================================
ORANGE = HexColor("#E67E22")
DARK_BG = HexColor("#0a0e17")
CARD_BG = HexColor("#111827")
BORDER = HexColor("#1e2a3a")
TEXT_PRIMARY = HexColor("#e0e0e0")
TEXT_SECONDARY = HexColor("#9ca3af")
TEXT_MUTED = HexColor("#6b7280")
GREEN = HexColor("#10B981")
RED = HexColor("#EF4444")
YELLOW = HexColor("#F59E0B")
BLUE = HexColor("#3B82F6")
WHITE = HexColor("#FFFFFF")
BLACK = HexColor("#000000")


def _get_styles():
    """Build custom paragraph styles for the report."""
    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="ReportTitle",
        fontSize=22, leading=28, textColor=ORANGE,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle",
        fontSize=10, leading=14, textColor=TEXT_MUTED,
        fontName="Helvetica", alignment=TA_LEFT,
        spaceAfter=16,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeader",
        fontSize=14, leading=18, textColor=ORANGE,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        spaceBefore=16, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="SubHeader",
        fontSize=11, leading=14, textColor=WHITE,
        fontName="Helvetica-Bold", alignment=TA_LEFT,
        spaceBefore=10, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="Body",
        fontSize=10, leading=14, textColor=BLACK,
        fontName="Helvetica", alignment=TA_LEFT,
        spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="BodySmall",
        fontSize=9, leading=12, textColor=TEXT_MUTED,
        fontName="Helvetica", alignment=TA_LEFT,
        spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="MetricValue",
        fontSize=18, leading=22, textColor=ORANGE,
        fontName="Helvetica-Bold", alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="MetricLabel",
        fontSize=8, leading=10, textColor=TEXT_MUTED,
        fontName="Helvetica", alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="Footer",
        fontSize=7, leading=10, textColor=TEXT_MUTED,
        fontName="Helvetica", alignment=TA_CENTER,
    ))
    styles.add(ParagraphStyle(
        name="Disclaimer",
        fontSize=7, leading=9, textColor=TEXT_MUTED,
        fontName="Helvetica-Oblique", alignment=TA_LEFT,
        spaceBefore=8,
    ))

    return styles


def _header_footer(canvas, doc):
    """Add header and footer to each page."""
    canvas.saveState()
    width, height = letter

    # Top orange bar
    canvas.setFillColor(ORANGE)
    canvas.rect(0, height - 4, width, 4, fill=1, stroke=0)

    # Header text
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(ORANGE)
    canvas.drawString(54, height - 28, "TREASURY SIGNAL INTELLIGENCE")

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(HexColor("#6b7280"))
    canvas.drawRightString(width - 54, height - 28, f"Board Report  |  {datetime.now().strftime('%B %d, %Y')}")

    # Header line
    canvas.setStrokeColor(HexColor("#1e2a3a"))
    canvas.setLineWidth(0.5)
    canvas.line(54, height - 34, width - 54, height - 34)

    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(HexColor("#6b7280"))
    canvas.drawString(54, 30, "Treasury Signal Intelligence  |  Confidential")
    canvas.drawRightString(width - 54, 30, f"Page {doc.page}")

    # Bottom orange bar
    canvas.setFillColor(ORANGE)
    canvas.rect(0, 0, width, 3, fill=1, stroke=0)

    canvas.restoreState()


def _make_metric_table(metrics):
    """Create a row of metric boxes."""
    cells = []
    for m in metrics:
        val_color = m.get("color", ORANGE)
        cell_content = [
            Paragraph(str(m["value"]), ParagraphStyle("mv", fontSize=16, leading=20, textColor=val_color, fontName="Helvetica-Bold", alignment=TA_CENTER)),
            Paragraph(m["label"], ParagraphStyle("ml", fontSize=8, leading=10, textColor=TEXT_MUTED, fontName="Helvetica", alignment=TA_CENTER)),
        ]
        if m.get("subtitle"):
            cell_content.append(Paragraph(m["subtitle"], ParagraphStyle("ms", fontSize=7, leading=9, textColor=TEXT_SECONDARY, fontName="Helvetica", alignment=TA_CENTER)))
        cells.append(cell_content)

    col_width = (letter[0] - 108) / len(metrics)
    table = Table([cells], colWidths=[col_width] * len(metrics))
    table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
    ]))
    return table


def _make_leaderboard_table(companies, subscriber_ticker="", max_rows=15):
    """Create a leaderboard table."""
    header = ["#", "Company", "BTC Holdings", "Value ($B)", "P&L"]
    rows = [header]

    for c in companies[:max_rows]:
        if c.get("btc_holdings", 0) <= 0:
            continue
        pnl = f"{c.get('unrealized_pnl_pct', 0):+.1f}%" if c.get("unrealized_pnl_pct") else "N/A"
        rows.append([
            str(c.get("rank", "")),
            c.get("company", "")[:35],
            f"{c.get('btc_holdings', 0):,}",
            f"${c.get('btc_value_b', 0):.2f}",
            pnl,
        ])

    col_widths = [30, 200, 90, 80, 60]
    table = Table(rows, colWidths=col_widths)

    style_commands = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE),
        ("TEXTCOLOR", (0, 1), (-1, -1), BLACK),
        ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 1, ORANGE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.25, BORDER),
    ]

    # Highlight subscriber's company
    if subscriber_ticker:
        for i, row in enumerate(rows[1:], start=1):
            company_text = row[1]
            if subscriber_ticker in company_text:
                style_commands.append(("BACKGROUND", (0, i), (-1, i), HexColor("#1a0f00")))
                style_commands.append(("TEXTCOLOR", (0, i), (-1, i), ORANGE))

    table.setStyle(TableStyle(style_commands))
    return table


def generate_board_report(subscriber, btc_price, output_path=None):
    """
    Generate a complete board-ready PDF report.

    Args:
        subscriber: Subscriber profile dict
        btc_price: Current BTC price
        output_path: Where to save the PDF (default: auto-generated filename)

    Returns:
        Path to the generated PDF file, or bytes buffer if no path given.
    """
    logger.info(f"Generating board report for {subscriber.get('company_name', 'Unknown')}...")

    styles = _get_styles()
    story = []

    company_name = subscriber.get("company_name", "Your Company")
    subscriber_name = subscriber.get("name", "")
    ticker = subscriber.get("ticker", "")
    btc_holdings = float(subscriber.get("btc_holdings", 0))
    total_cost = float(subscriber.get("total_invested_usd", 0))
    avg_price = float(subscriber.get("avg_purchase_price", 0))
    sector = subscriber.get("sector", "")

    btc_value = btc_holdings * btc_price
    pnl = btc_value - total_cost if total_cost > 0 else 0
    pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0

    today = datetime.now().strftime("%B %d, %Y")
    time_now = datetime.now().strftime("%I:%M %p ET")

    # =========================================
    # PAGE 1: COVER + EXECUTIVE SUMMARY
    # =========================================

    story.append(Spacer(1, 40))
    story.append(Paragraph("Board Intelligence Report", styles["ReportTitle"]))
    story.append(Paragraph(f"{company_name}  |  {today}  |  {time_now}", styles["ReportSubtitle"]))
    story.append(Paragraph(f"Prepared for {subscriber_name}" if subscriber_name else "Treasury Signal Intelligence", styles["BodySmall"]))
    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1, color=ORANGE))
    story.append(Spacer(1, 16))

    # Market snapshot metrics
    try:
        from email_briefing import get_market_data
        market = get_market_data()
    except Exception:
        market = {"btc_price": btc_price, "btc_change": 0, "mstr_price": 0, "mstr_change": 0, "strc_ratio": 0}

    btc_change = market.get("btc_change", 0)
    btc_change_color = GREEN if btc_change >= 0 else RED

    story.append(Paragraph("Market Snapshot", styles["SectionHeader"]))
    story.append(_make_metric_table([
        {"value": f"${btc_price:,.0f}", "label": "BITCOIN PRICE", "subtitle": f"{'+'if btc_change>=0 else ''}{btc_change:.1f}%", "color": btc_change_color},
        {"value": f"${market.get('mstr_price', 0):,.0f}", "label": "MSTR PRICE", "color": ORANGE},
        {"value": f"{market.get('strc_ratio', 0):.1f}x", "label": "STRC VOLUME RATIO", "color": YELLOW if market.get("strc_ratio", 0) >= 1.5 else GREEN},
    ]))
    story.append(Spacer(1, 16))

    # Company position
    if btc_holdings > 0:
        story.append(Paragraph(f"Your Position: {company_name}", styles["SectionHeader"]))

        position_metrics = [
            {"value": f"{btc_holdings:,.0f}", "label": "BTC HOLDINGS", "color": ORANGE},
            {"value": f"${btc_value/1_000_000:,.1f}M", "label": "CURRENT VALUE", "color": WHITE},
        ]
        if total_cost > 0:
            pnl_color = GREEN if pnl >= 0 else RED
            position_metrics.append({"value": f"{pnl_pct:+.1f}%", "label": "UNREALIZED P&L", "subtitle": f"${pnl/1_000_000:+,.1f}M", "color": pnl_color})
            position_metrics.append({"value": f"${avg_price:,.0f}", "label": "AVG COST BASIS", "color": WHITE})

        # Get rank
        try:
            from subscriber_manager import subscribers as sub_mgr
            position = sub_mgr.get_leaderboard_position(subscriber["email"], btc_price)
            if position:
                position_metrics.insert(0, {"value": f"#{position['rank']}", "label": f"OF {position['total_companies']} COMPANIES", "color": ORANGE})
        except Exception:
            pass

        story.append(_make_metric_table(position_metrics[:5]))
        story.append(Spacer(1, 12))

        # Gap to next rank
        try:
            if position and position.get("next_rank_gap", 0) > 0:
                gap = position["next_rank_gap"]
                gap_cost = gap * btc_price
                story.append(Paragraph(
                    f"To move to #{position['rank']-1}: acquire {gap:,.0f} additional BTC (${gap_cost/1_000_000:,.1f}M at current price)",
                    styles["Body"]
                ))
        except Exception:
            pass

    story.append(Spacer(1, 12))

    # Risk Dashboard
    try:
        from market_intelligence import get_risk_dashboard, generate_action_signal
        risk = get_risk_dashboard()

        story.append(Paragraph("Risk Assessment", styles["SectionHeader"]))
        risk_color = RED if risk["risk_level"] == "HIGH" else YELLOW if "ELEVATED" in risk["risk_level"] else GREEN
        story.append(_make_metric_table([
            {"value": str(risk["fear_greed_value"]), "label": "FEAR & GREED INDEX", "subtitle": risk["fear_greed_label"], "color": risk_color},
            {"value": f"{risk['volatility_30d']}%", "label": "30-DAY VOLATILITY", "color": YELLOW if risk["volatility_30d"] > 50 else GREEN},
            {"value": f"{risk['drawdown_from_ath']}%", "label": "FROM ALL-TIME HIGH", "color": RED},
            {"value": risk["risk_level"], "label": "OVERALL RISK", "color": risk_color},
        ]))
    except Exception as e:
        logger.debug(f"Risk dashboard unavailable for PDF: {e}")

    # =========================================
    # PAGE 2: LEADERBOARD
    # =========================================
    story.append(PageBreak())
    story.append(Paragraph("BTC Treasury Leaderboard", styles["SectionHeader"]))

    try:
        from treasury_leaderboard import get_leaderboard_with_live_price
        companies, lb_summary = get_leaderboard_with_live_price(btc_price)

        story.append(Paragraph(
            f"{lb_summary['total_companies']} entities  |  {lb_summary['total_btc']:,} BTC  |  "
            f"${lb_summary['total_value_b']:.1f}B total value",
            styles["BodySmall"]
        ))
        story.append(Spacer(1, 8))

        # Top 15 corporate
        corporate = [c for c in companies if not c.get("is_government") and c.get("btc_holdings", 0) > 0][:15]
        story.append(Paragraph("Top 15 Corporate Holders", styles["SubHeader"]))
        story.append(_make_leaderboard_table(corporate, subscriber_ticker=ticker))
        story.append(Spacer(1, 12))

        # Top 5 sovereign
        sovereign = [c for c in companies if c.get("is_government") and c.get("btc_holdings", 0) > 0][:5]
        if sovereign:
            story.append(Paragraph("Top Sovereign/Government Holders", styles["SubHeader"]))
            story.append(_make_leaderboard_table(sovereign))
    except Exception as e:
        logger.warning(f"Leaderboard unavailable for PDF: {e}")
        story.append(Paragraph("Leaderboard data unavailable.", styles["Body"]))

    # =========================================
    # PAGE 3: PURCHASES + REGULATORY
    # =========================================
    story.append(PageBreak())

    # Recent purchases
    story.append(Paragraph("Recent BTC Purchases", styles["SectionHeader"]))
    try:
        from purchase_tracker import get_recent_purchases
        purchases = get_recent_purchases(10)

        if purchases:
            header = ["Date", "Company", "BTC", "USD", "$/BTC"]
            rows = [header]
            for p in purchases[:10]:
                rows.append([
                    p.get("filing_date", ""),
                    p.get("company", "")[:25],
                    f"{p.get('btc_amount', 0):,}",
                    f"${p.get('usd_amount', 0)/1_000_000:,.0f}M",
                    f"${p.get('price_per_btc', 0):,.0f}",
                ])

            t = Table(rows, colWidths=[70, 160, 70, 70, 70])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE),
                ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("LINEBELOW", (0, 0), (-1, 0), 1, ORANGE),
                ("LINEBELOW", (0, 1), (-1, -2), 0.25, BORDER),
            ]))
            story.append(t)
        else:
            story.append(Paragraph("No recent purchases detected.", styles["Body"]))
    except Exception as e:
        logger.debug(f"Purchases unavailable for PDF: {e}")

    story.append(Spacer(1, 20))

    # Regulatory landscape
    story.append(Paragraph("Global Regulatory Landscape", styles["SectionHeader"]))
    try:
        from regulatory_tracker import get_summary_stats
        reg = get_summary_stats()

        story.append(Paragraph(
            f"Tracking {reg['total_items']} regulatory items across {reg['regions_tracked']} regions. "
            f"{reg['active_passed']} active/passed, {reg['pending']} pending, "
            f"{reg['bullish']} bullish for Bitcoin.",
            styles["Body"]
        ))
        story.append(Spacer(1, 6))

        reg_data = [
            ["Region", "Items"],
            ["US Federal", str(reg.get("us_federal", 0))],
            ["US State", str(reg.get("us_state", 0))],
            ["Europe", str(reg.get("europe", 0))],
            ["Asia-Pacific", str(reg.get("asia_pacific", 0))],
            ["Latin America", str(reg.get("latin_america", 0))],
            ["Middle East & Africa", str(reg.get("middle_east_africa", 0))],
        ]
        t = Table(reg_data, colWidths=[160, 60])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, 0), ORANGE),
            ("ALIGN", (1, 0), (1, -1), "CENTER"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 0), (-1, 0), 1, ORANGE),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, BORDER),
        ]))
        story.append(t)
    except Exception as e:
        logger.debug(f"Regulatory data unavailable for PDF: {e}")

    # =========================================
    # DISCLAIMER
    # =========================================
    story.append(Spacer(1, 30))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BORDER))
    story.append(Paragraph(
        "This report is for informational purposes only and does not constitute financial, "
        "investment, or legal advice. Data sourced from TwitterAPI.io, Yahoo Finance, SEC EDGAR, "
        "CoinGecko, BitcoinTreasuries.net, and Google News RSS. Treasury Signal Intelligence "
        "makes no guarantee of data accuracy or completeness. Past performance is not indicative "
        "of future results. All investment decisions should be made in consultation with qualified "
        "financial and legal advisors.",
        styles["Disclaimer"]
    ))
    story.append(Spacer(1, 6))
    story.append(Paragraph(
        f"Generated by Treasury Signal Intelligence  |  {today}  |  Confidential",
        styles["Footer"]
    ))

    # =========================================
    # BUILD PDF
    # =========================================
    if output_path:
        doc = SimpleDocTemplate(
            output_path, pagesize=letter,
            topMargin=50, bottomMargin=50,
            leftMargin=54, rightMargin=54,
        )
        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        logger.info(f"Board report saved to {output_path}")
        return output_path
    else:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter,
            topMargin=50, bottomMargin=50,
            leftMargin=54, rightMargin=54,
        )
        doc.build(story, onFirstPage=_header_footer, onLaterPages=_header_footer)
        buffer.seek(0)
        logger.info(f"Board report generated (in-memory buffer)")
        return buffer


# ============================================
# QUICK TEST
# ============================================
if __name__ == "__main__":
    logger.info("PDF Report Generator — testing...")

    mock_profile = {
        "name": "John Smith",
        "email": "john@test.com",
        "company_name": "Acme Corp",
        "ticker": "ACME",
        "sector": "Software / Tech",
        "btc_holdings": 500,
        "avg_purchase_price": 48000,
        "total_invested_usd": 24000000,
    }

    path = generate_board_report(mock_profile, btc_price=72000, output_path="test_board_report.pdf")
    print(f"\nReport generated: {path}")
    logger.info("PDF Report test complete")
