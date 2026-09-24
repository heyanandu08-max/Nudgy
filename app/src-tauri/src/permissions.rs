//! OS permissions Nudgy needs, for onboarding and error states.
//! macOS gates screen recording, accessibility (UI tree, secure-field check) and the microphone;
//! Windows only has a microphone privacy switch; other targets need nothing.

use serde::Serialize;
use tauri::{AppHandle, Runtime};
use tauri_plugin_opener::OpenerExt;

#[derive(Debug, Clone, Copy, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Granted,
    Denied,
    /// The OS asks the first time it's used (or we can't read it without asking).
    Unknown,
}

#[derive(Debug, Clone, Serialize)]
pub struct Permissions {
    pub screen: Status,
    pub accessibility: Status,
    pub microphone: Status,
    /// Whether this OS needs the permission walkthrough at all.
    pub needs_walkthrough: bool,
}

#[cfg(target_os = "macos")]
mod platform {
    use super::Status;
    use accessibility_sys::{
        kAXTrustedCheckOptionPrompt, AXIsProcessTrusted, AXIsProcessTrustedWithOptions,
    };
    use core_foundation::base::TCFType;
    use core_foundation::boolean::CFBoolean;
    use core_foundation::dictionary::CFDictionary;
    use core_foundation::string::CFString;

    #[link(name = "CoreGraphics", kind = "framework")]
    extern "C" {
        fn CGPreflightScreenCaptureAccess() -> bool;
        fn CGRequestScreenCaptureAccess() -> bool;
    }

    fn status(granted: bool) -> Status {
        if granted {
            Status::Granted
        } else {
            Status::Denied
        }
    }

    pub const NEEDS_WALKTHROUGH: bool = true;

    pub fn screen() -> Status {
        // SAFETY: no arguments; reads this process's TCC state.
        status(unsafe { CGPreflightScreenCaptureAccess() })
    }

    pub fn accessibility() -> Status {
        // SAFETY: as above.
        status(unsafe { AXIsProcessTrusted() })
    }

    pub fn microphone() -> Status {
        Status::Unknown
    }

    /// Shows the system prompt where one exists. Returns the settings pane to open as well.
    pub fn request(kind: &str) -> Option<&'static str> {
        match kind {
            "screen" => {
                // SAFETY: shows the one-time system prompt; no arguments.
                unsafe { CGRequestScreenCaptureAccess() };
                Some(
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
                )
            }
            "accessibility" => {
                // SAFETY: the key is a static CFString from the framework; the dictionary
                // outlives the call.
                unsafe {
                    let key = CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt);
                    let opts = CFDictionary::from_CFType_pairs(&[(
                        key.as_CFType(),
                        CFBoolean::true_value().as_CFType(),
                    )]);
                    AXIsProcessTrustedWithOptions(opts.as_concrete_TypeRef());
                }
                Some(
                    "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
                )
            }
            "microphone" => {
                Some("x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")
            }
            _ => None,
        }
    }
}

#[cfg(target_os = "windows")]
mod platform {
    use super::Status;

    pub const NEEDS_WALKTHROUGH: bool = false;

    pub fn screen() -> Status {
        Status::Granted
    }

    pub fn accessibility() -> Status {
        Status::Granted
    }

    pub fn microphone() -> Status {
        Status::Unknown
    }

    pub fn request(kind: &str) -> Option<&'static str> {
        (kind == "microphone").then_some("ms-settings:privacy-microphone")
    }
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
mod platform {
    use super::Status;

    pub const NEEDS_WALKTHROUGH: bool = false;

    pub fn screen() -> Status {
        Status::Granted
    }

    pub fn accessibility() -> Status {
        Status::Granted
    }

    pub fn microphone() -> Status {
        Status::Unknown
    }

    pub fn request(_kind: &str) -> Option<&'static str> {
        None
    }
}

pub fn current() -> Permissions {
    Permissions {
        screen: platform::screen(),
        accessibility: platform::accessibility(),
        microphone: platform::microphone(),
        needs_walkthrough: platform::NEEDS_WALKTHROUGH,
    }
}

#[tauri::command]
pub fn permissions() -> Permissions {
    current()
}

/// Triggers the OS prompt (if any) and opens the matching settings pane.
#[tauri::command]
pub fn permission_request<R: Runtime>(app: AppHandle<R>, kind: String) -> Result<(), String> {
    if !matches!(kind.as_str(), "screen" | "accessibility" | "microphone") {
        return Err("unknown permission".into());
    }
    if let Some(url) = platform::request(&kind) {
        app.opener()
            .open_url(url, None::<&str>)
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}
