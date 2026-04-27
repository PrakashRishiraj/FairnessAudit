import logging
import json
import google.generativeai as genai
from app.core.config import settings

logger = logging.getLogger(__name__)

# Configure Gemini
if settings.GEMINI_API_KEY:
    genai.configure(api_key=settings.GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
else:
    logger.warning("GEMINI_API_KEY not found. AI insights will use rule-based fallback.")
    model = None

# ── Step-aware system prompts ────────────────────────────────────────────────

STEP_PROMPTS = {
    "upload": (
        "The user is on the DATASET UPLOAD step. They are choosing or uploading a dataset. "
        "Help them understand their data structure, suggest which columns might be sensitive "
        "(e.g., gender, race, age), and explain what a good dataset for fairness auditing looks like."
    ),
    "mapping": (
        "The user is on the COLUMN MAPPING step. They are selecting target, prediction, "
        "feature, and sensitive columns. Help them understand what each mapping means and "
        "why correct mapping is critical for accurate bias detection."
    ),
    "analyze": (
        "The user is on the FAIRNESS ANALYSIS step. They can see metrics like demographic parity, "
        "equalized odds, and fairness scores. Help them interpret these metrics in plain English, "
        "explain what the numbers mean, and why certain groups may be disadvantaged."
    ),
    "explain": (
        "The user is on the SHAP EXPLAINABILITY step. They can see feature importance values "
        "and proxy feature warnings. Help them understand which features drive bias, what SHAP "
        "values represent, and what proxy features mean for fairness."
    ),
    "mitigate": (
        "The user is on the BIAS MITIGATION step. They can see before/after fairness scores "
        "from algorithms like Reweighing and Exponentiated Gradient. Help them understand "
        "the trade-offs, which method to choose, and what the accuracy impact means."
    ),
    "report": (
        "The user is on the REPORT step. They can download compliance certificates and audit "
        "reports. Help them understand the report contents, compliance status, and next steps "
        "for deploying a fairer model."
    ),
}

STEP_SUGGESTIONS = {
    "upload": [
        "What makes a good dataset for fairness auditing?",
        "Which columns should I mark as sensitive?",
        "What is a target column?",
    ],
    "mapping": [
        "What's the difference between target and prediction columns?",
        "Why do I need to select sensitive columns?",
        "What are feature columns used for?",
    ],
    "analyze": [
        "What does the fairness score mean?",
        "Why is there bias in my data?",
        "What is demographic parity?",
    ],
    "explain": [
        "What are SHAP values?",
        "What does 'proxy feature' mean?",
        "Which features are causing bias?",
    ],
    "mitigate": [
        "Which mitigation method should I use?",
        "Why did accuracy change after mitigation?",
        "What is the fairness-accuracy trade-off?",
    ],
    "report": [
        "Is my model ready for deployment?",
        "What does compliance status mean?",
        "How do I share this report with stakeholders?",
    ],
}


async def generate_decision_summary(analysis_data: dict):
    """
    Generates a structured decision summary for the Fairness Audit.
    """
    if not model:
        return _get_fallback_decision_summary(analysis_data)

    prompt = f"""
    You are an expert AI Fairness Auditor. Based on the following fairness metrics, provide a high-level Decision Summary.
    Be extremely concise (1 sentence per field). Avoid jargon.
    
    Fields:
    1. Problem: What is the main fairness issue? (e.g., "Significant gender bias detected in loan approvals")
    2. Cause: What is the technical root cause? (e.g., "Model over-relies on 'income' which differs by group")
    3. Recommendation: What should the user do? (e.g., "Apply reweighing mitigation or remove proxy features")
    4. Expected Impact: What is the result of action? (e.g., "Bias reduced by 40% with <1% accuracy loss")

    Return ONLY structured JSON:
    {{
        "problem": "...",
        "cause": "...",
        "recommendation": "...",
        "expected_impact": "..."
    }}

    Fairness Data:
    {json.dumps(analysis_data, indent=2)}
    """

    try:
        response = await model.generate_content_async(prompt)
        text = response.text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "", 1).rsplit("```", 1)[0].strip()
        elif text.startswith("```"):
            text = text.replace("```", "", 1).rsplit("```", 1)[0].strip()
        
        return json.loads(text)
    except Exception as e:
        logger.error(f"Gemini Decision Summary failed: {e}")
        return _get_fallback_decision_summary(analysis_data)


def _get_fallback_decision_summary(data: dict):
    """Rule-based fallback for decision summary."""
    severity = data.get("overall_bias_severity", "Low")
    if severity == "High":
        return {
            "problem": "Significant bias detected across sensitive groups.",
            "cause": "Model outcomes show major disparity in selection rates.",
            "recommendation": "Immediate mitigation (Reweighing) is required before deployment.",
            "expected_impact": "Mitigation can reduce bias while maintaining functional accuracy."
        }
    return {
        "problem": "No significant bias detected.",
        "cause": "Model outcomes are relatively balanced across groups.",
        "recommendation": "Continue monitoring model performance in production.",
        "expected_impact": "Model remains compliant with standard fairness policies."
    }


