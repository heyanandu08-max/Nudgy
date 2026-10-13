//! Walkthroughs: turn a recording into a clean, shareable `.nudgy` document; import,
//! export, share by link, and hand them to the tutor for guided playback.

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Manager, State};
use tauri_plugin_dialog::DialogExt;

use crate::backend::{self, ApiError};
use crate::recorder::{self, log::RawStep, log::Target, Recorder, Recording};
use crate::settings::SettingsStore;
use crate::store::{Store, WalkthroughRow};

pub const FORMAT: &str = "nudgy.walkthrough";
pub const VERSION: u32 = 1;
pub const EXTENSION: &str = "nudgy";
const MAX_SCREENSHOT_CHARS: usize = 400_000;
const MAX_FILE_BYTES: u64 = 20 * 1024 * 1024;

/// Mirrors `WalkthroughStep` in backend/app/schemas/walkthrough.py.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Step {
    pub instruction: String,
    #[serde(default)]
    pub target: Option<Target>,
    #[serde(default)]
    pub action_hint: Option<String>,
    #[serde(default)]
    pub success_check: String,
    #[serde(default)]
    pub why: String,
    #[serde(default)]
    pub note: Option<String>,
    #[serde(default)]
    pub screenshot: Option<String>,
    #[serde(default)]
    pub raw: Vec<usize>,
}

/// The `.nudgy` document.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Walkthrough {
    pub format: String,
    pub version: u32,
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub app: String,
    #[serde(default)]
    pub summary: String,
    #[serde(default)]
    pub platform: String,
    #[serde(default)]
    pub created_at: i64,
    pub steps: Vec<Step>,
}

impl Walkthrough {
    pub fn validate(&self) -> Result<(), String> {
        if self.format != FORMAT {
            return Err("not a Nudgy walkthrough file".into());
        }
        if self.version > VERSION {
            return Err("this walkthrough needs a newer version of Nudgy".into());
        }
        if self.id.trim().is_empty() || self.title.trim().is_empty() {
            return Err("walkthrough is missing its id or title".into());
        }
        if self.steps.is_empty() || self.steps.len() > 100 {
            return Err("walkthrough must have 1–100 steps".into());
        }
        for (i, s) in self.steps.iter().enumerate() {
            if s.instruction.trim().is_empty() {
                return Err(format!("step {} has no instruction", i + 1));
            }
            if let Some(shot) = &s.screenshot {
                if !shot.starts_with("data:image/jpeg;base64,") || shot.len() > MAX_SCREENSHOT_CHARS
                {
                    return Err(format!("step {} has an invalid screenshot", i + 1));
                }
            }
        }
        Ok(())
    }

    pub fn without_screenshots(&self) -> Walkthrough {
        let mut w = self.clone();
        for s in &mut w.steps {
            s.screenshot = None;
        }
        w
    }

    /// The tutor's lesson-plan shape, so playback reuses tutor mode.
    pub fn as_lesson_plan(&self) -> Value {
        json!({
            "title": self.title,
            "app": self.app,
            "skill": format!("walkthrough.{}", self.id),
            "skill_name": self.title,
            "steps": self.steps.iter().map(|s| json!({
                "instruction": s.instruction,
                "target": s.target,
                "action_hint": s.action_hint,
                "success_check": if s.success_check.is_empty() { &s.instruction } else { &s.success_check },
                "why": match (&s.why, &s.note) {
                    (w, _) if !w.is_empty() => w.clone(),
                    (_, Some(n)) => n.clone(),
                    _ => String::new(),
                },
            })).collect::<Vec<_>>(),
        })
    }
}

/// Most frequent app in the recording.
pub fn main_app(raw: &[RawStep]) -> String {
    let mut counts: Vec<(&str, usize)> = Vec::new();
    for r in raw.iter().filter(|r| !r.app.is_empty()) {
        match counts.iter_mut().find(|(a, _)| *a == r.app) {
            Some(c) => c.1 += 1,
            None => counts.push((&r.app, 1)),
        }
    }
    counts
        .into_iter()
        .max_by_key(|c| c.1)
        .map(|c| c.0.to_string())
        .unwrap_or_default()
}

