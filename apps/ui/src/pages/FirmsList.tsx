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
        <div className="container">
            <header className="flex justify-between items-center" style={{ marginBottom: '2rem' }}>
                <div>
                    <h1>Law Firms</h1>
                    <p className="text-muted">Select a firm to view matters</p>
                </div>
                <div className="card flex items-center gap-2" style={{ padding: '0.5rem 1rem' }}>
                    <Building2 style={{ color: 'var(--primary)' }} />
                    <span className="font-mono" style={{ fontSize: '1.25rem' }}>{firms.length}</span>
                </div>
            </header>

            <div className="grid gap-4" style={{ marginBottom: '2rem' }}>
                {firms.map(firm => (
                    <Link
                        key={firm.id}
                        to={`/firms/${firm.id}`}
                        className="card flex justify-between items-center"
                        style={{ textDecoration: 'none' }}
                    >
                        <div className="flex items-center gap-4">
                            <div style={{ background: 'rgba(59, 130, 246, 0.1)', padding: '12px', borderRadius: '50%', color: 'var(--primary)' }}>
                                <Building2 size={24} />
                            </div>
                            <div>
                                <h2 style={{ marginBottom: 0, fontSize: '1.25rem' }}>{firm.name}</h2>
                                <code className="text-muted text-xs">{firm.id}</code>
                            </div>
                        </div>
                        <ArrowRight className="text-muted" />
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
