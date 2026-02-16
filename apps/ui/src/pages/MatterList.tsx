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

    if (loading) return <div className="p-8">Loading matters...</div>;
    if (!firm) return <div className="p-8">Firm not found</div>;

    return (
        <div className="max-w-4xl mx-auto p-6">
            <Link to="/" className="inline-flex items-center gap-2 text-gray-400 hover:text-white mb-6 transition-colors">
                <ArrowLeft size={16} /> Back to Firms
            </Link>

            <header className="mb-8 border-b border-gray-800 pb-6">
                <h1 className="text-3xl font-bold mb-2 flex items-center gap-3">
                    <Briefcase className="text-blue-500" size={32} />
                    {firm.name}
                </h1>
                <p className="text-gray-400 ml-11">Manage matters for this firm</p>
            </header>

            <div className="grid gap-4 mb-8">
                {matters.map(matter => (
                    <Link
                        key={matter.id}
                        to={`/matters/${matter.id}`}
                        className="block bg-gray-800 p-6 rounded-lg hover:bg-gray-750 transition-all border border-gray-700 hover:border-blue-500 group relative overflow-hidden"
                    >
                        <div className="absolute top-0 left-0 w-1 h-full bg-blue-600 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex justify-between items-start">
                            <div>
                                <h2 className="text-xl font-semibold mb-1 group-hover:text-blue-400 transition-colors">{matter.title}</h2>
                                <div className="flex gap-4 text-sm text-gray-400">
                                    {matter.client_ref && (
                                        <span className="flex items-center gap-1">Ref: {matter.client_ref}</span>
                                    )}
                                    <span className="flex items-center gap-1">
                                        <Calendar size={14} />
                                        {new Date(matter.created_at || '').toLocaleDateString()}
                                    </span>
                                </div>
                            </div>
                            <div className="text-xs font-mono text-gray-600 bg-gray-900 px-2 py-1 rounded">
                                {matter.id.slice(0, 8)}...
                            </div>
                        </div>
                    </Link>
                ))}
                {matters.length === 0 && (
                    <div className="text-center py-12 text-gray-500 bg-gray-800/30 rounded-lg border border-dashed border-gray-700">
                        No matters found. Create one below.
                    </div>
                )}
            </div>

            <form onSubmit={handleCreate} className="bg-gray-800 p-6 rounded-lg border border-gray-700 shadow-lg">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Plus size={20} className="text-green-500" /> New Matter
                </h3>
                <div className="grid md:grid-cols-[2fr_1fr_auto] gap-4">
                    <input
                        type="text"
                        value={newMatterTitle}
                        onChange={e => setNewMatterTitle(e.target.value)}
                        placeholder="Matter Title (e.g. Doe v. Hospital)"
                        className="bg-gray-900 border border-gray-700 rounded px-4 py-2 text-white focus:outline-none focus:border-blue-500"
                    />
                    <input
                        type="text"
                        value={clientRef}
                        onChange={e => setClientRef(e.target.value)}
                        placeholder="Client Ref (Optional)"
                        className="bg-gray-900 border border-gray-700 rounded px-4 py-2 text-white focus:outline-none focus:border-blue-500"
                    />
                    <button
                        type="submit"
                        className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded font-medium disabled:opacity-50 transition-colors"
                        disabled={!newMatterTitle.trim()}
                    >
                        Create
                    </button>
                </div>
            </form>
        </div>
    );
}
