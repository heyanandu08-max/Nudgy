//! Per-monitor overlay windows: transparent, borderless, always-on-top, click-through
//! except over the small interactive regions the overlay UI registers (lesson controls).
//!
//! A background thread polls the cursor (~60 Hz), tells the overlay under the cursor where
//! it is (in that overlay's CSS pixels), and toggles click-through for interactive regions.

use std::collections::HashMap;
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{
    AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, Runtime, WebviewUrl,
    WebviewWindowBuilder,
};

use crate::geometry::{self, MonitorInfo, Point, Rect};

const POLL: Duration = Duration::from_millis(16);
const MONITOR_RESCAN: Duration = Duration::from_secs(2);

pub fn label_for(monitor_index: usize) -> String {
    format!("overlay-{monitor_index}")
}

#[derive(Default)]
pub struct OverlayState {
    monitors: Mutex<Vec<MonitorInfo>>,
    /// Interactive regions per overlay label, in that overlay's CSS pixels.
    interactive: Mutex<HashMap<String, Vec<Rect>>>,
}

impl OverlayState {
    pub fn monitors(&self) -> Vec<MonitorInfo> {
        self.monitors.lock().unwrap().clone()
    }

    pub fn label_for_monitor(&self, id: &str) -> Option<String> {
        let ms = self.monitors.lock().unwrap();
        ms.iter().position(|m| m.id == id).map(label_for)
    }

    pub fn set_interactive(&self, label: &str, rects: Vec<Rect>) {
        self.interactive.lock().unwrap().insert(label.to_string(), rects);
    }
}

/// Target sent to an overlay to animate the pointer.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PointEvent {
    /// Target box in the overlay's CSS pixels.
    pub rect: Rect,
    pub action_hint: Option<String>,
    /// Whether to draw the highlight ring (false for bare x/y targets).
    pub highlight: bool,
}

#[derive(Debug, Clone, Copy, Serialize)]
struct CursorEvent {
    x: f64,
    y: f64,
}

pub fn read_monitors<R: Runtime>(app: &AppHandle<R>) -> Vec<MonitorInfo> {
    let primary = app.primary_monitor().ok().flatten().map(|m| *m.position());
    app.available_monitors()
        .unwrap_or_default()
        .iter()
        .enumerate()
        .map(|(i, m)| {
            let pos = m.position();
            let size = m.size();
            MonitorInfo {
                id: format!("{i}:{}", m.name().map(String::as_str).unwrap_or("display")),
                bounds: Rect::new(pos.x as f64, pos.y as f64, size.width as f64, size.height as f64),
                scale_factor: m.scale_factor(),
                is_primary: primary == Some(*pos),
            }
        })
        .collect()
}

/// Creates (or re-creates) one overlay per monitor and starts the cursor loop.
pub fn init<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    app.manage(OverlayState::default());
    rebuild(app)?;
    let handle = app.clone();
    thread::Builder::new()
        .name("nudgy-cursor".into())
        .spawn(move || cursor_loop(handle))
        .map_err(|e| tauri::Error::Anyhow(e.into()))?;
    Ok(())
}

fn rebuild<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let monitors = read_monitors(app);
    let state = app.state::<OverlayState>();

    // Close overlays for monitors that disappeared.
    for (label, w) in app.webview_windows() {
        if let Some(idx) = label.strip_prefix("overlay-").and_then(|s| s.parse::<usize>().ok()) {
            if idx >= monitors.len() {
                let _ = w.close();
            }
        }
    }

    for (i, m) in monitors.iter().enumerate() {
        let label = label_for(i);
        let window = match app.get_webview_window(&label) {
            Some(w) => w,
            None => create_window(app, &label)?,
        };
        window.set_position(PhysicalPosition::new(m.bounds.x as i32, m.bounds.y as i32))?;
        window.set_size(PhysicalSize::new(m.bounds.w as u32, m.bounds.h as u32))?;
        // Show before enabling click-through: on Linux the native window must be realized
        // first (tao unwraps it), and it is harmless ordering on Windows/macOS.
        window.show()?;
        window.set_ignore_cursor_events(true)?;
        let _ = window.emit("monitor-info", m);
    }

    *state.monitors.lock().unwrap() = monitors;
    state.interactive.lock().unwrap().clear();
    Ok(())
}

