import { Link } from 'react-router-dom';
import { 
  ShieldCheck, Zap, Scale, FileText, 
  ArrowRight, Search, CheckCircle, Database
} from 'lucide-react';

export default function Landing() {
  return (
    <div className="flex flex-col bg-[#0F172A] text-white overflow-x-hidden">
      {/* Hero Section */}
      <section className="relative pt-32 pb-24 px-8 overflow-hidden">
        <div className="absolute top-0 left-1/2 -translate-x-1/2 w-[1000px] h-[1000px] bg-sky-500/5 rounded-full blur-[120px] -z-10" />
        
        <div className="max-w-6xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-sky-500/10 border border-sky-500/20 text-sky-400 text-xs font-bold uppercase tracking-widest mb-8">
            <Zap size={14} /> Deterministic Medical Intelligence
          </div>
          
          <h1 className="text-6xl md:text-7xl font-serif mb-8 leading-[1.1] tracking-tight">
            The Truth in <span className="text-sky-400 italic font-medium">Every Page.</span>
          </h1>
          
          <p className="text-xl text-slate-400 max-w-2xl mx-auto mb-12 leading-relaxed">
            LineCite transforms messy medical records into structured, citeable evidence graphs. 
            Automate your chronologies with 100% auditability for every single fact.
          </p>
          
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link to="/matters" className="btn btn-primary h-14 px-8 text-lg font-serif">
              Start Your Analysis <ArrowRight className="ml-2" />
            </Link>
            <button className="btn h-14 px-8 text-lg bg-white/5 border-white/10 hover:bg-white/10">
              Watch Demo
            </button>
          </div>
        </div>
        
        {/* Product Preview Card */}
        <div className="max-w-5xl mx-auto mt-20 relative">
          <div className="absolute inset-0 bg-sky-500/20 blur-[80px] -z-10 opacity-30" />
          <div className="card bg-slate-900/80 backdrop-blur-sm border-white/10 p-2 shadow-2xl">
            <div className="h-8 border-b border-white/5 flex items-center px-4 gap-1.5 mb-2">
              <div className="w-2.5 h-2.5 rounded-full bg-rose-500/50" />
              <div className="w-2.5 h-2.5 rounded-full bg-amber-500/50" />
              <div className="w-2.5 h-2.5 rounded-full bg-emerald-500/50" />
            </div>
            <img 
              src="https://images.unsplash.com/photo-1586717791821-3f44a563eb4c?q=80&w=2070&auto=format&fit=crop" 
              alt="LineCite Command Center" 
              className="rounded-sm opacity-90 brightness-90 grayscale-[0.2]"
            />
          </div>
        </div>
      </section>

      {/* Features Grid */}
      <section className="py-24 px-8 bg-slate-950/50 border-y border-white/5">
        <div className="max-w-6xl mx-auto">
          <div className="text-center mb-20">
            <h2 className="text-4xl font-serif mb-4">Built for Litigation Experts</h2>
            <p className="text-slate-500">Stop wasting associate hours on manual chronology typing.</p>
          </div>

          <div className="grid md:grid-cols-3 gap-8">
            <FeatureCard 
              icon={<Database className="text-sky-400" />}
              title="Evidence Graphs"
              description="Every extracted medical event is an 'edge' in our graph, linked directly to the source page and bounding box."
            />
            <FeatureCard 
              icon={<Scale className="text-emerald-400" />}
              title="Defense Attack Paths"
              description="Our AI identifies potential defense arguments and contradictions before they are used against you."
            />
            <FeatureCard 
              icon={<Search className="text-amber-400" />}
              title="Missing Records Scout"
              description="Automatically detects gaps in the medical timeline and suggests specific providers to subpoena."
            />
          </div>
        </div>
      </section>

      {/* Trust Section */}
      <section className="py-24 px-8">
        <div className="max-w-4xl mx-auto flex flex-col items-center">
          <div className="flex gap-12 opacity-30 grayscale invert mb-16">
            <div className="text-2xl font-serif font-bold italic tracking-tighter uppercase">FirmOne</div>
            <div className="text-2xl font-serif font-bold italic tracking-tighter uppercase">JusticeLegal</div>
            <div className="text-2xl font-serif font-bold italic tracking-tighter uppercase">CaseMaster</div>
          </div>
          
          <div className="text-center">
            <blockquote className="text-3xl font-serif italic mb-8 leading-tight">
              "LineCite has reduced our medical review time by 80%. The citation fidelity is unmatched in the industry."
            </blockquote>
            <div className="flex items-center justify-center gap-4">
              <div className="w-12 h-12 rounded-full bg-slate-800 border border-white/10" />
              <div className="text-left">
                <div className="font-bold">David S. Chen</div>
                <div className="text-xs text-slate-500 uppercase tracking-widest font-bold">Partner, Chen & Associates</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Final CTA */}
      <section className="py-24 px-8">
        <div className="max-w-5xl mx-auto card bg-gradient-to-br from-sky-500/10 to-transparent border-sky-500/20 p-16 text-center">
          <h2 className="text-5xl font-serif mb-6">Ready to lead with intelligence?</h2>
          <p className="text-xl text-slate-400 mb-10 max-w-xl mx-auto">
            Join the elite firms using deterministic medical extraction to win bigger settlements.
          </p>
          <button className="btn btn-primary h-14 px-12 text-lg font-serif">
            Get Started Today
          </button>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-8 border-t border-white/5 text-slate-600 text-sm">
        <div className="max-w-6xl mx-auto flex justify-between items-center">
          <div className="flex items-center gap-2 font-bold text-slate-400">
            <FileText size={18} className="text-sky-500" /> LineCite
          </div>
          <div className="flex gap-8">
            <a href="#" className="hover:text-white transition-colors">Privacy</a>
            <a href="#" className="hover:text-white transition-colors">Security</a>
            <a href="#" className="hover:text-white transition-colors">Contact</a>
          </div>
          <div>© 2026 LineCite Intelligence. All rights reserved.</div>
        </div>
      </footer>
    </div>
  );
}

function FeatureCard({ icon, title, description }: { icon: React.ReactNode, title: string, description: string }) {
  return (
    <div className="card bg-slate-900/40 border-white/5 p-8 hover:bg-slate-900/60 hover:border-white/10 transition-all group">
      <div className="w-12 h-12 rounded-xl bg-slate-950 border border-white/10 flex items-center justify-center mb-6 group-hover:scale-110 transition-transform">
        {icon}
      </div>
      <h3 className="text-xl font-serif mb-3">{title}</h3>
      <p className="text-slate-500 text-sm leading-relaxed">{description}</p>
      <div className="mt-6 flex items-center gap-2 text-sky-400 text-xs font-bold uppercase tracking-widest opacity-0 group-hover:opacity-100 transition-opacity">
        Learn More <ArrowRight size={14} />
      </div>
    </div>
  );
}
