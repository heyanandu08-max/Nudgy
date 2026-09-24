//! macOS Accessibility (AXUIElement). Needs the Accessibility permission
//! (System Settings → Privacy & Security → Accessibility). AX geometry is in points with a
//! top-left origin on the primary display; converted to screen space via geometry.rs.

use std::ffi::c_void;
use std::ptr;
use std::time::{Duration, Instant};

use accessibility_sys::{
    kAXChildrenAttribute, kAXDescriptionAttribute, kAXEnabledAttribute, kAXErrorSuccess,
    kAXFocusedApplicationAttribute, kAXFocusedUIElementAttribute, kAXFocusedWindowAttribute,
    kAXPositionAttribute, kAXRoleAttribute, kAXSecureTextFieldSubrole, kAXSizeAttribute,
    kAXSubroleAttribute, kAXTitleAttribute, kAXValueAttribute, kAXValueTypeCGPoint,
    kAXValueTypeCGSize, AXIsProcessTrusted, AXUIElementCopyAttributeValue,
    AXUIElementCopyElementAtPosition, AXUIElementCreateSystemWide, AXUIElementRef,
    AXUIElementSetMessagingTimeout, AXValueGetValue, AXValueRef,
};
use core_foundation::array::{CFArray, CFArrayRef};
use core_foundation::base::{CFType, CFTypeRef, TCFType};
use core_foundation::boolean::CFBoolean;
use core_foundation::string::CFString;

use super::{UiElement, UiSnapshot, MAX_ELEMENTS};
use crate::geometry::{self, MonitorInfo, Point, Rect};

const BUDGET: Duration = Duration::from_millis(600);
const MAX_DEPTH: usize = 30;
const MAX_VISITED: usize = 3000;

#[repr(C)]
#[derive(Default)]
struct CGPoint {
    x: f64,
    y: f64,
}

#[repr(C)]
#[derive(Default)]
struct CGSize {
    width: f64,
    height: f64,
}

/// An owned (+1) AX element or other CF object.
struct Ax(CFType);

impl Ax {
    fn system_wide() -> Ax {
        // SAFETY: returns a +1 reference we take ownership of.
        Ax(unsafe { CFType::wrap_under_create_rule(AXUIElementCreateSystemWide() as CFTypeRef) })
    }

    fn raw(&self) -> AXUIElementRef {
        self.0.as_CFTypeRef() as AXUIElementRef
    }

    fn attr(&self, name: &str) -> Option<CFType> {
        let key = CFString::new(name);
        let mut value: CFTypeRef = ptr::null();
        // SAFETY: key and element are valid; on success `value` is +1 and owned by us.
        let err = unsafe {
            AXUIElementCopyAttributeValue(self.raw(), key.as_concrete_TypeRef(), &mut value)
        };
        if err != kAXErrorSuccess || value.is_null() {
            return None;
        }
        Some(unsafe { CFType::wrap_under_create_rule(value) })
    }

    fn element(&self, name: &str) -> Option<Ax> {
        self.attr(name).map(Ax)
    }

    fn string(&self, name: &str) -> Option<String> {
        self.attr(name)?
            .downcast::<CFString>()
            .map(|s| s.to_string())
    }

    fn boolean(&self, name: &str) -> Option<bool> {
        self.attr(name)?.downcast::<CFBoolean>().map(bool::from)
    }

    fn children(&self) -> Vec<Ax> {
        let Some(v) = self.attr(kAXChildrenAttribute) else {
            return Vec::new();
        };
        // SAFETY: AXChildren is a CFArray of AXUIElements; get-rule retains it for `arr`.
        let arr: CFArray<CFType> =
            unsafe { CFArray::wrap_under_get_rule(v.as_CFTypeRef() as CFArrayRef) };
        arr.iter().map(|c| Ax(c.clone())).collect()
    }

    /// Frame in AX points (top-left origin).
    fn frame(&self) -> Option<Rect> {
        let pos = self.attr(kAXPositionAttribute)?;
        let size = self.attr(kAXSizeAttribute)?;
        let mut p = CGPoint::default();
        let mut s = CGSize::default();
        // SAFETY: AXPosition/AXSize hold AXValues of the requested types.
        let ok = unsafe {
            AXValueGetValue(
                pos.as_CFTypeRef() as AXValueRef,
                kAXValueTypeCGPoint,
                &mut p as *mut _ as *mut c_void,
            ) && AXValueGetValue(
                size.as_CFTypeRef() as AXValueRef,
                kAXValueTypeCGSize,
                &mut s as *mut _ as *mut c_void,
            )
        };
        ok.then(|| Rect::new(p.x, p.y, s.width, s.height))
    }

    fn role(&self) -> String {
        self.string(kAXRoleAttribute).unwrap_or_default()
    }

    fn is_secure(&self) -> bool {
        self.role() == kAXSecureTextFieldSubrole
            || self.string(kAXSubroleAttribute).as_deref() == Some(kAXSecureTextFieldSubrole)
    }

