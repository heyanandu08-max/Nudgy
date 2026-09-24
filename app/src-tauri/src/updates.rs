//! Auto-update via tauri-plugin-updater. Release builds get the signing public key and
//! `createUpdaterArtifacts` from CI (see .github/workflows/release.yml); local builds have
//! an empty key, so checking is disabled there instead of failing.

use serde::Serialize;
use tauri::{AppHandle, Runtime};
use tauri_plugin_updater::UpdaterExt;

use crate::backend::ApiError;

#[derive(Serialize)]
pub struct UpdateInfo {
    pub version: String,
    pub notes: Option<String>,
}

fn enabled<R: Runtime>(app: &AppHandle<R>) -> bool {
    app.config()
        .plugins
        .0
        .get("updater")
        .and_then(|u| u.get("pubkey"))
        .and_then(|k| k.as_str())
        .is_some_and(|k| !k.trim().is_empty())
}

fn err(e: impl std::fmt::Display) -> ApiError {
    ApiError::new("update_failed", e.to_string())
}

/// `None` when up to date; `updates_disabled` in builds without a signing key (dev).
#[tauri::command]
pub async fn update_check<R: Runtime>(app: AppHandle<R>) -> Result<Option<UpdateInfo>, ApiError> {
    if !enabled(&app) {
        return Err(ApiError::new("updates_disabled", "no update key in this build"));
    }
    let update = app.updater().map_err(err)?.check().await.map_err(err)?;
    Ok(update.map(|u| UpdateInfo {
        version: u.version,
        notes: u.body,
    }))
}

/// Downloads, verifies the signature, installs, and restarts.
#[tauri::command]
pub async fn update_install<R: Runtime>(app: AppHandle<R>) -> Result<(), ApiError> {
    if !enabled(&app) {
        return Err(ApiError::new("update_failed", "updates are off in this build"));
    }
    let Some(update) = app.updater().map_err(err)?.check().await.map_err(err)? else {
        return Ok(());
    };
    log::info!("installing update {}", update.version);
    update
        .download_and_install(|_, _| {}, || {})
        .await
        .map_err(err)?;
    app.restart();
}
