//! Linux and other targets: not a v1 platform. Returns empty data so the rest of the app
//! (and CI) still runs; the LLM falls back to pointing by screenshot pixels.

use super::{UiElement, UiSnapshot};
use crate::geometry::MonitorInfo;

pub fn snapshot(_monitors: &[MonitorInfo]) -> Result<UiSnapshot, String> {
    Ok(UiSnapshot::default())
}

pub fn secure_field_focused() -> Result<bool, String> {
    Ok(false)
}

pub fn element_at(
    _x: f64,
    _y: f64,
    _monitors: &[MonitorInfo],
) -> Result<Option<UiElement>, String> {
    Ok(None)
}

pub fn foreground_is_fullscreen(_monitors: &[MonitorInfo]) -> Result<bool, String> {
    Ok(false)
}

pub fn has_permission() -> bool {
    true
}