fn create_window<R: Runtime>(
    app: &AppHandle<R>,
    label: &str,
) -> tauri::Result<tauri::WebviewWindow<R>> {
    let builder = WebviewWindowBuilder::new(app, label, WebviewUrl::App("overlay.html".into()))
        .title("Nudgy overlay")
        .decorations(false)
        .transparent(true)
        .shadow(false)
        .always_on_top(true)
        .visible_on_all_workspaces(true)
        .skip_taskbar(true)
        .resizable(false)
        .focused(false)
        .visible(false);
    #[cfg(target_os = "windows")]
    let builder = builder.focusable(false);
    builder.build()
}

fn cursor_loop<R: Runtime>(app: AppHandle<R>) {
    let mut last: Option<Point> = None;
    let mut last_label: Option<String> = None;
    let mut ignoring: HashMap<String, bool> = HashMap::new();
    let mut last_scan = Instant::now();

    loop {
        thread::sleep(POLL);

        if last_scan.elapsed() >= MONITOR_RESCAN {
            last_scan = Instant::now();
            let state = app.state::<OverlayState>();
            if read_monitors(&app) != state.monitors() {
                log::info!("monitor layout changed; rebuilding overlays");
                let h = app.clone();
                let _ = app.run_on_main_thread(move || {
                    if let Err(e) = rebuild(&h) {
                        log::error!("overlay rebuild failed: {e}");
                    }
                });
                ignoring.clear();
                continue;
            }
        }

        let Ok(pos) = app.cursor_position() else { continue };
        let p = Point::new(pos.x, pos.y);
        if last == Some(p) {
            continue;
        }
        last = Some(p);

        let state = app.state::<OverlayState>();
        let monitors = state.monitors();
        let Some((idx, m)) = monitors
            .iter()
            .enumerate()
            .find(|(_, m)| m.bounds.contains(p))
            .or_else(|| {
                geometry::monitor_at(p, &monitors)
                    .and_then(|hit| monitors.iter().enumerate().find(|(_, m)| m.id == hit.id))
            })
        else {
            continue;
        };
        let label = label_for(idx);
        let local = geometry::screen_point_to_overlay(p, m);

        if last_label.as_deref() != Some(label.as_str()) {
            if let Some(prev) = last_label.take() {
                let _ = app.emit_to(prev.as_str(), "cursor-left", ());
            }
            last_label = Some(label.clone());
        }
        let _ = app.emit_to(label.as_str(), "cursor", CursorEvent { x: local.x, y: local.y });

        // Click-through everywhere except over registered interactive regions.
        let over_control = state
            .interactive
            .lock()
            .unwrap()
            .get(&label)
            .is_some_and(|rs| rs.iter().any(|r| r.contains(local)));
        let should_ignore = !over_control;
        if ignoring.get(&label) != Some(&should_ignore) {
            if let Some(w) = app.get_webview_window(&label) {
                if w.set_ignore_cursor_events(should_ignore).is_ok() {
                    ignoring.insert(label.clone(), should_ignore);
                }
            }
        }
    }
}

/// Animates the pointer to `rect` (screen space) on whichever overlay contains it.
pub fn point_at<R: Runtime>(
    app: &AppHandle<R>,
    rect: Rect,
    action_hint: Option<String>,
    highlight: bool,
) -> Result<(), String> {
    let state = app.state::<OverlayState>();
    let monitors = state.monitors();
    let m = geometry::monitor_at(rect.center(), &monitors).ok_or("no monitors")?;
    let label = state.label_for_monitor(&m.id).ok_or("no overlay for monitor")?;
    let event = PointEvent { rect: geometry::screen_to_overlay(&rect, m), action_hint, highlight };
    app.emit_to(label.as_str(), "point", event).map_err(|e| e.to_string())
}

/// Debug helper: point at the centre of the monitor under the cursor.
pub fn point_at_screen_center<R: Runtime>(app: &AppHandle<R>) -> Result<(), String> {
    let cursor = app.cursor_position().map_err(|e| e.to_string())?;
    let state = app.state::<OverlayState>();
    let monitors = state.monitors();
    let m = geometry::monitor_at(Point::new(cursor.x, cursor.y), &monitors).ok_or("no monitors")?;
    let c = m.bounds.center();
    let size = 48.0 * m.scale_factor;
    point_at(app, Rect::new(c.x - size / 2.0, c.y - size / 2.0, size, size), Some("look".into()), true)
}
