//! User settings, persisted as JSON in the app config dir (see DECISIONS.md D2).

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};

pub const FILE_NAME: &str = "settings.json";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResponseLength {
    Brief,
    Detailed,
}

/// Mirrors `Settings` in app/src/lib/settings.ts.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", default)]
pub struct Settings {
    pub backend_url: String,
    pub voice_enabled: bool,
    pub voice_id: Option<String>,
    /// Accelerator string for tauri-plugin-global-shortcut; Alt maps to Option on macOS.
    pub hotkey: String,
    pub response_length: ResponseLength,
    pub language: String,
    pub paused: bool,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            backend_url: "http://127.0.0.1:8787".into(),
            voice_enabled: true,
            voice_id: None,
            hotkey: "Ctrl+Alt+Space".into(),
            response_length: ResponseLength::Brief,
            language: "en".into(),
            paused: false,
        }
    }
}

impl Settings {
    pub fn validate(&self) -> Result<(), String> {
        let url = self.backend_url.trim();
        if !(url.starts_with("http://") || url.starts_with("https://")) {
            return Err("backend URL must start with http:// or https://".into());
        }
        if self.hotkey.trim().is_empty() {
            return Err("hotkey must not be empty".into());
        }
        if self.language.trim().is_empty() {
            return Err("language must not be empty".into());
        }
        Ok(())
    }
}

/// Thread-safe settings holder backed by a JSON file.
pub struct SettingsStore {
    path: PathBuf,
    current: Mutex<Settings>,
}

impl SettingsStore {
    /// Loads settings from `dir/settings.json`; a missing or corrupt file yields defaults.
    pub fn load(dir: &Path) -> Self {
        let path = dir.join(FILE_NAME);
        let current = fs::read_to_string(&path)
            .ok()
            .and_then(|s| match serde_json::from_str(&s) {
                Ok(v) => Some(v),
                Err(e) => {
                    log::warn!("ignoring unreadable settings file {}: {e}", path.display());
                    None
                }
            })
            .unwrap_or_default();
        Self { path, current: Mutex::new(current) }
    }

    pub fn get(&self) -> Settings {
        self.current.lock().unwrap().clone()
    }

    /// Validates, writes atomically (temp file + rename), then updates memory.
    pub fn set(&self, next: Settings) -> Result<Settings, String> {
        next.validate()?;
        if let Some(parent) = self.path.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let tmp = self.path.with_extension("json.tmp");
        let json = serde_json::to_string_pretty(&next).map_err(|e| e.to_string())?;
        fs::write(&tmp, json).map_err(|e| e.to_string())?;
        fs::rename(&tmp, &self.path).map_err(|e| e.to_string())?;
        *self.current.lock().unwrap() = next.clone();
        Ok(next)
    }

    pub fn update(&self, f: impl FnOnce(&mut Settings)) -> Result<Settings, String> {
        let mut next = self.get();
        f(&mut next);
        self.set(next)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_file_gives_defaults() {
        let dir = tempfile::tempdir().unwrap();
        assert_eq!(SettingsStore::load(dir.path()).get(), Settings::default());
    }

    #[test]
    fn round_trips_through_disk() {
        let dir = tempfile::tempdir().unwrap();
        let store = SettingsStore::load(dir.path());
        store.update(|s| {
            s.voice_enabled = false;
            s.response_length = ResponseLength::Detailed;
            s.voice_id = Some("nova".into());
        })
        .unwrap();
        let reloaded = SettingsStore::load(dir.path()).get();
        assert!(!reloaded.voice_enabled);
        assert_eq!(reloaded.response_length, ResponseLength::Detailed);
        assert_eq!(reloaded.voice_id.as_deref(), Some("nova"));
    }

    #[test]
    fn corrupt_file_gives_defaults() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join(FILE_NAME), "{not json").unwrap();
        assert_eq!(SettingsStore::load(dir.path()).get(), Settings::default());
    }

    #[test]
    fn unknown_and_missing_fields_are_tolerated() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(dir.path().join(FILE_NAME), r#"{"language":"en","future":1}"#).unwrap();
        let s = SettingsStore::load(dir.path()).get();
        assert_eq!(s.hotkey, Settings::default().hotkey);
    }

    #[test]
    fn rejects_invalid_settings() {
        let dir = tempfile::tempdir().unwrap();
        let store = SettingsStore::load(dir.path());
        let bad = Settings { backend_url: "ftp://x".into(), ..Settings::default() };
        assert!(store.set(bad).is_err());
        assert_eq!(store.get(), Settings::default());
    }
}
