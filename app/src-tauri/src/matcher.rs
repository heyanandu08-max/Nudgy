//! Finds a described element (role + name) in the live UI tree. Used for lesson steps and
//! for replaying walkthroughs on another machine, where coordinates don't carry over but
//! names and roles mostly do (also across Windows ↔ macOS for apps like Chrome).

use crate::uitree::UiElement;

/// Minimum score to accept a match.
pub const THRESHOLD: f64 = 0.6;

fn normalize(s: &str) -> String {
    s.to_lowercase()
        .chars()
        .map(|c| if c.is_alphanumeric() { c } else { ' ' })
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

fn tokens(s: &str) -> Vec<String> {
    normalize(s)
        .split(' ')
        .filter(|t| !t.is_empty())
        .map(str::to_string)
        .collect()
}

/// Roles that mean the same thing across UIA, AX and our normalization.
fn role_family(role: &str) -> &'static str {
    match role {
        "button" | "splitbutton" | "popupbutton" | "menubutton" => "button",
        "edit" | "textfield" | "textarea" | "combobox" | "searchfield" => "text",
        "menuitem" | "menu" | "menubaritem" => "menu",
        "tab" | "tabitem" | "radio" => "tab",
        "listitem" | "treeitem" | "row" | "cell" | "dataitem" => "item",
        "link" | "hyperlink" => "link",
        "checkbox" | "switch" => "checkbox",
        _ => "other",
    }
}

/// Name similarity in [0, 1]: exact 1.0, containment 0.85, else token Jaccard.
pub fn name_score(want: &str, have: &str) -> f64 {
    let (w, h) = (normalize(want), normalize(have));
    if w.is_empty() || h.is_empty() {
        return 0.0;
    }
    if w == h {
        return 1.0;
    }
    if h.contains(&w) || w.contains(&h) {
        let (short, long) = if w.len() < h.len() {
            (&w, &h)
        } else {
            (&h, &w)
        };
        // "Bold" inside "Bold (Ctrl+B)" is strong; "B" inside "Bold" is not.
        return if short.len() >= 3 || short.len() * 2 >= long.len() {
            0.85
        } else {
            0.4
        };
    }
    let (tw, th) = (tokens(want), tokens(have));
    let inter = tw.iter().filter(|t| th.contains(t)).count() as f64;
    let union = (tw.len() + th.len()) as f64 - inter;
    if union == 0.0 {
        0.0
    } else {
        inter / union
    }
}

pub fn score(want_role: &str, want_name: &str, el: &UiElement) -> f64 {
    let n = name_score(want_name, &el.name);
    let r = if want_role.is_empty() || want_role == el.role {
        1.0
    } else if role_family(want_role) == role_family(&el.role) && role_family(want_role) != "other" {
        0.9
    } else {
        0.6
    };
    n * r
}

/// Best element for `role`/`name`, if any clears the threshold. Ties go to the first
/// element (tree order ≈ reading order).
pub fn find<'a>(
    want_role: &str,
    want_name: &str,
    elements: &'a [UiElement],
) -> Option<&'a UiElement> {
    let mut best: Option<(&UiElement, f64)> = None;
    for el in elements {
        let s = score(want_role, want_name, el);
        if s >= THRESHOLD && best.is_none_or(|(_, b)| s > b) {
            best = Some((el, s));
        }
    }
    best.map(|(el, _)| el)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::geometry::Rect;

    fn el(role: &str, name: &str) -> UiElement {
        UiElement {
            role: role.into(),
            name: name.into(),
            rect: Rect::new(0.0, 0.0, 10.0, 10.0),
        }
    }

    #[test]
    fn exact_and_case_insensitive() {
        let els = [el("button", "Italic"), el("button", "Bold")];
        assert_eq!(find("button", "bold", &els).unwrap().name, "Bold");
    }

    #[test]
    fn tolerates_decorations_and_role_aliases() {
        // Windows names often carry shortcuts; macOS uses different role names.
        let els = [
            el("splitbutton", "Accounting Number Format (Ctrl+Shift+$)"),
            el("text", "Accounting"),
        ];
        assert_eq!(
            find("button", "Accounting Number Format", &els)
                .unwrap()
                .role,
            "splitbutton"
        );
        let mac = [el("popupbutton", "Font Size"), el("textfield", "Search")];
        assert_eq!(
            find("combobox", "Font size", &mac).unwrap().name,
            "Font Size"
        );
    }

    #[test]
    fn rejects_weak_matches() {
        let els = [el("button", "B"), el("button", "Bookmarks")];
        assert!(find("button", "Bold", &els).is_none());
        assert!(find("button", "", &els).is_none());
    }

    #[test]
    fn prefers_higher_score_then_first() {
        let els = [
            el("menuitem", "New window"),
            el("menuitem", "New incognito window"),
            el("button", "New incognito window"),
        ];
        let hit = find("menuitem", "New Incognito Window", &els).unwrap();
        assert_eq!(
            (hit.role.as_str(), hit.name.as_str()),
            ("menuitem", "New incognito window")
        );
    }

    #[test]
    fn token_overlap_scores() {
        assert!((name_score("new incognito window", "incognito window new") - 1.0).abs() < 1e-9);
        assert!(name_score("save as", "save") >= 0.85);
        assert!(name_score("print", "export pdf") < 0.1);
    }
}
