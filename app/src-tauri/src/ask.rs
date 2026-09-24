//! Talk mode: capture context → POST /v1/ask → stream SSE → drive the overlay.
//!
//! Screenshots go straight from Rust to the backend (never through a webview) and are
//! dropped as soon as the request body is sent. See PLAN.md §1 "Ask flow".

use std::collections::{HashMap, VecDeque};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, Runtime};

use crate::capture::{self, Screenshot};
use crate::geometry::{self, MonitorInfo, Point, Rect, ScreenshotMeta};
use crate::overlay::{self, OverlayState};
use crate::settings::{ResponseLength, Settings, SettingsStore};
use crate::sse::{SseParser, Utf8Buffer};
use crate::uitree::{self, UiSnapshot};

const HISTORY_MESSAGES: usize = 20; // 10 exchanges

/// Everything captured for one question. Lives only until the request is sent.
pub struct Captured {
    pub monitor: MonitorInfo,
    pub overlay_label: String,
    pub screenshot: Option<Screenshot>,
    pub snapshot: UiSnapshot,
    /// Why screen content was withheld (privacy), if it was.
    pub withheld: Option<&'static str>,
    pub capture_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Turn {
    pub role: String,
    pub text: String,
}

#[derive(Default)]
pub struct AskState {
    history: Mutex<VecDeque<Turn>>,
    generation: AtomicU64,
    pub last_timings: Mutex<Option<Value>>,
    client: Mutex<Option<reqwest::Client>>,
    /// Current lesson step (title, step_index, step_count, instruction) while tutoring.
    lesson: Mutex<Option<Value>>,
}

impl AskState {
    fn client(&self) -> reqwest::Client {
        let mut c = self.client.lock().unwrap();
        c.get_or_insert_with(|| {
            reqwest::Client::builder()
                .connect_timeout(Duration::from_secs(5))
                .read_timeout(Duration::from_secs(30))
                .build()
                .expect("http client")
        })
        .clone()
    }

    pub fn history(&self) -> Vec<Turn> {
        self.history.lock().unwrap().iter().cloned().collect()
    }

    fn remember(&self, user: &str, assistant: &str) {
        let mut h = self.history.lock().unwrap();
        h.push_back(Turn {
            role: "user".into(),
            text: user.into(),
        });
        h.push_back(Turn {
            role: "assistant".into(),
            text: assistant.into(),
        });
        while h.len() > HISTORY_MESSAGES {
            h.pop_front();
        }
    }

    pub fn set_lesson(&self, lesson: Option<Value>) {
        *self.lesson.lock().unwrap() = lesson;
    }

    pub fn lesson(&self) -> Option<Value> {
        self.lesson.lock().unwrap().clone()
    }

