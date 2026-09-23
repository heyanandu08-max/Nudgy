//! System tray (Windows) / menu bar (macOS) icon: Open, Pause, Settings, Quit.

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem, Submenu};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::settings::SettingsStore;

const OPEN: &str = "open";
const PAUSE: &str = "pause";
const SETTINGS: &str = "settings";
const QUIT: &str = "quit";
const DEBUG_POINT_CENTER: &str = "debug-point-center";

/// Tray labels. The webview UI uses react-i18next; the native tray menu is built
/// before any webview exists, so it keeps its own small table (English only for v1).
struct Labels {
    open: &'static str,
    pause: &'static str,
    settings: &'static str,
    quit: &'static str,
    debug: &'static str,
    debug_point_center: &'static str,
    tooltip: &'static str,
}

fn labels(_language: &str) -> Labels {
    Labels {
        open: "Open Nudgy",
        pause: "Pause",
        settings: "Settings…",
        quit: "Quit Nudgy",
        debug: "Debug",
        debug_point_center: "Point at screen center",
        tooltip: "Nudgy",
    }
}

pub fn create<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let settings = app.state::<SettingsStore>().get();
    let l = labels(&settings.language);

    let open = MenuItem::with_id(app, OPEN, l.open, true, None::<&str>)?;
    let pause = CheckMenuItem::with_id(app, PAUSE, l.pause, true, settings.paused, None::<&str>)?;
    let settings_item = MenuItem::with_id(app, SETTINGS, l.settings, true, None::<&str>)?;
    let quit = MenuItem::with_id(app, QUIT, l.quit, true, None::<&str>)?;
    let sep = PredefinedMenuItem::separator(app)?;
    let point_center = MenuItem::with_id(app, DEBUG_POINT_CENTER, l.debug_point_center, true, None::<&str>)?;
    let debug = Submenu::with_items(app, l.debug, true, &[&point_center])?;
    let sep2 = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&open, &pause, &settings_item, &sep, &debug, &sep2, &quit])?;

    app.manage(PauseItem(pause.clone()));
    TrayIconBuilder::with_id("main")
        .icon(app.default_window_icon().cloned().expect("bundle icon missing"))
        .tooltip(l.tooltip)
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            OPEN | SETTINGS => show_main(app),
            PAUSE => toggle_pause(app),
            DEBUG_POINT_CENTER => {
                if let Err(e) = crate::overlay::point_at_screen_center(app) {
                    log::error!("debug point failed: {e}");
                }
            }
            QUIT => app.exit(0),
            _ => {}
        })
        .build(app)?;
    Ok(())
}

pub fn show_main<R: Runtime>(app: &AppHandle<R>) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
    }
}

fn toggle_pause<R: Runtime>(app: &AppHandle<R>) {
    let store = app.state::<SettingsStore>();
    match store.update(|s| s.paused = !s.paused) {
        Ok(s) => {
            sync_pause(app, s.paused);
            let _ = app.emit("settings-changed", &s);
        }
        Err(e) => log::error!("failed to toggle pause: {e}"),
    }
}

/// Keeps the tray checkbox in sync when settings change from the UI.
pub fn sync_pause<R: Runtime>(app: &AppHandle<R>, paused: bool) {
    if let Some(item) = app.try_state::<PauseItem<R>>() {
        let _ = item.0.set_checked(paused);
    }
}

struct PauseItem<R: Runtime>(CheckMenuItem<R>);
