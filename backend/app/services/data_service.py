"""
Data service: handles CSV upload, validation, and sample dataset loading.
"""
import pandas as pd
import numpy as np
import uuid
import os
import io
import logging
from typing import Optional, Tuple, Dict, Any, List

from app.core.config import settings
from app.models.schemas import ColumnInfo, ColumnType, UploadResponse

logger = logging.getLogger(__name__)

# In-memory session store  { session_id -> dataframe }
_SESSION_STORE: Dict[str, pd.DataFrame] = {}

SENSITIVE_KEYWORDS = ["sex", "gender", "race", "ethnicity", "age", "religion",
                      "nationality", "disability", "marital", "origin"]
TARGET_KEYWORDS = ["income", "label", "target", "outcome", "class", "default",
                   "recidivism", "decision", "approved", "hired", "admit"]
PREDICTION_KEYWORDS = ["prediction", "predicted", "score", "prob", "proba", "pred_"]


def store_session(df: pd.DataFrame, session_id: Optional[str] = None) -> str:
    sid = session_id or str(uuid.uuid4())
    _SESSION_STORE[sid] = df
    return sid


def get_session(session_id: str) -> Optional[pd.DataFrame]:
    return _SESSION_STORE.get(session_id)


def _infer_column_type(series: pd.Series) -> ColumnType:
    if pd.api.types.is_datetime64_any_dtype(series):
        return ColumnType.DATETIME
    unique_vals = series.dropna().unique()
    if pd.api.types.is_numeric_dtype(series):
        if len(unique_vals) == 2:
            return ColumnType.BINARY
        return ColumnType.NUMERIC
    if len(unique_vals) == 2:
        return ColumnType.BINARY
    if pd.api.types.is_object_dtype(series) or isinstance(series.dtype, pd.CategoricalDtype):
        if len(unique_vals) > 50 and series.str.len().mean() > 30:
            return ColumnType.TEXT
        return ColumnType.CATEGORICAL
    return ColumnType.CATEGORICAL


def _analyze_columns(df: pd.DataFrame) -> List[ColumnInfo]:
    cols = []
    for col in df.columns:
        series = df[col]
        missing = int(series.isna().sum())
        unique_count = int(series.nunique())
        sample_vals = series.dropna().unique()[:5].tolist()
        # convert numpy types
        sample_vals = [
            v.item() if hasattr(v, "item") else v for v in sample_vals
        ]
        cols.append(
            ColumnInfo(
                name=col,
                dtype=str(series.dtype),
                inferred_type=_infer_column_type(series),
                missing_count=missing,
                missing_pct=round(missing / len(df) * 100, 2) if len(df) > 0 else 0.0,
                unique_count=unique_count,
                sample_values=sample_vals,
            )
        )
    return cols


def _suggest_columns(df: pd.DataFrame, col_infos: List[ColumnInfo]):
    """Heuristically suggest target, sensitive, and prediction columns."""
    cols_lower = {c.name.lower(): c.name for c in col_infos}

    suggested_target = None
    suggested_sensitive = []
    suggested_prediction = None

    for lower, name in cols_lower.items():
        for kw in TARGET_KEYWORDS:
            if kw in lower and suggested_target is None:
                suggested_target = name

    for lower, name in cols_lower.items():
        for kw in SENSITIVE_KEYWORDS:
            if kw in lower:
                suggested_sensitive.append(name)

    for lower, name in cols_lower.items():
        for kw in PREDICTION_KEYWORDS:
            if kw in lower and suggested_prediction is None:
                suggested_prediction = name

    return suggested_target, list(set(suggested_sensitive)), suggested_prediction


