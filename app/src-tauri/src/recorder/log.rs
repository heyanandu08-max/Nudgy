//! Builds the raw walkthrough log from clicks and key events (pure; unit-tested).

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use super::keys::KeyEvent;

/// Typing pauses longer than this end a "type" step.
pub const TYPING_IDLE: Duration = Duration::from_millis(1500);
pub const HIDDEN: &str = "[hidden]";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct Target {
    pub role: String,
    pub name: String,
}

/// Mirrors `RawStep` in backend/app/schemas/walkthrough.py.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct RawStep {
    pub kind: String, // click | type | shortcut | key
    pub target: Option<Target>,
    pub text: Option<String>,
    pub keys: Option<String>,
    pub app: String,
    pub window: String,
    pub note: Option<String>,
}

impl RawStep {
    fn new(kind: &str, app: &str, window: &str) -> Self {
        RawStep {
            kind: kind.into(),
            target: None,
            text: None,
            keys: None,
            app: app.into(),
            window: window.into(),
            note: None,
        }
    }
}

/// Where input is going when a key event happens.
#[derive(Debug, Clone, Default)]
pub struct KeyContext {
    pub app: String,
    pub window: String,
    /// A password / secure field has focus: record *that* something was typed, not what.
    pub secure: bool,
}

struct Typing {
    text: String,
    hidden: bool,
    app: String,
    window: String,
    last: Instant,
}

#[derive(Default)]
pub struct LogBuilder {
    raw: Vec<RawStep>,
    shots: Vec<Option<String>>,
    typing: Option<Typing>,
    pending_note: Option<String>,
}

impl LogBuilder {
    pub fn len(&self) -> usize {
        self.raw.len() + usize::from(self.typing.is_some())
    }

    fn push(&mut self, mut step: RawStep, shot: Option<String>) {
        if let Some(n) = self.pending_note.take() {
            step.note = Some(n);
        }
        self.raw.push(step);
        self.shots.push(shot);
    }

    fn flush_typing(&mut self) {
        if let Some(t) = self.typing.take() {
            if t.hidden || !t.text.is_empty() {
                let mut s = RawStep::new("type", &t.app, &t.window);
                s.text = Some(if t.hidden { HIDDEN.into() } else { t.text });
                self.push(s, None);
            }
        }
    }

    pub fn click(&mut self, target: Option<Target>, app: &str, window: &str, shot: Option<String>) {
        let i = self.click_pending();
        self.fill_click(i, target, app, window, shot);
    }

    /// Records a click right away (keeping step order) and returns its index; details
    /// (element, app, thumbnail) are filled in later by [`fill_click`] so that slow
    /// lookups never block input polling.
    pub fn click_pending(&mut self) -> usize {
        self.flush_typing();
        self.push(RawStep::new("click", "", ""), None);
        self.raw.len() - 1
    }

    pub fn fill_click(
        &mut self,
        index: usize,
        target: Option<Target>,
        app: &str,
        window: &str,
        shot: Option<String>,
    ) {
        if let Some(s) = self.raw.get_mut(index) {
            s.target = target;
            s.app = app.into();
            s.window = window.into();
            self.shots[index] = shot;
        }
    }

    pub fn key(&mut self, ev: KeyEvent, ctx: &KeyContext, now: Instant) {
        match ev {
            KeyEvent::Char(c) => {
                let t = self.typing.get_or_insert_with(|| Typing {
                    text: String::new(),
                    hidden: false,
                    app: ctx.app.clone(),
                    window: ctx.window.clone(),
                    last: now,
                });
                t.hidden |= ctx.secure;
                if !t.hidden {
                    t.text.push(c);
                }
                t.last = now;
            }
            KeyEvent::Backspace => {
                if let Some(t) = self.typing.as_mut() {
                    t.text.pop();
                    t.last = now;
                }
            }
            KeyEvent::Named(k) => {
                self.flush_typing();
                let mut s = RawStep::new("key", &ctx.app, &ctx.window);
                s.keys = Some(k);
                self.push(s, None);
            }
            KeyEvent::Shortcut(k) => {
                self.flush_typing();
                let mut s = RawStep::new("shortcut", &ctx.app, &ctx.window);
                s.keys = Some(k);
                self.push(s, None);
            }
        }
    }

