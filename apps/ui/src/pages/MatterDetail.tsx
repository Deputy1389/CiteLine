import { useEffect, useMemo, useState, useRef } from 'react';
import { useParams, Link, useSearchParams } from 'react-router-dom';
import {
    getMatter, getMatterDocuments, getMatterRuns, getLatestExports,
    uploadDocument, createRun, getArtifactByNameUrl, getArtifactUrl, getDocumentDownloadUrl,
    type Matter, type Document, type Run
} from '../api';
import { ARTIFACT_TYPES } from '../artifacts';
import {
    FileText, Upload, Play, Clock, CheckCircle, AlertTriangle,
    FileSpreadsheet, ArrowLeft, RefreshCw, Loader2, Scale, GitBranch, ShieldAlert, ListChecks, ExternalLink, Calendar
} from 'lucide-react';
import TimelineView, { type ClaimRow } from '../components/TimelineView';

type CommandCenterData = {
    runId: string;
    claimRows: ClaimRow[];
    causationChains: Record<string, any>[];
    collapseCandidates: Record<string, any>[];
    contradictionMatrix: Record<string, any>[];
    narrativeDuality: Record<string, any>;
    citationFidelity: Record<string, any>;
};

const completedStatuses = new Set(['success', 'partial']);

type CitationLink = {
    label: string;
    filename: string | null;
    page: number | null;
    href: string | null;
};

