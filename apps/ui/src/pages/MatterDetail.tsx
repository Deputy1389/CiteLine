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
            // Poll for run updates every 5s if there are pending runs
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
        // Optimistic check: only fetch if we know we have actve runs? 
        // Or just fetch latest runs list to keep UI sync.
        // Fetching runs list is cheap.
        try {
            if (!matterId) return;
            const r = await getMatterRuns(matterId);
            // Determine if visual update needed? React handles diff.
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

    if (loading) return <div className="flex items-center justify-center h-screen"><Loader2 className="animate-spin mr-2" /> Loading...</div>;
    if (!matter) return <div className="p-8">Matter not found</div>;

    return (
        <div className="max-w-6xl mx-auto p-6">
            <Link to={`/firms/${matter.firm_id}`} className="inline-flex items-center gap-2 text-gray-400 hover:text-white mb-6 transition-colors">
                <ArrowLeft size={16} /> Back to Matter List
            </Link>

            <header className="mb-8 border-b border-gray-800 pb-6 flex justify-between items-start">
                <div>
                    <h1 className="text-3xl font-bold mb-2">{matter.title}</h1>
                    <div className="flex gap-4 text-gray-400">
                        {matter.client_ref && <span>Ref: {matter.client_ref}</span>}
                        <span>ID: {matter.id.slice(0, 8)}</span>
                    </div>
                </div>
                <button
                    onClick={handleStartRun}
                    disabled={docs.length === 0}
                    className="bg-green-600 hover:bg-green-700 text-white px-6 py-3 rounded-lg font-bold flex items-center gap-2 shadow-lg hover:shadow-green-900/20 disabled:opacity-50 disabled:cursor-not-allowed transition-all"
                >
                    <Play size={20} fill="currentColor" /> Start Analysis
                </button>
            </header>

            <div className="grid md:grid-cols-[1fr_1.2fr] gap-8">

                {/* Left Column: Documents */}
                <section className="bg-[#1e1e1e] rounded-xl border border-gray-800 shadow-xl overflow-hidden">
                    <div className="p-4 border-b border-gray-800 bg-gray-900/50 flex justify-between items-center">
                        <h2 className="text-lg font-semibold flex items-center gap-2">
                            <FileText className="text-blue-400" /> Source Documents
                        </h2>
                        <div className="text-xs font-mono bg-gray-800 px-2 py-1 rounded text-gray-400">
                            {docs.length} Files
                        </div>
                    </div>

                    <div className="p-4 space-y-3 max-h-[500px] overflow-y-auto">
                        {docs.map(doc => (
                            <div key={doc.id} className="bg-gray-800/50 p-3 rounded flex items-center gap-3 border border-gray-700 hover:border-blue-500/50 transition-colors">
                                <FileText size={20} className="text-gray-500 flex-shrink-0" />
                                <div className="min-w-0 flex-1">
                                    <div className="text-sm font-medium truncate" title={doc.filename}>{doc.filename}</div>
                                    <div className="text-xs text-gray-500 flex gap-3">
                                        <span>{(doc.bytes / 1024 / 1024).toFixed(2)} MB</span>
                                        <span>{new Date(doc.uploaded_at).toLocaleDateString()}</span>
                                    </div>
                                </div>
                            </div>
                        ))}
                        {docs.length === 0 && (
                            <div className="text-center py-8 text-gray-500 border border-dashed border-gray-800 rounded">
                                No documents uploaded yet.
                            </div>
                        )}
                    </div>

                    <div className="p-4 border-t border-gray-800 bg-gray-900/30">
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleUpload}
                            className="hidden"
                            accept=".pdf"
                        />
                        <button
                            onClick={() => fileInputRef.current?.click()}
                            disabled={uploading}
                            className="w-full border-2 border-dashed border-gray-700 hover:border-blue-500 bg-gray-800/50 hover:bg-gray-800 text-gray-300 py-4 rounded-lg flex items-center justify-center gap-2 transition-all"
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
                <section className="bg-[#1e1e1e] rounded-xl border border-gray-800 shadow-xl overflow-hidden">
                    <div className="p-4 border-b border-gray-800 bg-gray-900/50 flex justify-between items-center">
                        <h2 className="text-lg font-semibold flex items-center gap-2">
                            <RefreshCw className="text-purple-400" /> Run History
                        </h2>
                        <button onClick={loadData} className="text-gray-500 hover:text-white" title="Refresh">
                            <RefreshCw size={16} />
                        </button>
                    </div>

                    <div className="p-4 space-y-4 max-h-[600px] overflow-y-auto">
                        {runs.map(run => (
                            <div key={run.id} className="bg-gray-800 rounded-lg p-4 border border-gray-700">
                                <div className="flex justify-between items-start mb-3">
                                    <div className="flex items-center gap-2">
                                        {run.status === 'success' && <CheckCircle className="text-green-500" size={18} />}
                                        {run.status === 'pending' && <Clock className="text-yellow-500" size={18} />}
                                        {run.status === 'running' && <Loader2 className="text-blue-500 animate-spin" size={18} />}
                                        {run.status === 'failed' && <AlertTriangle className="text-red-500" size={18} />}
                                        <span className="font-semibold capitalize text-gray-200">{run.status}</span>
                                    </div>
                                    <div className="text-xs text-gray-500 font-mono">
                                        {new Date(run.started_at || Date.now()).toLocaleString()}
                                    </div>
                                </div>

                                {run.metrics && (
                                    <div className="grid grid-cols-2 gap-2 text-xs text-gray-400 mb-3 bg-gray-900/50 p-2 rounded">
                                        <div>Pages: <span className="text-white">{run.metrics.page_count}</span></div>
                                        <div>Events: <span className="text-white">{run.metrics.event_count}</span></div>
                                        <div>Providers: <span className="text-white">{run.metrics.provider_count}</span></div>
                                        <div>Duration: <span className="text-white">{(run.processing_seconds || 0).toFixed(1)}s</span></div>
                                    </div>
                                )}

                                {run.status === 'success' && (
                                    <div className="flex flex-wrap gap-2 mt-2">
                                        <a
                                            href={getArtifactUrl(run.id, 'docx')}
                                            target="_blank"
                                            className="flex items-center gap-1.5 bg-blue-900/30 hover:bg-blue-900/50 text-blue-300 px-3 py-1.5 rounded text-sm transition-colors border border-blue-900/50"
                                        >
                                            <FileText size={14} /> Chronology (DOCX)
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'specials_summary_pdf')}
                                            target="_blank"
                                            className="flex items-center gap-1.5 bg-purple-900/30 hover:bg-purple-900/50 text-purple-300 px-3 py-1.5 rounded text-sm transition-colors border border-purple-900/50"
                                        >
                                            <FileText size={14} /> Specials (PDF)
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'csv')}
                                            target="_blank"
                                            className="flex items-center gap-1.5 bg-gray-700 hover:bg-gray-600 text-gray-300 px-3 py-1.5 rounded text-sm transition-colors border border-gray-600"
                                        >
                                            <FileSpreadsheet size={14} /> CSV
                                        </a>
                                        <a
                                            href={getArtifactUrl(run.id, 'missing_records_csv')}
                                            target="_blank"
                                            className="flex items-center gap-1.5 bg-red-900/20 hover:bg-red-900/40 text-red-300 px-3 py-1.5 rounded text-sm transition-colors border border-red-900/50"
                                        >
                                            <AlertTriangle size={14} /> Gaps
                                        </a>
                                    </div>
                                )}
                                {run.error_message && (
                                    <div className="mt-2 text-xs text-red-400 bg-red-900/20 p-2 rounded border border-red-900/30">
                                        Error: {run.error_message}
                                    </div>
                                )}
                            </div>
                        ))}
                        {runs.length === 0 && (
                            <div className="text-center py-12 text-gray-500">
                                No runs yet. Upload documents and click "Start Analysis".
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
}
