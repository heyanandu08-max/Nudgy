//! On-demand screenshot of one monitor, downscaled to ≤1280 px wide and JPEG-encoded in
//! memory. Nothing is ever written to disk.

use std::io::Cursor;

use image::codecs::jpeg::JpegEncoder;
use image::imageops::FilterType;
use image::DynamicImage;

use crate::geometry::{self, MonitorInfo, Rect, ScreenshotMeta};

pub const MAX_WIDTH: u32 = 1280;
pub const JPEG_QUALITY: u8 = 80;

pub struct Screenshot {
    pub jpeg: Vec<u8>,
    pub meta: ScreenshotMeta,
}

/// xcap reports monitor geometry in physical pixels on Windows but in points on macOS.
/// Match against Tauri's monitor (physical) by trying both interpretations.
pub fn best_match(target: &Rect, candidates: &[(Rect, f64)]) -> Option<usize> {
    let dist = |r: &Rect| {
        (r.x - target.x).abs()
            + (r.y - target.y).abs()
            + (r.w - target.w).abs()
            + (r.h - target.h).abs()
    };
    candidates
        .iter()
        .enumerate()
        .map(|(i, (r, scale))| (i, dist(r).min(dist(&r.scale(*scale)))))
        .min_by(|a, b| a.1.total_cmp(&b.1))
        .map(|(i, _)| i)
}

pub fn capture_monitor(monitor: &MonitorInfo) -> Result<Screenshot, String> {
    let monitors = xcap::Monitor::all().map_err(|e| format!("list monitors: {e}"))?;
    let candidates: Vec<(Rect, f64)> = monitors
        .iter()
        .map(|m| {
            let r = Rect::new(
                m.x().unwrap_or(0) as f64,
                m.y().unwrap_or(0) as f64,
                m.width().unwrap_or(0) as f64,
                m.height().unwrap_or(0) as f64,
            );
            (r, m.scale_factor().unwrap_or(1.0) as f64)
        })
        .collect();
    let idx = best_match(&monitor.bounds, &candidates).ok_or("no monitor to capture")?;
    let img = monitors[idx]
        .capture_image()
        .map_err(|e| format!("capture: {e}"))?;
    encode(DynamicImage::ImageRgba8(img), monitor.bounds)
}

pub fn encode(img: DynamicImage, source: Rect) -> Result<Screenshot, String> {
    encode_sized(img, source, MAX_WIDTH, JPEG_QUALITY)
}

/// Small JPEG of one monitor for walkthrough step thumbnails, as a data URL.
pub fn thumbnail_data_url(monitor: &MonitorInfo) -> Result<String, String> {
    use base64::Engine as _;
    let monitors = xcap::Monitor::all().map_err(|e| format!("list monitors: {e}"))?;
    let candidates: Vec<(Rect, f64)> = monitors
        .iter()
        .map(|m| {
            let r = Rect::new(
                m.x().unwrap_or(0) as f64,
                m.y().unwrap_or(0) as f64,
                m.width().unwrap_or(0) as f64,
                m.height().unwrap_or(0) as f64,
            );
            (r, m.scale_factor().unwrap_or(1.0) as f64)
        })
        .collect();
    let idx = best_match(&monitor.bounds, &candidates).ok_or("no monitor to capture")?;
    let img = monitors[idx]
        .capture_image()
        .map_err(|e| format!("capture: {e}"))?;
    let shot = encode_sized(DynamicImage::ImageRgba8(img), monitor.bounds, 640, 70)?;
    Ok(format!(
        "data:image/jpeg;base64,{}",
        base64::engine::general_purpose::STANDARD.encode(shot.jpeg)
    ))
}

fn encode_sized(
    img: DynamicImage,
    source: Rect,
    max_width: u32,
    quality: u8,
) -> Result<Screenshot, String> {
    let (w, h) = geometry::screenshot_size(img.width(), img.height(), max_width);
    let img = if (w, h) == (img.width(), img.height()) {
        img
    } else {
        img.resize_exact(w, h, FilterType::Triangle)
    };
    let rgb = img.to_rgb8();
    let mut jpeg = Vec::with_capacity((w * h / 4) as usize);
    JpegEncoder::new_with_quality(Cursor::new(&mut jpeg), quality)
        .encode_image(&rgb)
        .map_err(|e| format!("jpeg: {e}"))?;
    Ok(Screenshot {
        jpeg,
        meta: ScreenshotMeta {
            source,
            width: w,
            height: h,
        },
    })
}

/// Name and title of the focused top-level window (cross-platform via xcap).
pub fn foreground_window() -> Option<(String, String)> {
    xcap::Window::all()
        .ok()?
        .into_iter()
        .find(|w| w.is_focused().unwrap_or(false))
        .map(|w| {
            (
                w.app_name().unwrap_or_default(),
                w.title().unwrap_or_default(),
            )
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use image::{Rgba, RgbaImage};

    #[test]
    fn matches_physical_windows_monitor() {
        let target = Rect::new(1920.0, 0.0, 2560.0, 1440.0);
        let cands = [
            (Rect::new(0.0, 0.0, 1920.0, 1080.0), 1.0),
            (Rect::new(1920.0, 0.0, 2560.0, 1440.0), 1.0),
        ];
        assert_eq!(best_match(&target, &cands), Some(1));
    }

    #[test]
    fn matches_macos_point_monitor_by_scale() {
        // Tauri: Retina primary is 3024x1964 physical; xcap reports 1512x982 points @2x.
        let target = Rect::new(0.0, 0.0, 3024.0, 1964.0);
        let cands = [
            (Rect::new(1512.0, 0.0, 1920.0, 1080.0), 1.0),
            (Rect::new(0.0, 0.0, 1512.0, 982.0), 2.0),
        ];
        assert_eq!(best_match(&target, &cands), Some(1));
    }

    #[test]
    fn encode_downscales_to_max_width_as_jpeg() {
        let img = RgbaImage::from_pixel(2560, 1440, Rgba([200, 100, 50, 255]));
        let shot = encode(
            DynamicImage::ImageRgba8(img),
            Rect::new(0.0, 0.0, 2560.0, 1440.0),
        )
        .unwrap();
        assert_eq!((shot.meta.width, shot.meta.height), (1280, 720));
        assert_eq!(&shot.jpeg[..2], &[0xFF, 0xD8]); // JPEG SOI marker
        let decoded = image::load_from_memory(&shot.jpeg).unwrap();
        assert_eq!((decoded.width(), decoded.height()), (1280, 720));
    }

    #[test]
    fn encode_keeps_small_images() {
        let img = RgbaImage::from_pixel(800, 600, Rgba([0, 0, 0, 255]));
        let shot = encode(
            DynamicImage::ImageRgba8(img),
            Rect::new(0.0, 0.0, 800.0, 600.0),
        )
        .unwrap();
        assert_eq!((shot.meta.width, shot.meta.height), (800, 600));
    }
}