/// Combines the backend's cleaned steps with the local thumbnails and author notes.
pub fn assemble(
    cleaned: &Value,
    rec: &Recording,
    id: &str,
    now: i64,
) -> Result<Walkthrough, String> {
    let steps = cleaned["steps"]
        .as_array()
        .ok_or("cleaned walkthrough has no steps")?;
    let mut out = Vec::with_capacity(steps.len());
    for s in steps {
        let mut step: Step = serde_json::from_value(s.clone()).map_err(|e| e.to_string())?;
        step.raw.retain(|&i| i < rec.raw.len());
        step.screenshot = step
            .raw
            .iter()
            .find_map(|&i| rec.shots.get(i).cloned().flatten());
        let notes: Vec<&str> = step
            .raw
            .iter()
            .filter_map(|&i| rec.raw[i].note.as_deref())
            .collect();
        step.note = (!notes.is_empty()).then(|| notes.join(" "));
        out.push(step);
    }
    let w = Walkthrough {
        format: FORMAT.into(),
        version: VERSION,
        id: id.into(),
        title: cleaned["title"].as_str().unwrap_or("Walkthrough").into(),
        app: cleaned["app"]
            .as_str()
            .filter(|a| !a.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| main_app(&rec.raw)),
        summary: cleaned["summary"].as_str().unwrap_or_default().into(),
        platform: std::env::consts::OS.into(),
        created_at: now,
        steps: out,
    };
    w.validate()?;
    Ok(w)
}

/// Accepts a share URL (`https://…/w/<slug>`), a deep link (`nudgy://w/<slug>`) or a bare slug.
pub fn slug_from_link(link: &str) -> Option<String> {
    let link = link.trim().trim_end_matches('/');
    let slug = match link.rfind("/w/") {
        Some(i) => &link[i + 3..],
        None if link.starts_with("nudgy://w/") => &link[10..],
        None => link,
    };
    let slug = slug.split(['?', '#']).next().unwrap_or_default();
    (!slug.is_empty()
        && slug.len() <= 32
        && slug
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'))
    .then(|| slug.to_string())
}

fn now() -> i64 {
    crate::nudges::now()
}

fn save(store: &Store, w: &Walkthrough) -> Result<(), String> {
    store.walkthrough_save(
        &w.id,
        &w.title,
        &w.app,
        &serde_json::to_string(w).map_err(|e| e.to_string())?,
        now(),
    )
}

fn load(store: &Store, id: &str) -> Result<Walkthrough, String> {
    let json = store.walkthrough_get(id)?.ok_or("walkthrough not found")?;
    serde_json::from_str(&json).map_err(|e| e.to_string())
}

// ---- commands ----

#[tauri::command]
pub fn recorder_start(app: AppHandle) -> Result<(), String> {
    recorder::start(&app)
}

#[tauri::command]
pub fn recorder_cancel(app: AppHandle) {
    recorder::stop(&app);
}

#[tauri::command]
pub fn recorder_note(state: State<'_, Recorder>, text: String) {
    state.note(&text);
}

/// Stops recording, cleans the log via the backend, saves and returns the walkthrough.
#[tauri::command]
pub async fn recorder_finish(app: AppHandle) -> Result<Walkthrough, ApiError> {
    let rec = recorder::stop(&app)
        .ok_or_else(|| ApiError::new("not_recording", "Nothing was recording"))?;
    if rec.raw.is_empty() {
        return Err(ApiError::new("empty_recording", "Nothing was recorded"));
    }
    let language = app.state::<SettingsStore>().get().language;
    let body = json!({"raw": rec.raw, "app": main_app(&rec.raw), "language": language});
    let cleaned = backend::post_json(&app, "/v1/walkthroughs/clean", &body).await?;
    let id = uuid::Uuid::new_v4().to_string();
    let w =
        assemble(&cleaned, &rec, &id, now()).map_err(|e| ApiError::new("bad_walkthrough", e))?;
    save(&app.state::<Store>(), &w).map_err(|e| ApiError::new("internal", e))?;
    Ok(w)
}

#[tauri::command]
pub fn walkthrough_list(store: State<'_, Store>) -> Result<Vec<WalkthroughRow>, String> {
    store.walkthrough_list()
}

#[tauri::command]
pub fn walkthrough_get(store: State<'_, Store>, id: String) -> Result<Walkthrough, String> {
    load(&store, &id)
}

#[tauri::command]
pub fn walkthrough_save(store: State<'_, Store>, walkthrough: Walkthrough) -> Result<(), String> {
    walkthrough.validate()?;
    save(&store, &walkthrough)
}

#[tauri::command]
pub fn walkthrough_delete(store: State<'_, Store>, id: String) -> Result<(), String> {
    store.walkthrough_delete(&id)
}

#[tauri::command]
pub fn walkthrough_plan(store: State<'_, Store>, id: String) -> Result<Value, String> {
    Ok(load(&store, &id)?.as_lesson_plan())
}

/// Save-as dialog → writes the `.nudgy` file. Returns false if the user cancelled.
#[tauri::command]
pub async fn walkthrough_export(
    app: AppHandle,
    id: String,
    include_screenshots: bool,
) -> Result<bool, String> {
    let w = load(&app.state::<Store>(), &id)?;
    let w = if include_screenshots {
        w
    } else {
        w.without_screenshots()
    };
    let file_name = format!("{}.{EXTENSION}", sanitize_file_name(&w.title));
    let h = app.clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        h.dialog()
            .file()
            .add_filter("Nudgy walkthrough", &[EXTENSION])
            .set_file_name(file_name)
            .blocking_save_file()
    })
    .await
    .map_err(|e| e.to_string())?;
    let Some(path) = picked else { return Ok(false) };
    let path = path.into_path().map_err(|e| e.to_string())?;
    std::fs::write(
        &path,
        serde_json::to_vec_pretty(&w).map_err(|e| e.to_string())?,
    )
    .map_err(|e| e.to_string())?;
    Ok(true)
}