    fn name(&self, role: &str) -> String {
        for key in [kAXTitleAttribute, kAXDescriptionAttribute] {
            if let Some(s) = self.string(key).filter(|s| !s.trim().is_empty()) {
                return s;
            }
        }
        // Static text and some buttons carry their label in AXValue; never read field values
        // (user content) — only labels.
        if matches!(
            role,
            "AXStaticText" | "AXButton" | "AXMenuButton" | "AXPopUpButton"
        ) {
            if let Some(s) = self.string(kAXValueAttribute) {
                return s;
            }
        }
        String::new()
    }
}

fn normalize_role(ax_role: &str) -> String {
    match ax_role {
        "AXTextField" | "AXSearchField" => "textfield".into(),
        "AXTextArea" => "edit".into(),
        "AXPopUpButton" => "popupbutton".into(),
        "AXMenuButton" => "button".into(),
        "AXCheckBox" => "checkbox".into(),
        "AXRadioButton" => "radio".into(),
        "AXStaticText" => "text".into(),
        "AXRow" => "listitem".into(),
        "AXDisclosureTriangle" => "button".into(),
        other => other.trim_start_matches("AX").to_lowercase(),
    }
}

fn focused_app(system: &Ax) -> Result<Ax, String> {
    let app = system
        .element(kAXFocusedApplicationAttribute)
        .ok_or("no focused application")?;
    // Don't let a hung app stall the ask pipeline.
    unsafe { AXUIElementSetMessagingTimeout(app.raw(), 0.25) };
    Ok(app)
}

pub fn snapshot(monitors: &[MonitorInfo]) -> Result<UiSnapshot, String> {
    if !has_permission() {
        return Err("accessibility permission not granted".into());
    }
    let started = Instant::now();
    let system = Ax::system_wide();
    let app = focused_app(&system)?;
    let app_name = app.string(kAXTitleAttribute).unwrap_or_default();
    let window = app
        .element(kAXFocusedWindowAttribute)
        .ok_or("no focused window")?;
    let window_title = window.string(kAXTitleAttribute).unwrap_or_default();

    let mut elements = Vec::new();
    let mut stack = vec![(window, 0usize)];
    let mut visited = 0;
    while let Some((el, depth)) = stack.pop() {
        visited += 1;
        if visited > MAX_VISITED || elements.len() >= MAX_ELEMENTS * 2 || started.elapsed() > BUDGET
        {
            break;
        }
        let role = el.role();
        if el.boolean(kAXEnabledAttribute) != Some(false) {
            if let Some(frame) = el.frame() {
                elements.push(UiElement {
                    role: normalize_role(&role),
                    name: el.name(&role),
                    rect: geometry::mac_ax_to_screen(&frame, monitors),
                });
            }
        }
        if depth < MAX_DEPTH {
            // Reverse so the depth-first walk visits children in on-screen order.
            let kids = el.children();
            stack.extend(kids.into_iter().rev().map(|k| (k, depth + 1)));
        }
    }

    let secure_field_focused = app
        .element(kAXFocusedUIElementAttribute)
        .is_some_and(|f| f.is_secure());
    Ok(UiSnapshot {
        app_name,
        window_title,
        elements,
        secure_field_focused,
    })
}

pub fn secure_field_focused() -> Result<bool, String> {
    if !has_permission() {
        return Ok(false);
    }
    let system = Ax::system_wide();
    let app = focused_app(&system)?;
    Ok(app
        .element(kAXFocusedUIElementAttribute)
        .is_some_and(|f| f.is_secure()))
}

pub fn element_at(x: f64, y: f64, monitors: &[MonitorInfo]) -> Result<Option<UiElement>, String> {
    if !has_permission() {
        return Ok(None);
    }
    let p = geometry::screen_to_mac_ax(Point::new(x, y), monitors);
    let system = Ax::system_wide();
    let mut hit: AXUIElementRef = ptr::null_mut();
    // SAFETY: on success `hit` is a +1 element we take ownership of.
    let err =
        unsafe { AXUIElementCopyElementAtPosition(system.raw(), p.x as f32, p.y as f32, &mut hit) };
    if err != kAXErrorSuccess || hit.is_null() {
        return Ok(None);
    }
    let el = Ax(unsafe { CFType::wrap_under_create_rule(hit as CFTypeRef) });
    let role = el.role();
    Ok(Some(UiElement {
        role: normalize_role(&role),
        name: el.name(&role),
        rect: el
            .frame()
            .map(|f| geometry::mac_ax_to_screen(&f, monitors))
            .unwrap_or_default(),
    }))
}

pub fn foreground_is_fullscreen(monitors: &[MonitorInfo]) -> Result<bool, String> {
    if !has_permission() {
        return Ok(false);
    }
    let system = Ax::system_wide();
    let app = focused_app(&system)?;
    let Some(window) = app.element(kAXFocusedWindowAttribute) else {
        return Ok(false);
    };
    if window.boolean("AXFullScreen") == Some(true) {
        return Ok(true);
    }
    let Some(frame) = window.frame() else {
        return Ok(false);
    };
    Ok(monitors.iter().any(|m| {
        let b = m.logical_bounds();
        frame.x <= b.x
            && frame.y <= b.y
            && frame.x + frame.w >= b.x + b.w
            && frame.y + frame.h >= b.y + b.h
    }))
}

pub fn has_permission() -> bool {
    // SAFETY: no arguments; reads the TCC state for this process.
    unsafe { AXIsProcessTrusted() }
}
