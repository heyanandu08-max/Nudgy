//! Coordinate conversion. See PLAN.md §1 "Coordinate model" and DECISIONS.md D5.
//!
//! Canonical space ("screen space"): **physical pixels, top-left origin, virtual desktop**,
//! as reported by Tauri/tao for monitor positions and the cursor. Every rect crossing a
//! module boundary is in this space.
//!
//! Other spaces we convert from/to:
//! - *Screenshot space*: pixels of the (possibly downscaled) JPEG sent to the LLM.
//! - *Overlay space*: CSS/logical pixels inside one monitor's overlay window.
//! - *macOS AX space*: points, top-left origin at the primary display (Quartz global).
//! - *Cocoa space*: points, **bottom-left** origin at the primary display (NSScreen/NSEvent).

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, Default)]
pub struct Point {
    pub x: f64,
    pub y: f64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize, Default)]
pub struct Rect {
    pub x: f64,
    pub y: f64,
    pub w: f64,
    pub h: f64,
}

impl Point {
    pub const fn new(x: f64, y: f64) -> Self {
        Self { x, y }
    }
}

impl Rect {
    pub const fn new(x: f64, y: f64, w: f64, h: f64) -> Self {
        Self { x, y, w, h }
    }

    pub fn center(&self) -> Point {
        Point::new(self.x + self.w / 2.0, self.y + self.h / 2.0)
    }

    /// Half-open containment: the right/bottom edges belong to the next rect.
    pub fn contains(&self, p: Point) -> bool {
        p.x >= self.x && p.x < self.x + self.w && p.y >= self.y && p.y < self.y + self.h
    }

    pub fn is_empty(&self) -> bool {
        self.w <= 0.0 || self.h <= 0.0
    }

    pub fn intersects(&self, o: &Rect) -> bool {
        self.x < o.x + o.w && o.x < self.x + self.w && self.y < o.y + o.h && o.y < self.y + self.h
    }

    pub fn scale(&self, k: f64) -> Rect {
        Rect::new(self.x * k, self.y * k, self.w * k, self.h * k)
    }
}

/// One display, in screen space.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct MonitorInfo {
    /// Stable-ish identifier (index + name) used to address that monitor's overlay.
    pub id: String,
    /// Physical position and size in screen space.
    pub bounds: Rect,
    /// Physical pixels per logical point (1.0, 1.25, 1.5, 2.0 …).
    pub scale_factor: f64,
    pub is_primary: bool,
}

impl MonitorInfo {
    /// The monitor's bounds in logical points (what macOS AX and Cocoa speak).
    pub fn logical_bounds(&self) -> Rect {
        self.bounds.scale(1.0 / self.scale_factor)
    }
}

/// Metadata of a screenshot sent to the LLM.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ScreenshotMeta {
    /// Monitor bounds (screen space) the screenshot covers.
    pub source: Rect,
    /// Encoded image size in pixels.
    pub width: u32,
    pub height: u32,
}

/// Picks the monitor containing `p`; falls back to the nearest one (cursor can sit on an
/// edge pixel or in a gap between monitors of different heights).
pub fn monitor_at(p: Point, monitors: &[MonitorInfo]) -> Option<&MonitorInfo> {
    monitors.iter().find(|m| m.bounds.contains(p)).or_else(|| {
        monitors.iter().min_by(|a, b| {
            dist2_to_rect(p, &a.bounds).total_cmp(&dist2_to_rect(p, &b.bounds))
        })
    })
}

fn dist2_to_rect(p: Point, r: &Rect) -> f64 {
    let dx = (r.x - p.x).max(0.0).max(p.x - (r.x + r.w));
    let dy = (r.y - p.y).max(0.0).max(p.y - (r.y + r.h));
    dx * dx + dy * dy
}

/// Size to encode a screenshot at: at most `max_width` wide, aspect preserved, never upscaled.
pub fn screenshot_size(src_w: u32, src_h: u32, max_width: u32) -> (u32, u32) {
    if src_w <= max_width || src_w == 0 {
        return (src_w, src_h);
    }
    let h = (src_h as f64 * max_width as f64 / src_w as f64).round() as u32;
    (max_width, h.max(1))
}

/// Screenshot pixel → screen space. The LLM's `{x, y}` fallback target uses this.
pub fn screenshot_to_screen(p: Point, shot: &ScreenshotMeta) -> Point {
    let kx = shot.source.w / shot.width as f64;
    let ky = shot.source.h / shot.height as f64;
    Point::new(shot.source.x + p.x * kx, shot.source.y + p.y * ky)
}

/// Screen space rect → screenshot pixels (used to draw element boxes for the prompt).
pub fn screen_to_screenshot(r: &Rect, shot: &ScreenshotMeta) -> Rect {
    let kx = shot.width as f64 / shot.source.w;
    let ky = shot.height as f64 / shot.source.h;
    Rect::new((r.x - shot.source.x) * kx, (r.y - shot.source.y) * ky, r.w * kx, r.h * ky)
}