/// Open dialog → validates and stores a `.nudgy` file. Returns None if cancelled.
#[tauri::command]
pub async fn walkthrough_import_file(app: AppHandle) -> Result<Option<Walkthrough>, String> {
    let h = app.clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        h.dialog()
            .file()
            .add_filter("Nudgy walkthrough", &[EXTENSION])
            .blocking_pick_file()
    })
    .await
    .map_err(|e| e.to_string())?;
    let Some(path) = picked else { return Ok(None) };
    let path = path.into_path().map_err(|e| e.to_string())?;
    if std::fs::metadata(&path).map_err(|e| e.to_string())?.len() > MAX_FILE_BYTES {
        return Err("that file is too large to be a walkthrough".into());
    }
    let w: Walkthrough = serde_json::from_slice(&std::fs::read(&path).map_err(|e| e.to_string())?)
        .map_err(|_| "that file isn't a valid Nudgy walkthrough".to_string())?;
    w.validate()?;
    save(&app.state::<Store>(), &w)?;
    Ok(Some(w))
}

/// Uploads to the backend and returns the public link.
#[tauri::command]
pub async fn walkthrough_share(
    app: AppHandle,
    id: String,
    include_screenshots: bool,
    team: Option<bool>,
) -> Result<String, ApiError> {
    let store = app.state::<Store>();
    let w = load(&store, &id).map_err(|e| ApiError::new("not_found", e))?;
    let body = json!({
        "walkthrough": w,
        "include_screenshots": include_screenshots,
        "team": team.unwrap_or(false),
    });
    let resp = backend::post_json(&app, "/v1/walkthroughs", &body).await?;
    let url = resp["url"]
        .as_str()
        .ok_or_else(|| ApiError::new("backend_error", "no link returned"))?
        .to_string();
    store
        .walkthrough_set_share_url(&id, &url)
        .map_err(|e| ApiError::new("internal", e))?;
    Ok(url)
}

/// Downloads a shared walkthrough (link, deep link or slug) into the local library.
#[tauri::command]
pub async fn walkthrough_fetch(app: AppHandle, link: String) -> Result<Walkthrough, ApiError> {
    let slug = slug_from_link(&link)
        .ok_or_else(|| ApiError::new("bad_link", "That doesn't look like a Nudgy link"))?;
    let doc = backend::get_json(&app, &format!("/v1/walkthroughs/{slug}")).await?;
    let w: Walkthrough =
        serde_json::from_value(doc).map_err(|e| ApiError::new("bad_walkthrough", e.to_string()))?;
    w.validate()
        .map_err(|e| ApiError::new("bad_walkthrough", e))?;
    save(&app.state::<Store>(), &w).map_err(|e| ApiError::new("internal", e))?;
    Ok(w)
}

