import axios from 'axios';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 120000, // 2 min for heavy ML ops
  headers: { 'Content-Type': 'application/json' },
});

api.interceptors.response.use(
  (res) => res,
  (error) => {
    const message =
      error?.response?.data?.message ||
      error?.message ||
      'An unexpected error occurred';
    return Promise.reject(new Error(message));
  }
);

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ColumnInfo {
  name: string;
  dtype: string;
  inferred_type: 'numeric' | 'categorical' | 'binary' | 'text' | 'datetime';
  missing_count: number;
  missing_pct: number;
  unique_count: number;
  sample_values: (string | number | boolean)[];
}

export interface UploadResponse {
  session_id: string;
  dataset_name: string;
  num_rows: number;
  num_cols: number;
  columns: ColumnInfo[];
  suggested_target?: string;
  suggested_sensitive: string[];
  suggested_prediction?: string;
  warnings: string[];
}

export interface SampleDataset {
  id: string;
  name: string;
  description: string;
  num_rows: number;
  num_cols: number;
  sensitive_columns: string[];
  target_column: string;
  prediction_column?: string;
  feature_columns: string[];
  task_type: string;
  bias_types: string[];
}

export interface GroupMetric {
  group_value: string;
  count: number;
  selection_rate: number;
  true_positive_rate?: number;
  false_positive_rate?: number;
  accuracy?: number;
  precision?: number;
}

export interface FairnessMetrics {
  sensitive_column: string;
  demographic_parity_difference?: number;
  demographic_parity_ratio?: number;
  equalized_odds_difference?: number;
  equal_opportunity_difference?: number;
  overall_accuracy?: number;
  group_metrics: GroupMetric[];
  bias_severity: 'Low' | 'Medium' | 'High';
  fairness_score: number;
  explanation: string;
  warnings: string[];
}

export interface DecisionSummary {
  problem: string;
  cause: string;
  recommendation: string;
  expected_impact: string;
}

export interface AnalysisResponse {
  session_id: string;
  dataset_summary: Record<string, unknown>;
  metrics: FairnessMetrics[];
  overall_fairness_score: number;
  overall_bias_severity: 'Low' | 'Medium' | 'High';
  bias_explanation: string;
  policy_compliance: Record<string, unknown>;
  recommendations: string[];
  impact_simulation?: {
    estimated_affected_users: number;
    impact_description: string;
  };
  decision_summary?: DecisionSummary;
  warnings: string[];
  timestamp?: string;
  version?: string;
}

export interface FeatureImportance {
  feature: string;
  importance: number;
  mean_abs_shap: number;
  is_proxy_warning: boolean;
  proxy_correlation?: number;
}

export interface ExplainResponse {
  session_id: string;
  top_features: FeatureImportance[];
  shap_values_summary: Record<string, unknown>[];
  proxy_features: string[];
  explanation_text: string;
  model_type: string;
}

export interface MitigationResult {
  method: string;
  method_display_name: string;
  before_metrics: FairnessMetrics[];
  after_metrics: FairnessMetrics[];
  before_accuracy?: number;
  after_accuracy?: number;
  accuracy_delta?: number;
  fairness_score_before: number;
  fairness_score_after: number;
  fairness_improvement: number;
  explanation: string;
  tradeoff_summary: string;
}

export interface MitigationResponse {
  session_id: string;
  results: MitigationResult[];
  best_method: string;
  overall_recommendation: string;
}

export interface AnalysisRequest {
  session_id?: string;
  sample_dataset_id?: string;
  target_column: string;
  prediction_column?: string;
  feature_columns: string[];
  sensitive_columns: string[];
  positive_label?: string;
}

// ─── API Functions ────────────────────────────────────────────────────────────

export async function checkHealth() {
  const { data } = await api.get('/health');
  return data;
}

export async function uploadCSV(file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getDriveAuthUrl(): Promise<{ url: string }> {
  const { data } = await api.get('/drive/auth/url');
  return data;
}

export async function getDriveCreds(code: string): Promise<any> {
  const { data } = await api.get(`/drive/auth/callback?code=${code}`);
  return data;
}

export async function listDriveFiles(creds: any): Promise<{ files: any[] }> {
  const { data } = await api.post('/drive/files', creds);
  return data;
}

export async function importDriveFile(fileId: string, creds: any): Promise<UploadResponse> {
  const form = new FormData();
  form.append('file_id', fileId);
  form.append('creds_json', JSON.stringify(creds));
  const { data } = await api.post('/drive/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return data;
}

export async function getSampleDatasets(): Promise<SampleDataset[]> {
  const { data } = await api.get('/sample-datasets');
  return data.datasets;
}

export async function runAnalysis(req: AnalysisRequest): Promise<AnalysisResponse> {
  const { data } = await api.post('/analyze', req);
  return data;
}

export async function runExplain(req: {
  session_id?: string;
  sample_dataset_id?: string;
  target_column: string;
  feature_columns: string[];
  sensitive_columns: string[];
  prediction_column?: string;
  positive_label?: string | number;
}): Promise<ExplainResponse> {
  const { data } = await api.post('/explain', req);
  return data;
}

export async function runMitigation(req: {
  session_id?: string;
  sample_dataset_id?: string;
  target_column: string;
  feature_columns: string[];
  sensitive_columns: string[];
  prediction_column?: string;
  method?: string;
  positive_label?: string | number;
}): Promise<MitigationResponse> {
  const { data } = await api.post('/mitigate', req);
  return data;
}

export async function generateReport(req: {
  session_id?: string;
  analysis_response?: Record<string, unknown>;
  explain_response?: Record<string, unknown>;
  mitigation_response?: Record<string, unknown>;
  format?: 'json' | 'pdf';
}) {
  if (req.format === 'pdf') {
    const response = await api.post('/report', req, { responseType: 'blob' });
    return response.data;
  }
  const { data } = await api.post('/report', req);
  return data;
}

export async function downloadMitigatedDataset(req: {
  session_id?: string;
  sample_dataset_id?: string;
  target_column: string;
  feature_columns: string[];
  sensitive_columns: string[];
  prediction_column?: string;
  method?: string;
  positive_label?: string | number;
}): Promise<Blob> {
  const response = await api.post('/dataset/mitigated/download', req, { responseType: 'blob' });
  return response.data;
}

export async function simulateScenario(req: {
  session_id?: string;
  sample_dataset_id?: string;
  target_column: string;
  sensitive_columns: string[];
  threshold: number;
  positive_label?: string;
}): Promise<{
  threshold: number;
  fairness_score: number;
  accuracy: number;
  demographic_parity_difference: number;
  group_selection_rates: Record<string, number>;
}> {
  const { data } = await api.post('/simulate-scenario', req);
  return data;
}

export async function downloadComplianceCertificate(complianceData: any): Promise<Blob> {
  const response = await api.post('/compliance/certificate', { compliance_data: complianceData }, { responseType: 'blob' });
  return response.data;
}
