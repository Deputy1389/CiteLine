import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getFirms, createFirm, type Firm } from '../api';
import { Building2, Plus, ArrowRight } from 'lucide-react';

export default function FirmsList() {
    const [firms, setFirms] = useState<Firm[]>([]);
    const [loading, setLoading] = useState(true);
    const [newFirmName, setNewFirmName] = useState('');

    useEffect(() => {
        loadFirms();
    }, []);

    const loadFirms = async () => {
        try {
            const data = await getFirms();
            setFirms(data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!newFirmName.trim()) return;
        try {
            await createFirm(newFirmName);
            setNewFirmName('');
            loadFirms();
        } catch (err) {
            console.error(err);
            alert('Failed to create firm');
        }
    };

    if (loading) return <div className="container">Loading firms...</div>;

    return (
        <div className="container animate-fade">
            <header className="flex justify-between items-end" style={{ marginBottom: '3rem', borderBottom: '1px solid var(--border)', paddingBottom: '1.5rem' }}>
                <div>
                    <h1 className="font-serif text-4xl mb-2">Practice Groups</h1>
                    <p className="text-slate-400">Select a law firm to manage litigation matters</p>
                </div>
                <div className="flex items-center gap-3 bg-slate-900/50 px-4 py-2 rounded-lg border border-slate-800">
                    <Building2 size={18} className="text-sky-400" />
                    <span className="font-serif text-xl text-sky-400">{firms.length}</span>
                    <span className="text-[10px] uppercase font-bold tracking-widest text-slate-500">Active Firms</span>
                </div>
            </header>

            <div className="grid gap-4" style={{ marginBottom: '4rem' }}>
                {firms.map(firm => (
                    <Link
                        key={firm.id}
                        to={`/firms/${firm.id}`}
                        className="card flex justify-between items-center group"
                        style={{ padding: '1.25rem 2rem' }}
                    >
                        <div className="flex items-center gap-6">
                            <div style={{ background: 'rgba(56, 189, 248, 0.05)', padding: '14px', borderRadius: '12px', color: 'var(--primary)', border: '1px solid rgba(56, 189, 248, 0.1)' }} className="group-hover:scale-110 transition-transform duration-300">
                                <Building2 size={28} />
                            </div>
                            <div>
                                <h2 style={{ marginBottom: '0.2rem', fontSize: '1.5rem' }} className="font-serif group-hover:text-primary transition-colors">{firm.name}</h2>
                                <div className="flex items-center gap-2">
                                    <span className="text-[10px] font-bold uppercase tracking-widest text-slate-500">Practice ID:</span>
                                    <code className="text-[11px] text-slate-400 font-mono">{firm.id}</code>
                                </div>
                            </div>
                        </div>
                        <div className="bg-slate-800 p-2 rounded-full text-slate-500 group-hover:text-primary group-hover:bg-sky-500/10 transition-all">
                            <ArrowRight size={20} />
                        </div>
                    </Link>
                ))}
                {firms.length === 0 && (
                    <div className="empty-state">
                        No firms found. Create one to get started.
                    </div>
                )}
            </div>

            <form onSubmit={handleCreate} className="card">
                <h3 className="flex items-center gap-2">
                    <Plus size={20} /> New Firm
                </h3>
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={newFirmName}
                        onChange={e => setNewFirmName(e.target.value)}
                        placeholder="e.g. Smith & Associates"
                        style={{ flex: 1 }}
                    />
                    <button
                        type="submit"
                        className="btn btn-primary"
                        disabled={!newFirmName.trim()}
                    >
                        Create
                    </button>
                </div>
            </form>
        </div>
    );
}
