#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
fn main() {
    midm_lib::run();
}
