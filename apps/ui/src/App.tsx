import { BrowserRouter, Routes, Route, Link } from 'react-router-dom';
import FirmsList from './pages/FirmsList';
import MatterList from './pages/MatterList';
import MatterDetail from './pages/MatterDetail';
import { LayoutDashboard } from 'lucide-react';

function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[#1a1a1a] text-gray-100 font-sans">
        <nav className="border-b border-gray-800 bg-[#242424] sticky top-0 z-10">
          <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
            <Link to="/" className="flex items-center gap-3 text-xl font-bold tracking-tight hover:text-blue-400 transition-colors">
              <div className="bg-blue-600 p-1.5 rounded">
                <LayoutDashboard size={20} className="text-white" />
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
