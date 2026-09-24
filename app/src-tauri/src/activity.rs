//! Detects that the learner *did something* (a click or a key press) so a lesson step can be
//! verified. Only the fact that input happened is reported — never which keys or where.

use std::sync::atomic::{AtomicBool, Ordering};
use std::thread;
use std::time::{Duration, Instant};

use device_query::{DeviceQuery, DeviceState};
use tauri::{AppHandle, Emitter, Manager, Runtime};

const POLL: Duration = Duration::from_millis(40);
const IDLE_POLL: Duration = Duration::from_millis(250);
const THROTTLE: Duration = Duration::from_millis(200);

#[derive(Default)]
pub struct Activity {
    enabled: AtomicBool,
}

impl Activity {
    pub fn set_enabled(&self, on: bool) {
        self.enabled.store(on, Ordering::SeqCst);
    }
}

/// Pure edge detection: something newly pressed since the last sample.
pub fn newly_pressed(
    prev_buttons: &[bool],
    buttons: &[bool],
    prev_keys: usize,
    keys: usize,
) -> bool {
    let click = buttons
        .iter()
        .enumerate()
        .any(|(i, &b)| b && !prev_buttons.get(i).copied().unwrap_or(false));
    click || keys > prev_keys
}

pub fn init<R: Runtime>(app: &AppHandle<R>) {
    app.manage(Activity::default());
    let app = app.clone();
    let _ = thread::Builder::new()
        .name("nudgy-activity".into())
        .spawn(move || {
            let mut device: Option<DeviceState> = None;
            let mut prev_buttons: Vec<bool> = Vec::new();
            let mut prev_keys = 0usize;
            let mut last_emit = Instant::now() - THROTTLE;
            loop {
                if !app.state::<Activity>().enabled.load(Ordering::SeqCst) {
                    prev_buttons.clear();
                    prev_keys = 0;
                    thread::sleep(IDLE_POLL);
                    continue;
                }
                // Created lazily: on macOS this needs the Accessibility permission.
                if device.is_none() {
                    device = DeviceState::checked_new();
                    if device.is_none() {
                        log::warn!(
                            "input activity unavailable (permission?); lessons rely on 'done'"
                        );
                        app.state::<Activity>().set_enabled(false);
                        continue;
                    }
                }
                let d = device.as_ref().unwrap();
                let buttons = d.get_mouse().button_pressed;
                let keys = d.get_keys().len();
                if newly_pressed(&prev_buttons, &buttons, prev_keys, keys)
                    && last_emit.elapsed() >= THROTTLE
                {
                    last_emit = Instant::now();
                    let _ = app.emit_to("main", "user-activity", ());
                }
                prev_buttons = buttons;
                prev_keys = keys;
                thread::sleep(POLL);
            }
        });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detects_press_edges_not_holds() {
        assert!(newly_pressed(&[false, false], &[true, false], 0, 0));
        assert!(!newly_pressed(&[true, false], &[true, false], 0, 0)); // still held
        assert!(newly_pressed(&[], &[false], 1, 2)); // extra key
        assert!(!newly_pressed(&[], &[false], 2, 1)); // key released
    }
}