async def generate_ai_insights(analysis_data: dict):
    """
    Sends fairness analysis JSON to Gemini and returns:
    - Plain-English explanation
    - Business-level insights
    - Suggested fixes
    """
    if not model:
        return get_fallback_insights(analysis_data)

    prompt = f"""
    You are an expert AI Fairness Consultant. Analyze the fairness audit data and provide short, clear insights.
    Focus on DECISIONS and ACTIONS.
    
    Return the response in a structured JSON format:
    {{
        "explanation": "Short summary of findings.",
        "business_insights": "Business impact (risk/trust).",
        "suggested_fixes": ["Fix 1", "Fix 2"]
    }}

    Fairness Audit Data:
    {json.dumps(analysis_data, indent=2)}
    """

    try:
        response = await model.generate_content_async(prompt)
        # Clean response text in case it includes markdown code blocks
        text = response.text.strip()
        if text.startswith("```json"):
            text = text.replace("```json", "", 1).rsplit("```", 1)[0].strip()
        elif text.startswith("```"):
            text = text.replace("```", "", 1).rsplit("```", 1)[0].strip()
        
        return json.loads(text)
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return get_fallback_insights(analysis_data)


async def chat_with_report(query: str, report_context: dict, step: str = "report"):
    """
    Handles user chat queries about their fairness audit.
    Step-aware: tailors the system prompt based on which step the user is on.
    """
    if not query or not query.strip():
        return "Please ask a question and I'll do my best to help!"

    # Truncate context to avoid token limits
    context_str = json.dumps(report_context, default=str)
    if len(context_str) > 8000:
        context_str = context_str[:8000] + "... [truncated for brevity]"

    step_instruction = STEP_PROMPTS.get(step, STEP_PROMPTS["report"])

    if not model:
        return _get_fallback_chat_response(query, step, report_context)

    prompt = f"""You are FairnessAudit AI — a friendly, expert AI Fairness Consultant embedded in a bias auditing platform.

CURRENT STEP: {step.upper()}
ROLE: {step_instruction}

RULES:
- Be concise (2-4 paragraphs max).
- Use plain English; avoid jargon unless explaining it.
- Reference specific numbers from the context when available.
- If unsure, say so honestly.
- Never make up data that isn't in the context.

Audit Context:
{context_str}

User Question: {query}

Provide a helpful, professional answer:"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        logger.error(f"Gemini Chat failed: {e}")
        return _get_fallback_chat_response(query, step, report_context)


def _get_fallback_chat_response(query: str, step: str, context: dict) -> str:
    """Rule-based fallback when Gemini is unavailable."""
    q = query.lower()

    # Step-specific fallbacks
    if step == "analyze":
        score = context.get("analysisResponse", {}).get("overall_fairness_score", "N/A")
        severity = context.get("analysisResponse", {}).get("overall_bias_severity", "N/A")
        if "score" in q or "fair" in q:
            return f"Your model's fairness score is {score}/100 with {severity} bias severity. A score above 75 is generally considered acceptable for deployment."
        if "bias" in q or "why" in q:
            return f"Bias severity is currently {severity}. This means the model treats some demographic groups differently. Check the group-level metrics to see which groups are disadvantaged."
        if "parity" in q or "dp" in q:
            return "Demographic Parity measures whether the selection rate (positive prediction rate) is equal across all groups. A difference greater than 0.1 is generally considered significant."

    elif step == "explain":
        if "shap" in q:
            return "SHAP (SHapley Additive exPlanations) values show how much each feature contributes to a prediction. Higher absolute SHAP values mean the feature has more influence on the outcome."
        if "proxy" in q:
            return "A proxy feature is one that is highly correlated with a sensitive attribute (like race or gender). Even if the model doesn't directly use the sensitive attribute, proxy features can propagate bias."

    elif step == "mitigate":
        if "method" in q or "which" in q:
            return "We recommend the method with the highest fairness improvement and minimal accuracy loss. Reweighing is a simpler pre-processing approach, while Exponentiated Gradient is more powerful but may have a larger accuracy trade-off."
        if "accuracy" in q or "trade" in q:
            return "Some accuracy loss is expected when imposing fairness constraints. This is known as the fairness-accuracy trade-off. The goal is to find the best balance for your use case."

    # Generic fallback
    return (
        "I'm currently running in offline mode (AI API key not configured). "
        "Based on your audit data, I'd recommend reviewing the fairness metrics carefully "
        "and using the mitigation tools to address any detected bias. "
        "Set your GEMINI_API_KEY in the .env file to enable full AI-powered responses."
    )


def get_fallback_insights(data: dict):
    """Rule-based fallback for AI insights."""
    overall_score = data.get("overall_fairness_score", 100)
    severity = data.get("overall_bias_severity", "Low")
    
    insights = {
        "explanation": f"The model has an overall fairness score of {overall_score} with {severity} bias severity.",
        "business_insights": "Bias in model predictions can lead to reputational risk and regulatory non-compliance.",
        "suggested_fixes": [
            "Review the dataset for historical imbalances.",
            "Try re-weighting the training samples.",
            "Consider using a different mitigation algorithm like Exponentiated Gradient."
        ]
    }
    
    if severity == "High":
        insights["explanation"] = "CRITICAL: The model shows significant bias against one or more sensitive groups. Immediate intervention is required."
        insights["suggested_fixes"].insert(0, "Halt deployment of the model until bias is mitigated.")
        
    return insights
