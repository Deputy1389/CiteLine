import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import FirmsList from './pages/FirmsList';
import MatterList from './pages/MatterList';
import MatterDetail from './pages/MatterDetail';
import Landing from './pages/Landing';
import { FileText, Database, Shield } from 'lucide-react';

function Navigation() {
  const location = useLocation();
  const isLanding = location.pathname === '/';

  return (
    <nav className={`h-16 flex items-center justify-between px-8 border-b border-white/10 z-50 sticky top-0 backdrop-blur-md ${isLanding ? 'bg-[#0F172A]/80' : 'bg-[#020617]'}`}>
      <Link to="/" className="flex items-center gap-2.5">
        <div className="bg-sky-500/20 p-1.5 rounded-lg border border-sky-500/20">
          <FileText size={22} className="text-sky-400" />
        </div>
        <span className="text-xl font-serif font-bold tracking-tight text-white">LineCite</span>
      </Link>

      <div className="hidden md:flex items-center gap-8">
        <NavLink to="/firms" label="Case Dashboard" icon={<Database size={14} />} active={location.pathname.startsWith('/firms')} />
        <NavLink to="/security" label="Trust Center" icon={<Shield size={14} />} />
      </div>

      <div className="flex items-center gap-4">
        <Link to="/firms" className="text-sm font-medium text-slate-400 hover:text-white transition-colors">Sign In</Link>
        <button className="btn btn-primary text-xs h-9 px-5 font-serif font-bold">Request Access</button>
      </div>
    </nav>
  );
}

function NavLink({ to, label, icon, active }: { to: string; label: string; icon?: React.ReactNode; active?: boolean }) {
  return (
    <Link 
      to={to} 
      className={`flex items-center gap-2 text-sm font-medium transition-colors ${active ? 'text-sky-400' : 'text-slate-400 hover:text-slate-200'}`}
    >
      {icon}
      {label}
    </Link>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen flex flex-col bg-[#0F172A]">
        <Navigation />
        <main className="flex-1 flex flex-col">
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/firms" element={<FirmsList />} />
            <Route path="/firms/:firmId" element={<MatterList />} />
            <Route path="/matters/:matterId" element={<MatterDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
