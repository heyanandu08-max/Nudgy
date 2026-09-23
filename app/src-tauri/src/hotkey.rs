//! Push-to-talk: hold the hotkey to talk, release to send. Tap it twice to type instead.
//!
//! Screen capture starts on key-down (in parallel with speaking, which hides its latency)
//! and only ever happens while the key is held — see PLAN.md Phase 8.

use std::str::FromStr;
use std::sync::Mutex;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, Runtime, WebviewUrl, WebviewWindowBuilder,
};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutEvent, ShortcutState};

use crate::ask::{self, Captured};
use crate::audio::Recording;
use crate::settings::SettingsStore;

/// Presses shorter than this are taps, not push-to-talk.
const TAP: Duration = Duration::from_millis(250);
/// Two taps within this window open the text box.
const DOUBLE_TAP: Duration = Duration::from_millis(400);
pub const ASK_WINDOW: &str = "ask";

#[derive(Default)]
pub struct HotkeyState {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    pressed_at: Option<Instant>,
    last_tap: Option<Instant>,
    recording: Option<Recording>,
    capture: Option<JoinHandle<Captured>>,
    /// Context captured on the double-tap, used when the typed question is submitted.
    pending_text: Option<Captured>,
}

/// What a key event should do — pure so it can be unit tested.
#[derive(Debug, PartialEq, Eq)]
pub enum Action {
    Ignore,
    StartTalking,
    OpenTextBox,
    Send,
    Cancel,
}

pub fn decide(
    state: ShortcutState,
    now: Instant,
    pressed_at: Option<Instant>,
    last_tap: Option<Instant>,
) -> Action {
    match state {
        ShortcutState::Pressed if pressed_at.is_some() => Action::Ignore, // OS key repeat
        ShortcutState::Pressed => match last_tap {
            Some(t) if now.duration_since(t) <= DOUBLE_TAP => Action::OpenTextBox,
            _ => Action::StartTalking,
        },
        ShortcutState::Released => match pressed_at {
            None => Action::Ignore,
            Some(p) if now.duration_since(p) < TAP => Action::Cancel,
            Some(_) => Action::Send,
        },
    }
}

pub fn validate(accelerator: &str) -> Result<Shortcut, String> {
    Shortcut::from_str(accelerator).map_err(|e| format!("invalid hotkey {accelerator:?}: {e}"))
}

/// (Re)registers the push-to-talk shortcut from settings.
pub fn register<R: Runtime>(app: &AppHandle<R>, accelerator: &str) -> Result<(), String> {
    let shortcut = validate(accelerator)?;
    let gs = app.global_shortcut();
    gs.unregister_all().map_err(|e| e.to_string())?;
    gs.on_shortcut(shortcut, |app, _shortcut, event| on_event(app, event))
        .map_err(|e| e.to_string())
}

fn on_event<R: Runtime>(app: &AppHandle<R>, event: ShortcutEvent) {
    let settings = app.state::<SettingsStore>().get();
    let hk = app.state::<HotkeyState>();
    let mut s = hk.inner.lock().unwrap();
    let now = Instant::now();
    let action = decide(event.state, now, s.pressed_at, s.last_tap);
    if settings.paused && matches!(action, Action::StartTalking | Action::OpenTextBox) {
        return;
    }
    let label = companion_label(app);
    match action {
        Action::Ignore => {}
        Action::StartTalking => {
            s.pressed_at = Some(now);
            s.last_tap = None;
            ask::set_companion(app, &label, "listening");
            let _ = app.emit("capture-indicator", true);
            match Recording::start() {
                Ok(r) => s.recording = Some(r),
                Err(e) => {
                    log::warn!("microphone unavailable: {e}");
                    let _ = app.emit_to(
                        label.as_str(),
                        "ask-error",
                        serde_json::json!({"code": "no_microphone"}),
                    );
                }
            }
            let handle = app.clone();
            s.capture = Some(thread::spawn(move || ask::capture_context(&handle)));
        }
        Action::OpenTextBox => {
            s.pressed_at = None;
            s.last_tap = None;
            drop(s);
            let captured = ask::capture_context(app);
            let _ = app.emit("capture-indicator", false);
            let mut s = hk.inner.lock().unwrap();
            s.pending_text = Some(captured);
            drop(s);
            open_text_box(app);
        }
        Action::Cancel => {
            s.pressed_at = None;
            s.last_tap = Some(now);
            if let Some(r) = s.recording.take() {
                r.cancel();
            }
            let capture = s.capture.take();
            drop(s);
            // Join off-thread so a slow UI tree walk can't stall the hotkey handler.
            thread::spawn(move || drop(capture.map(JoinHandle::join)));
            ask::set_companion(app, &label, "idle");
            let _ = app.emit("capture-indicator", false);
        }
        Action::Send => {
            s.pressed_at = None;
            let recording = s.recording.take();
            let capture = s.capture.take();
            drop(s);
            let app = app.clone();
            thread::spawn(move || {
                let audio = recording.map(Recording::stop);
                let captured = capture.and_then(|h| h.join().ok());
                let _ = app.emit("capture-indicator", false);
                let label = companion_label(&app);
                let audio = match audio {
                    Some(Ok(Some(wav))) => wav,
                    Some(Ok(None)) => {
                        let _ = app.emit_to(
                            label.as_str(),
                            "ask-error",
                            serde_json::json!({"code": "no_speech"}),
                        );
                        return ask::set_companion(&app, &label, "idle");
                    }
                    Some(Err(e)) => {
                        log::warn!("recording failed: {e}");
                        let _ = app.emit_to(
                            label.as_str(),
                            "ask-error",
                            serde_json::json!({"code": "no_microphone"}),
                        );
                        return ask::set_companion(&app, &label, "idle");
                    }
                    None => return ask::set_companion(&app, &label, "idle"),
                };
                let Some(captured) = captured else {
                    return ask::set_companion(&app, &label, "idle");
                };
                tauri::async_runtime::spawn(ask::run(app.clone(), captured, Some(audio), None));
            });
        }
    }
}

