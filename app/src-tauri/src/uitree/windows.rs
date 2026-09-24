//! Windows UI Automation. Tauri apps are per-monitor DPI aware, so UIA bounding rectangles
//! are already physical screen pixels — our canonical space.

use std::time::{Duration, Instant};

use uiautomation::types::{ControlType, Handle, Point as UiaPoint, TreeScope, UIProperty};
use uiautomation::variants::Variant;
use uiautomation::{UIAutomation, UIElement};
use windows_sys::Win32::Foundation::RECT;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    GetClassNameW, GetForegroundWindow, GetWindowRect,
};

use super::{UiElement, UiSnapshot, MAX_ELEMENTS};
use crate::geometry::{MonitorInfo, Rect};

const BUDGET: Duration = Duration::from_millis(600);

fn err(e: uiautomation::Error) -> String {
    e.to_string()
}

fn role_of(ct: ControlType) -> String {
    match ct {
        ControlType::Hyperlink => "link".into(),
        ControlType::TabItem => "tab".into(),
        ControlType::RadioButton => "radio".into(),
        ControlType::Spinner => "spinbutton".into(),
        ControlType::DataItem => "cell".into(),
        other => format!("{other:?}").to_lowercase(),
    }
}

fn rect_of(r: uiautomation::types::Rect) -> Rect {
    Rect::new(
        r.get_left() as f64,
        r.get_top() as f64,
        r.get_width() as f64,
        r.get_height() as f64,
    )
}

fn foreground() -> Result<Handle, String> {
    let hwnd = unsafe { GetForegroundWindow() };
    if hwnd.is_null() {
        return Err("no foreground window".into());
    }
    Ok(Handle::from(hwnd as isize))
}

pub fn snapshot(_monitors: &[MonitorInfo]) -> Result<UiSnapshot, String> {
    let started = Instant::now();
    let auto = UIAutomation::new().map_err(err)?;
    let root = auto.element_from_handle(foreground()?).map_err(err)?;
    let window_title = root.get_name().unwrap_or_default();

    let cache = auto.create_cache_request().map_err(err)?;
    for p in [
        UIProperty::Name,
        UIProperty::ControlType,
        UIProperty::BoundingRectangle,
        UIProperty::IsEnabled,
    ] {
        cache.add_property(p).map_err(err)?;
    }
    let on_screen = auto
        .create_property_condition(UIProperty::IsOffscreen, Variant::from(false), None)
        .map_err(err)?;
    let condition = auto
        .create_and_condition(auto.get_control_view_condition().map_err(err)?, on_screen)
        .map_err(err)?;
    let found = root
        .find_all_build_cache(TreeScope::Descendants, &condition, &cache)
        .map_err(err)?;

    let mut elements = Vec::with_capacity(found.len().min(MAX_ELEMENTS * 2));
    for e in found.iter() {
        if elements.len() >= MAX_ELEMENTS * 2 || started.elapsed() > BUDGET {
            break;
        }
        if !e.is_cached_enabled().unwrap_or(true) {
            continue;
        }
        let Ok(r) = e.get_cached_bounding_rectangle() else {
            continue;
        };
        elements.push(UiElement {
            role: e.get_cached_control_type().map(role_of).unwrap_or_default(),
            name: e.get_cached_name().unwrap_or_default(),
            rect: rect_of(r),
        });
    }

    Ok(UiSnapshot {
        app_name: String::new(), // filled from the window list by the caller
        window_title,
        elements,
        secure_field_focused: focused_is_password(&auto),
    })
}

fn focused_is_password(auto: &UIAutomation) -> bool {
    auto.get_focused_element()
        .and_then(|e: UIElement| e.is_password())
        .unwrap_or(false)
}

pub fn secure_field_focused() -> Result<bool, String> {
    let auto = UIAutomation::new().map_err(err)?;
    Ok(focused_is_password(&auto))
}

pub fn element_at(x: f64, y: f64, _monitors: &[MonitorInfo]) -> Result<Option<UiElement>, String> {
    let auto = UIAutomation::new().map_err(err)?;
    let e = auto
        .element_from_point(UiaPoint::new(x as i32, y as i32))
        .map_err(err)?;
    Ok(Some(UiElement {
        role: e.get_control_type().map(role_of).unwrap_or_default(),
        name: e.get_name().unwrap_or_default(),
        rect: e.get_bounding_rectangle().map(rect_of).unwrap_or_default(),
    }))
}

pub fn foreground_is_fullscreen(monitors: &[MonitorInfo]) -> Result<bool, String> {
    let hwnd = unsafe { GetForegroundWindow() };
    if hwnd.is_null() {
        return Ok(false);
    }
    let mut class = [0u16; 64];
    let n = unsafe { GetClassNameW(hwnd, class.as_mut_ptr(), class.len() as i32) };
    let class = String::from_utf16_lossy(&class[..n.max(0) as usize]);
    if matches!(class.as_str(), "Progman" | "WorkerW" | "Shell_TrayWnd") {
        return Ok(false); // the desktop itself covers the screen
    }
    let mut r = RECT {
        left: 0,
        top: 0,
        right: 0,
        bottom: 0,
    };
    if unsafe { GetWindowRect(hwnd, &mut r) } == 0 {
        return Ok(false);
    }
    let w = Rect::new(
        r.left as f64,
        r.top as f64,
        (r.right - r.left) as f64,
        (r.bottom - r.top) as f64,
    );
    Ok(monitors.iter().any(|m| covers(&w, &m.bounds)))
}

fn covers(window: &Rect, monitor: &Rect) -> bool {
    window.x <= monitor.x
        && window.y <= monitor.y
        && window.x + window.w >= monitor.x + monitor.w
        && window.y + window.h >= monitor.y + monitor.h
}

pub fn has_permission() -> bool {
    true
}
