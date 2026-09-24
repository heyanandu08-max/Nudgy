//! Foreground-window UI element snapshot: Windows UI Automation / macOS Accessibility.
//!
//! Every platform returns rects in screen space (physical px, top-left, virtual desktop);
//! see geometry.rs. Elements are pruned to visible, enabled, non-zero-size ones inside a
//! monitor, capped at `MAX_ELEMENTS`.

use serde::Serialize;

use crate::geometry::{MonitorInfo, Rect};

#[cfg(target_os = "macos")]
mod macos;
#[cfg(not(any(target_os = "windows", target_os = "macos")))]
mod stub;
#[cfg(target_os = "windows")]
mod windows;

#[cfg(target_os = "macos")]
use macos as platform;
#[cfg(not(any(target_os = "windows", target_os = "macos")))]
use stub as platform;
#[cfg(target_os = "windows")]
use windows as platform;

pub const MAX_ELEMENTS: usize = 300;

#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct UiElement {
    pub role: String,
    pub name: String,
    /// Screen space.
    pub rect: Rect,
}

#[derive(Debug, Clone, Default, Serialize)]
pub struct UiSnapshot {
    pub app_name: String,
    pub window_title: String,
    pub elements: Vec<UiElement>,
    /// A password / secure text field has keyboard focus: never capture in this state.
    pub secure_field_focused: bool,
}

/// Snapshot of the foreground window. Never fails hard: missing permissions or an
/// uncooperative app yield an empty element list (the LLM then points by pixel).
pub fn snapshot(monitors: &[MonitorInfo]) -> UiSnapshot {
    let mut snap = platform::snapshot(monitors).unwrap_or_else(|e| {
        log::warn!("ui tree unavailable: {e}");
        UiSnapshot::default()
    });
    snap.elements = prune(std::mem::take(&mut snap.elements), monitors);
    snap
}

/// Whether a password field is focused right now (cheap; used before any capture).
pub fn secure_field_focused() -> bool {
    platform::secure_field_focused().unwrap_or(false)
}

/// Topmost element under a screen-space point (for walkthrough recording).
pub fn element_at(x: f64, y: f64, monitors: &[MonitorInfo]) -> Option<UiElement> {
    platform::element_at(x, y, monitors).ok().flatten()
}

/// Whether the foreground window covers its whole monitor (games, videos, slideshows).
pub fn foreground_is_fullscreen(monitors: &[MonitorInfo]) -> bool {
    platform::foreground_is_fullscreen(monitors).unwrap_or(false)
}

/// Whether this process may read other apps' UI (macOS Accessibility permission).
pub fn has_permission() -> bool {
    platform::has_permission()
}

/// Drops zero-size, off-monitor, unnamed-and-uninteresting and duplicate elements, then caps.
pub fn prune(elements: Vec<UiElement>, monitors: &[MonitorInfo]) -> Vec<UiElement> {
    let mut out: Vec<UiElement> = Vec::with_capacity(elements.len().min(MAX_ELEMENTS));
    for mut e in elements {
        if e.rect.w < 2.0 || e.rect.h < 2.0 {
            continue;
        }
        if !monitors.is_empty() && !monitors.iter().any(|m| m.bounds.intersects(&e.rect)) {
            continue;
        }
        e.name = e.name.split_whitespace().collect::<Vec<_>>().join(" ");
        if e.name.chars().count() > 120 {
            e.name = e.name.chars().take(117).collect::<String>() + "...";
        }
        if e.name.is_empty() && !is_interactive(&e.role) {
            continue;
        }
        if out
            .iter()
            .any(|o| o.rect == e.rect && o.role == e.role && o.name == e.name)
        {
            continue;
        }
        out.push(e);
        if out.len() == MAX_ELEMENTS {
            break;
        }
    }
    out
}

/// Normalized, platform-independent roles (lower-case, like ARIA).
pub fn is_interactive(role: &str) -> bool {
    matches!(
        role,
        "button"
            | "checkbox"
            | "combobox"
            | "edit"
            | "textfield"
            | "link"
            | "menuitem"
            | "tab"
            | "radio"
            | "slider"
            | "listitem"
            | "treeitem"
            | "menu"
            | "spinbutton"
            | "splitbutton"
            | "cell"
            | "switch"
            | "popupbutton"
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    fn el(role: &str, name: &str, x: f64, y: f64, w: f64, h: f64) -> UiElement {
        UiElement {
            role: role.into(),
            name: name.into(),
            rect: Rect::new(x, y, w, h),
        }
    }

    fn monitor() -> MonitorInfo {
        MonitorInfo {
            id: "0".into(),
            bounds: Rect::new(0.0, 0.0, 1920.0, 1080.0),
            scale_factor: 1.0,
            is_primary: true,
        }
    }

    #[test]
    fn prune_drops_tiny_offscreen_duplicates_and_anonymous_containers() {
        let input = vec![
            el("button", "Bold", 10.0, 10.0, 20.0, 20.0),
            el("button", "Bold", 10.0, 10.0, 20.0, 20.0), // duplicate
            el("button", "Zero", 10.0, 10.0, 0.0, 20.0),  // zero width
            el("button", "Far", 5000.0, 10.0, 20.0, 20.0), // off every monitor
            el("group", "", 0.0, 0.0, 500.0, 500.0),      // anonymous container
            el("edit", "", 50.0, 50.0, 200.0, 20.0),      // anonymous but interactive
            el("text", "  Font   size  ", 0.0, 0.0, 50.0, 10.0),
        ];
        let out = prune(input, &[monitor()]);
        let names: Vec<_> = out
            .iter()
            .map(|e| (e.role.as_str(), e.name.as_str()))
            .collect();
        assert_eq!(
            names,
            vec![("button", "Bold"), ("edit", ""), ("text", "Font size")]
        );
    }

    #[test]
    fn prune_caps_and_truncates() {
        let many: Vec<_> = (0..500)
            .map(|i| el("button", &format!("b{i}"), i as f64, 0.0, 5.0, 5.0))
            .collect();
        assert_eq!(prune(many, &[monitor()]).len(), MAX_ELEMENTS);
        let long = "x".repeat(300);
        let out = prune(vec![el("text", &long, 0.0, 0.0, 5.0, 5.0)], &[monitor()]);
        assert_eq!(out[0].name.chars().count(), 120);
    }
}
