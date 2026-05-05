import { useState, useEffect, useRef } from 'react';
import { X, Download, Link, FolderOpen, Sliders } from 'lucide-react';
import { useDownloadStore } from '../store/downloadStore';
import { open } from '@tauri-apps/plugin-dialog';  // ← this was missing

async function pickFolder() {
  try {
    const selected = await open({
      directory: true,
      multiple: false,
    });
    return selected ?? null;
  } catch (e) {
    console.warn('Folder picker failed:', e);
  }
  return null;
}

export default function AddDownloadModal({ onClose }) {
  const { addDownload, settings } = useDownloadStore();
  const [url, setUrl] = useState('');
  const [saveDir, setSaveDir] = useState('');
  const [filename, setFilename] = useState('');
  const [connections, setConnections] = useState(8);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [showAdvanced, setShowAdvanced] = useState(false);
  const inputRef = useRef();

  useEffect(() => {
    inputRef.current?.focus();
    navigator.clipboard?.readText().then(text => {
      if (text?.startsWith('http')) setUrl(text.trim());
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  const handleBrowse = async () => {
    const folder = await pickFolder();
    if (folder) setSaveDir(folder);
  };

  const handleSubmit = async () => {
    if (!url.trim()) { setError('Please enter a URL'); return; }
    try { new URL(url); } catch { setError('Invalid URL'); return; }

    setLoading(true);
    setError('');
    try {
      await addDownload(url.trim(), { saveDir, filename, connections });
      onClose();
    } catch (e) {
      setError(e.message || 'Failed to add download');
      setLoading(false);
    }
  };

  const handleKey = (e) => { if (e.key === 'Enter') handleSubmit(); };

  return (
    <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal">

        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">
            <Download size={16} />
            <span>New Download</span>
          </div>
          <button className="modal-close" onClick={onClose}><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="modal-body">

          {/* URL field */}
          <div className="field">
            <label><Link size={13} /> Download URL</label>
            <input
              ref={inputRef}
              type="url"
              placeholder="https://example.com/file.zip"
              value={url}
              onChange={e => { setUrl(e.target.value); setError(''); }}
              onKeyDown={handleKey}
              className={error ? 'has-error' : ''}
              spellCheck={false}
            />
            {error && <span className="field-error">{error}</span>}
          </div>

          {/* Advanced toggle */}
          <button className="advanced-toggle" onClick={() => setShowAdvanced(v => !v)}>
            <Sliders size={12} />
            {showAdvanced ? 'Hide' : 'Show'} advanced options
          </button>

          {showAdvanced && (
            <div className="advanced-fields">

              {/* Save location */}
              <div className="field">
                <label><FolderOpen size={13} /> Save to</label>
                <div className="input-with-btn">
                  <input
                    type="text"
                    placeholder={`${settings?.save_dir || '~/Downloads'}`}
                    value={saveDir}
                    onChange={e => setSaveDir(e.target.value)}
                    spellCheck={false}
                  />
                  <button
                    type="button"
                    className="browse-btn"
                    onClick={handleBrowse}
                    title="Browse for folder"
                  >
                    <FolderOpen size={14} />
                    Browse
                  </button>
                </div>
                {settings?.save_dir && <span className="field-hint">Default: {settings.save_dir}</span>}
              </div>

              {/* Custom filename */}
              <div className="field">
                <label>Filename (optional)</label>
                <input
                  type="text"
                  placeholder="Leave blank to auto-detect"
                  value={filename}
                  onChange={e => setFilename(e.target.value)}
                />
              </div>

              {/* Connection count */}
              <div className="field">
                <label>Connections: <strong>{connections}</strong></label>
                <input
                  type="range"
                  min={1} max={16}
                  value={connections}
                  onChange={e => setConnections(Number(e.target.value))}
                  className="range-input"
                />
                <div className="range-labels">
                  <span>1 (single)</span>
                  <span>16 (max)</span>
                </div>
              </div>

            </div>
          )}
        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            onClick={handleSubmit}
            disabled={loading || !url.trim()}
          >
            {loading ? <span className="spinner" /> : <><Download size={14} /> Start Download</>}
          </button>
        </div>

      </div>
    </div>
  );
}