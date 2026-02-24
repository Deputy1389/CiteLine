import { useMemo, useState } from 'react';
import { 
  Calendar, FileText, ExternalLink, AlertTriangle, 
  Stethoscope, Activity, Pill, Siren, CheckCircle2 
} from 'lucide-react';
import { getDocumentDownloadUrl, type Document } from '../api';

export type ClaimRow = {
  id: string;
  date: string;
  claim_type: string;
  assertion: string;
  citations: string[];
  provider?: string;
  flags?: string[];
  body_region?: string;
};

interface TimelineViewProps {
  rows: ClaimRow[];
  docs: Document[];
  onCitationClick?: (link: { href: string; label: string; title: string }) => void;
}

const getIconForType = (type: string) => {
  const t = type.toLowerCase();
  if (t.includes('procedure') || t.includes('surgery')) return <Activity size={18} className="text-sky-400" />;
  if (t.includes('dx') || t.includes('diagnosis')) return <Stethoscope size={18} className="text-emerald-400" />;
  if (t.includes('rx') || t.includes('medication')) return <Pill size={18} className="text-purple-400" />;
  if (t.includes('ed') || t.includes('emergency')) return <Siren size={18} className="text-rose-400" />;
  return <FileText size={18} className="text-slate-400" />;
};

export default function TimelineView({ rows, docs, onCitationClick }: TimelineViewProps) {
  const [filter, setFilter] = useState('');

  const sortedRows = useMemo(() => {
    return [...rows].sort((a, b) => new Date(a.date).getTime() - new Date(b.date).getTime());
  }, [rows]);

  const filteredRows = useMemo(() => {
    if (!filter) return sortedRows;
    const lower = filter.toLowerCase();
    return sortedRows.filter(r => 
      r.assertion.toLowerCase().includes(lower) || 
      r.provider?.toLowerCase().includes(lower) ||
      r.claim_type.toLowerCase().includes(lower)
    );
  }, [sortedRows, filter]);

  const getCitationLink = (citation: string) => {
    // Expected format: "filename.pdf p. 123" or just "p. 123"
    const match = citation.match(/^(?:(.+?)\s+)?p\.\s*(\d+)$/i);
    if (!match) return null;

    const [_, filename, pageStr] = match;
    const page = parseInt(pageStr, 10);
    
    // Find document
    let doc: Document | undefined;
    if (filename) {
      doc = docs.find(d => d.filename.toLowerCase() === filename.toLowerCase());
    } else if (docs.length > 0) {
      doc = docs[0];
    }

    if (!doc) return null;

    return {
      href: getDocumentDownloadUrl(doc.id, page),
      label: `p.${page}`,
      title: doc.filename
    };
  };

  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <Calendar className="mx-auto mb-4 opacity-20" size={64} />
        <h3 className="font-serif">No Events Extracted</h3>
        <p className="text-sm">Run a full analysis to generate the medical timeline.</p>
      </div>
    );
  }

  return (
    <div className="timeline-view">
      <div className="flex justify-between items-center px-6 py-4 bg-slate-900/50 border-b border-white/5">
        <div className="text-sm font-medium text-slate-400">
          Showing <span className="text-white">{filteredRows.length}</span> critical medical events
        </div>
        <div className="flex gap-4">
          <input 
            type="text" 
            placeholder="Search timeline (e.g. 'surgery', 'MRI')..." 
            className="bg-slate-950/50 border border-slate-700 rounded-md px-4 py-1.5 text-sm text-white focus:outline-none focus:border-sky-500 w-80"
            value={filter}
            onChange={e => setFilter(e.target.value)}
          />
        </div>
      </div>

      <div className="overflow-auto max-h-[750px] scroll-shadow">
        <table className="w-full text-left border-collapse timeline-table">
          <thead className="sticky top-0 z-20">
            <tr>
              <th className="w-32">Date</th>
              <th className="w-48">Event Category</th>
              <th>Clinical Findings & Legal Leverage</th>
              <th className="w-56">Verified Source</th>
            </tr>
          </thead>
          <tbody>
            {filteredRows.map((row) => {
              const isCaseDriver = row.claim_type === 'PROCEDURE' || row.claim_type === 'IMAGING_FINDING';
              return (
                <tr key={row.id} className={`hover:bg-white/[0.03] transition-colors border-b border-white/[0.02] ${isCaseDriver ? 'bg-sky-500/[0.02]' : ''}`}>
                  <td className="align-top font-mono text-[13px] text-slate-400 pt-5">
                    {row.date}
                  </td>
                  <td className="align-top pt-5">
                    <div className="flex items-center gap-2.5">
                      {getIconForType(row.claim_type)}
                      <span className={`text-[11px] font-bold uppercase tracking-widest ${isCaseDriver ? 'text-sky-400' : 'text-slate-500'}`}>
                        {row.claim_type.replace('_', ' ')}
                      </span>
                    </div>
                  </td>
                  <td className="align-top pt-4 pb-5">
                    <div className={`text-[15px] leading-relaxed ${isCaseDriver ? 'text-slate-100 font-medium' : 'text-slate-300'}`}>
                      {row.assertion}
                    </div>
                    {row.provider && row.provider !== 'unknown' && (
                      <div className="text-[11px] text-slate-500 mt-2 flex items-center gap-1.5 italic">
                        <CheckCircle2 size={12} className="text-emerald-500/50" /> {row.provider}
                      </div>
                    )}
                    {row.flags && row.flags.length > 0 && (
                      <div className="flex flex-wrap gap-2 mt-3">
                        {row.flags.map((flag, i) => (
                          <span key={i} className="badge-risk">
                            <AlertTriangle size={10} className="mr-1 inline" /> {flag.replace('_', ' ')}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="align-top pt-5">
                    <div className="flex flex-wrap gap-1.5">
                      {row.citations.map((cite, i) => {
                        const link = getCitationLink(cite);
                        if (link) {
                          return (
                            <button 
                              key={i}
                              type="button"
                              className="btn py-1 px-2 text-[11px] border-slate-700 bg-slate-800/50 hover:bg-sky-500/20 hover:text-sky-300 hover:border-sky-500/50 transition-all"
                              title={link.title}
                              onClick={(e) => {
                                if (onCitationClick) {
                                  e.preventDefault();
                                  onCitationClick(link);
                                }
                              }}
                            >
                              <ExternalLink size={11} className="mr-1" /> {link.label}
                            </button>
                          );
                        }
                        return (
                          <span key={i} className="text-[10px] text-slate-600 px-2 py-1 border border-slate-800 rounded uppercase">
                            {cite}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
