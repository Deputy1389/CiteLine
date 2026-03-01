import React, { useState, useEffect } from 'react';
import { AlertCircle, CheckCircle, Play, Pause, Activity, TrendingUp, BarChart3, Terminal, ShieldAlert } from 'lucide-react';

interface CockpitSummary {
  timestamp: string;
  product_health: {
    total_runs_24h: number;
    export_success_rate: number;
    open_incidents: number;
  };
  top_incidents: Array<{
    id: string;
    fingerprint: string;
    impact_score: number;
    count_24h: number;
    last_seen: string;
  }>;
  sales: {
    active_trials: number;
    paid_firms: number;
  };
}

interface WarModeEvent {
  id: string;
  ts: string;
  source: string;
  stage: string;
  fingerprint: string;
  message: string;
  firm_id?: string;
  run_id?: string;
}

export default function Cockpit() {
  const [summary, setSummary] = useState<CockpitSummary | null>(null);
  const [warMode, setWarMode] = useState<{ events: WarModeEvent[] }>({ events: [] });
  const [loading, setLoading] = useState(true);
  const [outboundPaused, setOutboundPaused] = useState(false);

  useEffect(() => {
    async function fetchData() {
      try {
        const [summaryRes, warRes] = await Promise.all([
          fetch('/api/citeline/admin/cockpit/summary'),
          fetch('/api/citeline/admin/cockpit/war-mode')
        ]);
        
        const summaryData = await summaryRes.json();
        const warData = await warRes.json();
        
        setSummary(summaryData);
        setWarMode(warData);
      } catch (err) {
        console.error("Failed to fetch cockpit data", err);
      } finally {
        setLoading(false);
      }
    }
    
    fetchData();
    const interval = setInterval(fetchData, 30000); // Refresh every 30s
    return () => clearInterval(interval);
  }, []);

  const handlePauseOutbound = async (paused: boolean) => {
    try {
      await fetch('/api/citeline/admin/ops/control?key=outbound_paused', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(paused)
      });
      setOutboundPaused(paused);
    } catch (err) {
      console.error("Failed to toggle outbound", err);
    }
  };

  const triggerSnapshot = async () => {
    try {
      await fetch('/api/citeline/admin/cockpit/snapshot');
      alert("Snapshot triggered and written to root directory.");
    } catch (err) {
      console.error("Failed to trigger snapshot", err);
    }
  };

  if (loading || !summary) {
    return (
      <div className="flex-1 flex items-center justify-center bg-[#020617] text-white">
        <Activity className="animate-spin mr-3 text-sky-400" />
        <span className="font-serif">Initializing Linecite Cockpit...</span>
      </div>
    );
  }

  const successRate = summary.product_health.export_success_rate;
  const statusColor = successRate >= 95 ? 'text-emerald-400' : successRate >= 90 ? 'text-amber-400' : 'text-rose-400';
  const statusBg = successRate >= 95 ? 'bg-emerald-500/10' : successRate >= 90 ? 'bg-amber-500/10' : 'bg-rose-500/10';
  const statusBorder = successRate >= 95 ? 'border-emerald-500/20' : successRate >= 90 ? 'border-amber-500/20' : 'border-rose-500/20';

  return (
    <div className="flex-1 bg-[#020617] p-8 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-3xl font-serif font-bold text-white mb-1">🧭 Operational Cockpit</h1>
          <p className="text-slate-400 text-sm">Real-time system health and sales engine monitoring</p>
        </div>
        <div className="flex gap-4">
          <button 
            onClick={triggerSnapshot}
            className="flex items-center gap-2 px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white rounded-lg border border-white/10 text-sm font-medium transition-colors"
          >
            <Terminal size={16} className="text-sky-400" />
            Trigger Snapshot
          </button>
          <button 
            onClick={() => handlePauseOutbound(!outboundPaused)}
            className={`flex items-center gap-2 px-6 py-2 rounded-lg font-bold text-sm transition-all border ${outboundPaused ? 'bg-rose-500/20 border-rose-500/30 text-rose-400 hover:bg-rose-500/30' : 'bg-sky-500 hover:bg-sky-400 text-white border-transparent shadow-lg shadow-sky-500/20'}`}
          >
            {outboundPaused ? <Play size={16} /> : <Pause size={16} />}
            {outboundPaused ? 'RESUME OUTBOUND' : 'PAUSE OUTBOUND'}
          </button>
        </div>
      </div>

      {/* Stoplight Status Bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-6 mb-8">
        <StatusCard 
          label="Export Success Rate" 
          value={`${successRate}%`} 
          subtext="Last 24h"
          color={statusColor}
          bg={statusBg}
          border={statusBorder}
          icon={successRate >= 95 ? <CheckCircle className={statusColor} /> : <AlertCircle className={statusColor} />}
        />
        <StatusCard 
          label="Open Incidents" 
          value={summary.product_health.open_incidents} 
          subtext="Ranked by impact"
          color={summary.product_health.open_incidents > 0 ? 'text-rose-400' : 'text-emerald-400'}
          bg={summary.product_health.open_incidents > 0 ? 'bg-rose-500/10' : 'bg-emerald-500/10'}
          border={summary.product_health.open_incidents > 0 ? 'border-rose-500/20' : 'border-emerald-500/20'}
          icon={<ShieldAlert size={20} className={summary.product_health.open_incidents > 0 ? 'text-rose-400' : 'text-emerald-400'} />}
        />
        <StatusCard 
          label="Active Trials" 
          value={summary.sales.active_trials} 
          subtext="Total across all firms"
          color="text-sky-400"
          bg="bg-sky-500/10"
          border="border-sky-500/20"
          icon={<Activity size={20} className="text-sky-400" />}
        />
        <StatusCard 
          label="Paid Firms" 
          value={summary.sales.paid_firms} 
          subtext="Recurring revenue"
          color="text-emerald-400"
          bg="bg-emerald-500/10"
          border="border-emerald-500/20"
          icon={<TrendingUp size={20} className="text-emerald-400" />}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Left Col: War Mode Live Feed */}
        <div className="lg:col-span-2 space-y-8">
          <div className="bg-[#0F172A] rounded-xl border border-white/5 overflow-hidden shadow-2xl">
            <div className="px-6 py-4 border-b border-white/5 flex items-center justify-between bg-slate-900/50">
              <h2 className="font-serif font-bold text-lg text-white flex items-center gap-2">
                <Activity size={18} className="text-rose-400" />
                War Mode: Live Incident Feed
              </h2>
              <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">Live Updates Every 30s</span>
            </div>
            <div className="divide-y divide-white/5 max-h-[600px] overflow-y-auto custom-scrollbar">
              {warMode.events.length === 0 ? (
                <div className="py-12 text-center">
                  <CheckCircle className="mx-auto text-emerald-500/30 mb-3" size={40} />
                  <p className="text-slate-500 font-serif">No critical incidents in last 24h. System stable.</p>
                </div>
              ) : (
                warMode.events.map((event) => (
                  <div key={event.id} className="px-6 py-4 hover:bg-white/[0.02] transition-colors">
                    <div className="flex items-start justify-between mb-2">
                      <div className="flex items-center gap-3">
                        <span className="text-[10px] font-mono font-bold px-2 py-0.5 rounded bg-rose-500/20 text-rose-400 border border-rose-500/20 uppercase">
                          {event.stage}
                        </span>
                        <span className="text-xs font-mono text-slate-500">{new Date(event.ts).toLocaleTimeString()}</span>
                      </div>
                      <span className="text-[10px] font-mono text-slate-600 uppercase tracking-tighter">Source: {event.source}</span>
                    </div>
                    <h3 className="text-sm font-bold text-white mb-1">{event.fingerprint}</h3>
                    <p className="text-xs text-slate-400 font-mono line-clamp-2 mb-3">{event.message}</p>
                    <div className="flex items-center gap-4">
                      <button className="text-[10px] font-bold text-sky-400 hover:text-sky-300 uppercase tracking-wider flex items-center gap-1 transition-colors">
                        Investigate with AI
                      </button>
                      <button className="text-[10px] font-bold text-slate-500 hover:text-slate-300 uppercase tracking-wider flex items-center gap-1 transition-colors">
                        View Run Details
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>

        {/* Right Col: Top Incidents & Funnel */}
        <div className="space-y-8">
          <div className="bg-[#0F172A] rounded-xl border border-white/5 overflow-hidden shadow-xl">
            <div className="px-6 py-4 border-b border-white/5 bg-slate-900/50">
              <h2 className="font-serif font-bold text-lg text-white">Top Impact Incidents</h2>
            </div>
            <div className="p-6 space-y-4">
              {summary.top_incidents.map((inc) => (
                <div key={inc.id} className="p-3 rounded-lg bg-white/[0.03] border border-white/5">
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[10px] font-mono font-bold text-sky-400 uppercase tracking-wider">Impact Score: {inc.impact_score}</span>
                    <span className="text-[10px] font-mono text-slate-500">{inc.count_24h} hits (24h)</span>
                  </div>
                  <h4 className="text-xs font-bold text-white truncate">{inc.fingerprint}</h4>
                </div>
              ))}
              {summary.top_incidents.length === 0 && (
                <p className="text-xs text-slate-500 italic text-center py-4">All incidents cleared.</p>
              )}
            </div>
          </div>

          <div className="bg-[#0F172A] rounded-xl border border-white/5 overflow-hidden shadow-xl">
            <div className="px-6 py-4 border-b border-white/5 bg-slate-900/50">
              <h2 className="font-serif font-bold text-lg text-white">Intelligence Engine</h2>
            </div>
            <div className="p-6">
              <div className="flex items-center justify-center py-8">
                <div className="text-center">
                  <BarChart3 className="mx-auto text-slate-700 mb-3" size={32} />
                  <p className="text-xs text-slate-500 uppercase tracking-widest font-bold">Awaiting N &ge; 25</p>
                  <p className="text-[10px] text-slate-600 mt-1 italic">Cross-firm aggregates locked for privacy</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatusCard({ label, value, subtext, color, bg, border, icon }: { label: string; value: string | number; subtext: string; color: string; bg: string; border: string; icon: React.ReactNode }) {
  return (
    <div className={`p-6 rounded-xl border ${border} ${bg} shadow-lg transition-all hover:scale-[1.02] duration-300`}>
      <div className="flex items-center justify-between mb-4">
        <span className="text-xs font-serif font-bold uppercase tracking-wider text-slate-400">{label}</span>
        {icon}
      </div>
      <div className={`text-3xl font-serif font-bold mb-1 ${color}`}>
        {value}
      </div>
      <div className="text-[10px] font-mono font-bold text-slate-500 uppercase tracking-tighter">
        {subtext}
      </div>
    </div>
  );
}