/// Overlay label for the monitor currently under the cursor.
pub fn companion_label<R: Runtime>(app: &AppHandle<R>) -> String {
    let state = app.state::<crate::overlay::OverlayState>();
    let monitors = state.monitors();
    app.cursor_position()
        .ok()
        .and_then(|p| {
            crate::geometry::monitor_at(crate::geometry::Point::new(p.x, p.y), &monitors).cloned()
        })
        .and_then(|m| state.label_for_monitor(&m.id))
        .unwrap_or_else(|| crate::overlay::label_for(0))
}

fn open_text_box<R: Runtime>(app: &AppHandle<R>) {
    let window = match app.get_webview_window(ASK_WINDOW) {
        Some(w) => w,
        None => match WebviewWindowBuilder::new(
            app,
            ASK_WINDOW,
            WebviewUrl::App("index.html#ask".into()),
        )
        .title("Ask Nudgy")
        .inner_size(520.0, 64.0)
        .decorations(false)
        .resizable(false)
        .always_on_top(true)
        .skip_taskbar(true)
        .visible(false)
        .build()
        {
            Ok(w) => w,
            Err(e) => return log::error!("could not open text box: {e}"),
        },
    };
    // Place it just below the cursor, clamped to the cursor's monitor.
    if let (Ok(cursor), Ok(Some(m))) = (app.cursor_position(), window.current_monitor()) {
        let size = window
            .outer_size()
            .unwrap_or(tauri::PhysicalSize::new(520, 64));
        let (mx, my) = (m.position().x as f64, m.position().y as f64);
        let (mw, mh) = (m.size().width as f64, m.size().height as f64);
        let x = (cursor.x - size.width as f64 / 2.0).clamp(mx, mx + mw - size.width as f64);
        let y = (cursor.y + 32.0).clamp(my, my + mh - size.height as f64);
        let _ = window.set_position(PhysicalPosition::new(x as i32, y as i32));
    }
    let _ = window.show();
    let _ = window.set_focus();
    let _ = window.emit("ask-box-open", ());
}

/// Submits a typed question using the context captured on the double-tap.
pub fn submit_text<R: Runtime>(app: &AppHandle<R>, text: String) -> Result<(), String> {
    if let Some(w) = app.get_webview_window(ASK_WINDOW) {
        let _ = w.hide();
    }
    let text = text.trim().to_string();
    let captured = app
        .state::<HotkeyState>()
        .inner
        .lock()
        .unwrap()
        .pending_text
        .take();
    let captured = captured.ok_or("nothing to ask about — press the hotkey twice again")?;
    if text.is_empty() {
        return Ok(());
    }
    tauri::async_runtime::spawn(ask::run(app.clone(), captured, None, Some(text)));
    Ok(())
}

pub fn cancel_text<R: Runtime>(app: &AppHandle<R>) {
    app.state::<HotkeyState>()
        .inner
        .lock()
        .unwrap()
        .pending_text = None;
    if let Some(w) = app.get_webview_window(ASK_WINDOW) {
        let _ = w.hide();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hold_then_release_sends() {
        let t0 = Instant::now();
        assert_eq!(
            decide(ShortcutState::Pressed, t0, None, None),
            Action::StartTalking
        );
        assert_eq!(
            decide(
                ShortcutState::Released,
                t0 + Duration::from_millis(900),
                Some(t0),
                None
            ),
            Action::Send
        );
    }

    #[test]
    fn short_tap_cancels_and_second_tap_opens_text_box() {
        let t0 = Instant::now();
        assert_eq!(
            decide(
                ShortcutState::Released,
                t0 + Duration::from_millis(100),
                Some(t0),
                None
            ),
            Action::Cancel
        );
        let tap_end = t0 + Duration::from_millis(100);
        assert_eq!(
            decide(
                ShortcutState::Pressed,
                tap_end + Duration::from_millis(200),
                None,
                Some(tap_end)
            ),
            Action::OpenTextBox
        );
        assert_eq!(
            decide(
                ShortcutState::Pressed,
                tap_end + Duration::from_millis(900),
                None,
                Some(tap_end)
            ),
            Action::StartTalking
        );
    }

    #[test]
    fn key_repeat_and_stray_release_are_ignored() {
        let t0 = Instant::now();
        assert_eq!(
            decide(ShortcutState::Pressed, t0, Some(t0), None),
            Action::Ignore
        );
        assert_eq!(
            decide(ShortcutState::Released, t0, None, None),
            Action::Ignore
        );
    }

    #[test]
    fn default_hotkey_parses() {
        assert!(validate("Ctrl+Alt+Space").is_ok());
        assert!(validate("CommandOrControl+Shift+K").is_ok());
        assert!(validate("Ctrl+Nope").is_err());
    }
}
