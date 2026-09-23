mod settings;
mod tray;

use tauri::{AppHandle, Emitter, Manager, State, WindowEvent};

use settings::{Settings, SettingsStore};

#[tauri::command]
fn get_settings(store: State<'_, SettingsStore>) -> Settings {
    store.get()
}

#[tauri::command]
fn save_settings(
    app: AppHandle,
    store: State<'_, SettingsStore>,
    settings: Settings,
) -> Result<Settings, String> {
    let saved = store.set(settings)?;
    tray::sync_pause(&app, saved.paused);
    let _ = app.emit("settings-changed", &saved);
    Ok(saved)
}

pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        .setup(|app| {
            let dir = app.path().app_config_dir()?;
            app.manage(SettingsStore::load(&dir));

            // Menu-bar-only app on macOS (no Dock icon); the settings window still opens.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            tray::create(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Closing the settings window hides it; Nudgy keeps running in the tray.
            if let WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![get_settings, save_settings])
        .run(tauri::generate_context!())
        .expect("error while running Nudgy");
}
