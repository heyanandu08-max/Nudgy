//! Shortcut coach (opt-in, off by default). When you click the same toolbar or menu command a
//! few times (Copy, Bold, Save…), the companion mentions its keyboard shortcut, once.
//!
//! Privacy: only the *name* of the clicked element is read, on this computer, and only while
//! the coach is on. Nothing is captured or sent anywhere. Blocklisted apps and password fields
//! are skipped, and nothing runs while Nudgy is paused, in a lesson or recording.

use std::collections::HashMap;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use device_query::{DeviceQuery, DeviceState};
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::geometry::Point;
use crate::overlay::OverlayState;
use crate::settings::SettingsStore;

const POLL: Duration = Duration::from_millis(50);
const IDLE_POLL: Duration = Duration::from_secs(1);
/// Clicks on the same command before a tip.
pub const REPEATS: u32 = 3;
/// At most one tip in this long.
const TIP_GAP: Duration = Duration::from_secs(10 * 60);

pub struct Shortcut {
    pub id: &'static str,
    /// Lower-case element names that mean this command (menu text, toolbar tooltips).
    names: &'static [&'static str],
    win: &'static str,
    mac: &'static str,
}

#[rustfmt::skip]
const SHORTCUTS: &[Shortcut] = &[
    Shortcut { id: "copy", names: &["copy"], win: "Ctrl+C", mac: "Super+C" },
    Shortcut { id: "paste", names: &["paste"], win: "Ctrl+V", mac: "Super+V" },
    Shortcut { id: "cut", names: &["cut"], win: "Ctrl+X", mac: "Super+X" },
    Shortcut { id: "undo", names: &["undo"], win: "Ctrl+Z", mac: "Super+Z" },
    Shortcut { id: "redo", names: &["redo"], win: "Ctrl+Y", mac: "Super+Shift+Z" },
    Shortcut { id: "save", names: &["save"], win: "Ctrl+S", mac: "Super+S" },
    Shortcut { id: "print", names: &["print"], win: "Ctrl+P", mac: "Super+P" },
    Shortcut { id: "find", names: &["find", "find and replace"], win: "Ctrl+F", mac: "Super+F" },
    Shortcut { id: "selectAll", names: &["select all"], win: "Ctrl+A", mac: "Super+A" },
    Shortcut { id: "bold", names: &["bold"], win: "Ctrl+B", mac: "Super+B" },
    Shortcut { id: "italic", names: &["italic"], win: "Ctrl+I", mac: "Super+I" },
    Shortcut { id: "underline", names: &["underline"], win: "Ctrl+U", mac: "Super+U" },
    Shortcut { id: "newTab", names: &["new tab"], win: "Ctrl+T", mac: "Super+T" },
    Shortcut { id: "closeTab", names: &["close tab"], win: "Ctrl+W", mac: "Super+W" },
    Shortcut { id: "reload", names: &["reload", "refresh", "reload this page"], win: "Ctrl+R", mac: "Super+R" },
    Shortcut { id: "newWindow", names: &["new window"], win: "Ctrl+N", mac: "Super+N" },
    Shortcut { id: "zoomIn", names: &["zoom in"], win: "Ctrl+=", mac: "Super+=" },
    Shortcut { id: "zoomOut", names: &["zoom out"], win: "Ctrl+-", mac: "Super+-" },
    Shortcut { id: "insertLink", names: &["insert link"], win: "Ctrl+K", mac: "Super+K" },
];

/// Toolbar names often carry the shortcut or extra words: "Copy (Ctrl+C)", "Bold\tCtrl+B",
/// "Save…". Keep the command part only.
fn normalize(name: &str) -> String {
    let cut = name
        .split(['(', '\t'])
        .next()
        .unwrap_or_default()
        .trim()
        .trim_end_matches(['…', '.'])
        .trim();
    cut.to_lowercase()
}

/// The command a clicked element stands for, if it has a shortcut worth teaching.
pub fn shortcut_for(role: &str, name: &str) -> Option<&'static Shortcut> {
    // Text you click into is not a command, even if it's called "Search".
    if matches!(
        role,
        "text" | "textfield" | "edit" | "document" | "statictext"
    ) {
        return None;
    }
    let n = normalize(name);
    if n.is_empty() {
        return None;
    }
    SHORTCUTS.iter().find(|s| s.names.contains(&n.as_str()))
}

impl Shortcut {
    pub fn accelerator(&self) -> &'static str {
        if cfg!(target_os = "macos") {
            self.mac
        } else {
            self.win
        }
    }
}

/// Counts clicks per command and decides when a tip is due. Pure, so it's testable.
#[derive(Default)]
pub struct Counter {
    counts: HashMap<&'static str, u32>,
    last_tip: Option<Instant>,
}

impl Counter {
    /// Records a click; returns true when it's time to show this command's tip.
    pub fn click(&mut self, id: &'static str, seen: &[String], now: Instant) -> bool {
        if seen.iter().any(|s| s == id) {
            return false;
        }
        let n = self.counts.entry(id).or_default();
        *n += 1;
        if *n < REPEATS
            || self
                .last_tip
                .is_some_and(|t| now.duration_since(t) < TIP_GAP)
        {
            return false;
        }
        self.last_tip = Some(now);
        self.counts.remove(id);
        true
    }
}

