"""
Fairness analysis service | computes all fairness metrics.
"""
import pandas as pd
import numpy as np
import logging
from typing import List, Optional, Dict, Any, Tuple, Union
from sklearn.preprocessing import LabelEncoder

from app.models.schemas import (
    FairnessMetrics, GroupMetric, BiasSeverity, AnalysisResponse
)

logger = logging.getLogger(__name__)

# Threshold constants
SEVERITY_LOW = 0.1
SEVERITY_MEDIUM = 0.2

POLICY_THRESHOLDS = {
    "demographic_parity_difference": 0.1,
    "equalized_odds_difference": 0.1,
    "equal_opportunity_difference": 0.1,
}


def _safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or np.isnan(denominator):
        return default
    return numerator / denominator


def _encode_binary(series: pd.Series, positive_label=None) -> Tuple[pd.Series, Any]:
    """Encode a series to 0/1 binary. Returns encoded series and the positive label used."""
    vals = series.dropna().unique()
    if len(vals) < 2:
        return series.fillna(0).astype(int), vals[0] if len(vals) == 1 else 1

    if positive_label is not None:
        pos = positive_label
    else:
        # Prefer >50K, 1, True, "yes", "high" style labels as positive
        for v in vals:
            sv = str(v).lower()
            if sv in [">50k", "1", "true", "yes", "high", "positive", "recidivated"]:
                pos = v
                break
        else:
            # pick the higher/later sorted value
            pos = sorted(vals)[-1]

    encoded = (series == pos).astype(int)
    return encoded, pos


def _get_severity(gap: float) -> BiasSeverity:
    abs_gap = abs(gap)
    if abs_gap <= SEVERITY_LOW:
        return BiasSeverity.LOW
    elif abs_gap <= SEVERITY_MEDIUM:
        return BiasSeverity.MEDIUM
    return BiasSeverity.HIGH


def _fairness_score_from_metrics(dpd: Optional[float], eod: Optional[float],
                                  eqod: Optional[float]) -> float:
    """Compute a 0–100 fairness score. 100 = perfectly fair."""
    penalties = []
    if dpd is not None:
        penalties.append(min(abs(dpd) * 200, 40))
    if eod is not None:
        penalties.append(min(abs(eod) * 200, 35))
    if eqod is not None:
        penalties.append(min(abs(eqod) * 100, 25))
    if not penalties:
        return 100.0
    total_penalty = sum(penalties)
    return max(0.0, round(100.0 - total_penalty, 1))


def _build_group_metrics(df: pd.DataFrame, sensitive_col: str,
                          y_true: pd.Series, y_pred: pd.Series) -> List[GroupMetric]:
    groups = []
    for grp_val in sorted(df[sensitive_col].dropna().unique()):
        mask = df[sensitive_col] == grp_val
        yt = y_true[mask]
        yp = y_pred[mask]
        count = int(mask.sum())
        if count == 0:
            continue

        sel_rate = float(yp.mean())
        accuracy = float((yt == yp).mean()) if len(yt) > 0 else None

        tp = int(((yp == 1) & (yt == 1)).sum())
        fp = int(((yp == 1) & (yt == 0)).sum())
        fn = int(((yp == 0) & (yt == 1)).sum())
        tn = int(((yp == 0) & (yt == 0)).sum())

        tpr = _safe_divide(tp, tp + fn)
        fpr = _safe_divide(fp, fp + tn)
        precision = _safe_divide(tp, tp + fp)

        groups.append(GroupMetric(
            group_value=str(grp_val),
            count=count,
            selection_rate=round(sel_rate, 4),
            true_positive_rate=round(tpr, 4),
            false_positive_rate=round(fpr, 4),
            accuracy=round(accuracy, 4) if accuracy is not None else None,
            precision=round(precision, 4),
        ))
    return groups


