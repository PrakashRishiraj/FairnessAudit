'use client';

import { useState, useRef, useCallback } from 'react';
import { motion } from 'framer-motion';
import { FilePlus, Database, Sparkles, FileText, AlertCircle, ShieldCheck, X, Cloud, Loader2 } from 'lucide-react';
import { SampleDataset, UploadResponse, uploadCSV, getDriveAuthUrl, getDriveCreds, listDriveFiles, importDriveFile } from '@/lib/api';
import { useEffect } from 'react';

interface DatasetStepProps {
  sampleDatasets: SampleDataset[];
  onSampleSelect: (sample: SampleDataset) => void;
  onUpload: (res: UploadResponse) => void;
  isDemo: boolean;
}

export function DatasetStep({ sampleDatasets, onSampleSelect, onUpload, isDemo }: DatasetStepProps) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const [showDriveModal, setShowDriveModal] = useState(false);
  const [driveFiles, setDriveFiles] = useState<any[]>([]);
  const [fetchingFiles, setFetchingFiles] = useState(false);
  const [driveCreds, setDriveCredsState] = useState<any>(null);

  // Handle OAuth Callback
  useEffect(() => {
    const urlParams = new URLSearchParams(window.location.search);
    const code = urlParams.get('code');
    if (code) {
      // Clear URL params
      window.history.replaceState({}, document.title, window.location.pathname);
      handleDriveCallback(code);
    }
    
    // Check session storage for existing creds
    const stored = sessionStorage.getItem('drive_creds');
    if (stored) {
      try {
        const parsed = JSON.parse(stored);
        setDriveCredsState(parsed);
      } catch (e) {}
    }
  }, []);

  const handleDriveCallback = async (code: string) => {
    setUploading(true);
    try {
      const creds = await getDriveCreds(code);
      setDriveCredsState(creds);
      sessionStorage.setItem('drive_creds', JSON.stringify(creds));
      setShowDriveModal(true);
      fetchFiles(creds);
    } catch (e: any) {
      setError(e.message || 'Drive auth failed');
    } finally {
      setUploading(false);
    }
  };

  const fetchFiles = async (creds: any) => {
    setFetchingFiles(true);
    try {
      const { files } = await listDriveFiles(creds);
      setDriveFiles(files);
    } catch (e: any) {
      setError(e.message || 'Failed to list Drive files');
    } finally {
      setFetchingFiles(false);
    }
  };

  const handleDriveButtonClick = async () => {
    if (driveCreds) {
      setShowDriveModal(true);
      fetchFiles(driveCreds);
    } else {
      setUploading(true);
      try {
        const { url } = await getDriveAuthUrl();
        window.location.href = url;
      } catch (e: any) {
        setError(e.message || 'Failed to get auth URL');
        setUploading(false);
      }
    }
  };

  const handleDriveFileSelect = async (fileId: string) => {
    setUploading(true);
    setShowDriveModal(false);
    setError(null);
    try {
      const res = await importDriveFile(fileId, driveCreds);
      onUpload(res);
    } catch (e: any) {
      setError(e.message || 'Drive import failed');
    } finally {
      setUploading(false);
    }
  };

  const handleFile = useCallback(async (file: File) => {
    if (!file.name.endsWith('.csv')) {
      setError('Please upload a CSV file.');
      return;
    }
    setUploading(true);
    setError(null);
    try {
      const res = await uploadCSV(file);
      onUpload(res);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'FilePlus failed');
    } finally {
      setUploading(false);
    }
  }, [onUpload]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) handleFile(file);
  }, [handleFile]);


  const biasColors: Record<string, string> = {
    'Gender bias': '#EF4444', // Red
    'Racial bias': '#8B0000', // Maroon
    'Socioeconomic bias': '#F59E0B', // Amber
  };

  return (
    <div className="max-w-5xl mx-auto space-y-8">
      <div className="text-center">
        <h2 className="text-2xl font-bold mb-2 text-text-primary">
          Choose Your Dataset
        </h2>
        <p className="text-text-secondary">
          FilePlus a CSV file or select a built-in sample dataset to get started immediately.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* FilePlus zone */}
        <div>
          <h3 className="font-semibold text-sm mb-3 uppercase tracking-wider text-text-muted">
            FilePlus Your Dataset
          </h3>
          <div
            className={`upload-zone ${dragOver ? 'drag-over' : ''} ${uploading ? 'opacity-60' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => !uploading && fileRef.current?.click()}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".csv"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFile(f); }}
            />
            <div className="flex flex-col items-center gap-4">
              {uploading ? (
                <>
                  <div className="w-16 h-16 rounded-full flex items-center justify-center bg-maroon/10">
                    <div className="w-8 h-8 border-2 border-red border-t-transparent rounded-full spinner" />
                  </div>
                  <p className="text-text-secondary">Processing your CSV...</p>
                </>
              ) : (
                <>
                  <div className="w-16 h-16 rounded-full flex items-center justify-center bg-maroon/10">
                    <FilePlus size={28} className="text-red"  strokeWidth={1.5}/>
                  </div>
                  <div>
                    <p className="font-semibold text-text-primary">
                      Drop your CSV here
                    </p>
                    <p className="text-sm mt-1 text-text-secondary">
                      or click to browse files
                    </p>
                  </div>
                  <div className="flex items-center gap-4 text-xs text-text-muted">
                    <span className="flex items-center gap-1"><FileText size={12}  strokeWidth={1.5}/> CSV format</span>
                    <span>Max 50 MB</span>
                  </div>
                </>
              )}
            </div>
          </div>
          
          <button onClick={handleDriveButtonClick} disabled={uploading} className="mt-4 flex items-center justify-center gap-2 w-full py-2.5 bg-background-elevated hover:bg-white/5 border border-border-default text-text-primary rounded-xl transition-colors text-sm font-medium disabled:opacity-50">
            <Cloud size={16} className="text-red"  strokeWidth={1.5}/> Import from Google Drive
          </button>

          {error && (
            <div className="mt-3 p-3 rounded-lg flex items-center gap-2 text-sm"
              style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#f87171' }}>
              <AlertCircle size={16}  strokeWidth={1.5}/>
              {error}
              <button onClick={() => setError(null)} className="ml-auto"><X size={14}  strokeWidth={1.5}/></button>
            </div>
          )}

          <div className="mt-4 p-4 rounded-xl text-sm bg-maroon/5 border border-maroon/10">
            <p className="font-medium mb-2 text-text-secondary">
              CSV requirements:
            </p>
            <ul className="space-y-1 text-text-muted">
              <li>• At least 10 rows and 2 columns</li>
              <li>• Must include a target/outcome column</li>
              <li>• Include one or more sensitive attribute columns</li>
              <li>• Optional: include a model prediction column</li>
            </ul>
          </div>
        </div>

        {/* Sample datasets */}
        <div>
          <h3 className="font-semibold text-sm mb-3 uppercase tracking-wider text-text-muted">
            Built-in Sample Datasets
          </h3>
          <div className="space-y-4">
            {sampleDatasets.map((ds, i) => (
              <motion.div
                key={ds.id}
                initial={{ opacity: 0, x: 20 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: i * 0.1 }}
                className="glass-card p-5 cursor-pointer hover:border-indigo-500/40 transition-all group"
                onClick={() => onSampleSelect(ds)}
              >
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-maroon/10">
                      <Database size={18} className="text-red"  strokeWidth={1.5}/>
                    </div>
                    <div>
                      <h4 className="font-semibold text-text-primary">{ds.name}</h4>
                      <p className="text-xs text-text-muted">
                        {ds.num_rows.toLocaleString()} rows · {ds.num_cols} columns
                      </p>
                    </div>
                  </div>
                  {ds.id === 'adult_income' && (
                    <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-accent-success/15 text-accent-success border border-accent-success/30">
                      Recommended
                    </span>
                  )}
                </div>

                <p className="text-sm mb-3 text-text-secondary">{ds.description}</p>

                <div className="flex flex-wrap gap-2 mb-3">
                  {ds.bias_types.map((bt) => (
                    <span key={bt} className="text-xs px-2 py-0.5 rounded-full"
                      style={{
                        background: `${biasColors[bt] || '#8B0000'}20`,
                        color: biasColors[bt] || '#EF4444',
                        border: `1px solid ${biasColors[bt] || '#8B0000'}40`,
                      }}>
                      {bt}
                    </span>
                  ))}
                </div>

                <div className="flex items-center justify-between">
                  <div className="text-xs text-text-muted">
                    Sensitive: <span className="text-text-secondary">{ds.sensitive_columns.join(', ')}</span>
                  </div>
                  <button className="text-xs font-medium text-red group-hover:translate-x-1 transition-transform">
                    Select →
                  </button>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </div>

      {/* Demo hint */}
      <div className="glass-card p-4 flex items-center gap-4 border-accent-success/20">
        <Sparkles size={20} className="text-accent-success"  strokeWidth={1.5}/>
        <div className="flex-1">
          <p className="text-sm font-medium text-text-primary">
            Want a quick demo?
          </p>
          <p className="text-xs text-text-muted">
            Click &quot;Adult Income (UCI)&quot; above to instantly load a preconfigured dataset with visible gender & racial bias.
          </p>
        </div>
        <button
          onClick={() => sampleDatasets.length > 0 && onSampleSelect(sampleDatasets.find(d => d.id === 'adult_income') || sampleDatasets[0])}
          className="btn-secondary text-sm"
        >
          Load Demo
        </button>
      </div>

      {showDriveModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4">
          <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl flex flex-col max-h-[80vh]">
            <div className="p-4 border-b border-border-default flex justify-between items-center bg-background-primary">
              <h3 className="font-bold text-text-primary flex items-center gap-2"><Cloud className="text-red" strokeWidth={1.5}/> Select Google Drive Dataset</h3>
              <button onClick={() => setShowDriveModal(false)} className="text-text-muted hover:text-text-primary"><X size={20} strokeWidth={1.5}/></button>
            </div>
            
            <div className="flex-1 overflow-y-auto p-4">
              {fetchingFiles ? (
                <div className="py-20 flex flex-col items-center gap-4">
                  <Loader2 className="animate-spin text-red" size={32} />
                  <p className="text-sm text-text-secondary">Fetching your files...</p>
                </div>
              ) : driveFiles.length > 0 ? (
                <div className="space-y-2">
                  {driveFiles.map((file) => (
                    <div 
                      key={file.id}
                      onClick={() => handleDriveFileSelect(file.id)}
                      className="flex items-center justify-between p-3 rounded-xl border border-white/5 bg-white/[0.02] hover:bg-white/5 cursor-pointer group transition-all"
                    >
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-lg bg-maroon/10 flex items-center justify-center">
                          <FileText size={16} className="text-red" />
                        </div>
                        <div>
                          <p className="text-sm font-medium text-text-primary group-hover:text-red transition-colors">{file.name}</p>
                          <p className="text-[10px] text-text-muted">{file.mimeType.includes('spreadsheet') ? 'Google Sheet' : 'CSV File'}</p>
                        </div>
                      </div>
                      <span className="text-[10px] text-text-muted">
                        Modified: {new Date(file.modifiedTime).toLocaleDateString()}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-20 text-center space-y-3">
                  <p className="text-text-secondary">No valid CSV or Sheets found in your Drive.</p>
                  <p className="text-xs text-text-muted">Try uploading a CSV to your Drive first.</p>
                </div>
              )}
            </div>
            
            <div className="p-4 border-t border-border-default bg-background-primary flex justify-between items-center">
              <p className="text-[10px] text-text-muted">Only showing .csv and Google Sheets</p>
              <button 
                onClick={() => { setDriveCredsState(null); sessionStorage.removeItem('drive_creds'); handleDriveButtonClick(); }}
                className="text-[11px] font-medium text-red hover:underline"
              >
                Switch Account
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
