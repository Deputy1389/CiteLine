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
        <div className="container">
            <Link to="/" className="text-muted hover:text-white flex items-center gap-2 mb-4" style={{ display: 'inline-flex', marginBottom: '1.5rem' }}>
                <ArrowLeft size={16} /> Back to Firms
            </Link>

            <header style={{ marginBottom: '2.5rem', borderBottom: '1px solid var(--border)', paddingBottom: '1.5rem' }}>
                <h1 className="flex items-center gap-4 font-serif text-4xl">
                    <div style={{ background: 'rgba(56, 189, 248, 0.1)', padding: '10px', borderRadius: '12px' }}>
                        <Briefcase size={28} style={{ color: 'var(--primary)' }} />
                    </div>
                    {firm.name}
                </h1>
                <p className="text-slate-400" style={{ marginLeft: '68px', fontSize: '1rem' }}>Active litigation matters and record analysis</p>
            </header>

            <div className="grid gap-4" style={{ marginBottom: '3rem' }}>
                {matters.map(matter => (
                    <Link
                        key={matter.id}
                        to={`/matters/${matter.id}`}
                        className="card"
                        style={{ display: 'block', padding: '1.25rem 1.5rem' }}
                    >
                        <div className="flex justify-between items-center">
                            <div>
                                <h2 style={{ marginBottom: '0.4rem', fontSize: '1.4rem' }} className="font-serif group-hover:text-primary transition-colors">{matter.title}</h2>
                                <div className="flex gap-4 text-xs text-slate-500 uppercase tracking-wider font-bold">
                                    {matter.client_ref && (
                                        <span className="badge" style={{ background: 'rgba(56, 189, 248, 0.05)', color: 'var(--primary)', border: '1px solid rgba(56, 189, 248, 0.1)' }}>Ref: {matter.client_ref}</span>
                                    )}
                                    <span className="flex items-center gap-1.5">
                                        <Calendar size={13} />
                                        Created {new Date(matter.created_at || '').toLocaleDateString()}
                                    </span>
                                </div>
                            </div>
                            <div className="flex items-center gap-4">
                                <code className="text-[10px] text-slate-600 bg-slate-900/50 px-2 py-1 rounded border border-slate-800 font-mono">
                                    {matter.id.slice(0, 8)}
                                </code>
                                <div className="text-slate-700">
                                    <ArrowLeft size={18} style={{ transform: 'rotate(180deg)' }} />
                                </div>
                            </div>
                        </div>
                    </Link>
                ))}
                {matters.length === 0 && (
                    <div className="empty-state">
                        No matters found. Create one below.
                    </div>
                )}
            </div>

            <form onSubmit={handleCreate} className="card">
                <h3 className="flex items-center gap-2">
                    <Plus size={20} style={{ color: 'var(--success)' }} /> New Matter
                </h3>
                <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr auto', gap: '1rem' }}>
                    <input
                        type="text"
                        value={newMatterTitle}
                        onChange={e => setNewMatterTitle(e.target.value)}
                        placeholder="Matter Title (e.g. Doe v. Hospital)"
                    />
                    <input
                        type="text"
                        value={clientRef}
                        onChange={e => setClientRef(e.target.value)}
                        placeholder="Client Ref (Optional)"
                    />
                    <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={!newMatterTitle.trim()}
                    >
                        Create
                    </button>
                </div>
            </form>
        </div>
    );
}