    pub fn clear_history(&self) {
        self.history.lock().unwrap().clear();
    }
}

/// Grabs the screenshot + UI tree for the monitor under the cursor, honouring privacy rules.
pub fn capture_context<R: Runtime>(app: &AppHandle<R>) -> Captured {
    let started = Instant::now();
    let monitors = app.state::<OverlayState>().monitors();
    let cursor = app
        .cursor_position()
        .map(|p| Point::new(p.x, p.y))
        .unwrap_or_default();
    let monitor = geometry::monitor_at(cursor, &monitors)
        .cloned()
        .unwrap_or_else(|| MonitorInfo {
            id: "0".into(),
            bounds: Rect::new(0.0, 0.0, 1920.0, 1080.0),
            scale_factor: 1.0,
            is_primary: true,
        });
    let overlay_label = app
        .state::<OverlayState>()
        .label_for_monitor(&monitor.id)
        .unwrap_or_else(|| overlay::label_for(0));

    let settings = app.state::<SettingsStore>().get();
    let mut snapshot = uitree::snapshot(&monitors);
    if snapshot.app_name.is_empty() || snapshot.window_title.is_empty() {
        if let Some((name, title)) = capture::foreground_window() {
            if snapshot.app_name.is_empty() {
                snapshot.app_name = name;
            }
            if snapshot.window_title.is_empty() {
                snapshot.window_title = title;
            }
        }
    }

    let withheld = crate::privacy::capture_blocker(&settings, &snapshot);
    let screenshot = if withheld.is_some() {
        snapshot.elements.clear();
        snapshot.window_title.clear();
        None
    } else {
        capture::capture_monitor(&monitor)
            .map_err(|e| log::warn!("screenshot failed: {e}"))
            .ok()
    };

    Captured {
        monitor,
        overlay_label,
        screenshot,
        snapshot,
        withheld,
        capture_ms: started.elapsed().as_millis() as u64,
    }
}

/// Request context + a map from element id to its screen rect (for resolving the target).
pub struct Prepared {
    pub context: Value,
    pub targets: HashMap<String, Rect>,
    pub meta: ScreenshotMeta,
}

pub fn prepare(
    captured: &Captured,
    history: &[Turn],
    settings: &Settings,
    text: Option<&str>,
    lesson: Option<&Value>,
) -> Prepared {
    let meta = captured
        .screenshot
        .as_ref()
        .map(|s| s.meta)
        .unwrap_or_else(|| {
            let b = captured.monitor.bounds;
            let (w, h) = geometry::screenshot_size(b.w as u32, b.h as u32, capture::MAX_WIDTH);
            ScreenshotMeta {
                source: b,
                width: w,
                height: h,
            }
        });
    let mut targets = HashMap::new();
    let mut elements = Vec::new();
    for e in captured
        .snapshot
        .elements
        .iter()
        .filter(|e| captured.monitor.bounds.intersects(&e.rect))
    {
        let id = format!("e{}", elements.len() + 1);
        let r = geometry::screen_to_screenshot(&e.rect, &meta);
        elements.push(json!({
            "id": id,
            "role": e.role,
            "name": e.name,
            "rect": {"x": r.x.round(), "y": r.y.round(), "w": r.w.round(), "h": r.h.round()},
        }));
        targets.insert(id, e.rect);
    }
    let mut context = json!({
        "elements": elements,
        "app": {"name": captured.snapshot.app_name, "title": captured.snapshot.window_title},
        "history": history,
        "response_length": match settings.response_length {
            ResponseLength::Brief => "brief",
            ResponseLength::Detailed => "detailed",
        },
        "language": settings.language,
        "voice_enabled": settings.voice_enabled,
        "voice_id": settings.voice_id,
    });
    if captured.screenshot.is_some() {
        context["screenshot"] = json!({"width": meta.width, "height": meta.height});
    }
    if let Some(t) = text {
        context["text"] = json!(t);
    }
    if let Some(l) = lesson {
        context["lesson"] = l.clone();
    }
    Prepared {
        context,
        targets,
        meta,
    }
}

/// Resolves the model's target to a screen rect and whether to draw the highlight ring.
pub fn resolve_target(
    target: &Value,
    prepared: &Prepared,
    monitor: &MonitorInfo,
) -> Option<(Rect, bool)> {
    if let Some(id) = target.get("element_id").and_then(Value::as_str) {
        return prepared.targets.get(id).map(|r| (*r, true));
    }
    let x = target.get("x").and_then(Value::as_f64)?;
    let y = target.get("y").and_then(Value::as_f64)?;
    let p = geometry::screenshot_to_screen(Point::new(x, y), &prepared.meta);
    let size = 36.0 * monitor.scale_factor;
    Some((
        Rect::new(p.x - size / 2.0, p.y - size / 2.0, size, size),
        false,
    ))
}

fn emit<R: Runtime>(app: &AppHandle<R>, label: &str, event: &str, payload: Value) {
    let _ = app.emit_to(label, event, payload);
}

pub fn set_companion<R: Runtime>(app: &AppHandle<R>, label: &str, mode: &str) {
    let _ = app.emit_to(label, "companion-state", mode);
}

/// Runs one question end to end. `audio` is WAV bytes; `text` is a typed question.
pub async fn run<R: Runtime>(
    app: AppHandle<R>,
    captured: Captured,
    audio: Option<Vec<u8>>,
    text: Option<String>,
) {
    let state = app.state::<AskState>();
    let generation = state.generation.fetch_add(1, Ordering::SeqCst) + 1;
    let current = || app.state::<AskState>().generation.load(Ordering::SeqCst) == generation;
    let label = captured.overlay_label.clone();
    let started = Instant::now();
    set_companion(&app, &label, "thinking");

    let settings = app.state::<SettingsStore>().get();
    let lesson = state.lesson();
    let prepared = prepare(
        &captured,
        &state.history(),
        &settings,
        text.as_deref(),
        lesson.as_ref(),
    );
    if let Some(reason) = captured.withheld {
        emit(
            &app,
            &label,
            "ask-notice",
            json!({"code": "screen_withheld", "reason": reason}),
        );
    }

    let mut form = reqwest::multipart::Form::new().text("context", prepared.context.to_string());
    if let Some(wav) = audio {
        form = form.part(
            "audio",
            reqwest::multipart::Part::bytes(wav)
                .file_name("question.wav")
                .mime_str("audio/wav")
                .unwrap(),
        );
    }
    if let Some(shot) = captured.screenshot {
        form = form.part(
            "screenshot",
            reqwest::multipart::Part::bytes(shot.jpeg)
                .file_name("screen.jpg")
                .mime_str("image/jpeg")
                .unwrap(),
        );
    }

    let url = format!("{}/v1/ask", settings.backend_url.trim_end_matches('/'));
    let mut req = state.client().post(url).multipart(form);
    if let Some(token) = crate::auth::token(&app) {
        req = req.bearer_auth(token);
    }
    let resp = match req.send().await {
        Ok(r) => r,
        Err(e) => {
            log::warn!("ask request failed: {e}");
            return fail(&app, &label, "backend_unreachable");
        }
    };
    if !resp.status().is_success() {
        let status = resp.status().as_u16();
        let body: Value = resp.json().await.unwrap_or(Value::Null);
        let code = body
            .pointer("/detail/code")
            .and_then(Value::as_str)
            .unwrap_or(match status {
                401 => "auth_required",
                402 | 429 => "limit_reached",
                _ => "backend_error",
            });
        return fail(&app, &label, code);
    }

    let mut transcript = String::new();
    let mut first_event_ms = None;
    let mut first_audio_ms = None;
    let mut parser = SseParser::default();
    let mut utf8 = Utf8Buffer::default();
    let mut body = resp.bytes_stream();
    while let Some(chunk) = body.next().await {
        if !current() {
            return; // a newer question superseded this one
        }
        let chunk = match chunk {
            Ok(c) => c,
            Err(e) => {
                log::warn!("ask stream broke: {e}");
                return fail(&app, &label, "backend_unreachable");
            }
        };
        for ev in parser.push(&utf8.push_bytes(&chunk)) {
            let data: Value = serde_json::from_str(&ev.data).unwrap_or(Value::Null);
            first_event_ms.get_or_insert(started.elapsed().as_millis() as u64);
            match ev.event.as_str() {
                "transcript" => {
                    transcript = data["text"].as_str().unwrap_or_default().to_string();
                    emit(&app, &label, "ask-transcript", data);
                }
                "speech_text" => emit(&app, &label, "ask-speech", data),
                "audio" => {
                    first_audio_ms.get_or_insert(started.elapsed().as_millis() as u64);
                    emit(&app, &label, "ask-audio", data);
                }
                "target" => {
                    let hint = data["action_hint"].as_str().map(str::to_string);
                    if let Some((rect, ring)) =
                        resolve_target(&data["target"], &prepared, &captured.monitor)
                    {
                        if let Err(e) = overlay::point_at(&app, rect, hint, ring) {
                            log::warn!("pointing failed: {e}");
                        }
                    }
                }
                "done" => {
                    let speech = data["speech"].as_str().unwrap_or_default();
                    state.remember(&transcript, speech);
                    let timings = json!({
                        "client": {
                            "capture_ms": captured.capture_ms,
                            "first_event_ms": first_event_ms,
                            "first_audio_ms": first_audio_ms,
                            "total_ms": started.elapsed().as_millis() as u64,
                        },
                        "server": data["timings"],
                    });
                    *state.last_timings.lock().unwrap() = Some(timings.clone());
                    if data["intent"].is_null() {
                        let total = started.elapsed().as_millis() as i64;
                        let _ = app.state::<crate::store::Store>().record_ask(
                            &transcript,
                            &captured.snapshot.app_name,
                            total,
                            crate::nudges::now(),
                        );
                        let _ = app.emit_to("main", "progress-changed", "ask");
                    }
                    let _ = app.emit_to("main", "ask-timings", &timings);
                    emit(
                        &app,
                        &label,
                        "ask-done",
                        json!({"speech": speech, "timings": timings}),
                    );
                    // Spoken lesson commands ("teach me…", "done", "skip"…) go to the tutor.
                    if !data["intent"].is_null() {
                        log::info!("intent {} → tutor", data["intent"]);
                        let _ = app.emit_to(
                            "main",
                            "ask-intent",
                            json!({"intent": data["intent"], "lesson_goal": data["lesson_goal"]}),
                        );
                    }
                }
                "error" => {
                    emit(&app, &label, "ask-error", data.clone());
                    if data["fatal"].as_bool() != Some(false) {
                        set_companion(&app, &label, "idle");
                    }
                }
                other => log::debug!("ignoring ask event {other}"),
            }
        }
    }
}

fn fail<R: Runtime>(app: &AppHandle<R>, label: &str, code: &str) {
    emit(app, label, "ask-error", json!({"code": code}));
    set_companion(app, label, "idle");
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::uitree::UiElement;

    fn captured(elements: Vec<UiElement>, with_shot: bool) -> Captured {
        let monitor = MonitorInfo {
            id: "1".into(),
            bounds: Rect::new(1920.0, 0.0, 2560.0, 1440.0),
            scale_factor: 1.25,
            is_primary: false,
        };
        let screenshot = with_shot.then(|| Screenshot {
            jpeg: vec![0xFF, 0xD8],
            meta: ScreenshotMeta {
                source: monitor.bounds,
                width: 1280,
                height: 720,
            },
        });
        Captured {
            monitor,
            overlay_label: "overlay-1".into(),
            screenshot,
            snapshot: UiSnapshot {
                app_name: "Notepad".into(),
                window_title: "notes.txt".into(),
                elements,
                secure_field_focused: false,
            },
            withheld: None,
            capture_ms: 5,
        }
    }

    fn el(name: &str, x: f64) -> UiElement {
        UiElement {
            role: "button".into(),
            name: name.into(),
            rect: Rect::new(x, 100.0, 40.0, 20.0),
        }
    }

    #[test]
    fn prepare_numbers_elements_on_the_monitor_in_screenshot_space() {
        let c = captured(
            vec![el("Other monitor", 100.0), el("Bold", 1920.0 + 200.0)],
            true,
        );
        let p = prepare(&c, &[], &Settings::default(), None, None);
        let els = p.context["elements"].as_array().unwrap();
        assert_eq!(els.len(), 1);
        assert_eq!(els[0]["id"], "e1");
        assert_eq!(els[0]["name"], "Bold");
        assert_eq!(
            els[0]["rect"],
            json!({"x": 100.0, "y": 50.0, "w": 20.0, "h": 10.0})
        );
        assert_eq!(p.targets["e1"], Rect::new(2120.0, 100.0, 40.0, 20.0));
        assert_eq!(
            p.context["screenshot"],
            json!({"width": 1280, "height": 720})
        );
        assert_eq!(p.context["response_length"], "brief");
    }

    #[test]
    fn prepare_without_screenshot_omits_it_but_keeps_text() {
        let c = captured(vec![], false);
        let p = prepare(
            &c,
            &[Turn {
                role: "user".into(),
                text: "hi".into(),
            }],
            &Settings::default(),
            Some("make it bold"),
            None,
        );
        assert!(p.context.get("screenshot").is_none());
        assert_eq!(p.context["text"], "make it bold");
        assert_eq!(p.context["history"][0]["text"], "hi");
    }

    #[test]
    fn resolves_element_and_pixel_targets_to_screen_space() {
        let c = captured(vec![el("Bold", 2120.0)], true);
        let p = prepare(&c, &[], &Settings::default(), None, None);
        let (r, ring) = resolve_target(&json!({"element_id": "e1"}), &p, &c.monitor).unwrap();
        assert_eq!((r, ring), (Rect::new(2120.0, 100.0, 40.0, 20.0), true));
        let (r, ring) = resolve_target(&json!({"x": 640, "y": 360}), &p, &c.monitor).unwrap();
        assert!(!ring);
        assert_eq!(r.center(), Point::new(1920.0 + 1280.0, 720.0));
        assert!(resolve_target(&json!({"element_id": "e9"}), &p, &c.monitor).is_none());
        assert!(resolve_target(&Value::Null, &p, &c.monitor).is_none());
    }

    #[test]
    fn history_keeps_last_ten_exchanges() {
        let s = AskState::default();
        for i in 0..15 {
            s.remember(&format!("q{i}"), &format!("a{i}"));
        }
        let h = s.history();
        assert_eq!(h.len(), 20);
        assert_eq!(h[0].text, "q5");
        assert_eq!(h[19].text, "a14");
    }
}
