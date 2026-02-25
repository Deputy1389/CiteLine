import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { getFirmMatters, createMatter, getFirms, type Matter, type Firm } from '../api';
import { Briefcase, Plus, Calendar, ArrowLeft } from 'lucide-react';

export default function MatterList() {
    const { firmId } = useParams<{ firmId: string }>();
    const [firm, setFirm] = useState<Firm | null>(null);
    const [matters, setMatters] = useState<Matter[]>([]);
    const [loading, setLoading] = useState(true);
    const [newMatterTitle, setNewMatterTitle] = useState('');
    const [clientRef, setClientRef] = useState('');

    useEffect(() => {
        if (firmId) {
            loadData();
        }
    }, [firmId]);

    const loadData = async () => {
        try {
            const [firmsData, mattersData] = await Promise.all([
                getFirms(),
                getFirmMatters(firmId!)
            ]);
            const currentFirm = firmsData.find(f => f.id === firmId);
            setFirm(currentFirm || null);
            setMatters(mattersData);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newMatterTitle.trim()) return;
        try {
            await createMatter(firmId!, newMatterTitle, clientRef);
            setNewMatterTitle('');
            setClientRef('');
            loadData();
        } catch (err) {
            console.error(err);
            alert('Failed to create matter');
        }
    };

    if (loading) return <div className="container">Loading matters...</div>;
    if (!firm) return <div className="container">Firm not found</div>;

    return (
        <div className="container max-w-5xl py-12">
            <Link to="/firms" className="text-slate-500 hover:text-sky-400 flex items-center gap-2 mb-8 transition-colors text-sm font-medium">
                <ArrowLeft size={16} /> Back to Practice Groups
            </Link>

            <header className="mb-12 border-b border-white/5 pb-8 flex justify-between items-end">
                <div className="flex items-center gap-6">
                    <div className="bg-sky-500/10 p-4 rounded-2xl border border-sky-500/20 text-sky-400">
                        <Briefcase size={32} />
                    </div>
                    <div>
                        <h1 className="text-4xl font-serif tracking-tight">{firm.name}</h1>
                        <p className="text-slate-500 text-sm mt-1">Active litigation matters and record analysis</p>
                    </div>
                </div>
                <div className="bg-slate-900/40 px-4 py-2 rounded-lg border border-white/5 text-slate-400">
                    <span className="text-2xl font-serif font-bold mr-2">{matters.length}</span>
                    <span className="text-[10px] font-bold uppercase tracking-widest opacity-60">Matters</span>
                </div>
            </header>

            <div className="space-y-3 mb-12">
                {matters.map(matter => (
                    <Link
                        key={matter.id}
                        to={`/matters/${matter.id}`}
                        className="card group block bg-slate-900/20 hover:bg-slate-900/40 border-white/5 hover:border-sky-500/30 transition-all p-5"
                    >
                        <div className="flex justify-between items-center">
                            <div>
                                <h2 className="text-xl font-serif mb-2 group-hover:text-slate-100 transition-colors">{matter.title}</h2>
                                <div className="flex items-center gap-4">
                                    {matter.client_ref && (
                                        <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-sky-500/10 text-sky-400 border border-sky-500/20 uppercase tracking-wider">Ref: {matter.client_ref}</span>
                                    )}
                                    <span className="flex items-center gap-1.5 text-[10px] text-slate-500 font-bold uppercase tracking-widest">
                                        <Calendar size={12} className="opacity-40" />
                                        Created {new Date(matter.created_at || '').toLocaleDateString()}
                                    </span>
                                </div>
                            </div>
                            <div className="flex items-center gap-6">
                                <code className="text-[10px] text-slate-600 font-mono tracking-tighter uppercase">#{matter.id.slice(0, 8)}</code>
                                <div className="w-8 h-8 rounded-full bg-slate-800 flex items-center justify-center text-slate-600 group-hover:bg-sky-500/10 group-hover:text-sky-400 transition-all">
                                    <ArrowLeft size={16} className="rotate-180" />
                                </div>
                            </div>
                        </div>
                    </Link>
                ))}
                {matters.length === 0 && (
                    <div className="empty-state border-dashed">
                        No active matters found for this firm.
                    </div>
                )}
            </div>

            <form onSubmit={handleCreate} className="card bg-slate-950/50 border-dashed border-white/10 p-8">
                <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 rounded-lg bg-white/5 text-slate-400">
                        <Plus size={20} />
                    </div>
                    <h3 className="text-lg font-serif">Initiate New Matter</h3>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <input
                        type="text"
                        value={newMatterTitle}
                        onChange={e => setNewMatterTitle(e.target.value)}
                        placeholder="Matter Title (e.g. Doe v. Hospital)"
                        className="bg-slate-900 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-sky-500/50"
                    />
                    <input
                        type="text"
                        value={clientRef}
                        onChange={e => setClientRef(e.target.value)}
                        placeholder="Internal Reference (Optional)"
                        className="bg-slate-900 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-sky-500/50"
                    />
                    <button
                        type="submit"
                        className="btn btn-primary font-serif font-bold"
                        disabled={!newMatterTitle.trim()}
                    >
                        Create Matter
                    </button>
                </div>
            </form>
        </div>
    );
}
