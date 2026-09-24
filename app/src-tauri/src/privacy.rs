//! Capture gating. Screen content is only captured while the hotkey is held or a lesson
//! step is being verified, and never when a password field is focused or a blocklisted
//! app is in front. See PLAN.md Phase 8.

use serde_json::json;
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_dialog::DialogExt;

use crate::auth::AuthStore;
use crate::backend::{self, ApiError};
use crate::settings::{Settings, SettingsStore};
use crate::store::Store;
use crate::uitree::UiSnapshot;

/// Apps never captured unless the user removes them from the list in Settings.
pub const DEFAULT_BLOCKLIST: &[&str] = &[
    "1Password",
    "Bitwarden",
    "LastPass",
    "KeePass",
    "KeePassXC",
    "Dashlane",
    "Keeper",
    "Keychain Access",
    "Passwords",
    "Enpass",
];

/// Returns why screen content must be withheld, or `None` if capture is allowed.
pub fn capture_blocker(settings: &Settings, snap: &UiSnapshot) -> Option<&'static str> {
    if snap.secure_field_focused {
        return Some("password_field");
    }
    if is_blocked(&settings.blocklist, &snap.app_name, &snap.window_title) {
        return Some("blocked_app");
    }
    None
}

/// Case-insensitive match of any blocklist entry against the app name or window title.
pub fn is_blocked(blocklist: &[String], app_name: &str, window_title: &str) -> bool {
    let app = app_name.to_lowercase();
    let title = window_title.to_lowercase();
    blocklist
        .iter()
        .map(|b| b.trim().to_lowercase())
        .filter(|b| !b.is_empty())
        .any(|b| {
            app == b || app.trim_end_matches(".exe") == b || app.contains(&b) || title.contains(&b)
        })
}

// ---- "Your data" (Settings → Privacy) ----

/// Save dialog → one JSON file with local learning data, settings and (if signed in)
/// everything the server holds. Returns false if cancelled.
#[tauri::command]
pub async fn privacy_export(app: AppHandle) -> Result<bool, ApiError> {
    let internal = |e: String| ApiError::new("internal", e);
    let local = app.state::<Store>().export_json().map_err(internal)?;
    let account = if app.state::<AuthStore>().get().is_some() {
        Some(backend::get_json(&app, "/v1/me/export").await?)
    } else {
        None
    };
    let doc = json!({
        "format": "nudgy-export",
        "version": 1,
        "exported_at": unix_now(),
        "settings": app.state::<SettingsStore>().get(),
        "local": local,
        "account": account,
    });
    let h = app.clone();
    let picked = tauri::async_runtime::spawn_blocking(move || {
        h.dialog()
            .file()
            .add_filter("JSON", &["json"])
            .set_file_name("nudgy-data.json")
            .blocking_save_file()
    })
    .await
    .map_err(|e| internal(e.to_string()))?;
    let Some(path) = picked else { return Ok(false) };
    let path = path.into_path().map_err(|e| internal(e.to_string()))?;
    let bytes = serde_json::to_vec_pretty(&doc).map_err(|e| internal(e.to_string()))?;
    std::fs::write(path, bytes).map_err(|e| internal(e.to_string()))?;
    Ok(true)
}

/// Deletes local learning data (lessons, skills, reviews, walkthroughs, question history).
/// With `account`, first deletes the server account; if that fails nothing local is touched.
#[tauri::command]
pub async fn privacy_delete(app: AppHandle, account: bool) -> Result<(), ApiError> {
    let signed_in = app.state::<AuthStore>().get().is_some();
    if account && signed_in {
        backend::delete(&app, "/v1/me").await?;
    }
    app.state::<Store>()
        .wipe()
        .map_err(|e| ApiError::new("internal", e))?;
    if account && signed_in {
        let _ = app.state::<AuthStore>().set(None);
        let _ = app.emit("auth-changed", ());
    }
    let _ = app.emit("walkthroughs-changed", ());
    let _ = app.emit("data-wiped", ());
    log::info!(
        "local data wiped (account deleted: {})",
        account && signed_in
    );
    Ok(())
}

fn unix_now() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or_default()
}

/// Marks "Nudgy is looking at your screen" for as long as it lives (overlay chip + tray tooltip).
pub struct CaptureGuard<R: Runtime>(AppHandle<R>);

impl<R: Runtime> CaptureGuard<R> {
    pub fn new(app: &AppHandle<R>) -> Self {
        set_capturing(app, true);
        Self(app.clone())
    }
}

impl<R: Runtime> Drop for CaptureGuard<R> {
    fn drop(&mut self) {
        set_capturing(&self.0, false);
    }
}

fn set_capturing<R: Runtime>(app: &AppHandle<R>, on: bool) {
    let _ = app.emit("screen-capture", on);
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_tooltip(Some(if on {
            "Nudgy · looking at your screen"
        } else {
            "Nudgy"
        }));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snap(app: &str, title: &str, secure: bool) -> UiSnapshot {
        UiSnapshot {
            app_name: app.into(),
            window_title: title.into(),
            elements: vec![],
            secure_field_focused: secure,
        }
    }

    #[test]
    fn password_field_blocks_capture() {
        assert_eq!(
            capture_blocker(&Settings::default(), &snap("Chrome", "Login", true)),
            Some("password_field")
        );
    }

    #[test]
    fn default_blocklist_blocks_password_managers_only() {
        let s = Settings::default();
        assert_eq!(
            capture_blocker(&s, &snap("1Password", "Vault", false)),
            Some("blocked_app")
        );
        assert_eq!(
            capture_blocker(&s, &snap("keepassxc.exe", "db", false)),
            Some("blocked_app")
        );
        assert_eq!(
            capture_blocker(&s, &snap("Excel", "Budget.xlsx", false)),
            None
        );
    }

    #[test]
    fn user_entries_match_window_titles() {
        let list = vec!["Chase Online".to_string(), "  ".to_string()];
        assert!(is_blocked(
            &list,
            "Google Chrome",
            "Chase Online - Accounts"
        ));
        assert!(!is_blocked(&list, "Google Chrome", "Docs"));
    }
}
