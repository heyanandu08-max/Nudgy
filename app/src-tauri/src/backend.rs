//! Small JSON client for the backend's non-streaming endpoints.

use std::time::Duration;

use serde_json::Value;
use tauri::{AppHandle, Manager, Runtime};

use crate::capture::Screenshot;
use crate::settings::SettingsStore;

/// Stable error code the UI can map to a friendly message (see app/src/lib/errors.ts).
#[derive(Debug, Clone, serde::Serialize)]
pub struct ApiError {
    pub code: String,
    pub message: String,
}

impl ApiError {
    pub fn new(code: &str, message: impl Into<String>) -> Self {
        Self {
            code: code.into(),
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ApiError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}: {}", self.code, self.message)
    }
}

fn client() -> reqwest::Client {
    static CLIENT: std::sync::OnceLock<reqwest::Client> = std::sync::OnceLock::new();
    CLIENT
        .get_or_init(|| {
            reqwest::Client::builder()
                .connect_timeout(Duration::from_secs(5))
                .timeout(Duration::from_secs(90))
                .build()
                .expect("http client")
        })
        .clone()
}

pub fn url<R: Runtime>(app: &AppHandle<R>, path: &str) -> String {
    let base = app.state::<SettingsStore>().get().backend_url;
    format!("{}{}", base.trim_end_matches('/'), path)
}

fn authed<R: Runtime>(app: &AppHandle<R>, req: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
    match crate::auth::token(app) {
        Some(t) => req.bearer_auth(t),
        None => req,
    }
}

async fn finish(resp: Result<reqwest::Response, reqwest::Error>) -> Result<Value, ApiError> {
    let resp = resp.map_err(|e| {
        log::warn!("backend request failed: {e}");
        ApiError::new("backend_unreachable", "Can't reach the Nudgy server")
    })?;
    let status = resp.status();
    let body: Value = resp.json().await.unwrap_or(Value::Null);
    if status.is_success() {
        return Ok(body);
    }
    let detail = &body["detail"];
    let code = detail["code"].as_str().unwrap_or(match status.as_u16() {
        401 => "auth_required",
        402 | 429 => "limit_reached",
        _ => "backend_error",
    });
    Err(ApiError::new(
        code,
        detail["message"].as_str().unwrap_or("request failed"),
    ))
}

pub async fn post_json<R: Runtime>(
    app: &AppHandle<R>,
    path: &str,
    body: &Value,
) -> Result<Value, ApiError> {
    finish(
        authed(app, client().post(url(app, path)).json(body))
            .send()
            .await,
    )
    .await
}

pub async fn get_json<R: Runtime>(app: &AppHandle<R>, path: &str) -> Result<Value, ApiError> {
    finish(authed(app, client().get(url(app, path))).send().await).await
}

pub async fn delete<R: Runtime>(app: &AppHandle<R>, path: &str) -> Result<Value, ApiError> {
    finish(authed(app, client().delete(url(app, path))).send().await).await
}

/// multipart: `context` JSON + optional `screenshot` JPEG (dropped once sent).
pub async fn post_context<R: Runtime>(
    app: &AppHandle<R>,
    path: &str,
    context: &Value,
    screenshot: Option<Screenshot>,
) -> Result<Value, ApiError> {
    let mut form = reqwest::multipart::Form::new().text("context", context.to_string());
    if let Some(shot) = screenshot {
        form = form.part(
            "screenshot",
            reqwest::multipart::Part::bytes(shot.jpeg)
                .file_name("screen.jpg")
                .mime_str("image/jpeg")
                .unwrap(),
        );
    }
    finish(
        authed(app, client().post(url(app, path)).multipart(form))
            .send()
            .await,
    )
    .await
}

/// multipart `audio` (WAV) → JSON.
pub async fn post_audio<R: Runtime>(
    app: &AppHandle<R>,
    path: &str,
    wav: Vec<u8>,
) -> Result<Value, ApiError> {
    let form = reqwest::multipart::Form::new().part(
        "audio",
        reqwest::multipart::Part::bytes(wav)
            .file_name("note.wav")
            .mime_str("audio/wav")
            .unwrap(),
    );
    finish(
        authed(app, client().post(url(app, path)).multipart(form))
            .send()
            .await,
    )
    .await
}
