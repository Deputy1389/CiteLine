import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import FirmsList from './pages/FirmsList';
import MatterList from './pages/MatterList';
import MatterDetail from './pages/MatterDetail';
import { LayoutDashboard } from 'lucide-react';

function App() {
  return (
    <BrowserRouter>
      <div className="app-root">
        <nav className="nav-header">
          <div className="container" style={{ padding: '0 2rem', height: '64px', display: 'flex', alignItems: 'center' }}>
            <Link to="/" className="flex items-center gap-2" style={{ fontSize: '1.25rem', fontWeight: 'bold' }}>
              <div style={{ background: 'var(--primary)', padding: '6px', borderRadius: '4px', display: 'flex' }}>
                <LayoutDashboard size={20} color="white" />
              </div>
              CiteLine
            </Link>
          </div>
        </nav>

        <main>
          <Routes>
            <Route path="/" element={<FirmsList />} />
            <Route path="/firms/:firmId" element={<MatterList />} />
            <Route path="/matters/:matterId" element={<MatterDetail />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  );
}

export default App;
