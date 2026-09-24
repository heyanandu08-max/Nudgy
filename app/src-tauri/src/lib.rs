mod account;
mod activity;
mod apps;
mod ask;
mod audio;
mod auth;
mod backend;
mod capture;
mod geometry;
mod hotkey;
mod lesson;
mod matcher;
mod nudges;
mod overlay;
mod permissions;
mod privacy;
mod recorder;
mod settings;
mod sse;
mod store;
mod tray;
mod uitree;
mod updates;
mod walkthrough;

use tauri::{AppHandle, Emitter, Manager, State, WebviewWindow, WindowEvent};

use geometry::{MonitorInfo, Rect};
use overlay::OverlayState;

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
    hotkey::validate(&settings.hotkey)?;
    let previous = store.get();
    let saved = store.set(settings)?;
    if saved.hotkey != previous.hotkey {
        hotkey::register(&app, &saved.hotkey)?;
    }
    tray::sync_pause(&app, saved.paused);
    let _ = app.emit("settings-changed", &saved);
    Ok(saved)
}

/// Overlay UI reports its clickable regions (CSS px) so the cursor loop can turn
/// click-through off only while the cursor is over them.
#[tauri::command]
fn set_interactive_regions(
    window: WebviewWindow,
    state: State<'_, OverlayState>,
    rects: Vec<Rect>,
) {
    state.set_interactive(window.label(), rects);
}

#[tauri::command]
fn get_monitor_for_overlay(
    window: WebviewWindow,
    state: State<'_, OverlayState>,
) -> Option<MonitorInfo> {
    let idx: usize = window.label().strip_prefix("overlay-")?.parse().ok()?;
    state.monitors().get(idx).cloned()
}

#[tauri::command]
fn debug_point_at_screen_center(app: AppHandle) -> Result<(), String> {
    overlay::point_at_screen_center(&app)
}

#[tauri::command]
fn ask_text(app: AppHandle, text: String) -> Result<(), String> {
    hotkey::submit_text(&app, text)
}

#[tauri::command]
fn cancel_text_ask(app: AppHandle) {
    hotkey::cancel_text(&app)
}

#[tauri::command]
fn last_timings(state: State<'_, ask::AskState>) -> Option<serde_json::Value> {
    state.last_timings.lock().unwrap().clone()
}

#[tauri::command]
fn open_note_box(app: AppHandle) {
    hotkey::open_text_box(&app, "note");
}

/// Webview errors land in the app log (webviews have no console in release builds).
#[tauri::command]
fn ui_log(window: WebviewWindow, level: String, message: String) {
    let msg: String = message.chars().take(2000).collect();
    match level.as_str() {
        "error" => log::error!("[{}] {msg}", window.label()),
        "warn" => log::warn!("[{}] {msg}", window.label()),
        _ => log::info!("[{}] {msg}", window.label()),
    }
}

#[tauri::command]
fn forget_conversation(state: State<'_, ask::AskState>) {
    state.clear_history()
}

pub fn run() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    tauri::Builder::default()
        // Must be first: a second launch (e.g. from a nudgy:// link on Windows/Linux)
        // forwards its URL to the running instance instead of starting another app.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            tray::show_main(app);
        }))
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let dir = app.path().app_config_dir()?;
            app.manage(SettingsStore::load(&dir));
            app.manage(auth::AuthStore::load(&app.path().app_data_dir()?));
            app.manage(ask::AskState::default());
            app.manage(hotkey::HotkeyState::default());
            app.manage(lesson::LessonState::default());
            app.manage(recorder::Recorder::default());
            let db = app.path().app_data_dir()?.join("nudgy.db");
            app.manage(store::Store::open(&db).map_err(|e| format!("open {}: {e}", db.display()))?);
            activity::init(app.handle());
            nudges::init(app.handle());

            // Menu-bar-only app on macOS (no Dock icon); the settings window still opens.
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            tray::create(app.handle())?;
            overlay::init(app.handle())?;
            {
                use tauri_plugin_deep_link::DeepLinkExt;
                #[cfg(any(target_os = "windows", target_os = "linux"))]
                if let Err(e) = app.deep_link().register_all() {
                    log::warn!("could not register nudgy:// links: {e}");
                }
                let handle = app.handle().clone();
                app.deep_link().on_open_url(move |event| {
                    let urls = event.urls().into_iter().map(|u| u.to_string()).collect();
                    account::handle_urls(&handle, urls);
                });
                if let Ok(Some(urls)) = app.deep_link().get_current() {
                    account::handle_urls(
                        app.handle(),
                        urls.into_iter().map(|u| u.to_string()).collect(),
                    );
                }
            }
            account::rotate_on_start(app.handle());
            let accelerator = app.state::<SettingsStore>().get().hotkey;
            if let Err(e) = hotkey::register(app.handle(), &accelerator) {
                log::error!("could not register hotkey {accelerator}: {e}");
            }

            // First run: open the window so onboarding (permissions, first question) shows.
            if std::env::var_os("NUDGY_SHOW_MAIN").is_some()
                || !app.state::<SettingsStore>().get().onboarded
            {
                tray::show_main(app.handle());
            }

            // Manual/CI testing aid: NUDGY_DEBUG_POINT=1 fires "Point at screen center"
            // shortly after launch, without needing the tray.
            if std::env::var_os("NUDGY_DEBUG_POINT").is_some() {
                let h = app.handle().clone();
                std::thread::spawn(move || {
                    std::thread::sleep(std::time::Duration::from_secs(4));
                    if let Err(e) = overlay::point_at_screen_center(&h) {
                        log::error!("debug point failed: {e}");
                    }
                });
            }
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
        .invoke_handler(tauri::generate_handler![
            get_settings,
            permissions::permissions,
            permissions::permission_request,
            updates::update_check,
            updates::update_install,
            privacy::privacy_export,
            privacy::privacy_delete,
            save_settings,
            set_interactive_regions,
            get_monitor_for_overlay,
            debug_point_at_screen_center,
            ask_text,
            cancel_text_ask,
            last_timings,
            forget_conversation,
            ui_log,
            lesson::lesson_plan,
            lesson::lesson_begin_step,
            lesson::lesson_verify,
            lesson::lesson_point,
            lesson::speak,
            lesson::lesson_set_context,
            lesson::activity_watch,
            lesson::lesson_record_start,
            lesson::lesson_record_step,
            lesson::lesson_record_finish,
            lesson::dashboard,
            lesson::review_plan,
            lesson::review_snooze,
            walkthrough::recorder_start,
            walkthrough::recorder_cancel,
            walkthrough::recorder_note,
            walkthrough::recorder_finish,
            walkthrough::walkthrough_list,
            walkthrough::walkthrough_get,
            walkthrough::walkthrough_save,
            walkthrough::walkthrough_delete,
            walkthrough::walkthrough_plan,
            walkthrough::walkthrough_export,
            walkthrough::walkthrough_import_file,
            walkthrough::walkthrough_share,
            walkthrough::walkthrough_fetch,
            open_note_box,
            apps::focus_app,
            hotkey::escape_listen,
            apps::wait_for_app,
            account::auth_state,
            account::auth_send_magic,
            account::auth_open_provider,
            account::auth_sign_out,
            account::account_me,
            account::access_get,
            account::billing_checkout,
            account::billing_portal,
            account::team_get,
            account::team_invite,
            account::team_remove,
            account::team_walkthroughs,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Nudgy");
}
