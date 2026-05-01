import { create } from 'zustand';
import { isPermissionGranted, requestPermission, sendNotification } from '@tauri-apps/plugin-notification';

const WS_URL = 'ws://127.0.0.1:7475/ws';
const HTTP_URL = 'http://127.0.0.1:7475';

let ws = null;
let reconnectTimer = null;
let pendingReplies = {};
let msgId = 0;

function nextId() { return `${++msgId}`; }

function upsertTask(tasks, incoming) {
  const idx = tasks.findIndex(t => t.id === incoming.id);
  if (idx !== -1) {
    const updated = [...tasks];
    updated[idx] = { ...tasks[idx], ...incoming };
    return updated;
  }
  return [incoming, ...tasks];
}

// Apply theme to document
function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme || 'dark');
}

async function notifyComplete(filename) {
  try {
    let granted = await isPermissionGranted();
    if (!granted) {
      const permission = await requestPermission();
      granted = permission === 'granted';
    }
    if (granted) {
      sendNotification({
        title: 'Download Complete',
        body: `${filename} has finished downloading.`,
      });
    }
  } catch (e) {
    console.error('Notification failed:', e);
  }
}

export const useDownloadStore = create((set, get) => ({
  // ── State ──────────────────────────────────────
  tasks:           [],
  stats:           {},
  settings:        {},
  connected:       false,
  connectionError: null,
  selectedId:      null,
  filterStatus:    'all',

  // ── Derived ────────────────────────────────────
  filteredTasks: () => {
    const { tasks, filterStatus } = get();
    if (filterStatus === 'all') return tasks;
    return tasks.filter(t => t.status === filterStatus);
  },

  totalSpeed: () => {
    const { tasks } = get();
    return tasks
      .filter(t => t.status === 'downloading')
      .reduce((sum, t) => sum + (t.speed || 0), 0);
  },

  // ── Connection ─────────────────────────────────
  connect: () => {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      set({ connected: true, connectionError: null });
      clearTimeout(reconnectTimer);
      // Apply saved theme on reconnect
      const { settings } = get();
      if (settings?.theme) applyTheme(settings.theme);
    };

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data);
        get()._handleMessage(msg);
      } catch {}
    };

    ws.onerror = () => {
      set({ connectionError: 'Cannot connect to MiDM backend.' });
    };

    ws.onclose = () => {
      set({ connected: false });
      reconnectTimer = setTimeout(() => get().connect(), 3000);
    };
  },

  disconnect: () => {
    clearTimeout(reconnectTimer);
    if (ws) { ws.close(); ws = null; }
    set({ connected: false });
  },

  // ── Message Handling ───────────────────────────
  _handleMessage: (msg) => {
    if (msg.type === 'reply') {
      const cb = pendingReplies[msg.id];
      if (cb) {
        delete pendingReplies[msg.id];
        if (msg.error) cb.reject(new Error(msg.error));
        else cb.resolve(msg.result);
      }
      return;
    }

    if (msg.type === 'event') {
      const { event, data } = msg;

      if (event === 'init') {
        set({
          tasks:    data.tasks    || [],
          stats:    data.stats    || {},
          settings: data.settings || {},
        });
        // Apply theme from persisted settings immediately on init
        if (data.settings?.theme) applyTheme(data.settings.theme);
        return;
      }

      if (event === 'task_added') {
        set(s => ({ tasks: upsertTask(s.tasks, data) }));
        return;
      }

      if (event === 'task_progress' || event === 'task_updated') {
        set(s => {
          const old = s.tasks.find(t => t.id === data.id);
          if (
            old &&
            old.status !== 'completed' &&
            data.status === 'completed' &&
            s.settings?.notify_on_complete !== false
          ) {
            notifyComplete(data.filename || old.filename);
          }
          return {
            tasks: s.tasks.map(t => t.id === data.id ? { ...t, ...data } : t),
          };
        });
        return;
      }

      if (event === 'task_removed') {
        set(s => ({ tasks: s.tasks.filter(t => t.id !== data.id) }));
        return;
      }

      if (event === 'settings_updated') {
        set({ settings: data });
        applyTheme(data.theme);
        return;
      }
    }
  },

  // ── Commands ───────────────────────────────────
  _send: (cmd, data) => {
    return new Promise((resolve, reject) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        reject(new Error('Not connected'));
        return;
      }
      const id = nextId();
      pendingReplies[id] = { resolve, reject };
      ws.send(JSON.stringify({ cmd, data, id }));
      setTimeout(() => {
        if (pendingReplies[id]) {
          delete pendingReplies[id];
          reject(new Error('Timeout'));
        }
      }, 10000);
    });
  },

  addDownload: async (url, options = {}) => {
    return get()._send('add_download', {
      url,
      save_dir:    options.saveDir    || '',
      filename:    options.filename   || '',
      connections: options.connections || 0,
    });
  },

  pauseDownload:  (id) => get()._send('pause',  { id }),
  resumeDownload: (id) => get()._send('resume', { id }),
  cancelDownload: (id) => get()._send('cancel', { id }),
  retryDownload:  (id) => get()._send('retry',  { id }),
  startDownload: (id) => get()._send('start', { id }),
  removeDownload: (id, deleteFile = false) =>
    get()._send('remove', { id, delete_file: deleteFile }),

  getSettings:  ()       => get()._send('get_settings',  {}),
  saveSettings: (data)   => get()._send('save_settings', data),

  // ── UI State ───────────────────────────────────
  setFilter:  (filterStatus) => set({ filterStatus }),
  selectTask: (id)           => set({ selectedId: id }),
}));

// ── Utilities ────────────────────────────────────────────────────────────────

export function fmtBytes(bytes) {
  if (!bytes || bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function fmtSpeed(bps) {
  if (!bps || bps === 0) return '0 KB/s';
  if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} MB/s`;
  return `${(bps / 1_000).toFixed(0)} KB/s`;
}

export function fmtEta(seconds) {
  if (!seconds || seconds <= 0) return '--';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

export function fmtProgress(task) {
  if (!task.total_size) return '';
  return `${fmtBytes(task.downloaded)} / ${fmtBytes(task.total_size)}`;
}