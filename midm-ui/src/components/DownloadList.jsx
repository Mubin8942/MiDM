import { useState } from 'react';
import { useDownloadStore, fmtBytes, fmtSpeed, fmtEta } from '../store/downloadStore';
import {
  Download, Pause, Play, X, Trash2, FolderOpen,
  Film, Music, Archive, FileText, Image, Package, File,
  Plus, RotateCcw, AlertTriangle
} from 'lucide-react';
import { revealItemInDir } from '@tauri-apps/plugin-opener';
import { exists } from '@tauri-apps/plugin-fs';

// ─── Toast ───────────────────────────────────────────────────────────────────
function Toast({ message, onClose }) {
  return (
    <div className="toast">
      <AlertTriangle size={14} />
      <span>{message}</span>
      <button className="toast-close" onClick={onClose}>×</button>
    </div>
  );
}

// ─── File type icons ────────────────────────────────────────────────────────
const TYPE_ICONS = {
  video:    Film,
  audio:    Music,
  archive:  Archive,
  document: FileText,
  image:    Image,
  software: Package,
  other:    File,
};

const STATUS_COLORS = {
  downloading: '#3b9eff',
  completed:   '#22c55e',
  paused:      '#f59e0b',
  queued:      '#94a3b8',
  failed:      '#ef4444',
  cancelled:   '#64748b',
  connecting:  '#a78bfa',
  merging:     '#22d3ee',
};

// ─── Download Card ───────────────────────────────────────────────────────────
function DownloadCard({ task, onToast }) {
  const {
    pauseDownload, resumeDownload, cancelDownload,
    removeDownload, retryDownload, selectTask, selectedId
  } = useDownloadStore();

  const Icon = TYPE_ICONS[task.file_type] || File;
  const color = STATUS_COLORS[task.status] || '#94a3b8';
  const isActive    = task.status === 'downloading';
  const isPaused    = task.status === 'paused';
  const isDone      = task.status === 'completed';
  const isFailed    = task.status === 'failed';
  const isSelected  = selectedId === task.id;

  const progress = task.progress || 0;

  const segBars = (task.segments || []).slice(0, 16).map((seg, i) => {
    const segTotal = seg.end - seg.start + 1;
    const segPct = segTotal > 0 ? Math.min((seg.downloaded / segTotal) * 100, 100) : 0;
    return (
      <div key={i} className="seg-bar-wrap" title={`Segment ${i+1}: ${segPct.toFixed(0)}%`}>
        <div className="seg-bar" style={{ height: `${segPct}%`, background: color }} />
      </div>
    );
  });

  const handleShowInFolder = async () => {
  try {
    const sep = task.save_dir.endsWith('\\') || task.save_dir.endsWith('/') ? '' : '\\';
    const filePath = `${task.save_dir}${sep}${task.filename}`;
    await revealItemInDir(filePath);
    } catch (e) {
      onToast(`"${task.filename}" was not found. It may have been moved or deleted.`);
    }
  };

  return (
    <div
      className={`download-card ${isSelected ? 'selected' : ''} status-${task.status}`}
      onClick={() => selectTask(isSelected ? null : task.id)}
    >
      <div className="card-icon" style={{ color }}>
        <Icon size={20} strokeWidth={1.5} />
      </div>

      <div className="card-body">
        <div className="card-top">
          <span className="card-filename" title={task.filename}>{task.filename}</span>
          <span className="card-status" style={{ color }}>{task.status}</span>
        </div>

        <div className="progress-track">
          <div
            className="progress-fill"
            style={{
              width: `${progress}%`,
              background: isDone
                ? '#22c55e'
                : `linear-gradient(90deg, ${color}99, ${color})`,
            }}
          />
        </div>

        <div className="card-stats">
          <span className="stat-size">
            {task.total_size
              ? `${fmtBytes(task.downloaded)} / ${fmtBytes(task.total_size)}`
              : fmtBytes(task.downloaded)}
          </span>
          <span className="stat-pct">{progress.toFixed(1)}%</span>
          {isActive && (
            <>
              <span className="stat-speed">{fmtSpeed(task.speed)}</span>
              <span className="stat-eta">ETA {fmtEta(task.eta)}</span>
            </>
          )}
          {isFailed && <span className="stat-error">{task.error}</span>}
          <span className="stat-threads">
            {(task.segments || []).length > 0 && `${(task.segments || []).length} threads`}
          </span>
        </div>

        {isActive && segBars.length > 1 && (
          <div className="seg-bars">{segBars}</div>
        )}
      </div>

      <div className="card-actions" onClick={e => e.stopPropagation()}>
        {isActive && (
          <button className="action-btn" title="Pause" onClick={() => pauseDownload(task.id)}>
            <Pause size={14} />
          </button>
        )}
        {isPaused && (
          <button className="action-btn" title="Resume" onClick={() => resumeDownload(task.id)}>
            <Play size={14} />
          </button>
        )}
        {isFailed && (
          <button className="action-btn retry" title="Retry" onClick={() => retryDownload(task.id)}>
            <RotateCcw size={14} />
          </button>
        )}
        {isDone && (
          <button className="action-btn" title="Show in folder" onClick={handleShowInFolder}>
            <FolderOpen size={14} />
          </button>
        )}
        {!isDone && !isFailed && (
          <button className="action-btn danger" title="Cancel" onClick={() => cancelDownload(task.id)}>
            <X size={14} />
          </button>
        )}
        <button className="action-btn danger" title="Remove" onClick={() => removeDownload(task.id)}>
          <Trash2 size={14} />
        </button>
      </div>
    </div>
  );
}

// ─── Download List ───────────────────────────────────────────────────────────
export default function DownloadList({ onAdd }) {
  const { tasks, filterStatus } = useDownloadStore();
  const [toast, setToast] = useState(null);

  const showToast = (message) => {
    setToast(message);
    setTimeout(() => setToast(null), 4000);
  };

  const visible = filterStatus === 'all'
    ? tasks
    : tasks.filter(t => t.status === filterStatus);

  if (visible.length === 0) {
    return (
      <div className="empty-state">
        <div className="empty-icon"><Download size={40} strokeWidth={1} /></div>
        <h3>No downloads {filterStatus !== 'all' ? `(${filterStatus})` : ''}</h3>
        <p>Press <kbd>Ctrl+N</kbd> or click <strong>New Download</strong> to get started.</p>
        <button className="btn-primary" onClick={onAdd}>
          <Plus size={14} /> Add Download
        </button>
      </div>
    );
  }

  return (
    <div className="download-list">
      {toast && <Toast message={toast} onClose={() => setToast(null)} />}
      <div className="list-header">
        <span>{visible.length} item{visible.length !== 1 ? 's' : ''}</span>
      </div>
      <div className="cards">
        {visible.map(task => (
          <DownloadCard key={task.id} task={task} onToast={showToast} />
        ))}
      </div>
    </div>
  );
}