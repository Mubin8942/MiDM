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
use tauri::Manager;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            let resource_path = app
                .path()
                .resource_dir()
                .expect("failed to get resource dir")
                .join("midm-backend.exe");

            if resource_path.exists() {
                Command::new("taskkill")
                    .args(["/F", "/IM", "midm-backend.exe"])
                    .output()
                    .ok();
                std::thread::sleep(std::time::Duration::from_millis(500));
                Command::new(&resource_path)
                    .spawn()
                    .expect("failed to start midm-backend");
            } else {
                eprintln!("Backend not found at: {:?}", resource_path);
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}