import { Download, Plus, Settings, Minus, Square, X } from 'lucide-react';
import { useDownloadStore, fmtSpeed } from '../store/downloadStore';
import logo from '../../src-tauri/icons/logo.png';

export default function TitleBar({ onAdd }) {
  const { connected, tasks } = useDownloadStore();
  const totalSpeed = tasks
    .filter(t => t.status === 'downloading')
    .reduce((s, t) => s + (t.speed || 0), 0);

  const handleClose = () => {
    if (window.__TAURI__) window.__TAURI__.window.getCurrent().close();
  };
  const handleMin = () => {
    if (window.__TAURI__) window.__TAURI__.window.getCurrent().minimize();
  };
  const handleMax = () => {
    if (window.__TAURI__) window.__TAURI__.window.getCurrent().toggleMaximize();
  };

  return (
    <header className="titlebar" data-tauri-drag-region>
      <div className="titlebar-left">
        <div className="app-logo">
          <img src={logo} alt="MiDM" />
        </div>
        <span className="app-name">MiDM</span>
        <div className={`conn-pill ${connected ? 'conn-on' : 'conn-off'}`}>
          <span className="conn-dot" />
          {connected ? (totalSpeed > 0 ? fmtSpeed(totalSpeed) : 'Ready') : 'Offline'}
        </div>
      </div>

      <div className="titlebar-center" data-tauri-drag-region>
        {/* Draggable zone */}
      </div>

      <div className="titlebar-right">
        <button className="tb-btn add-btn" onClick={onAdd} title="New Download (Ctrl+N)">
          <Plus size={14} />
          <span>New Download</span>
        </button>
        <button className="tb-icon" onClick={handleMin} title="Minimize"><Minus size={12} /></button>
        <button className="tb-icon" onClick={handleMax} title="Maximize"><Square size={11} /></button>
        <button className="tb-icon tb-close" onClick={handleClose} title="Close"><X size={12} /></button>
      </div>
    </header>
  );
}