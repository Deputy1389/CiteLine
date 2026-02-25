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
        <div className="container max-w-4xl py-12">
            <header className="mb-12 border-b border-white/5 pb-8 flex justify-between items-end">
                <div>
                    <h1 className="text-4xl font-serif mb-2 tracking-tight">Practice Groups</h1>
                    <p className="text-slate-500 text-sm">Select a litigation firm to view active medical chronologies</p>
                </div>
                <div className="bg-sky-500/10 px-4 py-2 rounded-lg border border-sky-500/20 text-sky-400">
                    <span className="text-2xl font-serif font-bold mr-2">{firms.length}</span>
                    <span className="text-[10px] font-bold uppercase tracking-widest opacity-60">Firms</span>
                </div>
            </header>

            <div className="space-y-4 mb-12">
                {firms.map(firm => (
                    <Link
                        key={firm.id}
                        to={`/firms/${firm.id}`}
                        className="card flex justify-between items-center group bg-slate-900/20 hover:bg-slate-900/40 border-white/5 hover:border-sky-500/30 transition-all p-6"
                    >
                        <div className="flex items-center gap-6">
                            <div className="bg-slate-950 p-4 rounded-xl border border-white/5 text-slate-400 group-hover:text-sky-400 transition-colors">
                                <Building2 size={24} />
                            </div>
                            <div>
                                <h2 className="text-xl font-serif mb-1">{firm.name}</h2>
                                <div className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">ID: {firm.id.slice(0, 8)}</div>
                            </div>
                        </div>
                        <ArrowRight size={20} className="text-slate-600 group-hover:text-sky-400 transform group-hover:translate-x-1 transition-all" />
                    </Link>
                ))}
            </div>

            <form onSubmit={handleCreate} className="card bg-slate-950/50 border-dashed border-white/10 p-8">
                <div className="flex items-center gap-3 mb-6">
                    <div className="p-2 rounded-lg bg-white/5 text-slate-400">
                        <Plus size={20} />
                    </div>
                    <h3 className="text-lg font-serif">Onboard New Firm</h3>
                </div>
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={newFirmName}
                        onChange={e => setNewFirmName(e.target.value)}
                        placeholder="e.g. Litigation Partners LLP"
                        className="flex-1 bg-slate-900 border border-white/10 rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-sky-500/50"
                    />
                    <button
                        type="submit"
                        className="btn btn-primary px-8"
                        disabled={!newFirmName.trim()}
                    >
                        Register Firm
                    </button>
                </div>
            </form>
        </div>
    );
}
