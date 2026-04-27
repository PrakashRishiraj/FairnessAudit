"""
Report service: generates JSON and PDF audit reports.
"""
import json
import io
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def generate_json_report(
    analysis: Optional[Dict] = None,
    explain: Optional[Dict] = None,
    mitigation: Optional[Dict] = None,
) -> Dict[str, Any]:
    report = {
        "report_metadata": {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "tool": "FairnessAudit Platform v1.0",
            "purpose": "AI Fairness Audit Report",
        },
        "sections": {},
    }

    if analysis:
        report["sections"]["fairness_analysis"] = {
            "dataset_summary": analysis.get("dataset_summary", {}),
            "overall_fairness_score": analysis.get("overall_fairness_score"),
            "overall_bias_severity": analysis.get("overall_bias_severity"),
            "bias_explanation": analysis.get("bias_explanation"),
            "metrics": analysis.get("metrics", []),
            "policy_compliance": analysis.get("policy_compliance", {}),
            "recommendations": analysis.get("recommendations", []),
            "impact_simulation": analysis.get("impact_simulation", {}),
            "decision_summary": analysis.get("decision_summary"),
            "timestamp": analysis.get("timestamp"),
            "version": analysis.get("version", "v1.0"),
        }

    if explain:
        report["sections"]["explainability"] = {
            "model_type": explain.get("model_type"),
            "top_features": explain.get("top_features", []),
            "proxy_features": explain.get("proxy_features", []),
            "explanation_text": explain.get("explanation_text"),
        }

    if mitigation:
        report["sections"]["mitigation"] = {
            "best_method": mitigation.get("best_method"),
            "overall_recommendation": mitigation.get("overall_recommendation"),
            "results_summary": [
                {
                    "method": r.get("method"),
                    "method_display_name": r.get("method_display_name"),
                    "fairness_score_before": r.get("fairness_score_before"),
                    "fairness_score_after": r.get("fairness_score_after"),
                    "fairness_improvement": r.get("fairness_improvement"),
                    "accuracy_delta": r.get("accuracy_delta"),
                    "tradeoff_summary": r.get("tradeoff_summary"),
                }
                for r in mitigation.get("results", [])
            ],
        }

    # Executive summary
    overall_score = (analysis or {}).get("overall_fairness_score", "N/A")
    severity = (analysis or {}).get("overall_bias_severity", "Unknown")
    recs = (analysis or {}).get("recommendations", [])
    best_method = (mitigation or {}).get("best_method", "N/A") if mitigation else "N/A"

    report["executive_summary"] = {
        "overall_fairness_score": overall_score,
        "bias_severity": severity,
        "key_findings": [
            f"Overall fairness score: {overall_score}/100",
            f"Bias severity: {severity}",
            f"Best mitigation method: {best_method}",
        ],
        "recommended_actions": recs[:3],
    }

    return report


def generate_pdf_report(report_data: Dict[str, Any]) -> bytes:
    """Generate a PDF report using ReportLab."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.lib import colors
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
        )

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter,
                                rightMargin=0.75 * inch, leftMargin=0.75 * inch,
                                topMargin=1 * inch, bottomMargin=0.75 * inch)

        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "title", parent=styles["Title"],
            fontSize=22, textColor=colors.HexColor("#1f6feb"), spaceAfter=6,
        )
        h2_style = ParagraphStyle(
            "h2", parent=styles["Heading2"],
            fontSize=14, textColor=colors.HexColor("#1e293b"), spaceBefore=12,
        )
        body_style = ParagraphStyle(
            "body", parent=styles["Normal"],
            fontSize=10, textColor=colors.HexColor("#334155"), leading=14,
        )

        story = []

        # Title
        story.append(Paragraph("FairnessAudit | AI Bias Audit Report", title_style))
        meta = report_data.get("report_metadata", {})
        story.append(Paragraph(f"Generated: {meta.get('generated_at', '')}", body_style))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 0.2 * inch))

        # Executive Summary
        summary = report_data.get("executive_summary", {})
        story.append(Paragraph("Executive Summary", h2_style))
        score = summary.get("overall_fairness_score", "N/A")
        severity = summary.get("bias_severity", "N/A")
        story.append(Paragraph(f"<b>Overall Fairness Score:</b> {score}/100", body_style))
        story.append(Paragraph(f"<b>Bias Severity:</b> {severity}", body_style))
        story.append(Spacer(1, 0.1 * inch))

        # Recommendations
        recs = summary.get("recommended_actions", [])
        if recs:
            story.append(Paragraph("Recommended Actions:", body_style))
            for rec in recs:
                story.append(Paragraph(f"• {rec}", body_style))

        story.append(Spacer(1, 0.2 * inch))

        # Fairness Analysis
        fa = report_data.get("sections", {}).get("fairness_analysis", {})
        if fa:
            story.append(Paragraph("Fairness Analysis", h2_style))
            story.append(Paragraph(fa.get("bias_explanation", ""), body_style))
            story.append(Spacer(1, 0.1 * inch))

            metrics = fa.get("metrics", [])
            for m in metrics:
                sens = m.get("sensitive_column", "")
                story.append(Paragraph(f"Sensitive Attribute: {sens}", h2_style))

                data = [["Metric", "Value"]]
                if m.get("demographic_parity_difference") is not None:
                    data.append(["Demographic Parity Difference", f"{m['demographic_parity_difference']:.4f}"])
                if m.get("demographic_parity_ratio") is not None:
                    data.append(["Demographic Parity Ratio", f"{m['demographic_parity_ratio']:.4f}"])
                if m.get("equalized_odds_difference") is not None:
                    data.append(["Equalized Odds Difference", f"{m['equalized_odds_difference']:.4f}"])
                if m.get("equal_opportunity_difference") is not None:
                    data.append(["Equal Opportunity Difference", f"{m['equal_opportunity_difference']:.4f}"])
                data.append(["Fairness Score", f"{m.get('fairness_score', 0):.1f}/100"])
                data.append(["Bias Severity", m.get("bias_severity", "Unknown")])

                t = Table(data, colWidths=[3 * inch, 2 * inch])
                t.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f6feb")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]))
                story.append(t)
                story.append(Spacer(1, 0.1 * inch))

        # Mitigation
        mit = report_data.get("sections", {}).get("mitigation", {})
        if mit:
            story.append(Paragraph("Mitigation Results", h2_style))
            story.append(Paragraph(f"Best Method: {mit.get('best_method', 'N/A')}", body_style))
            story.append(Paragraph(mit.get("overall_recommendation", ""), body_style))

        doc.build(story)
        return buffer.getvalue()

    except ImportError:
        logger.warning("ReportLab not available. Returning JSON as bytes.")
        return json.dumps(report_data, indent=2).encode()
    except Exception as e:
        logger.error(f"PDF generation failed: {e}")
        return json.dumps(report_data, indent=2).encode()