#[derive(Default)]
pub struct CoachState {
    counter: Mutex<Counter>,
}

pub fn init<R: Runtime>(app: &AppHandle<R>) {
    app.manage(CoachState::default());
    let app = app.clone();
    let _ = thread::Builder::new()
        .name("nudgy-coach".into())
        .spawn(move || run(app));
}

fn active<R: Runtime>(app: &AppHandle<R>) -> bool {
    let s = app.state::<SettingsStore>().get();
    s.shortcut_coach
        && !s.paused
        && app.state::<crate::ask::AskState>().lesson().is_none()
        && !app.state::<crate::recorder::Recorder>().is_recording()
}

fn run<R: Runtime>(app: AppHandle<R>) {
    let mut device: Option<DeviceState> = None;
    let mut prev_left = false;
    loop {
        if !active(&app) {
            prev_left = false;
            thread::sleep(IDLE_POLL);
            continue;
        }
        // Created lazily: on macOS this needs the Accessibility permission.
        if device.is_none() {
            device = DeviceState::checked_new();
            if device.is_none() {
                log::warn!("shortcut coach: input monitoring unavailable (permission?)");
                thread::sleep(Duration::from_secs(30));
                continue;
            }
        }
        // Index 1 is the primary button in device_query.
        let left = device
            .as_ref()
            .unwrap()
            .get_mouse()
            .button_pressed
            .get(1)
            .copied()
            .unwrap_or(false);
        if left && !prev_left {
            on_click(&app);
        }
        prev_left = left;
        thread::sleep(POLL);
    }
}

fn on_click<R: Runtime>(app: &AppHandle<R>) {
    let Ok(p) = app.cursor_position() else { return };
    let p = Point::new(p.x, p.y);
    let overlay = app.state::<OverlayState>();
    if overlay.is_interactive_at(p) {
        return;
    }
    let settings = app.state::<SettingsStore>().get();
    let (name, title) = crate::capture::foreground_window().unwrap_or_default();
    if crate::privacy::is_blocked(&settings.blocklist, &name, &title)
        || crate::uitree::secure_field_focused()
    {
        return;
    }
    let Some(el) = crate::uitree::element_at(p.x, p.y, &overlay.monitors()) else {
        return;
    };
    let Some(sc) = shortcut_for(&el.role, &el.name) else {
        return;
    };
    let due = app.state::<CoachState>().counter.lock().unwrap().click(
        sc.id,
        &settings.shortcut_tips_seen,
        Instant::now(),
    );
    if !due {
        return;
    }
    // Each tip is shown once, ever.
    let saved = app.state::<SettingsStore>().update(|s| {
        s.shortcut_tips_seen.push(sc.id.to_string());
    });
    if let Ok(s) = saved {
        let _ = app.emit("settings-changed", &s);
    }
    let label = crate::hotkey::companion_label(app);
    let _ = app.emit_to(
        label.as_str(),
        "shortcut-tip",
        json!({"id": sc.id, "keys": sc.accelerator(), "app": name}),
    );
}

/// "Stop tips" on the tip card: turns the coach off.
#[tauri::command]
pub fn coach_off(app: AppHandle) -> Result<(), String> {
    let s = app
        .state::<SettingsStore>()
        .update(|s| s.shortcut_coach = false)?;
    let _ = app.emit("settings-changed", &s);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_command_names() {
        assert_eq!(shortcut_for("button", "Bold").map(|s| s.id), Some("bold"));
        assert_eq!(
            shortcut_for("menuitem", "Copy\tCtrl+C").map(|s| s.id),
            Some("copy")
        );
        assert_eq!(
            shortcut_for("button", "Save (Ctrl+S)").map(|s| s.id),
            Some("save")
        );
        assert_eq!(
            shortcut_for("menuitem", "Print…").map(|s| s.id),
            Some("print")
        );
        assert!(shortcut_for("button", "Bold text").is_none());
        assert!(shortcut_for("textfield", "Find").is_none());
        assert!(shortcut_for("button", "").is_none());
    }

    #[test]
    fn tip_after_repeats_once_and_spaced_out() {
        let t0 = Instant::now();
        let mut c = Counter::default();
        assert!(!c.click("bold", &[], t0));
        assert!(!c.click("bold", &[], t0));
        assert!(c.click("bold", &[], t0), "third click");
        // Another command reaching 3 soon after waits for the gap.
        for _ in 0..3 {
            assert!(!c.click("copy", &[], t0 + Duration::from_secs(60)));
        }
        assert!(c.click("copy", &[], t0 + TIP_GAP));
        // Already seen: never again.
        let seen = vec!["save".to_string()];
        for _ in 0..5 {
            assert!(!c.click("save", &seen, t0 + 3 * TIP_GAP));
        }
    }
}
