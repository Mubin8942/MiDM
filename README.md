# MiDM — Modern Internet Download Manager

A fast, modern download manager for Windows built with:
- **Python 3.13** — Async download engine with dynamic segmentation
- **Tauri 2** — Native Windows app shell (Rust)
- **React + Vite** — Modern UI with real-time progress

---

## Architecture

```
MiDM/
├── backend/                  # Python async download engine
│   ├── core/
│   │   ├── downloader.py     # IDM-style dynamic segment engine
│   │   └── manager.py        # Queue, state persistence, scheduling
│   └── server.py             # WebSocket + HTTP bridge to UI
│
├── midm-ui/                  # Tauri + React frontend
│   ├── src/
│   │   ├── components/
│   │   │   ├── TitleBar.jsx
│   │   │   ├── Sidebar.jsx
│   │   │   ├── DownloadList.jsx
│   │   │   └── AddDownloadModal.jsx
│   │   ├── store/
│   │   │   └── downloadStore.js   # Zustand + WebSocket state
│   │   ├── App.jsx
│   │   └── App.css
│   └── src-tauri/            # Tauri Rust shell
│
├── setup.bat                 # One-time setup
├── dev.bat                   # Development mode
├── build.bat                 # Build production .exe
└── requirements.txt
```

---

## Prerequisites

| Tool | Version | Download |
|------|---------|----------|
| Python | 3.11+ | https://python.org |
| Node.js | 18+ | https://nodejs.org |
| Rust | latest | https://rustup.rs |
| VS Build Tools | 2019+ | https://visualstudio.microsoft.com/visual-cpp-build-tools/ |

---

## Getting Started

### 1. One-time Setup
```bat
setup.bat
```

### 2. Development Mode (2 terminals)
```bat
# Terminal 1 — Python backend
python backend/server.py

# Terminal 2 — Tauri UI
cd midm-ui
npm run tauri dev
```

Or use the helper script:
```bat
dev.bat
```

### 3. Build Production .exe
```bat
build.bat
```
Output → `midm-ui/src-tauri/target/release/bundle/nsis/MiDM_1.0.0_x64-setup.exe`

---

## How the Download Engine Works

MiDM implements IDM's core algorithm:

1. **Probe**: HEAD request to get file size and check `Accept-Ranges: bytes`
2. **Segment**: Split file into N equal parts (default: 8)
3. **Parallel fetch**: Each segment downloads on its own async connection
4. **Dynamic stealing**: When a thread finishes, it splits the largest remaining segment in half and takes over the second half — no thread ever idles
5. **Merge**: Segments assembled in order into the final file
6. **Resume**: `.part` files persist across restarts via state saved to `~/.midm/state.json`

---

## WebSocket Protocol

The UI communicates with the Python backend over `ws://localhost:7475/ws`.

**Commands (UI → Backend):**
```json
{ "cmd": "add_download", "data": { "url": "...", "connections": 8 }, "id": "1" }
{ "cmd": "pause",   "data": { "id": "abc123" }, "id": "2" }
{ "cmd": "resume",  "data": { "id": "abc123" }, "id": "3" }
{ "cmd": "cancel",  "data": { "id": "abc123" }, "id": "4" }
{ "cmd": "remove",  "data": { "id": "abc123", "delete_file": false }, "id": "5" }
```

**Events (Backend → UI):**
```json
{ "type": "event", "event": "task_added",    "data": { ...task } }
{ "type": "event", "event": "task_progress", "data": { ...task } }
{ "type": "event", "event": "task_updated",  "data": { ...task } }
{ "type": "event", "event": "task_removed",  "data": { "id": "abc123" } }
```

**HTTP API** (for browser extension): `http://localhost:7475`
```
GET  /status      → health check
GET  /downloads   → all tasks
POST /add         → { "url": "..." }
GET  /stats       → aggregated stats
```

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Ctrl+N` | New download |
| `Escape` | Close modal |

---

## Roadmap

- [x] Phase 1: Dynamic segment engine
- [x] Phase 2: WebSocket bridge
- [x] Phase 3: Tauri + React UI
- [ ] Phase 4: Browser extensions (Chrome, Firefox, Edge)
- [ ] Phase 5: Scheduler (download at night, speed limits)
- [ ] Phase 6: System tray icon
- [ ] Phase 7: Auto-update
