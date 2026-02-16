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

    if (loading) return <div className="p-8">Loading firms...</div>;

    return (
        <div className="max-w-4xl mx-auto p-6">
            <header className="mb-8 flex justify-between items-center">
                <div>
                    <h1 className="text-3xl font-bold mb-2">Law Firms</h1>
                    <p className="text-gray-400">Select a firm to view matters</p>
                </div>
                <div className="bg-gray-800 p-4 rounded-lg flex items-center gap-2">
                    <Building2 className="text-blue-400" />
                    <span className="font-mono text-xl">{firms.length}</span>
                </div>
            </header>

            <div className="grid gap-4 mb-8">
                {firms.map(firm => (
                    <Link
                        key={firm.id}
                        to={`/firms/${firm.id}`}
                        className="block bg-gray-800 p-6 rounded-lg hover:bg-gray-750 transition-colors border border-gray-700 hover:border-blue-500 group"
                    >
                        <div className="flex justify-between items-center">
                            <div className="flex items-center gap-4">
                                <div className="bg-blue-900/30 p-3 rounded-full text-blue-400">
                                    <Building2 size={24} />
                                </div>
                                <div>
                                    <h2 className="text-xl font-semibold group-hover:text-blue-400 transition-colors">{firm.name}</h2>
                                    <code className="text-xs text-gray-500">{firm.id}</code>
                                </div>
                            </div>
                            <ArrowRight className="text-gray-600 group-hover:text-blue-400 transition-colors" />
                        </div>
                    </Link>
                ))}
                {firms.length === 0 && (
                    <div className="text-center py-12 text-gray-500 bg-gray-800/50 rounded-lg border border-dashed border-gray-700">
                        No firms found. Create one to get started.
                    </div>
                )}
            </div>

            <form onSubmit={handleCreate} className="bg-gray-800 p-6 rounded-lg border border-gray-700">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                    <Plus size={20} /> New Firm
                </h3>
                <div className="flex gap-4">
                    <input
                        type="text"
                        value={newFirmName}
                        onChange={e => setNewFirmName(e.target.value)}
                        placeholder="e.g. Smith & Associates"
                        className="flex-1 bg-gray-900 border border-gray-700 rounded px-4 py-2 text-white focus:outline-none focus:border-blue-500"
                    />
                    <button
                        type="submit"
                        className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded font-medium disabled:opacity-50"
                        disabled={!newFirmName.trim()}
                    >
                        Create
                    </button>
                </div>
            </form>
        </div>
    );
}