def _build_explanation(sensitive_col: str, dpd: Optional[float], dpr: Optional[float],
                        eod: Optional[float], eqod: Optional[float],
                        group_metrics: List[GroupMetric],
                        severity: BiasSeverity) -> str:
    if not group_metrics:
        return "Insufficient data to generate an explanation."

    # Find best and worst groups by selection rate
    sorted_groups = sorted(group_metrics, key=lambda g: g.selection_rate)
    worst = sorted_groups[0]
    best = sorted_groups[-1]

    lines = []
    if dpd is not None:
        gap_pct = abs(dpd) * 100
        lines.append(
            f"The model shows a demographic parity difference of {dpd:.3f} across '{sensitive_col}'. "
            f"The '{best.group_value}' group receives favorable decisions {gap_pct:.1f}% more often "
            f"than the '{worst.group_value}' group."
        )
    if eod is not None:
        lines.append(
            f"Equitable Opportunity: The true positive rate varies by {abs(eod)*100:.1f}% "
            f"across groups in '{sensitive_col}'. This indicates disparities in how correctly "
            f"positive outcomes are assigned."
        )
    if severity == BiasSeverity.HIGH:
        lines.append(
            "⚠️ This is a HIGH severity bias. Immediate remediation is recommended before deployment."
        )
    elif severity == BiasSeverity.MEDIUM:
        lines.append(
            "⚡ This is a MEDIUM severity bias. Consider applying mitigation techniques."
        )
    else:
        lines.append(
            "✅ Bias severity is LOW. The model is relatively fair across this attribute."
        )
    return " ".join(lines)


def simulate_impact(df_size: int, metrics: List[FairnessMetrics]) -> Dict[str, Any]:
    """
    Estimates the real-world impact of detected bias.
    """
    max_dpd = max([m.demographic_parity_difference for m in metrics if m.demographic_parity_difference is not None] or [0])
    affected_users = int(df_size * max_dpd)
    
    return {
        "estimated_affected_users": affected_users,
        "impact_description": f"Approximately {affected_users:,} users may be unfairly affected due to model bias based on current selection disparities."
    }


def compute_intersectional_metrics(
    df: pd.DataFrame,
    sensitive_cols: List[str],
    y_true: pd.Series,
    y_pred: pd.Series
) -> Optional[FairnessMetrics]:
    """
    Computes fairness metrics for the intersection of all sensitive columns.
    Example: gender + race.
    """
    if len(sensitive_cols) < 2:
        return None
        
    inter_col = "_intersectional_"
    df_temp = df.copy()
    df_temp[inter_col] = df_temp[sensitive_cols].astype(str).agg(' + '.join, axis=1)
    
    try:
        group_metrics = _build_group_metrics(df_temp, inter_col, y_true, y_pred)
        if not group_metrics:
            return None
            
        sel_rates = [g.selection_rate for g in group_metrics]
        dpd = round(max(sel_rates) - min(sel_rates), 4) if len(sel_rates) >= 2 else 0
        
        # Sort to find worst/best subgroup
        sorted_groups = sorted(group_metrics, key=lambda g: g.selection_rate)
        worst = sorted_groups[0]
        best = sorted_groups[-1]
        
        explanation = (
            f"Intersectional analysis across {', '.join(sensitive_cols)} shows a selection rate gap of {dpd:.3f}. "
            f"The '{best.group_value}' group has the highest favorability, while '{worst.group_value}' has the lowest."
        )
        
        score = _fairness_score_from_metrics(dpd, None, None)
        severity = _get_severity(dpd)
        
        return FairnessMetrics(
            sensitive_column="Intersectional (" + " + ".join(sensitive_cols) + ")",
            demographic_parity_difference=dpd,
            group_metrics=group_metrics,
            bias_severity=severity,
            fairness_score=score,
            explanation=explanation,
        )
    except Exception as e:
        logger.error(f"Intersectional analysis failed: {e}")
        return None