/// Screen space → CSS pixels inside the overlay window that covers `monitor`.
pub fn screen_to_overlay(r: &Rect, monitor: &MonitorInfo) -> Rect {
    let s = monitor.scale_factor;
    Rect::new((r.x - monitor.bounds.x) / s, (r.y - monitor.bounds.y) / s, r.w / s, r.h / s)
}

pub fn screen_point_to_overlay(p: Point, monitor: &MonitorInfo) -> Point {
    let s = monitor.scale_factor;
    Point::new((p.x - monitor.bounds.x) / s, (p.y - monitor.bounds.y) / s)
}

/// macOS AX rect (points, top-left of primary display) → screen space.
///
/// tao reports a macOS monitor's physical position as its Quartz point origin times that
/// monitor's own scale factor, so we find the monitor in *point* space and apply its scale.
pub fn mac_ax_to_screen(r: &Rect, monitors: &[MonitorInfo]) -> Rect {
    let centre = r.center();
    let hit = monitors
        .iter()
        .find(|m| m.logical_bounds().contains(centre))
        .or_else(|| {
            monitors.iter().min_by(|a, b| {
                dist2_to_rect(centre, &a.logical_bounds())
                    .total_cmp(&dist2_to_rect(centre, &b.logical_bounds()))
            })
        });
    match hit {
        Some(m) => r.scale(m.scale_factor),
        None => *r,
    }
}

