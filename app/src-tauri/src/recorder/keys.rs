//! Turns polled key states into typing / shortcut events (US layout approximation).

use device_query::Keycode;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum KeyEvent {
    Char(char),
    Backspace,
    /// Enter, Tab, Escape, arrows… (ends a typing burst).
    Named(String),
    /// A modifier combination such as "Ctrl+B" or "Cmd+Shift+S".
    Shortcut(String),
}

fn is_modifier(k: &Keycode) -> bool {
    use Keycode::*;
    matches!(
        k,
        LControl
            | RControl
            | LShift
            | RShift
            | LAlt
            | RAlt
            | Command
            | RCommand
            | LOption
            | ROption
            | LMeta
            | RMeta
            | CapsLock
    )
}

fn char_of(k: &Keycode, shift: bool) -> Option<char> {
    use Keycode::*;
    let name = format!("{k:?}");
    if name.len() == 1 {
        let c = name.chars().next()?.to_ascii_lowercase();
        return Some(if shift { c.to_ascii_uppercase() } else { c });
    }
    let (plain, shifted) = match k {
        Key0 | Numpad0 => ('0', ')'),
        Key1 | Numpad1 => ('1', '!'),
        Key2 | Numpad2 => ('2', '@'),
        Key3 | Numpad3 => ('3', '#'),
        Key4 | Numpad4 => ('4', '$'),
        Key5 | Numpad5 => ('5', '%'),
        Key6 | Numpad6 => ('6', '^'),
        Key7 | Numpad7 => ('7', '&'),
        Key8 | Numpad8 => ('8', '*'),
        Key9 | Numpad9 => ('9', '('),
        Space => (' ', ' '),
        Minus | NumpadSubtract => ('-', '_'),
        Equal | NumpadEquals => ('=', '+'),
        NumpadAdd => ('+', '+'),
        NumpadMultiply => ('*', '*'),
        NumpadDivide => ('/', '/'),
        NumpadDecimal => ('.', '.'),
        LeftBracket => ('[', '{'),
        RightBracket => (']', '}'),
        BackSlash => ('\\', '|'),
        Semicolon => (';', ':'),
        Apostrophe => ('\'', '"'),
        Comma => (',', '<'),
        Dot => ('.', '>'),
        Slash => ('/', '?'),
        Grave => ('`', '~'),
        _ => return None,
    };
    Some(if shift { shifted } else { plain })
}

fn key_label(k: &Keycode) -> String {
    use Keycode::*;
    match k {
        Enter | NumpadEnter => "Enter".into(),
        Escape => "Esc".into(),
        Delete => "Delete".into(),
        Up => "Up".into(),
        Down => "Down".into(),
        Left => "Left".into(),
        Right => "Right".into(),
        Space => "Space".into(),
        other => {
            let n = format!("{other:?}");
            n.strip_prefix("Key")
                .filter(|d| d.len() == 1)
                .map(str::to_string)
                .unwrap_or(n)
        }
    }
}

#[derive(Default)]
pub struct KeyTracker {
    down: Vec<Keycode>,
}

impl KeyTracker {
    /// Feed the full set of currently pressed keys; returns what newly happened.
    pub fn feed(&mut self, now: &[Keycode]) -> Vec<KeyEvent> {
        let pressed: Vec<Keycode> = now
            .iter()
            .filter(|k| !self.down.contains(k))
            .cloned()
            .collect();
        self.down = now.to_vec();
        let has = |ks: &[Keycode]| now.iter().any(|k| ks.contains(k));
        let ctrl = has(&[Keycode::LControl, Keycode::RControl]);
        let alt = has(&[
            Keycode::LAlt,
            Keycode::RAlt,
            Keycode::LOption,
            Keycode::ROption,
        ]);
        let cmd = has(&[
            Keycode::Command,
            Keycode::RCommand,
            Keycode::LMeta,
            Keycode::RMeta,
        ]);
        let shift = has(&[Keycode::LShift, Keycode::RShift]);

        let mut out = Vec::new();
        for k in pressed.iter().filter(|k| !is_modifier(k)) {
            if ctrl || alt || cmd {
                let mut parts = Vec::new();
                if ctrl {
                    parts.push("Ctrl");
                }
                if cmd {
                    parts.push("Cmd");
                }
                if alt {
                    parts.push("Alt");
                }
                if shift {
                    parts.push("Shift");
                }
                let key = char_of(k, false)
                    .map(|c| c.to_ascii_uppercase().to_string())
                    .unwrap_or_else(|| key_label(k));
                out.push(KeyEvent::Shortcut(format!("{}+{key}", parts.join("+"))));
            } else if *k == Keycode::Backspace {
                out.push(KeyEvent::Backspace);
            } else if let Some(c) = char_of(k, shift) {
                out.push(KeyEvent::Char(c));
            } else if !matches!(
                k,
                Keycode::Home
                    | Keycode::End
                    | Keycode::PageUp
                    | Keycode::PageDown
                    | Keycode::Insert
            ) {
                out.push(KeyEvent::Named(key_label(k)));
            }
        }
        out
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use Keycode::*;

    fn run(frames: &[&[Keycode]]) -> Vec<KeyEvent> {
        let mut t = KeyTracker::default();
        frames.iter().flat_map(|f| t.feed(f)).collect()
    }

    #[test]
    fn typing_with_shift_and_backspace() {
        let ev = run(&[
            &[H],
            &[],
            &[LShift, I],
            &[LShift],
            &[Key1],
            &[],
            &[Backspace],
            &[],
        ]);
        assert_eq!(
            ev,
            vec![
                KeyEvent::Char('h'),
                KeyEvent::Char('I'),
                KeyEvent::Char('1'),
                KeyEvent::Backspace
            ]
        );
    }

    #[test]
    fn held_keys_do_not_repeat() {
        assert_eq!(run(&[&[A], &[A], &[A], &[]]), vec![KeyEvent::Char('a')]);
    }

    #[test]
    fn shortcuts_and_named_keys() {
        let ev = run(&[
            &[LControl],
            &[LControl, B],
            &[],
            &[Command, LShift, S],
            &[],
            &[Enter],
            &[],
            &[LAlt, Tab],
        ]);
        assert_eq!(
            ev,
            vec![
                KeyEvent::Shortcut("Ctrl+B".into()),
                KeyEvent::Shortcut("Cmd+Shift+S".into()),
                KeyEvent::Named("Enter".into()),
                KeyEvent::Shortcut("Alt+Tab".into()),
            ]
        );
    }

    #[test]
    fn symbols() {
        let ev = run(&[&[LShift, Equal], &[], &[Dot], &[]]);
        assert_eq!(ev, vec![KeyEvent::Char('+'), KeyEvent::Char('.')]);
    }
}