def compute_fairness_metrics(
    df: pd.DataFrame,
    target_col: str,
    sensitive_cols: List[str],
    prediction_col: Optional[str] = None,
    feature_cols: Optional[List[str]] = None,
    positive_label=None,
) -> Tuple[List[FairnessMetrics], Optional[float], Dict[str, Any]]:
    """
    Compute fairness metrics for each sensitive column + intersectional.
    Returns (list of FairnessMetrics, overall_accuracy, impact_simulation).
    """
    warnings = []

    # Validate target
    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in dataset.")

    y_true_raw = df[target_col].dropna()
    if len(y_true_raw) == 0:
        raise ValueError(f"Target column '{target_col}' has no valid values.")

    y_true_encoded, pos_label = _encode_binary(df[target_col], positive_label)
    y_true = y_true_encoded

    # If no prediction column, we can only compute selection rates from target
    if prediction_col and prediction_col in df.columns:
        y_pred_encoded, _ = _encode_binary(df[prediction_col], pos_label)
        y_pred = y_pred_encoded
    else:
        # Use target as pseudo-prediction (just show selection rates)
        y_pred = y_true.copy()
        warnings.append(
            "No prediction column provided. Showing selection rates from the target column. "
            "Upload a model prediction column for full fairness analysis."
        )

    overall_accuracy = float((y_true == y_pred).mean()) if len(y_true) > 0 else None
    results = []

    for sens_col in sensitive_cols:
        col_warnings = list(warnings)
        if sens_col not in df.columns:
            col_warnings.append(f"Sensitive column '{sens_col}' not found in dataset.")
            results.append(FairnessMetrics(
                sensitive_column=sens_col,
                bias_severity=BiasSeverity.LOW,
                fairness_score=100.0,
                warnings=col_warnings,
                explanation=f"Column '{sens_col}' not found.",
            ))
            continue

        grp_vals = df[sens_col].dropna().unique()
        if len(grp_vals) < 2:
            col_warnings.append(
                f"Sensitive column '{sens_col}' has only one unique value. "
                "Fairness metrics cannot be computed."
            )
            results.append(FairnessMetrics(
                sensitive_column=sens_col,
                bias_severity=BiasSeverity.LOW,
                fairness_score=100.0,
                warnings=col_warnings,
                explanation=f"Column '{sens_col}' contains only one group ('{grp_vals[0] if len(grp_vals)>0 else 'N/A'}'). Fairness audits require at least two groups to compare. This model assumes uniform treatment for this attribute.",
            ))
            continue

        # Align indices
        valid_idx = df[sens_col].notna() & y_true.notna() & y_pred.notna()
        df_v = df[valid_idx]
        yt = y_true[valid_idx]
        yp = y_pred[valid_idx]

        # Group metrics
        group_metrics = _build_group_metrics(df_v, sens_col, yt, yp)
        sel_rates = [g.selection_rate for g in group_metrics]
        tprs = [g.true_positive_rate for g in group_metrics if g.true_positive_rate is not None]
        fprs = [g.false_positive_rate for g in group_metrics if g.false_positive_rate is not None]

        # Demographic parity
        dpd = None
        dpr = None
        if len(sel_rates) >= 2:
            dpd = round(max(sel_rates) - min(sel_rates), 4)
            dpr = round(_safe_divide(min(sel_rates), max(sel_rates)), 4)

        # Equalized odds difference (max of TPR diff and FPR diff)
        eqod = None
        if len(tprs) >= 2 and len(fprs) >= 2:
            tpr_diff = max(tprs) - min(tprs)
            fpr_diff = max(fprs) - min(fprs)
            eqod = round(max(tpr_diff, fpr_diff), 4)

        # Equal opportunity difference (TPR diff only)
        eod = None
        if len(tprs) >= 2:
            eod = round(max(tprs) - min(tprs), 4)

        # Accuracy by group
        group_accs = [g.accuracy for g in group_metrics if g.accuracy is not None]
        overall_group_acc = float(np.mean(group_accs)) if group_accs else None

        # Severity
        max_gap = max(abs(dpd or 0), abs(eod or 0), abs(eqod or 0))
        severity = _get_severity(max_gap)

        fairness_score = _fairness_score_from_metrics(dpd, eod, eqod)
        explanation = _build_explanation(sens_col, dpd, dpr, eod, eqod, group_metrics, severity)

        results.append(FairnessMetrics(
            sensitive_column=sens_col,
            demographic_parity_difference=dpd,
            demographic_parity_ratio=dpr,
            equalized_odds_difference=eqod,
            equal_opportunity_difference=eod,
            overall_accuracy=overall_group_acc,
            group_metrics=group_metrics,
            bias_severity=severity,
            fairness_score=fairness_score,
            explanation=explanation,
            warnings=col_warnings,
        ))

    # Intersectional analysis
    inter_result = compute_intersectional_metrics(df, sensitive_cols, y_true, y_pred)
    if inter_result:
        results.append(inter_result)

    impact = simulate_impact(len(df), results)

    return results, overall_accuracy, impact