export default function MatterDetail() {
    const { matterId } = useParams<{ matterId: string }>();
    const [searchParams, setSearchParams] = useSearchParams();
    const [matter, setMatter] = useState<Matter | null>(null);
    const [docs, setDocs] = useState<Document[]>([]);
    const [runs, setRuns] = useState<Run[]>([]);
    const [loading, setLoading] = useState(true);
    const [uploading, setUploading] = useState(false);
    const [commandCenterLoading, setCommandCenterLoading] = useState(false);
    const [commandCenterError, setCommandCenterError] = useState<string | null>(null);
    const [commandCenterData, setCommandCenterData] = useState<CommandCenterData | null>(null);

    const [selectedCitation, setSelectedCitation] = useState<CitationLink | null>(null);
    const [dockWidth, setDockWidth] = useState(window.innerWidth * 0.45);
    const isResizing = useRef(false);

    const startResizing = (e: React.MouseEvent) => {
        isResizing.current = true;
        document.addEventListener('mousemove', handleMouseMove);
        document.addEventListener('mouseup', stopResizing);
        document.body.style.cursor = 'col-resize';
    };

    const handleMouseMove = (e: MouseEvent) => {
        if (!isResizing.current) return;
        const newWidth = window.innerWidth - e.clientX;
        if (newWidth > 300 && newWidth < window.innerWidth * 0.8) {
            setDockWidth(newWidth);
        }
    };

    const stopResizing = () => {
        isResizing.current = false;
        document.removeEventListener('mousemove', handleMouseMove);
        document.removeEventListener('mouseup', stopResizing);
        document.body.style.cursor = 'default';
    };

    const fileInputRef = useRef<HTMLInputElement>(null);
    const commandCenterRef = useRef<HTMLElement | null>(null);
    
    const viewParam = searchParams.get('view');
    const view = (viewParam === 'audit' || viewParam === 'timeline') ? viewParam : 'intake';

    useEffect(() => {
        if (matterId) {
            loadData();
            const interval = setInterval(() => {
                const hasActiveRuns = runs.some(r => r.status === 'pending' || r.status === 'running');
                const latestCompleted = runs.find(r => completedStatuses.has(r.status));
                const needsData = latestCompleted && !commandCenterData;
                
                if (hasActiveRuns || needsData) {
                    checkRuns();
                }
            }, 5000);
            return () => clearInterval(interval);
        }
    }, [matterId, runs, commandCenterData]);

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

    const getLatestCompletedRun = (runList: Run[]) => {
        return runList.find((r) => completedStatuses.has(r.status)) || null;
    };
    const getLatestRun = (runList: Run[]) => {
        return runList.length ? runList[0] : null;
    };

    const loadCommandCenter = async (runList: Run[]) => {
        const latest = getLatestCompletedRun(runList);
        if (!latest || !matterId) {
            setCommandCenterData(null);
            setCommandCenterError(null);
            return;
        }

        setCommandCenterLoading(true);
        setCommandCenterError(null);

        try {
            // Try to confirm artifact availability; if this endpoint is unavailable, fallback to direct artifact fetch.
            try {
                await getLatestExports(matterId);
            } catch {
                // best-effort only
            }

            let res = await fetch(getArtifactByNameUrl(latest.id, 'evidence_graph.json'));
            if (!res.ok) {
                // Fallback for older runs where only generic json artifact type is available.
                res = await fetch(getArtifactUrl(latest.id, ARTIFACT_TYPES.JSON));
            }
            if (!res.ok) throw new Error(`Artifact fetch failed (${res.status})`);

            const payload = await res.json();
            const graph = payload?.evidence_graph ?? payload;
            const ext = graph?.extensions ?? {};

            setCommandCenterData({
                runId: latest.id,
                claimRows: (Array.isArray(ext?.claim_rows) ? ext.claim_rows : []) as ClaimRow[],
                causationChains: Array.isArray(ext?.causation_chains) ? ext.causation_chains : [],
                collapseCandidates: Array.isArray(ext?.case_collapse_candidates) ? ext.case_collapse_candidates : [],
                contradictionMatrix: Array.isArray(ext?.contradiction_matrix) ? ext.contradiction_matrix : [],
                narrativeDuality: (ext?.narrative_duality || {}) as Record<string, any>,
                citationFidelity: (ext?.citation_fidelity || {}) as Record<string, any>,
            });
        } catch (err) {
            setCommandCenterData(null);
            setCommandCenterError(err instanceof Error ? err.message : 'Unable to load command center data');
        } finally {
            setCommandCenterLoading(false);
        }
    };

    useEffect(() => {
        void loadCommandCenter(runs);
    }, [matterId, runs]);

    useEffect(() => {
        if ((view === 'audit' || view === 'timeline') && commandCenterRef.current) {
            commandCenterRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    }, [view, commandCenterData, commandCenterLoading]);

    const citationLinks = useMemo((): CitationLink[] => {
        if (!commandCenterData) return [];
        const out: CitationLink[] = [];
        const seen = new Set<string>();
        const docByName = new Map<string, Document>();
        for (const d of docs) docByName.set((d.filename || '').toLowerCase(), d);

        const rawCitations: string[] = [];
        for (const row of commandCenterData.claimRows || []) {
            for (const c of (row?.citations || [])) {
                const s = String(c || '').trim();
                if (s) rawCitations.push(s);
            }
        }
        for (const c of rawCitations) {
            // Supports patterns like "packet.pdf p. 3" and "p. 3"
            const m = c.match(/^(?:(.+?)\s+)?p\.\s*(\d+)$/i);
            let filename: string | null = null;
            let page: number | null = null;
            if (m) {
                filename = m[1] ? m[1].trim() : null;
                page = Number.parseInt(m[2], 10);
            }
            let targetDoc: Document | undefined;
            if (filename) {
                const key = filename.toLowerCase();
                targetDoc = docByName.get(key) || docs.find((d) => d.filename.toLowerCase().endsWith(key));
            } else if (docs.length === 1) {
                targetDoc = docs[0];
            }
            const href = targetDoc ? getDocumentDownloadUrl(targetDoc.id, page || undefined) : null;
            const key = `${c}|${href || ''}`;
            if (seen.has(key)) continue;
            seen.add(key);
            out.push({ label: c, filename: filename || targetDoc?.filename || null, page, href });
            if (out.length >= 24) break;
        }
        return out;
    }, [commandCenterData, docs]);

    const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        if (!e.target.files?.length) return;
        setUploading(true);
        try {
            await uploadDocument(matterId!, e.target.files[0]);
            await createRun(matterId!, { max_pages: 500 });
            await loadData();
            setSearchParams({ view: 'audit' });
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

            <div className="flex gap-2" style={{ marginBottom: '1rem' }}>
                <button
                    onClick={() => setSearchParams({ view: 'intake' })}
                    className="btn"
                    style={{
                        background: view === 'intake' ? 'var(--primary)' : 'transparent',
                        border: '1px solid var(--border)',
                    }}
                >
                    Intake
                </button>
                <button
                    onClick={() => setSearchParams({ view: 'timeline' })}
                    className="btn"
                    style={{
                        background: view === 'timeline' ? 'var(--info)' : 'transparent',
                        border: '1px solid var(--border)',
                        color: view === 'timeline' ? 'white' : 'var(--text-muted)'
                    }}
                >
                    Timeline
                </button>
                <button
                    onClick={() => setSearchParams({ view: 'audit' })}
                    className="btn"
                    style={{
                        background: view === 'audit' ? 'var(--success)' : 'transparent',
                        border: '1px solid var(--border)',
                    }}
                >
                    Audit Mode (Verification UI)
                </button>
            </div>

            {view === 'timeline' && commandCenterData ? (
                 <div className="animate-fade">
                    <section className="card" style={{ padding: '1.5rem', marginBottom: '2rem', borderLeft: '4px solid var(--warning)' }}>
                        <h3 className="font-serif text-xl mb-3 flex items-center gap-2">
                            <Scale className="text-warning" size={20} /> Case-Driving Claims
                        </h3>
                        <div className="grid grid-cols-2 gap-4">
                            {commandCenterData.claimRows
                                .filter(r => r.claim_type === 'PROCEDURE' || r.claim_type === 'IMAGING_FINDING')
                                .slice(0, 4)
                                .map(r => (
                                    <div key={r.id} className="p-3 bg-slate-950/30 border border-slate-800 rounded-md">
                                        <div className="text-[10px] uppercase font-bold text-sky-400 tracking-wider mb-1">{r.claim_type}</div>
                                        <div className="text-sm line-clamp-2 text-slate-200 leading-snug">{r.assertion}</div>
                                        <div className="mt-2 text-[10px] text-slate-500 font-mono">{r.date}</div>
                                    </div>
                                ))
                            }
                        </div>
                    </section>

                    <section className="card" style={{ padding: 0, overflow: 'hidden', border: '1px solid var(--border)' }}>
                        <TimelineView 
                            rows={commandCenterData.claimRows} 
                            docs={docs} 
                            onCitationClick={(link) => setSelectedCitation({ 
                                href: link.href, 
                                label: link.label, 
                                filename: link.title,
                                page: parseInt(link.label.replace('p.', ''), 10)
                            })}
                        />
                    </section>
                 </div>
            ) : (
                <div className="animate-fade">
                <div className="grid grid-cols-main gap-8">
                {/* Left Column: Documents */}
                <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.6rem' }} className="font-serif">
                            <FileText style={{ color: 'var(--primary)' }} size={20} /> Source Documents
                        </h2>
                        <div className="text-[10px] font-bold uppercase tracking-widest bg-slate-900 px-2 py-1 rounded text-slate-400 border border-slate-800">
                            {docs.length} Files
                        </div>
                    </div>

                    <div style={{ padding: '1rem', maxHeight: '500px', overflowY: 'auto' }}>
                        {docs.map(doc => (
                            <div key={doc.id} className="file-item" style={{ marginBottom: '0.5rem', background: 'rgba(15, 23, 42, 0.3)' }}>
                                <FileText size={18} className="text-slate-500 flex-shrink-0" />
                                <div style={{ minWidth: 0, flex: 1 }}>
                                    <div style={{ fontWeight: 500, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', fontSize: '0.9rem' }} title={doc.filename}>{doc.filename}</div>
                                    <div className="text-[11px] text-slate-500 flex gap-3 mt-0.5">
                                        <span>{(doc.bytes / 1024 / 1024).toFixed(2)} MB</span>
                                        <span className="opacity-50">•</span>
                                        <span>{new Date(doc.uploaded_at).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                        {docs.length === 0 && (
                            <div className="empty-state">
                                No documents uploaded.
                            </div>
                        )}
                    </div>

                    <div style={{ padding: '1.25rem', borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
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
                            style={{ width: '100%', justifyContent: 'center', border: '1px dashed var(--border)', background: 'transparent' }}
                        >
                            {uploading ? (
                                <>
                                    <Loader2 className="animate-spin" size={18} /> Processing...
                                </>
                            ) : (
                                <>
                                    <Upload size={18} /> Add Medical Record (PDF)
                                </>
                            )}
                        </button>
                    </div>
                </section>

                {/* Right Column: Runs */}
                <section className="card" style={{ padding: 0, overflow: 'hidden' }}>
                    <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.03)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                        <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.6rem' }} className="font-serif">
                            <RefreshCw style={{ color: 'var(--warning)' }} size={20} /> Analysis History
                        </h2>
                        <button onClick={loadData} className="text-slate-500 hover:text-white transition-colors" title="Refresh" style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                            <RefreshCw size={16} />
                        </button>
                    </div>

                    <div style={{ padding: '1rem', maxHeight: '600px', overflowY: 'auto' }}>
                        {runs.map(run => (
                            <div key={run.id} className="run-item" style={{ background: 'rgba(15, 23, 42, 0.4)', borderColor: 'rgba(255,255,255,0.05)' }}>
                                <div className="flex justify-between items-start" style={{ marginBottom: '0.75rem' }}>
                                    <div className="flex items-center gap-2">
                                        {run.status === 'success' && <CheckCircle style={{ color: 'var(--success)' }} size={16} />}
                                        {run.status === 'pending' && <Clock style={{ color: 'var(--warning)' }} size={16} />}
                                        {run.status === 'running' && <Loader2 style={{ color: 'var(--primary)' }} className="animate-spin" size={16} />}
                                        {run.status === 'failed' && <AlertTriangle style={{ color: 'var(--danger)' }} size={16} />}
                                        <span className="text-xs font-bold uppercase tracking-wider">{run.status}</span>
                                    </div>
                                    <div className="text-[10px] text-slate-500 font-mono">
                                        {new Date(run.started_at || Date.now()).toLocaleDateString()}
                                    </div>
                                </div>

                                {run.status === 'failed' && (
                                    <div className="text-[11px] text-rose-300 bg-rose-500/10 border border-rose-500/20 rounded-md px-3 py-2">
                                        {run.error_message || 'Run failed. No error details were recorded.'}
                                    </div>
                                )}

                                {Array.isArray(run.warnings) && run.warnings.length > 0 && (
                                    <div className="text-[11px] text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-md px-3 py-2 mt-2">
                                        Warnings: {run.warnings.slice(0, 3).join(' • ')}{run.warnings.length > 3 ? '…' : ''}
                                    </div>
                                )}

                                {run.metrics && (
                                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px] text-slate-400 mb-3 border-t border-white/5 pt-2">
                                        <div>Pages: <span className="text-slate-200">{run.metrics.page_count}</span></div>
                                        <div>Events: <span className="text-slate-200">{run.metrics.event_count}</span></div>
                                        <div>Duration: <span className="text-slate-200">{(run.processing_seconds || 0).toFixed(0)}s</span></div>
                                    </div>
                                )}

                                {run.status === 'success' && (
                                    <div className="flex flex-wrap gap-1.5 mt-2">
                                        <a href={getArtifactUrl(run.id, ARTIFACT_TYPES.PDF)} target="_blank" className="artifact-link" rel="noreferrer">
                                            <FileText size={12} /> PDF
                                        </a>
                                        <a href={getArtifactUrl(run.id, ARTIFACT_TYPES.DOCX)} target="_blank" className="artifact-link" rel="noreferrer">
                                            <FileText size={12} /> Word
                                        </a>
                                        <a href={getArtifactUrl(run.id, ARTIFACT_TYPES.SPECIALS_SUMMARY_PDF)} target="_blank" className="artifact-link" rel="noreferrer" style={{ opacity: 0.8 }}>
                                            <FileText size={12} /> Bills
                                        </a>
                                        <a href={getArtifactUrl(run.id, ARTIFACT_TYPES.MISSING_RECORDS_CSV)} target="_blank" className="artifact-link text-rose-400 border-rose-500/20" rel="noreferrer">
                                            <AlertTriangle size={12} /> Gaps
                                        </a>
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                </section>
                </div>

                <section ref={commandCenterRef} className="card" style={{ marginTop: '2rem', padding: 0, overflow: 'hidden', border: view === 'audit' ? '1px solid var(--success)' : '1px solid var(--border)' }}>
                <div style={{ padding: '1.25rem', borderBottom: '1px solid var(--border)', background: 'rgba(34, 197, 94, 0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.6rem' }} className="font-serif">
                        <Scale style={{ color: 'var(--success)' }} size={20} /> Analytical Verification (Audit Mode)
                    </h2>
                    <button
                        onClick={() => void loadCommandCenter(runs)}
                        className="text-slate-500 hover:text-white transition-colors"
                        title="Refresh analysis"
                        style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>

                <div style={{ padding: '1.5rem' }}>
                    {!getLatestCompletedRun(runs) && (
                        <div className="empty-state" style={{ border: 'none' }}>
                            Run analysis to unlock legal insights.
                        </div>
                    )}

                    {!commandCenterLoading && !commandCenterError && !commandCenterData && getLatestRun(runs)?.status === 'failed' && (
                        <div className="badge-risk py-3 px-4 rounded-md text-sm border-rose-500/20 w-full text-center">
                            Latest run failed: {getLatestRun(runs)?.error_message || 'No error details available.'}
                        </div>
                    )}

                    {commandCenterLoading && (
                        <div className="flex items-center gap-3 text-slate-400 py-8">
                            <Loader2 className="animate-spin" size={24} /> 
                            <span className="text-lg font-serif italic">Synthesizing litigation extensions...</span>
                        </div>
                    )}

                    {!commandCenterLoading && commandCenterError && (
                        <div className="badge-risk py-3 px-4 rounded-md text-sm border-rose-500/20 w-full text-center">
                            Analysis Unavailable: {commandCenterError}
                        </div>
                    )}

                    {!commandCenterLoading && !commandCenterError && commandCenterData && (
                        <div className="flex flex-col gap-8">
                            <div className="grid grid-cols-4 gap-4">
                                <div className="p-4 bg-slate-950/40 rounded-lg border border-slate-800">
                                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Anchor Fidelity</div>
                                    <div className="text-2xl font-serif text-emerald-400">{(Number(commandCenterData.citationFidelity?.claim_row_anchor_ratio || 0) * 100).toFixed(0)}%</div>
                                </div>
                                <div className="p-4 bg-slate-950/40 rounded-lg border border-slate-800">
                                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Causation Rungs</div>
                                    <div className="text-2xl font-serif text-sky-400">{commandCenterData.causationChains.length}</div>
                                </div>
                                <div className="p-4 bg-slate-950/40 rounded-lg border border-slate-800">
                                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Case Risks</div>
                                    <div className="text-2xl font-serif text-rose-400">{commandCenterData.collapseCandidates.length}</div>
                                </div>
                                <div className="p-4 bg-slate-950/40 rounded-lg border border-slate-800">
                                    <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Factual Conflicts</div>
                                    <div className="text-2xl font-serif text-amber-400">{commandCenterData.contradictionMatrix.length}</div>
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-8">
                                <div className="space-y-4">
                                    <h3 className="text-xl font-serif flex items-center gap-2 border-b border-white/10 pb-3">
                                        <GitBranch size={20} className="text-sky-400" /> Strategic Causation
                                    </h3>
                                    <div className="space-y-3">
                                        {(commandCenterData.causationChains || []).slice(0, 4).map((chain, idx) => (
                                            <div key={`chain-${idx}`} className="p-4 bg-slate-900/40 rounded-lg border border-white/5 hover:border-sky-500/30 transition-colors">
                                                <div className="flex justify-between items-center mb-2">
                                                    <strong className="text-slate-100 font-serif text-lg">{chain?.body_region || 'general'}</strong>
                                                    <span className="text-[10px] px-2 py-1 rounded bg-sky-500/10 text-sky-400 border border-sky-500/20 font-bold uppercase tracking-widest">Integrity {chain?.chain_integrity_score ?? 0}%</span>
                                                </div>
                                                <div className="text-[12px] text-slate-400 leading-relaxed">
                                                    <span className="text-rose-400 font-bold uppercase tracking-tighter mr-1">Missing Rungs:</span> 
                                                    <span className="italic">{(chain?.missing_rungs || []).join(', ') || 'None identified'}</span>
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>

                                <div className="space-y-4">
                                    <h3 className="text-xl font-serif flex items-center gap-2 border-b border-white/10 pb-3">
                                        <ShieldAlert size={20} className="text-rose-400" /> Vulnerability Scan
                                    </h3>
                                    <div className="space-y-3">
                                        {(commandCenterData.collapseCandidates || []).slice(0, 4).map((cand, idx) => (
                                            <div key={`collapse-${idx}`} className="p-4 bg-slate-900/40 rounded-lg border border-white/5 hover:border-rose-500/30 transition-colors">
                                                <div className="flex justify-between items-center mb-2">
                                                    <strong className="text-rose-100 font-serif text-lg capitalize">{cand?.fragility_type?.replace('_', ' ') || 'Case Risk'}</strong>
                                                    <div className="flex items-center gap-1.5">
                                                        <div style={{ width: 40, height: 4, background: '#334155', borderRadius: 2 }}>
                                                            <div style={{ width: `${cand?.fragility_score || 0}%`, height: '100%', background: 'var(--danger)', borderRadius: 2 }} />
                                                        </div>
                                                        <span className="text-[10px] font-bold text-rose-400 font-mono">{cand?.fragility_score ?? 0}</span>
                                                    </div>
                                                </div>
                                                <div className="text-[12px] text-slate-300 leading-relaxed font-medium">"{cand?.why || 'Specific rationale pending...'}"</div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            <div className="space-y-4">
                                <h3 className="text-xl font-serif flex items-center gap-2 border-b border-white/10 pb-3">
                                    <Scale size={20} className="text-emerald-400" /> Argumentative Duality
                                </h3>
                                <div className="grid grid-cols-2 gap-6">
                                    <div className="p-5 bg-emerald-500/[0.03] border border-emerald-500/10 rounded-xl">
                                        <div className="flex items-center gap-2 mb-3">
                                            <div className="w-2 h-2 rounded-full bg-emerald-500" />
                                            <div className="text-[11px] font-bold text-emerald-500 uppercase tracking-widest">Plaintiff Narrative</div>
                                        </div>
                                        <div className="text-sm text-slate-300 leading-relaxed font-serif italic">
                                            {commandCenterData.narrativeDuality?.plaintiff_narrative?.summary || 'Synthesizing plaintiff medical theory...'}
                                        </div>
                                    </div>
                                    <div className="p-5 bg-rose-500/[0.03] border border-rose-500/10 rounded-xl">
                                        <div className="flex items-center gap-2 mb-3">
                                            <div className="w-2 h-2 rounded-full bg-rose-500" />
                                            <div className="text-[11px] font-bold text-rose-500 uppercase tracking-widest">Defense Counter</div>
                                        </div>
                                        <div className="text-sm text-slate-300 leading-relaxed font-serif italic">
                                            {commandCenterData.narrativeDuality?.defense_narrative?.summary || 'Predicting defense medical challenges...'}
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </section>
                </div>
            )}

            {selectedCitation && (
                <div className="evidence-dock" style={{ width: `${dockWidth}px` }}>
                    <div 
                        onMouseDown={startResizing}
                        style={{ 
                            position: 'absolute', 
                            left: -4, 
                            top: 0, 
                            bottom: 0, 
                            width: 8, 
                            cursor: 'col-resize',
                            zIndex: 10,
                            background: isResizing.current ? 'var(--primary)' : 'transparent',
                            transition: 'background 200ms'
                        }} 
                    />
                    <div style={{ padding: '0.75rem 1rem', borderBottom: '1px solid var(--border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: 'var(--bg-card)' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                            <Scale size={18} className="text-primary" />
                            <span style={{ fontWeight: 600, fontSize: '0.9rem', fontFamily: 'var(--font-heading)' }}>
                                Source Verification: {selectedCitation.filename} (Page {selectedCitation.page})
                            </span>
                        </div>
                        <button 
                            onClick={() => setSelectedCitation(null)}
                            className="btn"
                            style={{ padding: '4px 8px', fontSize: '0.75rem' }}
                        >
                            Close Panel
                        </button>
                    </div>
                    <iframe 
                        src={selectedCitation.href || ''} 
                        className="pdf-viewer"
                        title="Evidence Source"
                    />
                </div>
            )}
        </div>
    );
}
