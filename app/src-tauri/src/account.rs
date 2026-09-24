//! Accounts on the desktop side: nudgy:// deep links (sign-in hand-off, shared
//! walkthroughs, billing return), the stored session, and account/billing/team commands.
//! The browser does the sign-in and checkout; the app only ever holds its session token.

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, Runtime};
use tauri_plugin_opener::OpenerExt;

use crate::auth::{AuthStore, Session};
use crate::backend::{self, ApiError};

/// What a nudgy:// URL asks for.
#[derive(Debug, PartialEq, Eq)]
pub enum DeepLink {
    SignIn(String),
    Walkthrough(String),
    BillingReturn,
    Unknown,
}

pub fn parse(url: &str) -> DeepLink {
    let Ok(u) = tauri::Url::parse(url) else {
        return DeepLink::Unknown;
    };
    if u.scheme() != "nudgy" {
        return DeepLink::Unknown;
    }
    // nudgy://auth?token=… → host "auth"; nudgy://w/<slug> → host "w", path "/<slug>"
    match u.host_str() {
        Some("auth") => u
            .query_pairs()
            .find(|(k, _)| k == "token")
            .map(|(_, v)| DeepLink::SignIn(v.into_owned()))
            .filter(|l| matches!(l, DeepLink::SignIn(t) if !t.is_empty()))
            .unwrap_or(DeepLink::Unknown),
        Some("w") => crate::walkthrough::slug_from_link(u.path().trim_start_matches('/'))
            .map(DeepLink::Walkthrough)
            .unwrap_or(DeepLink::Unknown),
        Some("billing") => DeepLink::BillingReturn,
        _ => DeepLink::Unknown,
    }
}

pub fn handle_urls(app: &AppHandle, urls: Vec<String>) {
    for url in urls {
        let link = parse(&url);
        log::info!(
            "deep link: {}",
            match &link {
                DeepLink::SignIn(_) => "sign-in",
                DeepLink::Walkthrough(_) => "walkthrough",
                DeepLink::BillingReturn => "billing",
                DeepLink::Unknown => "unknown",
            }
        );
        let app = app.clone();
        tauri::async_runtime::spawn(async move {
            match link {
                DeepLink::SignIn(token) => {
                    if let Err(e) = sign_in_with(&app, token).await {
                        log::warn!("sign-in hand-off failed: {e}");
                    }
                    show(&app, "account");
                }
                DeepLink::Walkthrough(slug) => {
                    match crate::walkthrough::walkthrough_fetch(app.clone(), slug).await {
                        Ok(_) => {
                            let _ = app.emit("walkthroughs-changed", ());
                        }
                        Err(e) => log::warn!("could not import shared walkthrough: {e}"),
                    }
                    show(&app, "walkthroughs");
                }
                DeepLink::BillingReturn => {
                    let _ = refresh(&app).await;
                    show(&app, "account");
                }
                DeepLink::Unknown => {}
            }
        });
    }
}

fn show<R: Runtime>(app: &AppHandle<R>, tab: &str) {
    crate::tray::show_main(app);
    let _ = app.emit_to("main", "navigate", tab);
}

/// Stores a session token handed over by the browser after checking it with /v1/me.
async fn sign_in_with<R: Runtime>(app: &AppHandle<R>, token: String) -> Result<Value, ApiError> {
    let store = app.state::<AuthStore>();
    let previous = store.get();
    store
        .set(Some(Session {
            token,
            email: String::new(),
            plan: String::new(),
        }))
        .map_err(|e| ApiError::new("internal", e))?;
    match refresh(app).await {
        Ok(me) => Ok(me),
        Err(e) => {
            let _ = store.set(previous);
            let _ = app.emit("auth-changed", ());
            Err(e)
        }
    }
}

/// Re-reads /v1/me into the stored session; signs out if the token was rejected.
pub async fn refresh<R: Runtime>(app: &AppHandle<R>) -> Result<Value, ApiError> {
    let store = app.state::<AuthStore>();
    let Some(mut session) = store.get() else {
        return Err(ApiError::new("auth_required", "Not signed in"));
    };
    match backend::get_json(app, "/v1/me").await {
        Ok(me) => {
            session.email = me["email"].as_str().unwrap_or_default().into();
            session.plan = me["plan"].as_str().unwrap_or_default().into();
            store
                .set(Some(session))
                .map_err(|e| ApiError::new("internal", e))?;
            let _ = app.emit("auth-changed", ());
            Ok(me)
        }
        Err(e) if e.code == "auth_expired" || e.code == "auth_required" => {
            let _ = store.set(None);
            let _ = app.emit("auth-changed", ());
            Err(e)
        }
        Err(e) => Err(e),
    }
}

