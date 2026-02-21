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
    FileSpreadsheet, ArrowLeft, RefreshCw, Loader2, Scale, GitBranch, ShieldAlert, ListChecks, ExternalLink
} from 'lucide-react';

type CommandCenterData = {
    runId: string;
    claimRows: Record<string, any>[];
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

    const fileInputRef = useRef<HTMLInputElement>(null);
    const commandCenterRef = useRef<HTMLElement | null>(null);
    const view = searchParams.get('view') === 'audit' ? 'audit' : 'intake';

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

    const getLatestCompletedRun = (runList: Run[]) => {
        return runList.find((r) => completedStatuses.has(r.status)) || null;
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
                claimRows: Array.isArray(ext?.claim_rows) ? ext.claim_rows : [],
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
        if (view === 'audit' && commandCenterRef.current) {
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
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.DOCX)}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#93c5fd', borderColor: 'rgba(147, 197, 253, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Docx
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.PDF)}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#d8b4fe', borderColor: 'rgba(216, 180, 254, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Chronology (PDF)
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.SPECIALS_SUMMARY_PDF)}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#d8b4fe', opacity: 0.6, borderColor: 'rgba(216, 180, 254, 0.1)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Bills
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.CSV)}
                                            target="_blank"
                                            className="artifact-link"
                                            rel="noreferrer"
                                        >
                                            <FileSpreadsheet size={14} /> CSV
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.MISSING_RECORDS_CSV)}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#fca5a5', borderColor: 'rgba(252, 165, 165, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <AlertTriangle size={14} /> Gaps
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, ARTIFACT_TYPES.MISSING_RECORD_REQUESTS_MD)}
                                            target="_blank"
                                            className="artifact-link"
                                            style={{ color: '#fdba74', borderColor: 'rgba(253, 186, 116, 0.2)' }}
                                            rel="noreferrer"
                                        >
                                            <FileText size={14} /> Requests
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

            <section ref={commandCenterRef} className="card" style={{ marginTop: '2rem', padding: 0, overflow: 'hidden', border: view === 'audit' ? '1px solid var(--success)' : undefined }}>
                <div style={{ padding: '1rem', borderBottom: '1px solid var(--border)', background: 'rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <h2 style={{ fontSize: '1.1rem', margin: 0, display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                        <Scale style={{ color: 'var(--primary)' }} /> Audit Mode (Verification UI)
                    </h2>
                    <button
                        onClick={() => void loadCommandCenter(runs)}
                        className="text-muted hover:text-white"
                        title="Refresh command center"
                        style={{ background: 'none', border: 'none', cursor: 'pointer' }}
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>

                <div style={{ padding: '1rem' }}>
                    {!getLatestCompletedRun(runs) && (
                        <div className="empty-state" style={{ border: 'none', padding: '1rem' }}>
                            Run a successful analysis to unlock command-center insights.
                        </div>
                    )}

                    {commandCenterLoading && (
                        <div className="flex items-center gap-2 text-muted">
                            <Loader2 className="animate-spin" size={16} /> Loading command center...
                        </div>
                    )}

                    {!commandCenterLoading && commandCenterError && (
                        <div style={{ fontSize: '0.85rem', color: 'var(--danger)', background: 'rgba(239, 68, 68, 0.1)', padding: '0.75rem', borderRadius: '6px' }}>
                            Command center unavailable for latest run: {commandCenterError}
                        </div>
                    )}

                    {!commandCenterLoading && !commandCenterError && commandCenterData && (
                        <div className="flex flex-col gap-4">
                            <div className="grid grid-cols-2 gap-2 text-sm" style={{ background: 'rgba(0,0,0,0.2)', padding: '0.75rem', borderRadius: '6px' }}>
                                <div>Run: <span className="font-mono">{commandCenterData.runId.slice(0, 8)}</span></div>
                                <div>Claims: <span className="text-main">{commandCenterData.claimRows.length}</span></div>
                                <div>Causation Chains: <span className="text-main">{commandCenterData.causationChains.length}</span></div>
                                <div>Collapse Candidates: <span className="text-main">{commandCenterData.collapseCandidates.length}</span></div>
                                <div>Contradictions: <span className="text-main">{commandCenterData.contradictionMatrix.length}</span></div>
                                <div>Anchored Ratio: <span className="text-main">{commandCenterData.citationFidelity?.claim_row_anchor_ratio ?? 'n/a'}</span></div>
                            </div>

                            <div className="grid grid-cols-2 gap-8">
                                <div>
                                    <h3 style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <GitBranch size={16} /> Causation Ladder
                                    </h3>
                                    {(commandCenterData.causationChains || []).slice(0, 3).map((chain, idx) => (
                                        <div key={`chain-${idx}`} className="run-item" style={{ marginBottom: '0.5rem' }}>
                                            <div><strong>{chain?.body_region || 'general'}</strong> | integrity {chain?.chain_integrity_score ?? 0}</div>
                                            <div className="text-xs text-muted">Missing: {(chain?.missing_rungs || []).join(', ') || 'none'}</div>
                                        </div>
                                    ))}
                                    {commandCenterData.causationChains.length === 0 && <div className="text-xs text-muted">No causation chains detected.</div>}
                                </div>

                                <div>
                                    <h3 style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <ShieldAlert size={16} /> Case Collapse
                                    </h3>
                                    {(commandCenterData.collapseCandidates || []).slice(0, 3).map((cand, idx) => (
                                        <div key={`collapse-${idx}`} className="run-item" style={{ marginBottom: '0.5rem' }}>
                                            <div><strong>{cand?.fragility_type || 'unknown'}</strong> | score {cand?.fragility_score ?? 0}</div>
                                            <div className="text-xs text-muted">{cand?.why || ''}</div>
                                        </div>
                                    ))}
                                    {commandCenterData.collapseCandidates.length === 0 && <div className="text-xs text-muted">No collapse candidates for this run.</div>}
                                </div>
                            </div>

                            <div className="grid grid-cols-2 gap-8">
                                <div>
                                    <h3 style={{ marginBottom: '0.5rem', display: 'flex', alignItems: 'center', gap: '0.4rem' }}>
                                        <ListChecks size={16} /> Contradiction Matrix
                                    </h3>
                                    {(commandCenterData.contradictionMatrix || []).slice(0, 4).map((row, idx) => (
                                        <div key={`cx-${idx}`} className="run-item" style={{ marginBottom: '0.5rem' }}>
                                            <div><strong>{row?.category || 'unknown'}</strong> | delta {row?.strength_delta ?? 0}</div>
                                            <div className="text-xs text-muted">
                                                {row?.supporting?.value || 'n/a'} vs {row?.contradicting?.value || 'n/a'}
                                            </div>
                                        </div>
                                    ))}
                                    {commandCenterData.contradictionMatrix.length === 0 && <div className="text-xs text-muted">No contradictions detected.</div>}
                                </div>

                                <div>
                                    <h3 style={{ marginBottom: '0.5rem' }}>Narrative Duality</h3>
                                    <div className="run-item">
                                        <div className="text-sm"><strong>Plaintiff:</strong> {commandCenterData.narrativeDuality?.plaintiff_narrative?.summary || 'n/a'}</div>
                                        <div className="text-sm" style={{ marginTop: '0.4rem' }}><strong>Defense:</strong> {commandCenterData.narrativeDuality?.defense_narrative?.summary || 'n/a'}</div>
                                    </div>
                                </div>
                            </div>

                            <div>
                                <h3 style={{ marginBottom: '0.5rem' }}>Record Packet</h3>
                                <div className="text-xs text-muted" style={{ marginBottom: '0.5rem' }}>
                                    Click any citation to open the original packet at the referenced page.
                                </div>
                                {citationLinks.length > 0 ? (
                                    <div className="flex flex-wrap gap-2">
                                        {citationLinks.map((c, idx) => (
                                            c.href ? (
                                                <a
                                                    key={`cite-${idx}`}
                                                    href={c.href}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="artifact-link"
                                                    title={c.filename || c.label}
                                                >
                                                    <ExternalLink size={12} /> {c.label}
                                                </a>
                                            ) : (
                                                <span key={`cite-${idx}`} className="artifact-link" style={{ opacity: 0.7 }}>
                                                    {c.label}
                                                </span>
                                            )
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-xs text-muted">No citation links available for this run yet.</div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </section>
        </div>
    );
}