def build_policy_compliance(metrics: List[FairnessMetrics]) -> Dict[str, Any]:
    """Check if model passes common fairness policy thresholds."""
    checks = {}
    all_pass = True

    for m in metrics:
        col = m.sensitive_column
        checks[col] = {}

        if m.demographic_parity_difference is not None:
            dpd_abs = abs(m.demographic_parity_difference)
            passed = dpd_abs <= POLICY_THRESHOLDS["demographic_parity_difference"]
            checks[col]["demographic_parity"] = {
                "value": m.demographic_parity_difference,
                "threshold": POLICY_THRESHOLDS["demographic_parity_difference"],
                "passed": passed,
            }
            if not passed:
                all_pass = False

        if m.equalized_odds_difference is not None:
            eqod_abs = abs(m.equalized_odds_difference)
            passed = eqod_abs <= POLICY_THRESHOLDS["equalized_odds_difference"]
            checks[col]["equalized_odds"] = {
                "value": m.equalized_odds_difference,
                "threshold": POLICY_THRESHOLDS["equalized_odds_difference"],
                "passed": passed,
            }
            if not passed:
                all_pass = False

    return {
        "overall_pass": all_pass,
        "checks": checks,
        "standard": "80% Rule / Fairness-Aware ML Thresholds",
    }


def generate_recommendations(metrics: List[FairnessMetrics], has_prediction: bool) -> List[str]:
    recs = []
    for m in metrics:
        if m.bias_severity == BiasSeverity.HIGH:
            recs.append(f"Apply bias mitigation for '{m.sensitive_column}' | bias severity is HIGH.")
            recs.append("Consider reweighing training data or applying Fairlearn in-processing.")
        elif m.bias_severity == BiasSeverity.MEDIUM:
            recs.append(f"Review data collection for '{m.sensitive_column}' group imbalances.")
    if not has_prediction:
        recs.append("Provide a model prediction column for complete fairness analysis.")
    recs.append("Run the Explainability analysis to identify proxy features driving bias.")
    recs.append("Use the Mitigation flow to compare before/after fairness improvements.")
    if not recs:
        recs.append("Model appears relatively fair. Continue monitoring in production.")
    return recs[:6]


def build_bias_explanation(metrics: List[FairnessMetrics]) -> str:
    high = [m for m in metrics if m.bias_severity == BiasSeverity.HIGH]
    medium = [m for m in metrics if m.bias_severity == BiasSeverity.MEDIUM]

    parts = []
    if high:
        cols = ", ".join(f"'{m.sensitive_column}'" for m in high)
        parts.append(
            f"Significant bias detected for attributes: {cols}. "
            "The model treats these groups very differently in its decisions."
        )
    if medium:
        cols = ", ".join(f"'{m.sensitive_column}'" for m in medium)
        parts.append(
            f"Moderate bias found for: {cols}. "
            "Some disparity exists but may be reducible with mitigation."
        )
    if not high and not medium:
        parts.append(
            "The model shows relatively low bias across the analyzed sensitive attributes."
        )

    parts.append(
        "Common causes include imbalanced training data, proxy features, "
        "historical label bias, and underrepresentation of minority groups."
    )
    return " ".join(parts)
