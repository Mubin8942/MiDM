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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Store backend process handle globally
    let backend_pid: Arc<Mutex<Option<u32>>> = Arc::new(Mutex::new(None));
    let backend_pid_clone = backend_pid.clone();

    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(move |app| {
            let resource_path = app
                .path()
                .resource_dir()
                .expect("failed to get resource dir")
                .join("midm-backend.exe");

            if resource_path.exists() {
                // Kill any stale instance first
                Command::new("taskkill")
                    .args(["/F", "/IM", "midm-backend.exe"])
                    .output()
                    .ok();

                std::thread::sleep(std::time::Duration::from_millis(500));

                // Launch and store PID
                if let Ok(child) = Command::new(&resource_path).spawn() {
                    let pid = child.id();
                    *backend_pid_clone.lock().unwrap() = Some(pid);
                    eprintln!("Backend started with PID: {}", pid);
                }
            } else {
                eprintln!("Backend not found at: {:?}", resource_path);
            }

            Ok(())
        })
        .on_window_event(move |_window, event| {
            // Kill backend when window closes
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                eprintln!("Window closing — killing backend...");

                // Kill by name (most reliable)
                Command::new("taskkill")
                    .args(["/F", "/IM", "midm-backend.exe"])
                    .output()
                    .ok();

                // Also kill by PID as backup
                if let Some(pid) = *backend_pid.lock().unwrap() {
                    Command::new("taskkill")
                        .args(["/F", "/PID", &pid.to_string()])
                        .output()
                        .ok();
                }

                std::process::exit(0);
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}