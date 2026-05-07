import { useEffect, useState } from "react";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { platform } from "@tauri-apps/plugin-os";

const appWindow = getCurrentWindow();

// ── macOS traffic lights ──────────────────────────────────────────────────────
function MacControls() {
  const [isMaximized, setIsMaximized] = useState(false);
  const [hovered, setHovered] = useState(false);

  useEffect(() => {
    appWindow.isMaximized().then(setIsMaximized);
    const unlisten = appWindow.onResized(() => {
      appWindow.isMaximized().then(setIsMaximized);
    });
    return () => { unlisten.then(f => f()); };
  }, []);

  return (
    <div
      className="mac-controls"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* Close — red */}
      <button
        className="mac-btn mac-close"
        onClick={() => appWindow.close()}
        title="Close"
      >
        {hovered && <span>✕</span>}
      </button>

      {/* Minimize — yellow */}
      <button
        className="mac-btn mac-minimize"
        onClick={() => appWindow.minimize()}
        title="Minimize"
      >
        {hovered && <span>−</span>}
      </button>

      {/* Maximize — green */}
      <button
        className="mac-btn mac-maximize"
        onClick={() => appWindow.toggleMaximize()}
        title={isMaximized ? "Restore" : "Maximize"}
      >
        {hovered && <span>{isMaximized ? "⤓" : "+"}</span>}
      </button>
    </div>
  );
}

// ── Windows / Linux controls ──────────────────────────────────────────────────
function WinControls() {
  const [isMaximized, setIsMaximized] = useState(false);

  useEffect(() => {
    appWindow.isMaximized().then(setIsMaximized);
    const unlisten = appWindow.onResized(() => {
      appWindow.isMaximized().then(setIsMaximized);
    });
    return () => { unlisten.then(f => f()); };
  }, []);

  return (
    <div className="win-controls">
      <button
        className="win-btn win-minimize"
        onClick={() => appWindow.minimize()}
        title="Minimize"
      >
        <svg width="10" height="1" viewBox="0 0 10 1">
          <rect width="10" height="1" fill="currentColor" />
        </svg>
      </button>

      <button
        className="win-btn win-maximize"
        onClick={() => appWindow.toggleMaximize()}
        title={isMaximized ? "Restore" : "Maximize"}
      >
        {isMaximized ? (
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path
              d="M2 0v2H0v8h8V8h2V0H2zm6 9H1V3h7v6zM9 7H8V2H3V1h6v6z"
              fill="currentColor"
            />
          </svg>
        ) : (
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path
              d="M0 0v10h10V0H0zm9 9H1V1h8v8z"
              fill="currentColor"
            />
          </svg>
        )}
      </button>

      <button
        className="win-btn win-close"
        onClick={() => appWindow.close()}
        title="Close"
      >
        <svg width="10" height="10" viewBox="0 0 10 10">
          <path
            d="M1 0L0 1l4 4-4 4 1 1 4-4 4 4 1-1-4-4 4-4-1-1-4 4z"
            fill="currentColor"
          />
        </svg>
      </button>
    </div>
  );
}

// ── Title Bar ─────────────────────────────────────────────────────────────────
export default function TitleBar() {
  const [os, setOs] = useState(null);

  useEffect(() => {
    platform().then(setOs);
  }, []);

  const isMac = os === "macos";

  return (
    <div
      className={`titlebar ${isMac ? "titlebar-mac" : "titlebar-win"}`}
      data-tauri-drag-region
    >
      {/* macOS: controls on LEFT, title centered */}
      {isMac && <MacControls />}

      <span className="titlebar-title" data-tauri-drag-region>
        MiDM
      </span>

      {/* Windows / Linux: controls on RIGHT */}
      {!isMac && os !== null && <WinControls />}
    </div>
  );
}