    /// Ends a typing burst after a pause.
    pub fn tick(&mut self, now: Instant) {
        if self
            .typing
            .as_ref()
            .is_some_and(|t| now.duration_since(t.last) >= TYPING_IDLE)
        {
            self.flush_typing();
        }
    }

    /// Attaches an author note to the latest step (or the next one if nothing yet).
    pub fn note(&mut self, text: &str) {
        let text = text.trim();
        if text.is_empty() {
            return;
        }
        self.flush_typing();
        match self.raw.last_mut() {
            Some(s) => {
                s.note = Some(match s.note.take() {
                    Some(prev) => format!("{prev} {text}"),
                    None => text.to_string(),
                })
            }
            None => self.pending_note = Some(text.to_string()),
        }
    }

    pub fn finish(mut self) -> (Vec<RawStep>, Vec<Option<String>>) {
        self.flush_typing();
        (self.raw, self.shots)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ctx(secure: bool) -> KeyContext {
        KeyContext {
            app: "Chrome".into(),
            window: "New Tab".into(),
            secure,
        }
    }

    #[test]
    fn typing_bursts_flush_on_click_idle_and_named_keys() {
        let t0 = Instant::now();
        let mut b = LogBuilder::default();
        b.click(
            Some(Target {
                role: "edit".into(),
                name: "Address".into(),
            }),
            "Chrome",
            "New Tab",
            Some("data:x".into()),
        );
        for c in "nudgy.app".chars() {
            b.key(KeyEvent::Char(c), &ctx(false), t0);
        }
        b.key(KeyEvent::Named("Enter".into()), &ctx(false), t0);
        b.key(KeyEvent::Char('h'), &ctx(false), t0);
        b.key(KeyEvent::Char('x'), &ctx(false), t0);
        b.key(KeyEvent::Backspace, &ctx(false), t0);
        b.key(KeyEvent::Char('i'), &ctx(false), t0);
        b.tick(t0 + TYPING_IDLE);
        b.key(KeyEvent::Shortcut("Ctrl+B".into()), &ctx(false), t0);
        let (raw, shots) = b.finish();
        let kinds: Vec<_> = raw
            .iter()
            .map(|s| (s.kind.as_str(), s.text.as_deref().or(s.keys.as_deref())))
            .collect();
        assert_eq!(
            kinds,
            vec![
                ("click", None),
                ("type", Some("nudgy.app")),
                ("key", Some("Enter")),
                ("type", Some("hi")),
                ("shortcut", Some("Ctrl+B")),
            ]
        );
        assert_eq!(shots, vec![Some("data:x".into()), None, None, None, None]);
    }

    #[test]
    fn secure_fields_are_recorded_as_hidden() {
        let t0 = Instant::now();
        let mut b = LogBuilder::default();
        b.key(KeyEvent::Char('p'), &ctx(false), t0);
        b.key(KeyEvent::Char('w'), &ctx(true), t0); // focus moved into a password field mid-burst
        let (raw, _) = b.finish();
        assert_eq!(raw[0].text.as_deref(), Some(HIDDEN));
        assert!(!format!("{raw:?}").contains("pw"));
    }

    #[test]
    fn notes_attach_to_latest_or_next_step() {
        let mut b = LogBuilder::default();
        b.note("first explain");
        b.click(None, "App", "", None);
        b.note("then this");
        b.note("and more");
        let (raw, _) = b.finish();
        assert_eq!(
            raw[0].note.as_deref(),
            Some("first explain then this and more")
        );
    }

    #[test]
    fn pending_click_keeps_order_when_details_arrive_late() {
        let t0 = Instant::now();
        let mut b = LogBuilder::default();
        let i = b.click_pending();
        b.key(KeyEvent::Char('h'), &ctx(false), t0); // typed while the click was being described
        b.fill_click(
            i,
            Some(Target {
                role: "edit".into(),
                name: "Search".into(),
            }),
            "Chrome",
            "Tab",
            Some("data:s".into()),
        );
        let (raw, shots) = b.finish();
        assert_eq!(raw[0].target.as_ref().unwrap().name, "Search");
        assert_eq!(raw[0].app, "Chrome");
        assert_eq!(raw[1].text.as_deref(), Some("h"));
        assert_eq!(shots[0].as_deref(), Some("data:s"));
    }

    #[test]
    fn len_counts_open_typing() {
        let mut b = LogBuilder::default();
        b.key(KeyEvent::Char('a'), &ctx(false), Instant::now());
        assert_eq!(b.len(), 1);
    }
}
