import { useState } from 'react';
import { useDownloadStore, fmtBytes, fmtSpeed, fmtEta } from '../store/downloadStore';
import {
  Download, Pause, Play, X, Trash2, FolderOpen,
  Film, Music, Archive, FileText, Image, Package, File,
  Plus, RotateCcw, AlertTriangle, CirclePlay
} from 'lucide-react';
import { revealItemInDir } from '@tauri-apps/plugin-opener';
import { openFolder } from '../lib/openFolder';

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
function fmtDate(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric'
  });
}
function fmtTime(ts) {
  if (!ts) return '';
  return new Date(ts * 1000).toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
}
function fmtDuration(startTs, endTs) {
  if (!startTs || !endTs) return '';
  const s = Math.round(endTs - startTs);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60), r = s % 60;
  return r > 0 ? `${m}m ${r}s` : `${m}m`;
}

function DownloadCard({ task, onToast }) {
  const {
    pauseDownload, resumeDownload, cancelDownload,
    removeDownload, retryDownload, startDownload, selectTask, selectedId
  } = useDownloadStore();

  const Icon = TYPE_ICONS[task.file_type] || File;
  const color = STATUS_COLORS[task.status] || '#94a3b8';
  const isActive    = task.status === 'downloading';
  const isPaused    = task.status === 'paused';
  const isDone      = task.status === 'completed';
  const isFailed    = task.status === 'failed';
  const isCancelled = task.status === 'cancelled';
  const isQueued = task.status === 'queued';
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
    const error = await openFolder(task.save_dir, task.filename);
    if (error) onToast(error);
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
          {isDone && task.started_at && (
            <span className="stat-timestamps">
              {fmtDate(task.completed_at)}
              <span className="ts-sep">·</span>
              {fmtTime(task.started_at)}–{fmtTime(task.completed_at)}
              <span className="ts-sep">·</span>
              {fmtDuration(task.started_at, task.completed_at)}
            </span>
          )}
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
        {isQueued && (
          <button
            className="action-btn start"
            title="Start now"
            onClick={() => startDownload(task.id)}
          >
            <CirclePlay size={14} />
          </button>
        )}
        {isDone && (
          <button className="action-btn" title="Show in folder" onClick={handleShowInFolder}>
            <FolderOpen size={14} />
          </button>
        )}
        {!isDone && !isFailed && !isCancelled && (
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