fn sanitize_file_name(title: &str) -> String {
    let s: String = title
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || c == ' ' || c == '-' || c == '_' {
                c
            } else {
                '-'
            }
        })
        .collect();
    let s = s.trim().chars().take(60).collect::<String>();
    if s.is_empty() {
        "walkthrough".into()
    } else {
        s
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn raw(kind: &str, app: &str, note: Option<&str>) -> RawStep {
        RawStep {
            kind: kind.into(),
            target: None,
            text: None,
            keys: None,
            app: app.into(),
            window: String::new(),
            note: note.map(str::to_string),
        }
    }

    fn recording() -> Recording {
        Recording {
            raw: vec![
                raw("click", "Chrome", None),
                raw("click", "Chrome", Some("the menu")),
                raw("type", "Finder", None),
            ],
            shots: vec![None, Some("data:image/jpeg;base64,AAA".into()), None],
        }
    }

    #[test]
    fn assemble_attaches_thumbnails_and_notes_and_drops_bad_indices() {
        let cleaned = json!({
            "title": "Open incognito", "app": "", "summary": "s",
            "steps": [
                {"instruction": "Open the menu.", "target": {"role": "button", "name": "Menu"}, "raw": [0, 1, 7]},
                {"instruction": "Type the name.", "raw": [2]},
            ]
        });
        let w = assemble(&cleaned, &recording(), "id-1", 42).unwrap();
        assert_eq!(w.app, "Chrome"); // most frequent app when the backend gives none
        assert_eq!(w.steps[0].raw, vec![0, 1]);
        assert_eq!(
            w.steps[0].screenshot.as_deref(),
            Some("data:image/jpeg;base64,AAA")
        );
        assert_eq!(w.steps[0].note.as_deref(), Some("the menu"));
        assert_eq!(w.steps[1].screenshot, None);
        assert_eq!(
            (w.format.as_str(), w.version, w.created_at),
            (FORMAT, 1, 42)
        );
    }

    #[test]
    fn file_round_trip_and_validation() {
        let w = assemble(
            &json!({"title": "T", "steps": [{"instruction": "Do it."}]}),
            &recording(),
            "id",
            0,
        )
        .unwrap();
        let text = serde_json::to_string_pretty(&w).unwrap();
        let back: Walkthrough = serde_json::from_str(&text).unwrap();
        assert_eq!(back, w);
        let mut bad = w.clone();
        bad.format = "something.else".into();
        assert!(bad.validate().is_err());
        let mut bad = w.clone();
        bad.version = 99;
        assert!(bad.validate().unwrap_err().contains("newer"));
        let mut bad = w.clone();
        bad.steps[0].screenshot = Some("data:image/png;base64,AA".into());
        assert!(bad.validate().is_err());
        let mut bad = w;
        bad.steps.clear();
        assert!(bad.validate().is_err());
    }

    #[test]
    fn lesson_plan_shape_for_playback() {
        let w = assemble(
            &json!({"title": "T", "steps": [{"instruction": "Click Bold.", "target": {"role": "button", "name": "Bold"}, "raw": [1]}]}),
            &recording(),
            "abc",
            0,
        )
        .unwrap();
        let plan = w.as_lesson_plan();
        assert_eq!(plan["skill"], "walkthrough.abc");
        assert_eq!(plan["steps"][0]["target"]["name"], "Bold");
        assert_eq!(plan["steps"][0]["success_check"], "Click Bold."); // falls back to the instruction
        assert_eq!(plan["steps"][0]["why"], "the menu"); // falls back to the author's note
    }

    #[test]
    fn links() {
        assert_eq!(
            slug_from_link("https://nudgy.app/w/Ab_c-12").as_deref(),
            Some("Ab_c-12")
        );
        assert_eq!(
            slug_from_link("nudgy://w/abc123/").as_deref(),
            Some("abc123")
        );
        assert_eq!(slug_from_link("  abc123?x=1 ").as_deref(), Some("abc123"));
        assert_eq!(slug_from_link("https://evil/w/../../etc"), None);
        assert_eq!(slug_from_link(""), None);
    }

    #[test]
    fn file_names() {
        assert_eq!(
            sanitize_file_name("Export: report/PDF?"),
            "Export- report-PDF-"
        );
        assert_eq!(sanitize_file_name("   "), "walkthrough");
    }
}
