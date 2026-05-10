import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { Plus } from "lucide-react";
import logo from '../../src-tauri/icons/logo.png';

const appWindow = getCurrentWindow();

function detectOS() {
  const ua = navigator.userAgent;
  if (ua.includes("Mac OS X") || ua.includes("Macintosh")) return "macos";
  if (ua.includes("Windows"))                                return "windows";
  return "linux";
}

const OS = detectOS();

// ── macOS traffic lights ──────────────────────────────────────────────────────
function MacControls() {
  const [hovered, setHovered] = useState(false);

  return (
    <div
      className="mac-controls"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button className="mac-btn mac-close"    onClick={() => appWindow.close()}          title="Close">
        {hovered && <span>✕</span>}
      </button>
      <button className="mac-btn mac-minimize" onClick={() => appWindow.minimize()}       title="Minimize">
        {hovered && <span>−</span>}
      </button>
      <button className="mac-btn mac-maximize" onClick={() => appWindow.toggleMaximize()} title="Maximize">
        {hovered && <span>+</span>}
      </button>
    </div>
  );
}

// ── Windows / Linux controls ──────────────────────────────────────────────────
function WinControls() {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    appWindow.isMaximized().then(setIsMaximized);
    let unlisten;
    appWindow.onResized(() => {
      appWindow.isMaximized().then(setIsMaximized);
    }).then(fn => { unlisten = fn; });
    return () => unlisten?.();
  }, []);

  return (
    <div className="win-controls">
      <button className="tb-icon win-min" onClick={() => appWindow.minimize()} title="Minimize">
        <svg width="10" height="1" viewBox="0 0 10 1">
          <rect width="10" height="1" fill="currentColor" />
        </svg>
      </button>
      <button className="tb-icon win-max" onClick={() => appWindow.toggleMaximize()} title={isMaximized ? "Restore" : "Maximize"}>
        {isMaximized ? (
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M2 0v2H0v8h8V8h2V0H2zm6 9H1V3h7v6zM9 7H8V2H3V1h6v6z" fill="currentColor" />
          </svg>
        ) : (
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M0 0v10h10V0H0zm9 9H1V1h8v8z" fill="currentColor" />
          </svg>
        )}
      </button>
      <button className="tb-icon tb-close win-close" onClick={() => appWindow.close()} title="Close">
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path d="M1 0L0 1l4 4-4 4 1 1 4-4 4 4 1-1-4-4 4-4-1-1-4 4z" fill="currentColor" />
        </svg>
      </button>
    </div>
  );
}

// ── Main TitleBar ─────────────────────────────────────────────────────────────
export default function TitleBar({ onAdd, connected }) {
  const isMac = OS === "macos";

  return (
    <div
      className="titlebar"
      data-tauri-drag-region
      style={{ paddingLeft: isMac ? "80px" : "12px" }}
    >
      {/* macOS traffic lights sit inside the drag region on the left */}
      {isMac && <MacControls />}

      {/* Left — logo + name + connection pill */}
      <div className="titlebar-left">
        <div className="app-logo">
          <img src={logo} alt="MiDM" />
        </div>
        <span className="app-name">MiDM</span>
        <div className={`conn-pill ${connected ? "conn-on" : "conn-off"}`}>
          <span className="conn-dot" />
          {connected ? "Ready" : "Offline"}
        </div>
      </div>

      {/* Center — spacer */}
      <div className="titlebar-center" data-tauri-drag-region />

      {/* Right — add button + win controls (Windows/Linux only) */}
      <div className="titlebar-right">
        <button className="tb-btn" onClick={onAdd}>
          <Plus size={13} />
          New Download
        </button>

        {/* Windows / Linux only — macOS uses traffic lights above */}
        {!isMac && <WinControls />}
      </div>
    </div>
  );
}