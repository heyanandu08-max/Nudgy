//! Tutor mode plumbing. The lesson state machine lives in the UI (app/src/features/tutor);
//! these commands give it eyes (capture), a voice (speak), a finger (point) and a memory
//! (store). Capture happens only to plan a lesson, to verify a step, or to find a step's
//! target when the element tree alone can't — never continuously.

use std::sync::Mutex;

use serde::Deserialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, Runtime, State};

use crate::ask::{self, Captured};
use crate::backend::{self, ApiError};
use crate::geometry::{self, ScreenshotMeta};
use crate::matcher;
use crate::overlay;
use crate::settings::SettingsStore;
use crate::store::{StepResult, Store};
use crate::uitree::{self, UiElement};

#[derive(Default)]
pub struct LessonState {
    /// UI elements (screen space) when the current step began, for the before/after diff.
    before: Mutex<Vec<UiElement>>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct StepTarget {
    #[serde(default)]
    pub role: String,
    #[serde(default)]
    pub name: String,
}

fn now() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

async fn capture<R: Runtime>(app: &AppHandle<R>) -> Result<Captured, ApiError> {
    let h = app.clone();
    tauri::async_runtime::spawn_blocking(move || ask::capture_context(&h))
        .await
        .map_err(|e| ApiError::new("internal", e.to_string()))
}

async fn snapshot_elements<R: Runtime>(app: &AppHandle<R>) -> Vec<UiElement> {
    let monitors = app.state::<overlay::OverlayState>().monitors();
    let settings = app.state::<SettingsStore>().get();
    tauri::async_runtime::spawn_blocking(move || {
        let snap = uitree::snapshot(&monitors);
        // Same gate as screenshots: no element names from password fields or blocked apps.
        if crate::privacy::capture_blocker(&settings, &snap).is_some() {
            Vec::new()
        } else {
            snap.elements
        }
    })
    .await
    .unwrap_or_default()
}

/// Elements as the backend expects them (ids + screenshot-space rects).
fn wire_elements(elements: &[UiElement], meta: &ScreenshotMeta) -> Vec<Value> {
    elements
        .iter()
        .filter(|e| meta.source.intersects(&e.rect))
        .enumerate()
        .map(|(i, e)| {
            let r = geometry::screen_to_screenshot(&e.rect, meta);
            json!({"id": format!("e{}", i + 1), "role": e.role, "name": e.name,
                   "rect": {"x": r.x.round(), "y": r.y.round(), "w": r.w.round(), "h": r.h.round()}})
        })
        .collect()
}

#[tauri::command]
pub async fn lesson_plan(app: AppHandle, goal: String) -> Result<Value, ApiError> {
    let captured = capture(&app).await?;
    let settings = app.state::<SettingsStore>().get();
    let prepared = ask::prepare(&captured, &[], &settings, None, None);
    let mut context = json!({
        "goal": goal,
        "app": prepared.context["app"],
        "elements": prepared.context["elements"],
        "language": settings.language,
    });
    if let Some(s) = prepared.context.get("screenshot") {
        context["screenshot"] = s.clone();
    }
    backend::post_context(&app, "/v1/lessons/plan", &context, captured.screenshot).await
}

#[tauri::command]
pub async fn lesson_begin_step(
    app: AppHandle,
    state: State<'_, LessonState>,
) -> Result<(), ApiError> {
    *state.before.lock().unwrap() = snapshot_elements(&app).await;
    Ok(())
}

#[tauri::command]
pub async fn lesson_verify(
    app: AppHandle,
    state: State<'_, LessonState>,
    step: Value,
    attempt: u32,
) -> Result<Value, ApiError> {
    let captured = capture(&app).await?;
    let settings = app.state::<SettingsStore>().get();
    let prepared = ask::prepare(&captured, &[], &settings, None, None);
    let before = state.before.lock().unwrap().clone();
    let mut context = json!({
        "step": step,
        "before": {"elements": wire_elements(&before, &prepared.meta)},
        "after": {"app": prepared.context["app"], "elements": prepared.context["elements"]},
        "attempt": attempt.max(1),
        "language": settings.language,
    });
    if let Some(s) = prepared.context.get("screenshot") {
        context["screenshot"] = s.clone();
    }
    backend::post_context(&app, "/v1/lessons/verify", &context, captured.screenshot).await
}

/// Points at a step's target. Tries the live element tree first (no capture, no network);
/// falls back to asking the backend to find it on a screenshot. Returns whether it pointed.
#[tauri::command]
pub async fn lesson_point(
    app: AppHandle,
    target: Option<StepTarget>,
    description: String,
    hint: Option<String>,
) -> Result<bool, ApiError> {
    if let Some(t) = target.as_ref().filter(|t| !t.name.is_empty()) {
        let elements = snapshot_elements(&app).await;
        if let Some(el) = matcher::find(&t.role, &t.name, &elements) {
            overlay::point_at(&app, el.rect, hint, true)
                .map_err(|e| ApiError::new("internal", e))?;
            return Ok(true);
        }
    }
    let captured = capture(&app).await?;
    if captured.screenshot.is_none() {
        return Ok(false);
    }
    let settings = app.state::<SettingsStore>().get();
    let prepared = ask::prepare(&captured, &[], &settings, None, None);
    let context = json!({
        "target": target.as_ref().map(|t| json!({"role": t.role, "name": t.name})),
        "description": description,
        "elements": prepared.context["elements"],
        "screenshot": prepared.context["screenshot"],
    });
    let found =
        backend::post_context(&app, "/v1/lessons/locate", &context, captured.screenshot).await?;
    match ask::resolve_target(&found["target"], &prepared, &captured.monitor) {
        Some((rect, ring)) => {
            overlay::point_at(&app, rect, hint, ring).map_err(|e| ApiError::new("internal", e))?;
            Ok(true)
        }
        None => Ok(false),
    }
}

/// Says `text` through the companion under the cursor: caption always, voice if enabled.
#[tauri::command]
pub async fn speak(app: AppHandle, text: String) -> Result<(), ApiError> {
    let settings = app.state::<SettingsStore>().get();
    let label = crate::hotkey::companion_label(&app);
    let clips = if settings.voice_enabled {
        let body =
            json!({"text": text, "voice_id": settings.voice_id, "language": settings.language});
        match backend::post_json(&app, "/v1/speak", &body).await {
            Ok(v) => v["clips"].clone(),
            Err(e) => {
                log::warn!("speak failed, captions only: {e}");
                json!([])
            }
        }
    } else {
        json!([])
    };
    let _ = app.emit_to(
        label.as_str(),
        "lesson-say",
        json!({"text": text, "clips": clips}),
    );
    Ok(())
}

#[tauri::command]
pub fn lesson_set_context(state: State<'_, ask::AskState>, context: Option<Value>) {
    state.set_lesson(context);
}

#[tauri::command]
pub fn activity_watch(state: State<'_, crate::activity::Activity>, on: bool) {
    state.set_enabled(on);
}

#[tauri::command]
pub fn lesson_record_start(
    store: State<'_, Store>,
    plan: Value,
    goal: String,
) -> Result<String, String> {
    let s = |k: &str| plan[k].as_str().unwrap_or_default().to_string();
    store.lesson_start(
        &s("skill"),
        &s("skill_name"),
        &s("app"),
        &s("title"),
        &goal,
        &plan.to_string(),
        now(),
    )
}

#[tauri::command]
pub fn lesson_record_step(
    store: State<'_, Store>,
    lesson_id: String,
    result: StepResult,
) -> Result<(), String> {
    store.lesson_step(&lesson_id, &result, now())
}

/// Finishes a lesson, grades it into the skill's SM-2 schedule, returns the skill id.
#[tauri::command]
pub fn lesson_record_finish(
    app: AppHandle,
    store: State<'_, Store>,
    lesson_id: String,
    status: String,
) -> Result<String, String> {
    let skill = store.lesson_finish(&lesson_id, &status, now())?;
    if let Err(e) = store.schedule_after_lesson(&lesson_id, &skill, now()) {
        log::warn!("could not schedule review for {skill}: {e}");
    }
    let _ = app.emit("progress-changed", &skill);
    Ok(skill)
}

#[tauri::command]
pub fn dashboard(store: State<'_, Store>) -> Result<crate::store::Dashboard, String> {
    store.dashboard(now())
}

/// The plan to replay as a review quiz for `skill_id`.
#[tauri::command]
pub fn review_plan(store: State<'_, Store>, skill_id: String) -> Result<Value, String> {
    let json = store
        .latest_plan_for_skill(&skill_id)?
        .ok_or("no lesson for this skill yet")?;
    serde_json::from_str(&json).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn review_snooze(state: State<'_, crate::nudges::NudgeState>) {
    state.snooze(now(), crate::nudges::SNOOZE_SECS);
}
