'use client';

import { useState, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Shield, ArrowLeft } from 'lucide-react';

import { DatasetStep } from '@/components/audit/DatasetStep';
import { ColumnMappingStep } from '@/components/audit/ColumnMappingStep';
import { AnalysisStep } from '@/components/audit/AnalysisStep';
import { ExplainStep } from '@/components/audit/ExplainStep';
import { MitigationStep } from '@/components/audit/MitigationStep';
import { ReportStep } from '@/components/audit/ReportStep';
import { AuditStepper } from '@/components/audit/AuditStepper';
import { FloatingChatbot } from '@/components/ai/FloatingChatbot';
import { LogoIcon } from '@/components/ui/Icons';

import {
  UploadResponse, SampleDataset, AnalysisResponse,
  ExplainResponse, MitigationResponse,
  getSampleDatasets, runAnalysis, runExplain, runMitigation
} from '@/lib/api';

export type AuditState = {
  step: number;
  sessionId?: string;
  sampleDatasetId?: string;
  datasetName?: string;
  uploadResponse?: UploadResponse;
  selectedSample?: SampleDataset;
  targetColumn?: string;
  predictionColumn?: string;
  featureColumns: string[];
  sensitiveColumns: string[];
  positiveLabel?: string;
  analysisResponse?: AnalysisResponse;
  explainResponse?: ExplainResponse;
  mitigationResponse?: MitigationResponse;
  isDemo: boolean;
};

const STEPS = [
  { id: 1, label: 'Dataset' },
  { id: 2, label: 'Mapping' },
  { id: 3, label: 'Analysis' },
  { id: 4, label: 'Explain' },
  { id: 5, label: 'Mitigate' },
  { id: 6, label: 'Report' },
];

