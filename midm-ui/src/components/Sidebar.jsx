import { useState } from 'react';
import { Download, CheckCircle, Pause, Clock, AlertCircle, Layers, Settings, FolderOpen, AlertTriangle } from 'lucide-react';
import { useDownloadStore } from '../store/downloadStore';
import { openPath, revealItemInDir } from '@tauri-apps/plugin-opener';
import { downloadDir } from '@tauri-apps/api/path';
import { exists } from '@tauri-apps/plugin-fs';

const NAV = [
  { id: 'all',         label: 'All Downloads', icon: Layers },
  { id: 'downloading', label: 'Downloading',   icon: Download },
  { id: 'completed',   label: 'Completed',     icon: CheckCircle },
  { id: 'paused',      label: 'Paused',        icon: Pause },
  { id: 'queued',      label: 'Queued',        icon: Clock },
  { id: 'failed',      label: 'Failed',        icon: AlertCircle },
];

function Toast({ message, onClose }) {
  return (
    <div className="toast">
      <AlertTriangle size={14} />
      <span>{message}</span>
      <button className="toast-close" onClick={onClose}>×</button>
    </div>
  );
}

export default function Sidebar() {
  const { tasks, filterStatus, setFilter } = useDownloadStore();
  const [toast, setToast] = useState(null);

  const count = (status) => {
    if (status === 'all') return tasks.length;
    return tasks.filter(t => t.status === status).length;
  };

  const showToast = (message) => {
    setToast(message);
    setTimeout(() => setToast(null), 4000);
  };

  const openDownloadsFolder = async () => {
  try {
    const recentCompleted = [...tasks]
      .reverse()
      .find(t => t.status === 'completed' && t.save_dir && t.filename);

    if (recentCompleted) {
      const sep = recentCompleted.save_dir.endsWith('\\') || recentCompleted.save_dir.endsWith('/') ? '' : '\\';
      const filePath = `${recentCompleted.save_dir}${sep}${recentCompleted.filename}`;
      try {
        await revealItemInDir(filePath);
        return;
      } catch {
        // File gone — try opening just the folder
        try {
          await openPath(recentCompleted.save_dir);
          return;
        } catch {
          showToast(`"${recentCompleted.filename}" was not found. It may have been moved or deleted.`);
          return;
        }
      }
    }

    // Fallback: system Downloads folder
    const dir = await downloadDir();
    await openPath(dir);
  } catch (e) {
    showToast('Could not open the downloads folder.');
  }
};

  return (
    <aside className="sidebar">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
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
        <button className="nav-item" onClick={openDownloadsFolder}>
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