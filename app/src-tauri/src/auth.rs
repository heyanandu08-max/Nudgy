//! Signed-in session (JWT from the backend). Stored in the app data dir with the file
//! restricted to the current user where the OS supports it.

use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager, Runtime};

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct Session {
    pub token: String,
    pub email: String,
    pub plan: String,
}

pub struct AuthStore {
    path: PathBuf,
    session: Mutex<Option<Session>>,
}

impl AuthStore {
    pub fn load(dir: &Path) -> Self {
        let path = dir.join("session.json");
        let session = fs::read_to_string(&path)
            .ok()
            .and_then(|s| serde_json::from_str(&s).ok());
        Self {
            path,
            session: Mutex::new(session),
        }
    }

    pub fn get(&self) -> Option<Session> {
        self.session.lock().unwrap().clone()
    }

    pub fn set(&self, session: Option<Session>) -> Result<(), String> {
        match &session {
            Some(s) => {
                if let Some(parent) = self.path.parent() {
                    fs::create_dir_all(parent).map_err(|e| e.to_string())?;
                }
                fs::write(
                    &self.path,
                    serde_json::to_vec(s).map_err(|e| e.to_string())?,
                )
                .map_err(|e| e.to_string())?;
                restrict(&self.path);
            }
            None => {
                let _ = fs::remove_file(&self.path);
            }
        }
        *self.session.lock().unwrap() = session;
        Ok(())
    }
}

#[cfg(unix)]
fn restrict(path: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let _ = fs::set_permissions(path, fs::Permissions::from_mode(0o600));
}

#[cfg(not(unix))]
fn restrict(_path: &Path) {} // %APPDATA% is already per-user on Windows

pub fn token<R: Runtime>(app: &AppHandle<R>) -> Option<String> {
    app.try_state::<AuthStore>()?.get().map(|s| s.token)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_and_sign_out() {
        let dir = tempfile::tempdir().unwrap();
        let store = AuthStore::load(dir.path());
        assert!(store.get().is_none());
        let s = Session {
            token: "jwt".into(),
            email: "a@b.c".into(),
            plan: "free".into(),
        };
        store.set(Some(s.clone())).unwrap();
        assert_eq!(AuthStore::load(dir.path()).get(), Some(s));
        store.set(None).unwrap();
        assert!(AuthStore::load(dir.path()).get().is_none());
    }
}
