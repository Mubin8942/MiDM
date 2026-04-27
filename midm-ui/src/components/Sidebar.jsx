import { Download, CheckCircle, Pause, Clock, AlertCircle, Layers, Settings, FolderOpen } from 'lucide-react';
import { useDownloadStore } from '../store/downloadStore';

const NAV = [
  { id: 'all',         label: 'All Downloads', icon: Layers },
  { id: 'downloading', label: 'Downloading',   icon: Download },
  { id: 'completed',   label: 'Completed',     icon: CheckCircle },
  { id: 'paused',      label: 'Paused',        icon: Pause },
  { id: 'queued',      label: 'Queued',        icon: Clock },
  { id: 'failed',      label: 'Failed',        icon: AlertCircle },
];

export default function Sidebar() {
  const { tasks, filterStatus, setFilter } = useDownloadStore();

  const count = (status) => {
    if (status === 'all') return tasks.length;
    return tasks.filter(t => t.status === status).length;
  };

  return (
    <aside className="sidebar">
      <nav className="sidebar-nav">
        {NAV.map(({ id, label, icon: Icon }) => {
          const n = count(id);
          return (
            <button
              key={id}
              className={`nav-item ${filterStatus === id ? 'active' : ''}`}
              onClick={() => setFilter(id)}
            >
              <Icon size={15} />
              <span>{label}</span>
              {n > 0 && <em className="badge">{n}</em>}
            </button>
          );
        })}
      </nav>

      <div className="sidebar-footer">
        <button className="nav-item" onClick={() => {
          if (window.__TAURI__) {
            window.__TAURI__.shell.open('Downloads');
          }
        }}>
          <FolderOpen size={15} />
          <span>Downloads Folder</span>
        </button>
        <button className="nav-item">
          <Settings size={15} />
          <span>Settings</span>
        </button>
      </div>
    </aside>
  );
}