/// On launch: swap the stored token for a fresh one so active users never get logged out.
pub fn rotate_on_start<R: Runtime>(app: &AppHandle<R>) {
    if app.state::<AuthStore>().get().is_none() {
        return;
    }
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        match backend::post_json(&app, "/v1/auth/refresh", &json!({})).await {
            Ok(v) => {
                if let (Some(token), Some(mut s)) =
                    (v["token"].as_str(), app.state::<AuthStore>().get())
                {
                    s.token = token.to_string();
                    let _ = app.state::<AuthStore>().set(Some(s));
                }
                let _ = refresh(&app).await;
            }
            Err(e) if e.code == "auth_expired" => {
                let _ = app.state::<AuthStore>().set(None);
                let _ = app.emit("auth-changed", ());
            }
            Err(e) => log::info!("session refresh skipped: {e}"),
        }
    });
}

fn open<R: Runtime>(app: &AppHandle<R>, url: &str) -> Result<(), ApiError> {
    app.opener()
        .open_url(url, None::<&str>)
        .map_err(|e| ApiError::new("internal", e.to_string()))
}

// ---- commands ----

#[tauri::command]
pub fn auth_state(store: tauri::State<'_, AuthStore>) -> Option<Value> {
    store
        .get()
        .map(|s| json!({"email": s.email, "plan": s.plan}))
}

#[tauri::command]
pub async fn auth_send_magic(app: AppHandle, email: String) -> Result<(), ApiError> {
    backend::post_json(&app, "/v1/auth/magic", &json!({"email": email.trim()}))
        .await
        .map(|_| ())
}

/// Opens Google/Apple sign-in in the browser; it comes back through nudgy://auth.
#[tauri::command]
pub fn auth_open_provider(app: AppHandle, provider: String) -> Result<(), ApiError> {
    if !matches!(provider.as_str(), "google" | "apple") {
        return Err(ApiError::new("bad_request", "unknown provider"));
    }
    open(
        &app,
        &backend::url(&app, &format!("/v1/auth/{provider}/start")),
    )
}

#[tauri::command]
pub fn auth_sign_out(app: AppHandle) -> Result<(), String> {
    app.state::<AuthStore>().set(None)?;
    let _ = app.emit("auth-changed", ());
    Ok(())
}

#[tauri::command]
pub async fn account_me(app: AppHandle) -> Result<Value, ApiError> {
    refresh(&app).await
}

/// Free-window notice and lesson allowance, always decided by the server (never the local
/// clock). Signed-out callers get the global notice only.
#[tauri::command]
pub async fn access_get(app: AppHandle) -> Result<Value, ApiError> {
    backend::get_json(&app, "/v1/access").await
}

#[tauri::command]
pub async fn billing_checkout(
    app: AppHandle,
    plan: String,
    seats: u32,
    student: bool,
    interval: Option<String>,
) -> Result<(), ApiError> {
    let v = backend::post_json(
        &app,
        "/v1/billing/checkout",
        &json!({
            "plan": plan,
            "seats": seats.max(1),
            "student": student,
            "interval": interval.as_deref().unwrap_or("month"),
        }),
    )
    .await?;
    open(
        &app,
        v["url"]
            .as_str()
            .ok_or_else(|| ApiError::new("billing_error", "no checkout url"))?,
    )
}

#[tauri::command]
pub async fn billing_portal(app: AppHandle) -> Result<(), ApiError> {
    let v = backend::post_json(&app, "/v1/billing/portal", &json!({})).await?;
    open(
        &app,
        v["url"]
            .as_str()
            .ok_or_else(|| ApiError::new("billing_error", "no portal url"))?,
    )
}

#[tauri::command]
pub async fn team_get(app: AppHandle) -> Result<Value, ApiError> {
    backend::get_json(&app, "/v1/team").await
}

#[tauri::command]
pub async fn team_invite(app: AppHandle, email: String) -> Result<Value, ApiError> {
    backend::post_json(&app, "/v1/team/invites", &json!({"email": email.trim()})).await
}

#[tauri::command]
pub async fn team_remove(app: AppHandle, member_id: i64) -> Result<Value, ApiError> {
    backend::delete(&app, &format!("/v1/team/members/{member_id}")).await
}

#[tauri::command]
pub async fn team_walkthroughs(app: AppHandle) -> Result<Value, ApiError> {
    backend::get_json(&app, "/v1/team/walkthroughs").await
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_deep_links() {
        assert_eq!(
            parse("nudgy://auth?token=abc.def"),
            DeepLink::SignIn("abc.def".into())
        );
        assert_eq!(parse("nudgy://auth?token="), DeepLink::Unknown);
        assert_eq!(
            parse("nudgy://w/Ab_c-12"),
            DeepLink::Walkthrough("Ab_c-12".into())
        );
        // ".." segments are normalized away by the URL parser; odd characters are rejected.
        assert_eq!(parse("nudgy://w/a%2Fb"), DeepLink::Unknown);
        assert_eq!(
            parse("nudgy://billing?status=success"),
            DeepLink::BillingReturn
        );
        assert_eq!(parse("https://nudgy.app/w/abc"), DeepLink::Unknown);
        assert_eq!(parse("not a url"), DeepLink::Unknown);
    }
}