function AuditPageInner() {
  const searchParams = useSearchParams();
  const isDemo = searchParams.get('demo') === 'true';

  const [state, setState] = useState<AuditState>({
    step: 1,
    featureColumns: [],
    sensitiveColumns: [],
    isDemo: false,
  });

  const [sampleDatasets, setSampleDatasets] = useState<SampleDataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSampleDatasets().then(setSampleDatasets).catch(() => {});
  }, []);

  // Auto-scroll to top on step change
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [state.step]);

  // Auto-load demo
  useEffect(() => {
    if (isDemo && sampleDatasets.length > 0) {
      const adult = sampleDatasets.find((d) => d.id === 'adult_income') || sampleDatasets[0];
      
      // True One-Click Demo Mode: Set state and jump straight to Analysis (Step 3)
      setState((prev) => ({
        ...prev,
        step: 3,
        sampleDatasetId: adult.id,
        selectedSample: adult,
        datasetName: adult.name,
        targetColumn: adult.target_column,
        predictionColumn: adult.prediction_column,
        featureColumns: adult.feature_columns,
        sensitiveColumns: adult.sensitive_columns,
        isDemo: true,
        analysisResponse: undefined,
        explainResponse: undefined,
        mitigationResponse: undefined
      }));
    }
  }, [isDemo, sampleDatasets]);

  function handleSampleSelect(sample: SampleDataset, demo = false) {
    setState((prev) => ({
      ...prev,
      step: 2,
      sampleDatasetId: sample.id,
      selectedSample: sample,
      datasetName: sample.name,
      targetColumn: sample.target_column,
      predictionColumn: sample.prediction_column,
      featureColumns: sample.feature_columns,
      sensitiveColumns: sample.sensitive_columns,
      isDemo: demo,
    }));
  }

  function handleUpload(res: UploadResponse) {
    setState((prev) => ({
      ...prev,
      step: 2,
      sessionId: res.session_id,
      uploadResponse: res,
      datasetName: res.dataset_name,
      targetColumn: res.suggested_target,
      predictionColumn: res.suggested_prediction,
      sensitiveColumns: res.suggested_sensitive,
      featureColumns: res.columns
        .filter((c) => !res.suggested_sensitive.includes(c.name) && c.name !== res.suggested_target && c.name !== res.suggested_prediction)
        .map((c) => c.name),
    }));
  }

  function handleMappingDone(mapping: {
    targetColumn: string;
    predictionColumn?: string;
    featureColumns: string[];
    sensitiveColumns: string[];
    positiveLabel?: string;
  }) {
    setState((prev) => ({ 
      ...prev, 
      ...mapping, 
      step: 3,
      analysisResponse: undefined,
      explainResponse: undefined,
      mitigationResponse: undefined
    }));
  }

  async function handleRunAnalysis() {
    setLoading(true);
    setError(null);
    try {
      const res = await runAnalysis({
        session_id: state.sessionId,
        sample_dataset_id: state.sampleDatasetId,
        target_column: state.targetColumn!,
        prediction_column: state.predictionColumn,
        feature_columns: state.featureColumns,
        sensitive_columns: state.sensitiveColumns,
        positive_label: state.positiveLabel,
      });
      setState((prev) => ({ 
        ...prev, 
        analysisResponse: res, 
        explainResponse: undefined, 
        mitigationResponse: undefined,
        step: 3 
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleRunExplain() {
    setLoading(true);
    setError(null);
    try {
      const res = await runExplain({
        session_id: state.sessionId,
        sample_dataset_id: state.sampleDatasetId,
        target_column: state.targetColumn!,
        feature_columns: state.featureColumns,
        sensitive_columns: state.sensitiveColumns,
        prediction_column: state.predictionColumn,
        positive_label: state.positiveLabel,
      });
      setState((prev) => ({ ...prev, explainResponse: res, step: 4 }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Explainability failed');
    } finally {
      setLoading(false);
    }
  }

  async function handleRunMitigation() {
    setLoading(true);
    setError(null);
    try {
      const res = await runMitigation({
        session_id: state.sessionId,
        sample_dataset_id: state.sampleDatasetId,
        target_column: state.targetColumn!,
        feature_columns: state.featureColumns,
        sensitive_columns: state.sensitiveColumns,
        prediction_column: state.predictionColumn,
        positive_label: state.positiveLabel,
      });
      setState((prev) => ({ ...prev, mitigationResponse: res, step: 5 }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Mitigation failed');
    } finally {
      setLoading(false);
    }
  }

  function goToStep(n: number) {
    setState((prev) => ({ ...prev, step: n }));
  }

  // Auto-run logic when navigating to a step with missing results
  useEffect(() => {
    if (loading || error) return;

    if (state.step === 3 && !state.analysisResponse) {
      handleRunAnalysis();
    } else if (state.step === 4 && !state.explainResponse) {
      handleRunExplain();
    } else if (state.step === 5 && !state.mitigationResponse) {
      handleRunMitigation();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [state.step, !!state.analysisResponse, !!state.explainResponse, !!state.mitigationResponse, loading]);

  return (
    <div className="min-h-screen bg-background-primary">
      {/* Header */}
      <header className="sticky top-0 z-40 px-6 py-4 flex items-center gap-4 bg-background-elevated border-b border-border-default">
        <Link href="/" className="flex items-center gap-1 text-sm text-text-muted transition-colors hover:text-text-primary">
          <ArrowLeft size={16}  strokeWidth={1.5}/>
          <span>Back</span>
        </Link>
        <div className="flex items-center gap-2">
          <LogoIcon size={20} className="text-white" />
          <span className="font-bold text-text-primary">FairnessAudit</span>
          {state.isDemo && (
            <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-accent-success/15 text-accent-success border border-accent-success/30">
              Demo Mode
            </span>
          )}
        </div>
        <div className="flex-1" />
        {state.datasetName && (
          <span className="text-xs text-text-muted">
            Dataset: <span className="text-text-secondary">{state.datasetName}</span>
          </span>
        )}
      </header>

      <div className="max-w-7xl mx-auto px-4 py-8">
        {/* Stepper */}
        <AuditStepper steps={STEPS} currentStep={state.step} onStepClick={goToStep} auditState={state} />

        {/* Error */}
        {error && (
          <div className="mb-6 p-4 rounded-xl flex items-center gap-3 bg-red/10 border border-red/30 text-red-light">
            <span className="font-medium">Error:</span> {error}
            <button onClick={() => setError(null)} className="ml-auto text-xs opacity-60 hover:opacity-100">✕</button>
          </div>
        )}

        {/* Step Content */}
        <div className="fade-in">
          {state.step === 1 && (
            <DatasetStep
              sampleDatasets={sampleDatasets}
              onSampleSelect={handleSampleSelect}
              onUpload={handleUpload}
              isDemo={isDemo}
            />
          )}

          {state.step === 2 && (
            <ColumnMappingStep
              uploadResponse={state.uploadResponse}
              selectedSample={state.selectedSample}
              initialMapping={{
                targetColumn: state.targetColumn,
                predictionColumn: state.predictionColumn,
                featureColumns: state.featureColumns,
                sensitiveColumns: state.sensitiveColumns,
              }}
              onDone={handleMappingDone}
              onRunAnalysis={handleRunAnalysis}
              loading={loading}
            />
          )}

          {state.step === 3 && (
            <AnalysisStep
              response={state.analysisResponse}
              loading={loading && !state.analysisResponse}
              onRunAnalysis={handleRunAnalysis}
              onContinue={() => goToStep(4)}
              onRunExplain={handleRunExplain}
              auditState={state}
            />
          )}

          {state.step === 4 && (
            <ExplainStep
              response={state.explainResponse}
              loading={loading}
              onRunExplain={handleRunExplain}
              onContinue={() => goToStep(5)}
              onRunMitigation={handleRunMitigation}
            />
          )}

          {state.step === 5 && (
            <MitigationStep
              response={state.mitigationResponse}
              loading={loading}
              onRunMitigation={handleRunMitigation}
              onContinue={() => goToStep(6)}
            />
          )}

          {state.step === 6 && (
            <ReportStep auditState={state} />
          )}
        </div>
      </div>

      {/* Floating AI Chatbot */}
      <FloatingChatbot 
        step={STEPS.find(s => s.id === state.step)?.label.toLowerCase() || 'report'} 
        context={state} 
      />
    </div>
  );
}

export default function AuditPage() {
  return (
    <Suspense fallback={<div className="min-h-screen flex items-center justify-center text-text-secondary">Loading...</div>}>
      <AuditPageInner />
    </Suspense>
  );
}
