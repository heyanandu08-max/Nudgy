//! Walkthrough recorder: logs clicks (with the element under the cursor), typing, shortcuts
//! and a thumbnail per click, until stopped. Everything stays local until the author
//! chooses to clean, export or share it. Never records password content; skips blocked apps.

pub mod keys;
pub mod log;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use device_query::{DeviceQuery, DeviceState};
use serde::Serialize;
use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::geometry::{self, Point};
use crate::overlay::OverlayState;
use crate::settings::SettingsStore;
use keys::KeyTracker;
use log::{KeyContext, LogBuilder, RawStep, Target};

/// Human clicks and key presses last ~50–150 ms; 8 ms polling catches them reliably.
const POLL: Duration = Duration::from_millis(8);
/// Refresh the foreground app / secure-field state at most this often while typing.
const CONTEXT_TTL: Duration = Duration::from_millis(700);

#[derive(Default)]
pub struct Recorder {
    session: Mutex<Option<Session>>,
}

struct Session {
    log: Arc<Mutex<LogBuilder>>,
    stop: Arc<AtomicBool>,
    handle: Option<thread::JoinHandle<()>>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Recording {
    pub raw: Vec<RawStep>,
    pub shots: Vec<Option<String>>,
}

impl Recorder {
    pub fn is_recording(&self) -> bool {
        self.session.lock().unwrap().is_some()
    }

    pub fn note(&self, text: &str) {
        if let Some(s) = self.session.lock().unwrap().as_ref() {
            s.log.lock().unwrap().note(text);
        }
    }

    fn take(&self) -> Option<Recording> {
        let mut s = self.session.lock().unwrap().take()?;
        s.stop.store(true, Ordering::SeqCst);
        if let Some(h) = s.handle.take() {
            let _ = h.join();
        }
        // Let in-flight click descriptions (element lookup + thumbnail) land.
        for _ in 0..40 {
            if Arc::strong_count(&s.log) == 1 {
                break;
            }
            thread::sleep(Duration::from_millis(25));
        }
        let log = Arc::try_unwrap(s.log).ok()?.into_inner().ok()?;
        let (raw, shots) = log.finish();
        Some(Recording { raw, shots })
    }
}

fn publish<R: Runtime>(app: &AppHandle<R>, recording: bool, steps: usize) {
    let _ = app.emit(
        "recorder-state",
        json!({"recording": recording, "steps": steps}),
    );
}

/// A visible Nudgy window has focus (e.g. the note box): don't record what happens there.
/// (Hidden windows can keep a stale focus flag on some window managers.)
fn nudgy_focused<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.webview_windows()
        .values()
        .any(|w| w.is_visible().unwrap_or(false) && w.is_focused().unwrap_or(false))
}

pub fn start<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let recorder = app.state::<Recorder>();
    let mut guard = recorder.session.lock().unwrap();
    if guard.is_some() {
        return Ok(());
    }
    let log = Arc::new(Mutex::new(LogBuilder::default()));
    let stop = Arc::new(AtomicBool::new(false));
    let (l, s, a) = (log.clone(), stop.clone(), app.clone());
    let handle = thread::Builder::new()
        .name("nudgy-recorder".into())
        .spawn(move || run(a, l, s))
        .map_err(|e| e.to_string())?;
    *guard = Some(Session {
        log,
        stop,
        handle: Some(handle),
    });
    drop(guard);
    publish(app, true, 0);
    let _ = app.emit("capture-indicator", true);
    Ok(())
}

pub fn stop<R: Runtime>(app: &AppHandle<R>) -> Option<Recording> {
    let rec = app.state::<Recorder>().take();
    publish(app, false, 0);
    let _ = app.emit("capture-indicator", false);
    rec
}

fn run<R: Runtime>(app: AppHandle<R>, log: Arc<Mutex<LogBuilder>>, stop: Arc<AtomicBool>) {
    let Some(device) = DeviceState::checked_new() else {
        ::log::warn!("recorder: input monitoring unavailable (permission?)");
        let _ = app.emit("recorder-error", "input_permission");
        return;
    };
    let mut keys = KeyTracker::default();
    let mut prev_left = false;
    let mut ctx = KeyContext::default();
    let mut ctx_at = Instant::now() - CONTEXT_TTL;
    let mut last_count = 0;

    while !stop.load(Ordering::SeqCst) {
        thread::sleep(POLL);
        let now = Instant::now();
        let focused_on_us = nudgy_focused(&app);
        let mouse = device.get_mouse();
        // Index 1 is the primary button in device_query.
        let left = mouse.button_pressed.get(1).copied().unwrap_or(false);
        let pressed_keys = device.get_keys();
        let key_events = keys.feed(&pressed_keys);

        if left && !prev_left && !focused_on_us {
            if let Ok(p) = app.cursor_position() {
                let p = Point::new(p.x, p.y);
                if !app.state::<OverlayState>().is_interactive_at(p) {
                    let index = log.lock().unwrap().click_pending();
                    let (a, l) = (app.clone(), log.clone());
                    thread::spawn(move || {
                        let (target, app_name, window, shot) = describe_click(&a, p);
                        l.lock()
                            .unwrap()
                            .fill_click(index, target, &app_name, &window, shot);
                    });
                }
            }
        }
        prev_left = left;

        if !key_events.is_empty() && !focused_on_us {
            if now.duration_since(ctx_at) >= CONTEXT_TTL {
                let (name, title) = crate::capture::foreground_window().unwrap_or_default();
                let settings = app.state::<SettingsStore>().get();
                let blocked = crate::privacy::is_blocked(&settings.blocklist, &name, &title);
                ctx = KeyContext {
                    secure: blocked || crate::uitree::secure_field_focused(),
                    window: if blocked { String::new() } else { title },
                    app: name,
                };
                ctx_at = now;
            }
            let mut l = log.lock().unwrap();
            for ev in key_events {
                l.key(ev, &ctx, now);
            }
        }
        let count = {
            let mut l = log.lock().unwrap();
            l.tick(now);
            l.len()
        };
        if count != last_count {
            last_count = count;
            publish(&app, true, count);
        }
    }
}

/// Element under the click, foreground app, and a thumbnail — unless privacy forbids.
fn describe_click<R: Runtime>(
    app: &AppHandle<R>,
    p: Point,
) -> (Option<Target>, String, String, Option<String>) {
    let monitors = app.state::<OverlayState>().monitors();
    let (name, title) = crate::capture::foreground_window().unwrap_or_default();
    let settings = app.state::<SettingsStore>().get();
    if crate::privacy::is_blocked(&settings.blocklist, &name, &title)
        || crate::uitree::secure_field_focused()
    {
        return (None, name, String::new(), None);
    }
    let target = crate::uitree::element_at(p.x, p.y, &monitors)
        .filter(|e| !e.name.trim().is_empty() || crate::uitree::is_interactive(&e.role))
        .map(|e| Target {
            role: e.role,
            name: e.name.split_whitespace().collect::<Vec<_>>().join(" "),
        });
    let shot = geometry::monitor_at(p, &monitors).and_then(|m| {
        crate::capture::thumbnail_data_url(m)
            .map_err(|e| ::log::warn!("thumbnail failed: {e}"))
            .ok()
    });
    (target, name, title, shot)
}
