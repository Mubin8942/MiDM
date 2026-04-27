import { useDownloadStore, fmtSpeed, fmtBytes } from '../store/downloadStore';
import { Activity, HardDrive, Wifi } from 'lucide-react';

export default function StatusBar() {
  const { tasks, connected } = useDownloadStore();

  const active = tasks.filter(t => t.status === 'downloading');
  const totalSpeed = active.reduce((s, t) => s + (t.speed || 0), 0);
  const totalDownloaded = tasks.reduce((s, t) => s + (t.downloaded || 0), 0);
  const completed = tasks.filter(t => t.status === 'completed').length;

  return (
    <footer className="statusbar">
      <div className="statusbar-left">
        <div className={`status-dot ${connected ? 'on' : 'off'}`} />
        <span>{connected ? 'Engine Connected' : 'Engine Offline'}</span>
      </div>

      <div className="statusbar-center">
        {active.length > 0 && (
          <>
            <Activity size={11} />
            <span>{active.length} active</span>
            <span className="status-divider">·</span>
            <Wifi size={11} />
            <span>{fmtSpeed(totalSpeed)}</span>
          </>
        )}
      </div>

      <div className="statusbar-right">
        <HardDrive size={11} />
        <span>{fmtBytes(totalDownloaded)} total · {completed} completed</span>
      </div>
    </footer>
  );
}