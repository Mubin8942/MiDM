import { useState, useEffect } from 'react';
import {
  X, FolderOpen, Save, RotateCcw,
  HardDrive, Zap, Layers, Moon, Sun,
  RefreshCw, Gauge, Play, Bell, Clock
} from 'lucide-react';
import { useDownloadStore } from '../store/downloadStore';
import { open } from '@tauri-apps/plugin-dialog';

const SECTION = ({ title, icon: Icon, children }) => (
  <div className="settings-section">
    <div className="settings-section-title">
      <Icon size={14} />
      <span>{title}</span>
    </div>
    {children}
  </div>
);

const Row = ({ label, hint, children }) => (
  <div className="settings-row">
    <div className="settings-row-label">
      <span>{label}</span>
      {hint && <small>{hint}</small>}
    </div>
    <div className="settings-row-control">
      {children}
    </div>
  </div>
);

const Toggle = ({ value, onChange }) => (
  <button
    className={`toggle ${value ? 'on' : ''}`}
    onClick={() => onChange(!value)}
  >
    <span className="toggle-knob" />
  </button>
);

export default function SettingsModal({ onClose }) {
  const { settings, saveSettings } = useDownloadStore();
  const [form, setForm] = useState({ ...settings });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setForm({ ...settings });
  }, [settings]);

  const set = (key, value) => setForm(f => ({ ...f, [key]: value }));

  const browseSaveDir = async () => {
    try {
      const selected = await open({ directory: true, multiple: false });
      if (selected) set('save_dir', selected);
    } catch (e) {
      console.error('Browse failed:', e);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await saveSettings(form);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error('Save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setForm({ ...settings });
  };

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal settings-modal">

        {/* Header */}
        <div className="modal-header">
          <div className="modal-title">
            <Zap size={16} style={{ color: 'var(--accent)' }} />
            Settings
          </div>
          <button className="modal-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="settings-body">

          {/* Download Location */}
          <SECTION title="Download Location" icon={HardDrive}>
            <Row label="Default Save Directory" hint="Where files are saved unless overridden">
              <div className="input-with-btn">
                <input
                  type="text"
                  value={form.save_dir || ''}
                  onChange={e => set('save_dir', e.target.value)}
                  className="settings-input"
                  readOnly
                />
                <button className="browse-btn" onClick={browseSaveDir}>
                  <FolderOpen size={13} /> Browse
                </button>
              </div>
            </Row>
          </SECTION>

          {/* Download Behaviour */}
          <SECTION title="Download Behaviour" icon={Layers}>
            <Row label="Default Connections" hint="Parallel threads per download (1–16)">
              <div className="slider-row">
                <input
                  type="range" min={1} max={16} step={1}
                  value={form.connections || 8}
                  onChange={e => set('connections', Number(e.target.value))}
                  className="range-input"
                />
                <span className="slider-val">{form.connections || 8}</span>
              </div>
            </Row>
            <Row label="Max Simultaneous Downloads" hint="How many downloads run at once (1–10)">
              <div className="slider-row">
                <input
                  type="range" min={1} max={10} step={1}
                  value={form.max_simultaneous || 5}
                  onChange={e => set('max_simultaneous', Number(e.target.value))}
                  className="range-input"
                />
                <span className="slider-val">{form.max_simultaneous || 5}</span>
              </div>
            </Row>
            <Row label="Auto-Start Downloads" hint="Begin downloading immediately after adding">
              <Toggle
                value={form.auto_start ?? true}
                onChange={v => set('auto_start', v)}
              />
            </Row>
          </SECTION>

          {/* Speed */}
          <SECTION title="Speed" icon={Gauge}>
            <Row label="Speed Limit per Download" hint="0 = unlimited">
              <div className="slider-row">
                <input
                  type="range" min={0} max={10240} step={128}
                  value={form.speed_limit_kbps || 0}
                  onChange={e => set('speed_limit_kbps', Number(e.target.value))}
                  className="range-input"
                />
                <span className="slider-val">
                  {form.speed_limit_kbps === 0
                    ? '∞'
                    : form.speed_limit_kbps >= 1024
                      ? `${(form.speed_limit_kbps / 1024).toFixed(1)} MB/s`
                      : `${form.speed_limit_kbps} KB/s`}
                </span>
              </div>
            </Row>
          </SECTION>

          {/* Retry */}
          <SECTION title="Retry" icon={RefreshCw}>
            <Row label="Auto-Retry on Failure" hint="Automatically retry failed downloads">
              <Toggle
                value={form.auto_retry ?? true}
                onChange={v => set('auto_retry', v)}
              />
            </Row>
            <Row label="Max Retry Attempts" hint="How many times to retry (1–10)">
              <div className="slider-row">
                <input
                  type="range" min={1} max={10} step={1}
                  value={form.max_retries || 3}
                  onChange={e => set('max_retries', Number(e.target.value))}
                  className="range-input"
                  disabled={!form.auto_retry}
                />
                <span className="slider-val" style={{ opacity: form.auto_retry ? 1 : 0.4 }}>
                  {form.max_retries || 3}
                </span>
              </div>
            </Row>
          </SECTION>

          {/* Notifications */}
          <SECTION title="Notifications" icon={Bell}>
            <Row label="Notify on Complete" hint="Show a notification when a download finishes">
              <Toggle
                value={form.notify_on_complete ?? true}
                onChange={v => set('notify_on_complete', v)}
              />
            </Row>
            <Row label="Auto-Remove Completed" hint="Remove completed downloads after N hours (0 = never)">
              <div className="slider-row">
                <input
                  type="range" min={0} max={72} step={1}
                  value={form.auto_remove_hours || 0}
                  onChange={e => set('auto_remove_hours', Number(e.target.value))}
                  className="range-input"
                />
                <span className="slider-val">
                  {form.auto_remove_hours === 0 ? 'Never' : `${form.auto_remove_hours}h`}
                </span>
              </div>
            </Row>
          </SECTION>

          {/* Theme */}
          <SECTION title="Appearance" icon={form.theme === 'dark' ? Moon : Sun}>
            <Row label="Theme" hint="Switch between dark and light mode">
              <div className="theme-toggle-row">
                <button
                  className={`theme-btn ${form.theme === 'dark' ? 'active' : ''}`}
                  onClick={() => set('theme', 'dark')}
                >
                  <Moon size={13} /> Dark
                </button>
                <button
                  className={`theme-btn ${form.theme === 'light' ? 'active' : ''}`}
                  onClick={() => set('theme', 'light')}
                >
                  <Sun size={13} /> Light
                </button>
              </div>
            </Row>
          </SECTION>

        </div>

        {/* Footer */}
        <div className="modal-footer">
          <button className="btn-ghost" onClick={handleReset}>
            <RotateCcw size={13} /> Reset
          </button>
          <button className="btn-ghost" onClick={onClose}>
            Cancel
          </button>
          <button
            className="btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? <span className="spinner" /> : <Save size={13} />}
            {saved ? 'Saved!' : 'Save Settings'}
          </button>
        </div>

      </div>
    </div>
  );
}