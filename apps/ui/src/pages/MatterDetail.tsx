import { useEffect, useState, useRef } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
    getMatter, getMatterDocuments, getMatterRuns,
    uploadDocument, createRun, getArtifactUrl,
    type Matter, type Document, type Run
} from '../api';
import {
    FileText, Upload, Play, Clock, CheckCircle, AlertTriangle,
    FileSpreadsheet, ArrowLeft, RefreshCw, Loader2
} from 'lucide-react';

export default function MatterDetail() {
    const { matterId } = useParams<{ matterId: string }>();
    const [matter, setMatter] = useState<Matter | null>(null);
    const [docs, setDocs] = useState<Document[]>([]);
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);

    const fileInputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (matterId) {
            loadData();
            const interval = setInterval(checkRuns, 5000);
            return () => clearInterval(interval);
        }
    }, [matterId]);

    const loadData = async () => {
        try {
            const [m, d, r] = await Promise.all([
                getMatter(matterId!),
                getMatterDocuments(matterId!),
                getMatterRuns(matterId!)
            ]);
            setMatter(m);
            setDocs(d);
            setRuns(r);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const checkRuns = async () => {
        try {
            if (!matterId) return;
            const r = await getMatterRuns(matterId);
            setRuns(r);
        } catch (err) {
            console.error(err);
        }
    };

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files?.length) return;
        setUploading(true);
        try {
            await uploadDocument(matterId!, e.target.files[0]);
            await loadData();
        } catch (err) {
            alert('Upload failed');
            console.error(err);
        } finally {
            setUploading(false);
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleStartRun = async () => {
        if (!confirm('Start processing analysis for this matter?')) return;
        try {
            await createRun(matterId!, { max_pages: 500 });
            await loadData();
        } catch (err) {
            alert('Failed to start run');
            console.error(err);
        }
    };

    if (loading) return <div className="container"><Loader2 className="animate-spin mr-2" /> Loading...</div>;
    if (!matter) return <div className="container">Matter not found</div>;

    return (
        <div className="container">
            <Link to={`/firms/${matter.firm_id}`} className="text-muted hover:text-white flex items-center gap-2 mb-4" style={{ display: 'inline-flex', marginBottom: '1.5rem' }}>
                <ArrowLeft size={16} /> Back to Matter List
            </Link>

            <header className="flex justify-between items-start" style={{ marginBottom: '2rem', borderBottom: '1px solid var(--border)', paddingBottom: '1.5rem' }}>
                <div>
                    <h1>{matter.title}</h1>
                    <div className="flex gap-4 text-muted">
                        {matter.client_ref && <span>Ref: {matter.client_ref}</span>}
                        <span>ID: {matter.id.slice(0, 8)}</span>
                    </div>
                </div>
                <button
                    onClick={handleStartRun}
                    disabled={docs.length === 0}
                    className="btn"
                    style={{ backgroundColor: 'var(--success)', color: 'white' }}
                >
                    <Play size={20} fill="currentColor" /> Start Analysis
                </button>
            </header>

            <div className="grid grid-cols-main gap-8">

                {/* Left Column: Documents */}
                <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <FileText style={{ color: 'var(--primary)' }} /> Source Documents
                        </h2>
                        <div className="text-xs font-mono bg-input px-2 py-1 rounded text-muted">
                            {docs.length} Files
                        </div>
                    </div>

                    <div style={{ padding: '1rem', maxHeight: '500px', overflowY: 'auto' }}>
                        {docs.map(doc => (
                            <div key={doc.id} className="file-item" style={{ marginBottom: '0.5rem' }}>
                                <FileText size={20} className="text-muted flex-shrink-0" />
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }} title={doc.filename}>{doc.filename}</div>
                                    <div className="text-xs text-muted flex gap-3">
                                        <span>{(doc.bytes / 1024 / 1024).toFixed(2)} MB</span>
                                        <span>{new Date(doc.uploaded_at).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                        {docs.length === 0 && (
                            <div className="empty-state" style={{ padding: '2rem' }}>
                                No documents uploaded yet.
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '1rem', borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.02)' }}>
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleUpload}
                            className="hidden"
                            accept=".pdf"
                            style={{ display: 'none' }}
                        />
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploading}
                            className="btn"
                            style={{ width: '100%', justifyContent: 'center', border: '2px dashed var(--border)', background: 'transparent' }}
                        >
                            {uploading ? (
                                <>
                                    <Loader2 className="animate-spin" /> Uploading...
                                </>
                            ) : (
                                <>
                                    <Upload size={20} /> Upload PDF
                                </>
                            )}
                        </button>
                    </div>
                </section>

                {/* Right Column: Runs */}
                <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                            <RefreshCw style={{ color: 'var(--warning)' }} /> Run History
                        </h2>
                        <button onClick={loadData} className="text-muted hover:text-white" title="Refresh" style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                            <RefreshCw size={16} />
                        </button>
                    </div>

                    <div style={{ padding: '1rem', maxHeight: '600px', overflowY: 'auto' }}>
                        {runs.map(run => (
                            <div key={run.id} className="run-item">
                                <div className="flex justify-between items-start" style={{ marginBottom: '0.75rem' }}>
                                    <div className="flex items-center gap-2">
                                        {run.status === 'success' && <CheckCircle style={{ color: 'var(--success)' }} size={18} />}
                                        {run.status === 'pending' && <Clock style={{ color: 'var(--warning)' }} size={18} />}
                                        {run.status === 'running' && <Loader2 style={{ color: 'var(--primary)' }} className="animate-spin" size={18} />}
                                        {run.status === 'failed' && <AlertTriangle style={{ color: 'var(--danger)' }} size={18} />}
                                        <span className="font-semibold capitalize">{run.status}</span>
                                    </div>
                                    <div className="text-xs text-muted font-mono">
                                        {new Date(run.started_at || Date.now()).toLocaleString()}
                                    </div>
                                </div>

                                {run.metrics && (
                                    <div className="grid grid-cols-2 gap-2 text-xs text-muted mb-3" style={{ background: 'rgba(0,0,0,0.2)', padding: '0.5rem', borderRadius: '4px' }}>
                                        <div>Pages: <span className="text-main">{run.metrics.page_count}</span></div>
                                        <div>Events: <span className="text-main">{run.metrics.event_count}</span></div>
                                        <div>Providers: <span className="text-main">{run.metrics.provider_count}</span></div>
                                        <div>Duration: <span className="text-main">{(run.processing_seconds || 0).toFixed(1)}s</span></div>
                                    </div>
                                )}

                                {run.status === 'success' && (
                                    <div className="flex flex-wrap gap-2 mt-2">
                                        <a
                                            href={getArtifactUrl(run.id, 'docx')}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#93c5fd', borderColor: 'rgba(147, 197, 253, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Docx
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'pdf')}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#d8b4fe', borderColor: 'rgba(216, 180, 254, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Chronology (PDF)
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'specials_summary_pdf')}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#d8b4fe', opacity: 0.6, borderColor: 'rgba(216, 180, 254, 0.1)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Bills
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'csv')}
                                            target="_blank"
                                            className="artifact-link"
                                            rel="noreferrer"
                                        >
                                            <FileSpreadsheet size={14} /> CSV
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'missing_records_csv')}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#fca5a5', borderColor: 'rgba(252, 165, 165, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <AlertTriangle size={14} /> Gaps
                                        </a>
                                    </div>
                                )}
                                {run.error_message && (
                                    <div style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: 'var(--danger)', background: 'rgba(239, 68, 68, 0.1)', padding: '0.5rem', borderRadius: '4px' }}>
                                        Error: {run.error_message}
                                    </div>
                                )}
                            </div>
                        ))}
                        {runs.length === 0 && (
                            <div className="empty-state" style={{ border: 'none', padding: '1rem' }}>
                                No runs yet.
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
}
