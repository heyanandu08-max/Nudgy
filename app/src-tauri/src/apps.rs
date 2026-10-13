//! Brings the app a lesson is about to the front (launching it if needed), so Nudgy guides
//! *inside the user's software* and never inside its own window.

use std::time::{Duration, Instant};

use tauri::{AppHandle, Runtime};

/// Friendly names from lesson plans → what the OS knows the app as.
pub fn canonical(app: &str) -> (&'static str, &'static str) {
    // (macOS app name, Windows executable)
    match app.trim().to_lowercase().as_str() {
        "excel" | "microsoft excel" => ("Microsoft Excel", "excel"),
        "word" | "microsoft word" => ("Microsoft Word", "winword"),
        "powerpoint" | "microsoft powerpoint" => ("Microsoft PowerPoint", "powerpnt"),
        "outlook" | "microsoft outlook" => ("Microsoft Outlook", "outlook"),
        "chrome" | "google chrome" => ("Google Chrome", "chrome"),
        "edge" | "microsoft edge" => ("Microsoft Edge", "msedge"),
        "firefox" => ("Firefox", "firefox"),
        "safari" => ("Safari", ""),
        "notepad" => ("TextEdit", "notepad"),
        "textedit" => ("TextEdit", "notepad"),
        "davinci resolve" | "resolve" => ("DaVinci Resolve", "Resolve"),
        "figma" => ("Figma", "figma"),
        "slack" => ("Slack", "slack"),
        "finder" => ("Finder", "explorer"),
        "file explorer" | "explorer" => ("Finder", "explorer"),
        _ => ("", ""),
    }
}

/// Does a foreground app/window name belong to `wanted` (a plan's app field)?
pub fn matches(wanted: &str, app_name: &str, window_title: &str) -> bool {
    let w = wanted.trim().to_lowercase();
    if w.is_empty() {
        return true;
    }
    let (mac, exe) = canonical(&w);
    let hay = format!(
        "{} {}",
        app_name.to_lowercase(),
        window_title.to_lowercase()
    );
    hay.contains(&w)
        || (!mac.is_empty() && hay.contains(&mac.to_lowercase()))
        || (!exe.is_empty()
            && app_name.to_lowercase().trim_end_matches(".exe") == exe.to_lowercase())
}

pub fn is_front(app: &str) -> bool {
    match crate::capture::foreground_window() {
        Some((name, title)) => matches(app, &name, &title),
        None => cfg!(not(any(target_os = "windows", target_os = "macos"))), // Linux: can't tell
    }
}

#[cfg(target_os = "macos")]
fn bring_to_front(app: &str) -> bool {
    let (mac, _) = canonical(app);
    let name = if mac.is_empty() { app.trim() } else { mac };
    // `open -a` focuses a running app or launches it.
    std::process::Command::new("open")
        .arg("-a")
        .arg(name)
        .status()
        .is_ok_and(|s| s.success())
}

#[cfg(target_os = "windows")]
fn bring_to_front(app: &str) -> bool {
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        IsIconic, SetForegroundWindow, ShowWindow, SW_RESTORE,
    };
    if let Ok(windows) = xcap::Window::all() {
        for w in windows {
            let (name, title) = (
                w.app_name().unwrap_or_default(),
                w.title().unwrap_or_default(),
            );
            if title.is_empty() || !matches(app, &name, &title) {
                continue;
            }
            let Ok(id) = w.id() else { continue };
            let hwnd = id as usize as *mut core::ffi::c_void;
            // SAFETY: plain Win32 calls on a window handle we just enumerated.
            unsafe {
                if IsIconic(hwnd) != 0 {
                    ShowWindow(hwnd, SW_RESTORE);
                }
                if SetForegroundWindow(hwnd) != 0 {
                    return true;
                }
            }
        }
    }
    let (_, exe) = canonical(app);
    if exe.is_empty() {
        return false;
    }
    // `start` resolves registered App Paths (excel, winword, chrome…).
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    std::process::Command::new("cmd")
        .args(["/C", "start", "", exe])
        .creation_flags(CREATE_NO_WINDOW)
        .status()
        .is_ok_and(|s| s.success())
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn bring_to_front(_app: &str) -> bool {
    true
}

/// Focuses (or launches) `app`; returns whether it is now in front.
#[tauri::command]
pub async fn focus_app(app: String) -> bool {
    if app.trim().is_empty() || is_front(&app) {
        return true;
    }
    let target = app.clone();
    let launched = tauri::async_runtime::spawn_blocking(move || bring_to_front(&target))
        .await
        .unwrap_or(false);
    if !launched {
        return false;
    }
    wait(&app, Duration::from_secs(12)).await
}

/// Waits until the user brings `app` to the front themselves (after "Open X and I'll take it
/// from there"). Returns false on timeout.
#[tauri::command]
pub async fn wait_for_app<R: Runtime>(_app: AppHandle<R>, name: String, timeout_secs: u64) -> bool {
    wait(&name, Duration::from_secs(timeout_secs.min(600))).await
}

async fn wait(app: &str, timeout: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < timeout {
        let a = app.to_string();
        if tauri::async_runtime::spawn_blocking(move || is_front(&a))
            .await
            .unwrap_or(false)
        {
            // Give the window a moment to finish appearing before we look at it.
            tokio::time::sleep(Duration::from_millis(600)).await;
            return true;
        }
        tokio::time::sleep(Duration::from_millis(800)).await;
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn matches_friendly_names_to_os_names() {
        assert!(matches("Excel", "Microsoft Excel", "Budget.xlsx"));
        assert!(matches("Excel", "EXCEL.EXE", "Book1"));
        assert!(matches("Chrome", "Google Chrome", "New Tab"));
        assert!(matches(
            "DaVinci Resolve",
            "Resolve",
            "DaVinci Resolve - Project"
        ));
        assert!(matches("Figma", "Figma", "Untitled"));
        assert!(!matches(
            "Excel",
            "Google Chrome",
            "Sheets tips - Google Search"
        ));
        assert!(matches("", "Anything", "")); // no app in the plan → don't block
    }

    #[test]
    fn unknown_apps_match_by_name() {
        assert!(matches("Blender", "Blender", "scene.blend"));
        assert!(!matches("Blender", "Finder", "Downloads"));
    }
}