async def process_upload(file_bytes: bytes, filename: str) -> UploadResponse:
    warnings = []
    try:
        df = pd.read_csv(io.BytesIO(file_bytes), low_memory=False)
    except Exception as e:
        raise ValueError(f"Failed to parse CSV file: {str(e)}")

    if df.empty:
        raise ValueError("Uploaded CSV is empty.")
    if len(df.columns) < 2:
        raise ValueError("CSV must have at least 2 columns.")

    # Clean column names
    df.columns = [str(c).strip() for c in df.columns]

    # Trim whitespace from string columns
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].astype(str).str.strip()
        df[col] = df[col].replace({"nan": np.nan, "None": np.nan, "": np.nan})

    if len(df) < 50:
        warnings.append("⚠️ Small Dataset Warning: Dataset has fewer than 50 rows. Fairness metrics may be statistically insignificant.")
    elif len(df) < 200:
        warnings.append("Notice: Dataset is relatively small. Interpret fairness gaps with caution.")

    # Missing values check
    total_missing_pct = (df.isna().sum().sum() / (df.shape[0] * df.shape[1])) * 100
    if total_missing_pct > 20:
        warnings.append(f"⚠️ Data Quality Warning: High overall missing values ({total_missing_pct:.1f}%). This may bias the results.")

    if len(df) > 100_000:
        warnings.append("Optimization: Large dataset detected. Analysis may take longer but provides higher confidence.")

    session_id = store_session(df)
    col_infos = _analyze_columns(df)
    suggested_target, suggested_sensitive, suggested_prediction = _suggest_columns(df, col_infos)

    return UploadResponse(
        session_id=session_id,
        dataset_name=filename,
        num_rows=len(df),
        num_cols=len(df.columns),
        columns=col_infos,
        suggested_target=suggested_target,
        suggested_sensitive=suggested_sensitive,
        suggested_prediction=suggested_prediction,
        warnings=warnings,
    )


# ── Sample datasets ─────────────────────────────────────────────────────────

def _generate_adult_income() -> pd.DataFrame:
    """Generate a representative synthetic Adult Income dataset."""
    np.random.seed(42)
    n = 2000
    age = np.random.randint(18, 75, n)
    sex = np.random.choice(["Male", "Female"], n, p=[0.67, 0.33])
    race = np.random.choice(["White", "Black", "Asian", "Other"], n, p=[0.85, 0.09, 0.04, 0.02])
    education_num = np.random.randint(5, 16, n)
    hours_per_week = np.clip(np.random.normal(40, 12, n), 1, 99).astype(int)
    capital_gain = np.where(np.random.rand(n) < 0.08, np.random.randint(1000, 99999, n), 0)
    capital_loss = np.where(np.random.rand(n) < 0.05, np.random.randint(100, 3900, n), 0)
    occupation = np.random.choice(
        ["Tech-support", "Craft-repair", "Sales", "Exec-managerial",
         "Prof-specialty", "Handlers-cleaners", "Machine-op-inspct",
         "Adm-clerical", "Farming-fishing", "Transport-moving"], n)
    workclass = np.random.choice(
        ["Private", "Self-emp-not-inc", "Self-emp-inc",
         "Federal-gov", "Local-gov", "State-gov"], n,
        p=[0.70, 0.09, 0.04, 0.03, 0.07, 0.07])
    marital_status = np.random.choice(
        ["Married-civ-spouse", "Divorced", "Never-married",
         "Separated", "Widowed"], n, p=[0.46, 0.14, 0.33, 0.04, 0.03])

    # Income probability with realistic bias
    logit = (
        0.03 * (age - 38)
        + 0.15 * education_num
        + 0.01 * hours_per_week
        + np.where(sex == "Male", 0.5, 0.0)
        + np.where(race == "White", 0.2, 0.0)
        + np.where(marital_status == "Married-civ-spouse", 0.4, 0.0)
        + np.random.normal(0, 0.5, n)
        - 3.0
    )
    prob = 1 / (1 + np.exp(-logit))
    income = np.where(prob > 0.5, ">50K", "<=50K")
    
    # Simulate a model prediction with slight over-prediction for Males
    logit_pred = logit + np.where(sex == "Male", 0.15, -0.05) + np.random.normal(0, 0.3, n)
    prob_pred = 1 / (1 + np.exp(-logit_pred))
    prediction = np.where(prob_pred > 0.5, ">50K", "<=50K")

    return pd.DataFrame({
        "age": age,
        "workclass": workclass,
        "education.num": education_num,
        "marital.status": marital_status,
        "occupation": occupation,
        "sex": sex,
        "race": race,
        "capital.gain": capital_gain,
        "capital.loss": capital_loss,
        "hours.per.week": hours_per_week,
        "income": income,
        "income_prediction": prediction,
        "prediction_probability": np.round(prob_pred, 4),
    })


