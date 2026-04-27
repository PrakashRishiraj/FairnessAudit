"""
Main API routes for the FairnessAudit backend.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
import io
from datetime import datetime

from app.core.config import settings
from app.core.errors import AppError
from app.models.schemas import (
    HealthResponse, UploadResponse, SampleDatasetsResponse,
    AnalysisRequest, AnalysisResponse,
    ExplainRequest, ExplainResponse,
    MitigationRequest, MitigationResponse,
    ReportRequest, BiasSeverity,
    AiInsightsRequest, AiInsightsResponse,
    ChatRequest, ComplianceResponse,
    ScenarioRequest, ScenarioResponse,
)
from app.services.data_service import (
    process_upload, get_sample_datasets_meta, load_sample_dataset,
    get_or_load_df, store_session,
)
from app.services.fairness_service import (
    compute_fairness_metrics, build_policy_compliance,
    generate_recommendations, build_bias_explanation,
)
from app.services.explainability_service import compute_explanations
from app.services.mitigation_service import run_mitigation
from app.services.report_service import generate_json_report, generate_pdf_report
from app.services.proxy_service import detect_proxy_features
from app.services.google_drive_service import drive_service
from app.services.gemini_service import generate_ai_insights, chat_with_report, generate_decision_summary
from app.services.compliance_service import check_compliance
from app.services.monitoring_service import track_monitoring_metrics, get_drift_data
from app.services.certificate_service import generate_compliance_certificate
from pydantic import BaseModel
router = APIRouter()
logger = logging.getLogger(__name__)


# ── Health ───────────────────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        services={"database": "ok", "fairness": "ok", "shap": "ok"},
    )


# ── Upload ───────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse)
async def upload_csv(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise AppError("Only CSV files are accepted.", status_code=400)

    contents = await file.read()
    if len(contents) == 0:
        raise AppError("Uploaded file is empty.", status_code=400)

    size_mb = len(contents) / (1024 * 1024)
    if size_mb > settings.MAX_FILE_SIZE_MB:
        raise AppError(
            f"File too large ({size_mb:.1f} MB). Maximum allowed is {settings.MAX_FILE_SIZE_MB} MB.",
            status_code=413,
        )

    try:
        result = await process_upload(contents, file.filename)
        return result
    except ValueError as e:
        raise AppError(str(e), status_code=422)
    except Exception as e:
        logger.error(f"Upload failed: {e}", exc_info=True)
        raise AppError("Failed to process uploaded file.", status_code=500)


# ── Sample Datasets ──────────────────────────────────────────────────────────

@router.get("/sample-datasets", response_model=SampleDatasetsResponse)
async def list_sample_datasets():
    datasets = get_sample_datasets_meta()
    return SampleDatasetsResponse(datasets=datasets)


# ── Analysis ─────────────────────────────────────────────────────────────────

@router.post("/analyze", response_model=AnalysisResponse)
async def analyze(req: AnalysisRequest):
    if not req.session_id and not req.sample_dataset_id:
        raise AppError("Either session_id or sample_dataset_id must be provided.", status_code=400)
    if not req.sensitive_columns:
        raise AppError("At least one sensitive column must be specified.", status_code=400)
    if not req.target_column:
        raise AppError("Target column must be specified.", status_code=400)

    try:
        df = get_or_load_df(req.session_id, req.sample_dataset_id)
    except ValueError as e:
        raise AppError(str(e), status_code=404)

    # Persist loaded sample dataset with session_id for reuse
    session_id = req.session_id or req.sample_dataset_id
    store_session(df, session_id)

    try:
        metrics, overall_accuracy, impact = compute_fairness_metrics(
            df=df,
            target_col=req.target_column,
            sensitive_cols=req.sensitive_columns,
            prediction_col=req.prediction_column,
            feature_cols=req.feature_columns,
            positive_label=req.positive_label,
        )
    except ValueError as e:
        raise AppError(str(e), status_code=422)
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise AppError("Fairness analysis failed unexpectedly.", status_code=500)

    # Overall scores
    if metrics:
        scores = [m.fairness_score for m in metrics]
        overall_score = round(sum(scores) / len(scores), 1)
        severities = [m.bias_severity for m in metrics]
        if any(s == BiasSeverity.HIGH for s in severities):
            overall_severity = BiasSeverity.HIGH
        elif any(s == BiasSeverity.MEDIUM for s in severities):
            overall_severity = BiasSeverity.MEDIUM
        else:
            overall_severity = BiasSeverity.LOW
    else:
        overall_score = 100.0
        overall_severity = BiasSeverity.LOW

    policy = build_policy_compliance(metrics)
    recs = generate_recommendations(metrics, bool(req.prediction_column))
    bias_exp = build_bias_explanation(metrics)

    dataset_summary = {
        "num_rows": len(df),
        "num_cols": len(df.columns),
        "target_column": req.target_column,
        "prediction_column": req.prediction_column,
        "sensitive_columns": req.sensitive_columns,
        "feature_columns": req.feature_columns,
        "overall_accuracy": round(overall_accuracy, 4) if overall_accuracy else None,
    }

    warnings = []
    
    if req.feature_columns:
        proxy_warnings = detect_proxy_features(df, req.sensitive_columns, req.feature_columns)
        for pw in proxy_warnings:
            warnings.append(f"Proxy Alert: '{pw['feature']}' correlates strongly with '{pw['sensitive_column']}' ({pw['association_type']}: {pw['association_score']})")

    for m in metrics:
        warnings.extend(m.warnings)

    # Decision Summary
    summary_data = {
        "metrics": [m.dict() for m in metrics],
        "overall_fairness_score": overall_score,
        "overall_bias_severity": overall_severity,
    }
    decision_summary = await generate_decision_summary(summary_data)

    return AnalysisResponse(
        session_id=session_id,
        dataset_summary=dataset_summary,
        metrics=metrics,
        overall_fairness_score=overall_score,
        overall_bias_severity=overall_severity,
        bias_explanation=bias_exp,
        policy_compliance=policy,
        recommendations=recs,
        impact_simulation=impact,
        decision_summary=decision_summary,
        warnings=list(set(warnings)),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ── Explain ──────────────────────────────────────────────────────────────────

@router.post("/explain", response_model=ExplainResponse)
async def explain(req: ExplainRequest):
    if not req.session_id and not req.sample_dataset_id:
        raise AppError("Either session_id or sample_dataset_id must be provided.", status_code=400)

    try:
        df = get_or_load_df(req.session_id, req.sample_dataset_id)
    except ValueError as e:
        raise AppError(str(e), status_code=404)

    if not req.feature_columns:
        raise AppError("At least one feature column must be specified for explainability.", status_code=400)

    try:
        result = compute_explanations(
            df=df,
            target_col=req.target_column,
            feature_cols=req.feature_columns,
            sensitive_cols=req.sensitive_columns,
            prediction_col=req.prediction_column,
            positive_label=req.positive_label,
        )
        result.session_id = req.session_id or req.sample_dataset_id or "explain"
        return result
    except Exception as e:
        logger.error(f"Explain failed: {e}", exc_info=True)
        raise AppError(f"Explainability computation failed: {str(e)}", status_code=500)


# ── Mitigate ─────────────────────────────────────────────────────────────────

@router.post("/mitigate", response_model=MitigationResponse)
async def mitigate(req: MitigationRequest):
    if not req.session_id and not req.sample_dataset_id:
        raise AppError("Either session_id or sample_dataset_id must be provided.", status_code=400)

    try:
        df = get_or_load_df(req.session_id, req.sample_dataset_id)
    except ValueError as e:
        raise AppError(str(e), status_code=404)

    if not req.feature_columns:
        raise AppError("Feature columns are required for mitigation.", status_code=400)

    methods = ["reweighing", "exponentiated_gradient"]

    try:
        result = run_mitigation(
            df=df,
            target_col=req.target_column,
            feature_cols=req.feature_columns,
            sensitive_cols=req.sensitive_columns,
            methods=methods,
            positive_label=req.positive_label,
        )
        result.session_id = req.session_id or req.sample_dataset_id or "mitigate"
        return result
    except ValueError as e:
        raise AppError(str(e), status_code=422)
    except Exception as e:
        logger.error(f"Mitigation failed: {e}", exc_info=True)
        raise AppError(f"Mitigation failed: {str(e)}", status_code=500)


# ── Report ───────────────────────────────────────────────────────────────────

@router.post("/dataset/mitigated/download")
async def download_mitigated_dataset(req: MitigationRequest):
    if not req.session_id and not req.sample_dataset_id:
        raise AppError("Either session_id or sample_dataset_id must be provided.", status_code=400)

    try:
        df = get_or_load_df(req.session_id, req.sample_dataset_id)
    except ValueError as e:
        raise AppError(str(e), status_code=404)

    if not req.feature_columns:
        raise AppError("Feature columns are required for mitigation.", status_code=400)

    from app.services.mitigation_service import get_mitigated_dataset
    try:
        mitigated_df = get_mitigated_dataset(
            df=df,
            target_col=req.target_column,
            feature_cols=req.feature_columns,
            sensitive_cols=req.sensitive_columns,
            method=req.method,
            positive_label=req.positive_label,
        )
        import io
        stream = io.StringIO()
        mitigated_df.to_csv(stream, index=False)
        response = Response(content=stream.getvalue(), media_type="text/csv")
        response.headers["Content-Disposition"] = f"attachment; filename=mitigated_dataset.csv"
        return response
    except Exception as e:
        logger.error(f"Download mitigated dataset failed: {e}", exc_info=True)
        raise AppError(f"Failed to generate mitigated dataset: {str(e)}", status_code=500)


# ── Report ───────────────────────────────────────────────────────────────────

@router.post("/report")
async def generate_report(req: ReportRequest):
    report = generate_json_report(
        analysis=req.analysis_response,
        explain=req.explain_response,
        mitigation=req.mitigation_response,
    )

    if req.format == "pdf":
        pdf_bytes = generate_pdf_report(report)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=fairness_audit_report.pdf"},
        )

    return JSONResponse(content=report)


# ── AI Insights & Chat ───────────────────────────────────────────────────────

@router.post("/ai-insights", response_model=AiInsightsResponse)
async def get_ai_insights(req: AiInsightsRequest):
    try:
        insights = await generate_ai_insights(req.analysis_data)
        return AiInsightsResponse(**insights)
    except Exception as e:
        logger.error(f"AI Insights failed: {e}")
        raise AppError("Failed to generate AI insights.", status_code=500)


@router.post("/chat")
async def chat_report(req: ChatRequest):
    try:
        reply = await chat_with_report(req.query, req.report_context, step=req.step)
        return {"reply": reply}
    except Exception as e:
        logger.error(f"Chat failed: {e}")
        raise AppError("Chat failed.", status_code=500)


@router.get("/chat/suggestions/{step}")
async def get_chat_suggestions(step: str):
    from app.services.gemini_service import STEP_SUGGESTIONS
    suggestions = STEP_SUGGESTIONS.get(step, STEP_SUGGESTIONS["report"])
    return {"suggestions": suggestions}


# ── Compliance ───────────────────────────────────────────────────────────────

@router.post("/compliance", response_model=ComplianceResponse)
async def run_compliance(req: AiInsightsRequest):  # Reusing request format
    try:
        # req.analysis_data["metrics"] contains the dictified metrics
        metrics = req.analysis_data.get("metrics", [])
        result = check_compliance(metrics)
        return ComplianceResponse(**result)
    except Exception as e:
        logger.error(f"Compliance check failed: {e}")
        raise AppError("Compliance check failed.", status_code=500)


# ── Monitoring ───────────────────────────────────────────────────────────────

class MonitorRequest(BaseModel):
    session_id: str
    metrics: list

@router.post("/monitor")
async def log_monitor(req: MonitorRequest):
    try:
        track_monitoring_metrics(req.session_id, req.metrics)
        return {"status": "success", "message": "Metrics logged"}
    except Exception as e:
        logger.error(f"Monitoring log failed: {e}")
        raise AppError("Monitoring log failed.", status_code=500)


@router.get("/monitoring/history")
async def get_monitor_history():
    try:
        data = get_drift_data()
        return {"history": data}
    except Exception as e:
        logger.error(f"Get monitoring history failed: {e}")
        raise AppError("Failed to fetch monitoring history.", status_code=500)


# ── Scenario Simulator ───────────────────────────────────────────────────────

@router.post("/simulate-scenario", response_model=ScenarioResponse)
async def simulate_scenario(req: ScenarioRequest):
    """Recalculate fairness metrics at a different decision threshold."""
    try:
        df = get_or_load_df(req.session_id, req.sample_dataset_id)
    except ValueError as e:
        raise AppError(str(e), status_code=404)

    if req.probability_column not in df.columns:
        raise AppError(
            f"Probability column '{req.probability_column}' not found. "
            "The Scenario Simulator requires a continuous probability column.",
            status_code=400,
        )
    if req.target_column not in df.columns:
        raise AppError(f"Target column '{req.target_column}' not found.", status_code=400)

    import numpy as np
    from app.services.fairness_service import _encode_binary, _fairness_score_from_metrics

    probs = df[req.probability_column].astype(float)
    y_pred_new = (probs >= req.threshold).astype(int)
    y_true, _ = _encode_binary(df[req.target_column], req.positive_label)

    accuracy = float((y_true == y_pred_new).mean())

    # Compute group selection rates for all sensitive cols combined
    group_rates: dict = {}
    all_dpds = []
    for sens_col in req.sensitive_columns:
        if sens_col not in df.columns:
            continue
        for grp_val in sorted(df[sens_col].dropna().unique()):
            mask = df[sens_col] == grp_val
            rate = float(y_pred_new[mask].mean())
            group_rates[f"{sens_col}:{grp_val}"] = round(rate, 4)
        rates = [group_rates[k] for k in group_rates if k.startswith(f"{sens_col}:")]
        if len(rates) >= 2:
            all_dpds.append(max(rates) - min(rates))

    dpd = max(all_dpds) if all_dpds else 0.0
    score = _fairness_score_from_metrics(dpd, None, None)

    return ScenarioResponse(
        threshold=req.threshold,
        fairness_score=round(score, 1),
        accuracy=round(accuracy, 4),
        demographic_parity_difference=round(dpd, 4),
        group_selection_rates=group_rates,
    )


# ── Google Cloud Integration ─────────────────────────────────────────────────

# ── Google Drive Integration ───────────────────────────────────────────────

@router.get("/drive/auth/url")
async def get_drive_auth_url():
    url = drive_service.get_authorization_url()
    if not url:
        raise AppError("Google Drive integration not configured on server.", status_code=500)
    return {"url": url}

@router.get("/drive/auth/callback")
async def drive_auth_callback(code: str):
    try:
        creds = drive_service.get_credentials(code)
        return creds
    except Exception as e:
        logger.error(f"Drive auth callback failed: {e}")
        raise AppError("Failed to authenticate with Google Drive.", status_code=400)

@router.post("/drive/files")
async def list_drive_files(creds: dict):
    try:
        files = drive_service.list_files(creds)
        return {"files": files}
    except Exception as e:
        logger.error(f"Failed to list Drive files: {e}")
        raise AppError("Unable to access Google Drive. Please re-authenticate.", status_code=401)

@router.post("/drive/import", response_model=UploadResponse)
async def drive_import(file_id: str = Form(...), creds_json: str = Form(...)):
    import json
    try:
        creds = json.loads(creds_json)
        df = drive_service.download_file(file_id, creds)
        
        # Convert DF to CSV stream for processing
        import io
        stream = io.StringIO()
        df.to_csv(stream, index=False)
        content = stream.getvalue().encode('utf-8')
        
        # Use existing processing logic
        result = await process_upload(content, f"drive_file_{file_id}")
        return result
    except ValueError as e:
        raise AppError(str(e), status_code=400)
    except Exception as e:
        logger.error(f"Drive import failed: {e}", exc_info=True)
        raise AppError("Failed to import from Google Drive.", status_code=500)


# ── Compliance Certificate ───────────────────────────────────────────────────

@router.post("/compliance/certificate")
async def download_compliance_certificate(request: dict):
    """
    Generate an official compliance certificate PDF based on the compliance data.
    Expected request body: {"compliance_data": {...}}
    """
    compliance_data = request.get("compliance_data")
    if not compliance_data:
        raise HTTPException(status_code=400, detail="compliance_data is required")
        
    try:
        pdf_bytes = generate_compliance_certificate(compliance_data)
        
        return StreamingResponse(
            io.BytesIO(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": "attachment; filename=fairness_compliance_certificate.pdf"
            }
        )
    except Exception as e:
        logger.error(f"Error generating certificate: {e}")
        raise HTTPException(status_code=500, detail=str(e))