/// Cocoa rect (points, bottom-left origin of primary display) → AX/Quartz (top-left).
pub fn cocoa_to_ax(r: &Rect, primary_height_points: f64) -> Rect {
    Rect::new(r.x, primary_height_points - r.y - r.h, r.w, r.h)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn mon(id: &str, x: f64, y: f64, w: f64, h: f64, s: f64, primary: bool) -> MonitorInfo {
        MonitorInfo { id: id.into(), bounds: Rect::new(x, y, w, h), scale_factor: s, is_primary: primary }
    }

    fn approx(a: Point, b: Point) {
        assert!((a.x - b.x).abs() < 0.51 && (a.y - b.y).abs() < 0.51, "{a:?} != {b:?}");
    }

    fn approx_rect(a: Rect, b: Rect) {
        for (u, v) in [(a.x, b.x), (a.y, b.y), (a.w, b.w), (a.h, b.h)] {
            assert!((u - v).abs() < 0.51, "{a:?} != {b:?}");
        }
    }

    #[test]
    fn screenshot_size_caps_width_and_keeps_aspect() {
        assert_eq!(screenshot_size(2560, 1440, 1280), (1280, 720));
        assert_eq!(screenshot_size(1920, 1200, 1280), (1280, 800));
        assert_eq!(screenshot_size(1024, 768, 1280), (1024, 768));
        assert_eq!(screenshot_size(3840, 2160, 1280), (1280, 720));
    }

    #[test]
    fn dpi_100_percent_round_trip() {
        let m = mon("0", 0.0, 0.0, 1920.0, 1080.0, 1.0, true);
        let (w, h) = screenshot_size(1920, 1080, 1280);
        let shot = ScreenshotMeta { source: m.bounds, width: w, height: h };
        let p = screenshot_to_screen(Point::new(640.0, 360.0), &shot);
        approx(p, Point::new(960.0, 540.0));
        approx(screen_point_to_overlay(p, &m), Point::new(960.0, 540.0));
    }

    #[test]
    fn dpi_125_percent() {
        // 1920x1080 physical at 125% → 1536x864 CSS px overlay.
        let m = mon("0", 0.0, 0.0, 1920.0, 1080.0, 1.25, true);
        let shot = ScreenshotMeta { source: m.bounds, width: 1280, height: 720 };
        let p = screenshot_to_screen(Point::new(1280.0, 720.0), &shot);
        approx(p, Point::new(1920.0, 1080.0));
        approx(screen_point_to_overlay(p, &m), Point::new(1536.0, 864.0));
        let r = screen_to_overlay(&Rect::new(100.0, 50.0, 250.0, 125.0), &m);
        approx_rect(r, Rect::new(80.0, 40.0, 200.0, 100.0));
    }

    #[test]
    fn dpi_150_percent() {
        let m = mon("0", 0.0, 0.0, 2880.0, 1620.0, 1.5, true);
        let shot = ScreenshotMeta { source: m.bounds, width: 1280, height: 720 };
        let p = screenshot_to_screen(Point::new(100.0, 100.0), &shot);
        approx(p, Point::new(225.0, 225.0));
        approx(screen_point_to_overlay(p, &m), Point::new(150.0, 150.0));
    }

    #[test]
    fn retina_2x() {
        // MacBook: 1512x982 points, 3024x1964 physical.
        let m = mon("0", 0.0, 0.0, 3024.0, 1964.0, 2.0, true);
        let ax = Rect::new(100.0, 40.0, 60.0, 20.0);
        let screen = mac_ax_to_screen(&ax, std::slice::from_ref(&m));
        approx_rect(screen, Rect::new(200.0, 80.0, 120.0, 40.0));
        approx_rect(screen_to_overlay(&screen, &m), ax);
    }

    #[test]
    fn dual_monitor_side_by_side_mixed_dpi() {
        let left = mon("0", 0.0, 0.0, 1920.0, 1080.0, 1.0, true);
        let right = mon("1", 1920.0, 0.0, 2880.0, 1620.0, 1.5, false);
        let ms = [left.clone(), right.clone()];
        let p = Point::new(2000.0, 100.0);
        assert_eq!(monitor_at(p, &ms).unwrap().id, "1");
        approx(screen_point_to_overlay(p, &right), Point::new(80.0 / 1.5, 100.0 / 1.5));

        let shot = ScreenshotMeta { source: right.bounds, width: 1280, height: 720 };
        approx(screenshot_to_screen(Point::new(0.0, 0.0), &shot), Point::new(1920.0, 0.0));
        approx(screenshot_to_screen(Point::new(640.0, 360.0), &shot), Point::new(3360.0, 810.0));
    }

    #[test]
    fn negative_offsets_monitor_left_and_above() {
        let primary = mon("0", 0.0, 0.0, 1920.0, 1080.0, 1.0, true);
        let left = mon("1", -2560.0, -360.0, 2560.0, 1440.0, 1.0, false);
        let ms = [primary, left.clone()];
        let p = Point::new(-1280.0, 0.0);
        assert_eq!(monitor_at(p, &ms).unwrap().id, "1");
        approx(screen_point_to_overlay(p, &left), Point::new(1280.0, 360.0));
        let shot = ScreenshotMeta { source: left.bounds, width: 1280, height: 720 };
        approx(screenshot_to_screen(Point::new(0.0, 0.0), &shot), Point::new(-2560.0, -360.0));
        approx(screenshot_to_screen(Point::new(640.0, 180.0), &shot), Point::new(-1280.0, 0.0));
        let back = screen_to_screenshot(&Rect::new(-1280.0, 0.0, 20.0, 20.0), &shot);
        approx_rect(back, Rect::new(640.0, 180.0, 10.0, 10.0));
    }

    #[test]
    fn point_in_gap_falls_back_to_nearest_monitor() {
        // Two monitors of different heights leave a dead zone under the smaller one.
        let a = mon("0", 0.0, 0.0, 1920.0, 1080.0, 1.0, true);
        let b = mon("1", 1920.0, 0.0, 2560.0, 1440.0, 1.0, false);
        let ms = [a, b];
        assert_eq!(monitor_at(Point::new(1000.0, 1300.0), &ms).unwrap().id, "0");
        assert_eq!(monitor_at(Point::new(1920.0, 5.0), &ms).unwrap().id, "1");
    }

    #[test]
    fn macos_origin_flip() {
        // Primary display 1512 points tall; a 100x20 rect whose Cocoa origin is y=900.
        let cocoa = Rect::new(10.0, 900.0, 100.0, 20.0);
        let ax = cocoa_to_ax(&cocoa, 982.0);
        approx_rect(ax, Rect::new(10.0, 62.0, 100.0, 20.0));
        // Flipping twice is the identity.
        approx_rect(cocoa_to_ax(&ax, 982.0), cocoa);
    }

    #[test]
    fn macos_secondary_display_above_and_left_mixed_scale() {
        // Retina primary (2x) + external 1x monitor above-left at negative Quartz coords.
        let primary = mon("0", 0.0, 0.0, 3024.0, 1964.0, 2.0, true);
        let ext = mon("1", -1920.0, -1080.0, 1920.0, 1080.0, 1.0, false);
        let ms = [primary, ext.clone()];
        let ax = Rect::new(-1000.0, -500.0, 50.0, 30.0);
        let screen = mac_ax_to_screen(&ax, &ms);
        approx_rect(screen, ax); // 1x monitor: points == pixels
        approx_rect(screen_to_overlay(&screen, &ext), Rect::new(920.0, 580.0, 50.0, 30.0));

        let on_primary = mac_ax_to_screen(&Rect::new(10.0, 10.0, 10.0, 10.0), &ms);
        approx_rect(on_primary, Rect::new(20.0, 20.0, 20.0, 20.0));
    }

    #[test]
    fn rect_helpers() {
        let r = Rect::new(0.0, 0.0, 10.0, 10.0);
        assert!(r.contains(Point::new(0.0, 0.0)));
        assert!(!r.contains(Point::new(10.0, 5.0)));
        assert!(r.intersects(&Rect::new(9.0, 9.0, 5.0, 5.0)));
        assert!(!r.intersects(&Rect::new(10.0, 0.0, 5.0, 5.0)));
        assert!(Rect::new(0.0, 0.0, 0.0, 5.0).is_empty());
        assert_eq!(r.center(), Point::new(5.0, 5.0));
    }
}
