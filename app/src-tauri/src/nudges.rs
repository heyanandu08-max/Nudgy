//! Gentle review reminders. Every few minutes, if a skill is due for review, the companion
//! offers a short quiz — but never while paused, during a lesson, over a full-screen app,
//! more than once every few hours, or while snoozed.

use std::sync::Mutex;
use std::thread;
use std::time::Duration;

use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::settings::SettingsStore;
use crate::store::Store;

const FIRST_CHECK: Duration = Duration::from_secs(90);
const CHECK_EVERY: Duration = Duration::from_secs(600);
pub const MIN_GAP_SECS: i64 = 4 * 3600;
pub const SNOOZE_SECS: i64 = 4 * 3600;

#[derive(Default)]
pub struct NudgeState {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    last_nudge: i64,
    snoozed_until: i64,
}

impl NudgeState {
    pub fn snooze(&self, now: i64, secs: i64) {
        self.inner.lock().unwrap().snoozed_until = now + secs;
    }
}

/// Pure gate so the rules are testable.
pub fn should_nudge(
    now: i64,
    last_nudge: i64,
    snoozed_until: i64,
    paused: bool,
    in_lesson: bool,
    fullscreen: bool,
    due: usize,
) -> bool {
    due > 0
        && !paused
        && !in_lesson
        && !fullscreen
        && now >= snoozed_until
        && now - last_nudge >= MIN_GAP_SECS
}

pub fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

pub fn init<R: Runtime>(app: &AppHandle<R>) {
    app.manage(NudgeState::default());
    let app = app.clone();
    let _ = thread::Builder::new()
        .name("nudgy-nudges".into())
        .spawn(move || {
            thread::sleep(FIRST_CHECK);
            loop {
                check(&app);
                thread::sleep(CHECK_EVERY);
            }
        });
}

fn check<R: Runtime>(app: &AppHandle<R>) {
    let t = now();
    let due = match app.state::<Store>().due_skills(t) {
        Ok(d) => d,
        Err(e) => return log::warn!("due reviews query failed: {e}"),
    };
    let paused = app.state::<SettingsStore>().get().paused;
    let in_lesson = app.state::<crate::ask::AskState>().lesson().is_some();
    let monitors = app.state::<crate::overlay::OverlayState>().monitors();
    let state = app.state::<NudgeState>();
    let (last, snoozed) = {
        let i = state.inner.lock().unwrap();
        (i.last_nudge, i.snoozed_until)
    };
    // Only ask the OS about full-screen apps when everything else says yes.
    if !should_nudge(t, last, snoozed, paused, in_lesson, false, due.len()) {
        return;
    }
    if crate::uitree::foreground_is_fullscreen(&monitors) {
        return;
    }
    state.inner.lock().unwrap().last_nudge = t;
    let (skill_id, skill_name) = &due[0];
    let label = crate::hotkey::companion_label(app);
    let _ = app.emit_to(
        label.as_str(),
        "review-nudge",
        json!({"skill_id": skill_id, "skill_name": skill_name, "due_count": due.len()}),
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn nudge_rules() {
        let t = 1_000_000;
        assert!(should_nudge(t, 0, 0, false, false, false, 1));
        assert!(
            !should_nudge(t, 0, 0, false, false, false, 0),
            "nothing due"
        );
        assert!(!should_nudge(t, 0, 0, true, false, false, 1), "paused");
        assert!(!should_nudge(t, 0, 0, false, true, false, 1), "in a lesson");
        assert!(
            !should_nudge(t, 0, 0, false, false, true, 1),
            "full-screen app"
        );
        assert!(
            !should_nudge(t, t - 60, 0, false, false, false, 1),
            "nudged recently"
        );
        assert!(
            !should_nudge(t, 0, t + 60, false, false, false, 1),
            "snoozed"
        );
    }
}
