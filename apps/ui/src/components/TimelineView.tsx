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

  if (rows.length === 0) {
    return (
      <div className="empty-state">
        <Calendar className="mx-auto mb-4 opacity-20" size={64} />
        <h3 className="font-serif text-xl">No Evidence Extracted</h3>
        <p className="text-sm opacity-60">Run a full analysis to generate the medical timeline.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <div className="flex justify-between items-center mb-6 bg-slate-900/40 p-3 rounded-lg border border-white/5">
        <div className="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-500 flex items-center gap-2">
          <Activity size={14} className="text-sky-500" />
          {filteredRows.length} Intelligence Points Found
        </div>
        <input 
          type="text" 
          placeholder="Filter intelligence (e.g. 'surgery', 'MRI')..." 
          className="bg-slate-950 border border-white/10 rounded px-4 py-1.5 text-xs text-white focus:outline-none focus:border-sky-500/50 w-64 transition-all"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
      </div>

      <div className="space-y-4">
        {filteredRows.map((row) => {
          const isCaseDriver = row.claim_type === 'PROCEDURE' || row.claim_type === 'IMAGING_FINDING' || row.claim_type === 'DIAGNOSIS';
          return (
            <div 
              key={row.id} 
              className={`group flex gap-6 p-5 rounded-xl border transition-all duration-300 ${isCaseDriver ? 'bg-sky-500/[0.03] border-sky-500/20 shadow-lg shadow-sky-500/5' : 'bg-slate-900/20 border-white/5 hover:border-white/10'}`}
            >
              {/* Left Column: Date & Type */}
              <div className="w-32 shrink-0 flex flex-col gap-2">
                <div className="text-[13px] font-mono font-bold text-slate-400">
                  {row.date}
                </div>
                <div className="flex items-center gap-2">
                  <div className={`p-1.5 rounded bg-slate-950 border ${isCaseDriver ? 'border-sky-500/30 text-sky-400' : 'border-white/5 text-slate-500'}`}>
                    {getIconForType(row.claim_type)}
                  </div>
                </div>
              </div>

              {/* Middle Column: Assertion */}
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-2">
                  <span className={`text-[9px] font-black uppercase tracking-[0.25em] ${isCaseDriver ? 'text-sky-500' : 'text-slate-600'}`}>
                    {row.claim_type.replace('_', ' ')}
                  </span>
                  {isCaseDriver && <div className="w-1 h-1 rounded-full bg-sky-500 animate-pulse" />}
                </div>
                
                <h4 className={`text-lg font-serif leading-snug mb-2 ${isCaseDriver ? 'text-slate-100' : 'text-slate-300 group-hover:text-slate-200'}`}>
                  {row.assertion}
                </h4>
                
                <div className="flex items-center gap-4">
                  {row.provider && row.provider !== 'unknown' && (
                    <div className="text-[11px] text-slate-500 flex items-center gap-1.5 font-medium">
                      <Stethoscope size={12} className="opacity-40" /> {row.provider}
                    </div>
                  )}
                  {row.body_region && (
                    <div className="text-[11px] text-slate-500 flex items-center gap-1.5 font-medium">
                      <Activity size={12} className="opacity-40" /> {row.body_region}
                    </div>
                  )}
                </div>

                {row.flags && row.flags.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-4">
                    {row.flags.map((flag, i) => (
                      <span key={i} className="px-2 py-0.5 rounded text-[9px] font-bold uppercase tracking-wider bg-rose-500/10 text-rose-400 border border-rose-500/20">
                        {flag.replace('_', ' ')}
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Right Column: Citations */}
              <div className="w-48 shrink-0 flex flex-col items-end gap-2">
                <div className="text-[10px] text-slate-600 font-bold uppercase tracking-widest mb-1">Citations</div>
                <div className="flex flex-col gap-2 w-full">
                  {row.citations.map((cite, i) => {
                    const link = getCitationLink(cite, docs);
                    if (link) {
                      return (
                        <button 
                          key={i}
                          onClick={(e) => {
                            e.preventDefault();
                            if (onCitationClick) onCitationClick(link);
                          }}
                          className="flex items-center justify-between px-3 py-1.5 text-[11px] font-bold bg-slate-950 border border-white/5 rounded hover:border-sky-500/50 hover:bg-sky-500/10 hover:text-sky-400 transition-all text-left"
                        >
                          <span className="truncate opacity-60 mr-2">{link.title.split('.').slice(0, -1).join('.')}</span>
                          <span className="shrink-0">{link.label}</span>
                        </button>
                      );
                    }
                    return null;
                  })}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// Helper to resolve citations
const getCitationLink = (citation: string, docs: Document[]) => {
  const match = citation.match(/^(?:(.+?)\s+)?p\.\s*(\d+)$/i);
  if (!match) return null;

  const [_, filename, pageStr] = match;
  const page = parseInt(pageStr, 10);
  
  let doc: Document | undefined;
  if (filename) {
    doc = docs.find(d => d.filename.toLowerCase().includes(filename.toLowerCase()));
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
