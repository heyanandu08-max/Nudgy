//! Capture gating. Screen content is only captured while the hotkey is held or a lesson
//! step is being verified, and never when a password field is focused or a blocklisted
//! app is in front. See PLAN.md Phase 8.

use crate::settings::Settings;
use crate::uitree::UiSnapshot;

/// Apps never captured unless the user removes them from the list in Settings.
pub const DEFAULT_BLOCKLIST: &[&str] = &[
    "1Password",
    "Bitwarden",
    "LastPass",
    "KeePass",
    "KeePassXC",
    "Dashlane",
    "Keeper",
    "Keychain Access",
    "Passwords",
    "Enpass",
];

/// Returns why screen content must be withheld, or `None` if capture is allowed.
pub fn capture_blocker(settings: &Settings, snap: &UiSnapshot) -> Option<&'static str> {
    if snap.secure_field_focused {
        return Some("password_field");
    }
    if is_blocked(&settings.blocklist, &snap.app_name, &snap.window_title) {
        return Some("blocked_app");
    }
    None
}

/// Case-insensitive match of any blocklist entry against the app name or window title.
pub fn is_blocked(blocklist: &[String], app_name: &str, window_title: &str) -> bool {
    let app = app_name.to_lowercase();
    let title = window_title.to_lowercase();
    blocklist
        .iter()
        .map(|b| b.trim().to_lowercase())
        .filter(|b| !b.is_empty())
        .any(|b| {
            app == b || app.trim_end_matches(".exe") == b || app.contains(&b) || title.contains(&b)
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn snap(app: &str, title: &str, secure: bool) -> UiSnapshot {
        UiSnapshot {
            app_name: app.into(),
            window_title: title.into(),
            elements: vec![],
            secure_field_focused: secure,
        }
    }

    #[test]
    fn password_field_blocks_capture() {
        assert_eq!(
            capture_blocker(&Settings::default(), &snap("Chrome", "Login", true)),
            Some("password_field")
        );
    }

    #[test]
    fn default_blocklist_blocks_password_managers_only() {
        let s = Settings::default();
        assert_eq!(
            capture_blocker(&s, &snap("1Password", "Vault", false)),
            Some("blocked_app")
        );
        assert_eq!(
            capture_blocker(&s, &snap("keepassxc.exe", "db", false)),
            Some("blocked_app")
        );
        assert_eq!(
            capture_blocker(&s, &snap("Excel", "Budget.xlsx", false)),
            None
        );
    }

    #[test]
    fn user_entries_match_window_titles() {
        let list = vec!["Chase Online".to_string(), "  ".to_string()];
        assert!(is_blocked(
            &list,
            "Google Chrome",
            "Chase Online - Accounts"
        ));
        assert!(!is_blocked(&list, "Google Chrome", "Docs"));
    }
}
