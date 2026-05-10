import { useEffect, useState } from 'react';
import { useDownloadStore } from './store/downloadStore';
import Sidebar from './components/Sidebar';
import DownloadList from './components/DownloadList';
import AddDownloadModal from './components/AddDownloadModal';
import TitleBar from './components/TitleBar';
import StatusBar from './components/StatusBar';
import './App.css';

export default function App() {
  const { connect, connected, connectionError } = useDownloadStore();
  const [showAdd, setShowAdd] = useState(false);

  useEffect(() => { connect(); }, []);

  useEffect(() => {
    const handler = (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
        e.preventDefault();
        setShowAdd(true);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div className="app">
      <TitleBar onAdd={() => setShowAdd(true)} connected={connected} />
      <div className="app-body">
        <Sidebar />
        <main className="main-content">
          {!connected && (
            <div className="connection-banner">
              <div className="connection-dot pulsing" />
              <span>
                {connectionError
                  ? connectionError + ' — Make sure the MiDM backend is running.'
                  : 'Connecting to MiDM engine…'}
              </span>
              <code>python backend/server.py</code>
            </div>
          )}
          <DownloadList onAdd={() => setShowAdd(true)} />
        </main>
      </div>
      <StatusBar />
      {showAdd && <AddDownloadModal onClose={() => setShowAdd(false)} />}
    </div>
  );
}