// #[cfg_attr(mobile, tauri::mobile_entry_point)]
// pub fn run() {
//     tauri::Builder::default()
//         .plugin(tauri_plugin_dialog::init())
//         .plugin(tauri_plugin_opener::init())
//         .plugin(tauri_plugin_notification::init())
//         .run(tauri::generate_context!())
//         .expect("error while running tauri application");
// }
use std::process::Command;
use std::sync::{Arc, Mutex};
use tauri::Manager;

// ── Platform-specific binary name ────────────────────────────────────────────
#[cfg(target_os = "windows")]
const BACKEND_BIN: &str = "midm-backend.exe";

#[cfg(not(target_os = "windows"))]
const BACKEND_BIN: &str = "midm-backend";

// ── Kill any running backend instance ────────────────────────────────────────
fn kill_backend(pid: Option<u32>) {
    // Kill by PID first (most precise)
    if let Some(p) = pid {
        #[cfg(target_os = "windows")]
        {
            Command::new("taskkill")
                .args(["/F", "/PID", &p.to_string()])
                .output()
                .ok();
        }

        #[cfg(not(target_os = "windows"))]
        {
            Command::new("kill")
                .args(["-9", &p.to_string()])
                .output()
                .ok();
        }
    }

    // Kill by name as fallback (catches stale instances from previous runs)
    #[cfg(target_os = "windows")]
    {
        Command::new("taskkill")
            .args(["/F", "/IM", "midm-backend.exe"])
            .output()
            .ok();
    }

    #[cfg(any(target_os = "macos", target_os = "linux"))]
    {
        Command::new("pkill")
            .args(["-f", "midm-backend"])
            .output()
            .ok();
    }
}

// ── Ensure the binary is executable (macOS / Linux only) ─────────────────────
#[cfg(not(target_os = "windows"))]
fn ensure_executable(path: &std::path::Path) {
    use std::os::unix::fs::PermissionsExt;
    if let Ok(meta) = std::fs::metadata(path) {
        let mut perms = meta.permissions();
        // Add +x for owner, group, others
        perms.set_mode(perms.mode() | 0o111);
        std::fs::set_permissions(path, perms).ok();
    }
}

#[cfg(target_os = "windows")]
fn ensure_executable(_path: &std::path::Path) {
    // No-op on Windows — .exe files are always executable
}

// ── Resolve backend path from Tauri resource dir ─────────────────────────────
fn find_backend(app: &tauri::App) -> Option<std::path::PathBuf> {
    let resource_dir = app
        .path()
        .resource_dir()
        .expect("failed to get resource dir");

    let candidate = resource_dir.join(BACKEND_BIN);

    eprintln!("[MiDM] Resource dir: {:?}", resource_dir);
    eprintln!("[MiDM] Looking for backend at: {:?}", candidate);

    if candidate.exists() {
        eprintln!("[MiDM] Backend found ✓");
        Some(candidate)
    } else {
        // Log what IS in the resource dir to help debug
        eprintln!("[MiDM] ERROR: Backend not found. Resource dir contents:");
        if let Ok(entries) = std::fs::read_dir(&resource_dir) {
            for entry in entries.flatten() {
                eprintln!("[MiDM]   {:?}", entry.path());
            }
        }
        None
    }
}

// ── Entry point ───────────────────────────────────────────────────────────────
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend_pid: Arc<Mutex<Option<u32>>> = Arc::new(Mutex::new(None));
    let backend_pid_setup = backend_pid.clone();
    let backend_pid_close = backend_pid.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(move |app| {
            let Some(backend_path) = find_backend(app) else {
                eprintln!("[MiDM] Backend binary missing — UI will run without backend");
                return Ok(());
            };

            // Ensure +x on macOS / Linux
            ensure_executable(&backend_path);

            // Kill any stale backend from a previous crash / run
            kill_backend(None);
            std::thread::sleep(std::time::Duration::from_millis(300));

            // Spawn the backend
            match Command::new(&backend_path).spawn() {
                Ok(child) => {
                    let pid = child.id();
                    *backend_pid_setup.lock().unwrap() = Some(pid);
                    eprintln!("[MiDM] Backend started — PID {}", pid);
                }
                Err(e) => {
                    eprintln!("[MiDM] ERROR: Failed to spawn backend: {}", e);
                }
            }

            Ok(())
        })
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                eprintln!("[MiDM] Window closing — shutting down backend...");
                let pid = *backend_pid_close.lock().unwrap();
                kill_backend(pid);
                // Small delay so the backend can flush state before we exit
                std::thread::sleep(std::time::Duration::from_millis(300));
                std::process::exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}