def _generate_compas() -> pd.DataFrame:
    """Generate a representative synthetic COMPAS-like dataset."""
    np.random.seed(123)
    n = 1500
    age = np.random.randint(18, 65, n)
    race = np.random.choice(["African-American", "Caucasian", "Hispanic", "Other"],
                            n, p=[0.51, 0.34, 0.09, 0.06])
    sex = np.random.choice(["Male", "Female"], n, p=[0.81, 0.19])
    priors_count = np.random.poisson(1.5, n)
    days_b_screening = np.abs(np.random.normal(0, 5, n)).astype(int)
    c_charge_degree = np.random.choice(["F", "M"], n, p=[0.55, 0.45])
    juv_fel_count = np.random.poisson(0.3, n)
    juv_misd_count = np.random.poisson(0.4, n)

    logit = (
        0.02 * (age - 30)
        + 0.4 * priors_count
        + np.where(race == "African-American", 0.6, 0.0)
        + np.where(sex == "Male", 0.3, 0.0)
        + np.where(c_charge_degree == "F", 0.3, 0.0)
        + np.random.normal(0, 0.5, n)
        - 1.0
    )
    prob = 1 / (1 + np.exp(-logit))
    two_year_recid = (prob > 0.5).astype(int)

    logit_pred = logit + np.where(race == "African-American", 0.2, 0.0) + np.random.normal(0, 0.3, n)
    prob_pred = 1 / (1 + np.exp(-logit_pred))
    score_text = np.where(prob_pred > 0.65, "High",
                 np.where(prob_pred > 0.35, "Medium", "Low"))
    predicted_recid = (prob_pred > 0.5).astype(int)

    return pd.DataFrame({
        "age": age,
        "sex": sex,
        "race": race,
        "priors_count": priors_count,
        "days_b_screening_arrest": days_b_screening,
        "c_charge_degree": c_charge_degree,
        "juv_fel_count": juv_fel_count,
        "juv_misd_count": juv_misd_count,
        "two_year_recid": two_year_recid,
        "score_text": score_text,
        "predicted_recid": predicted_recid,
        "prediction_probability": np.round(prob_pred, 4),
    })


SAMPLE_REGISTRY: Dict[str, Dict[str, Any]] = {
    "adult_income": {
        "meta": {
            "id": "adult_income",
            "name": "Adult Income (UCI)",
            "description": "Predict whether income exceeds $50K/yr. Classic benchmark for gender and race bias in automated hiring/loan decisions.",
            "num_rows": 2000,
            "num_cols": 12,
            "sensitive_columns": ["sex", "race"],
            "target_column": "income",
            "prediction_column": "income_prediction",
            "feature_columns": ["age", "workclass", "education.num", "marital.status",
                                "occupation", "capital.gain", "capital.loss", "hours.per.week"],
            "task_type": "binary_classification",
            "bias_types": ["Gender bias", "Racial bias", "Socioeconomic bias"],
        },
        "loader": _generate_adult_income,
    },
    "compas": {
        "meta": {
            "id": "compas",
            "name": "COMPAS Recidivism",
            "description": "Criminal recidivism risk scoring tool used in the US justice system. Known for racial bias against African-American defendants.",
            "num_rows": 1500,
            "num_cols": 11,
            "sensitive_columns": ["race", "sex"],
            "target_column": "two_year_recid",
            "prediction_column": "predicted_recid",
            "feature_columns": ["age", "priors_count", "days_b_screening_arrest",
                                "c_charge_degree", "juv_fel_count", "juv_misd_count"],
            "task_type": "binary_classification",
            "bias_types": ["Racial bias", "Gender bias"],
        },
        "loader": _generate_compas,
    },
}


def get_sample_datasets_meta() -> List[Dict]:
    return [v["meta"] for v in SAMPLE_REGISTRY.values()]


def load_sample_dataset(dataset_id: str) -> Tuple[pd.DataFrame, Dict]:
    if dataset_id not in SAMPLE_REGISTRY:
        raise ValueError(f"Unknown sample dataset: {dataset_id}")
    entry = SAMPLE_REGISTRY[dataset_id]
    df = entry["loader"]()
    return df, entry["meta"]


def get_or_load_df(session_id: Optional[str], sample_dataset_id: Optional[str]) -> pd.DataFrame:
    if session_id and session_id in _SESSION_STORE:
        return _SESSION_STORE[session_id]
    if sample_dataset_id:
        df, meta = load_sample_dataset(sample_dataset_id)
        store_session(df, session_id or sample_dataset_id)
        return df
    raise ValueError("No session or sample dataset provided.")
