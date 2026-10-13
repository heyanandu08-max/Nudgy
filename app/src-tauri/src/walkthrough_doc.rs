//! A walkthrough as a process document: one self-contained HTML page (steps, notes, optional
//! screenshots) that opens in any browser and prints cleanly to PDF.

use serde::Deserialize;

use crate::walkthrough::Walkthrough;

/// UI strings for the page, in the user's language (sent by the app).
#[derive(Debug, Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DocLabels {
    pub steps: String,
    pub why: String,
    pub note: String,
    pub footer: String,
    pub lang: String,
}

fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            _ => out.push(c),
        }
    }
    out
}

const STYLE: &str = "
:root{--ink:#0a0a0a;--ink2:#55534e;--ink3:#8a8780;--line:#e4e1d9;--paper:#f6f4ee;--accent:#e5484d}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif}
main{max-width:760px;margin:0 auto;padding:48px 24px 64px}
.meta{font:12px ui-monospace,Menlo,Consolas,monospace;color:var(--ink3);text-transform:uppercase;letter-spacing:.04em}
h1{font-size:34px;line-height:1.15;letter-spacing:-.02em;margin:8px 0 10px}
.summary{color:var(--ink2);margin:0 0 28px}
ol{list-style:none;margin:0;padding:0;counter-reset:s}
li{counter-increment:s;background:#fff;border:1px solid var(--line);border-radius:14px;padding:18px 20px;margin:0 0 14px;break-inside:avoid}
li h2{display:flex;gap:12px;font-size:16px;margin:0}
li h2::before{content:counter(s);flex:none;display:grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--ink);color:#fff;font:12px ui-monospace,Menlo,Consolas,monospace}
.why,.note{margin:8px 0 0 38px;color:var(--ink2);font-size:14px}
.note b,.why b{color:var(--ink);font-weight:600}
img{display:block;max-width:calc(100% - 38px);margin:12px 0 0 38px;border:1px solid var(--line);border-radius:10px}
footer{margin-top:28px;font:12px ui-monospace,Menlo,Consolas,monospace;color:var(--ink3)}
@media print{body{background:#fff}main{padding:0}li{border-color:#ccc}}
";

pub fn to_html(w: &Walkthrough, l: &DocLabels) -> String {
    let mut steps = String::new();
    for s in &w.steps {
        steps.push_str("<li><h2>");
        steps.push_str(&esc(s.instruction.trim()));
        steps.push_str("</h2>");
        if !s.why.trim().is_empty() {
            steps.push_str(&format!(
                "<p class=\"why\"><b>{}</b> {}</p>",
                esc(&l.why),
                esc(s.why.trim())
            ));
        }
        if let Some(n) = s.note.as_deref().filter(|n| !n.trim().is_empty()) {
            steps.push_str(&format!(
                "<p class=\"note\"><b>{}</b> {}</p>",
                esc(&l.note),
                esc(n.trim())
            ));
        }
        // Only screenshots the app itself recorded (validated as JPEG data URLs).
        if let Some(shot) = s
            .screenshot
            .as_deref()
            .filter(|d| d.starts_with("data:image/jpeg;base64,"))
        {
            steps.push_str(&format!("<img alt=\"\" src=\"{}\">", esc(shot)));
        }
        steps.push_str("</li>\n");
    }
    let meta = if w.app.trim().is_empty() {
        format!("{} {}", w.steps.len(), esc(&l.steps))
    } else {
        format!("{} · {} {}", esc(&w.app), w.steps.len(), esc(&l.steps))
    };
    let summary = if w.summary.trim().is_empty() {
        String::new()
    } else {
        format!("<p class=\"summary\">{}</p>", esc(w.summary.trim()))
    };
    format!(
        "<!doctype html>\n<html lang=\"{lang}\"><head><meta charset=\"utf-8\">\
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">\
<title>{title}</title><style>{STYLE}</style></head>\n<body><main>\
<p class=\"meta\">{meta}</p><h1>{title}</h1>{summary}<ol>\n{steps}</ol>\
<footer>{footer}</footer></main></body></html>\n",
        lang = esc(&l.lang),
        title = esc(&w.title),
        footer = esc(&l.footer),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::walkthrough::Step;

    fn step(instruction: &str) -> Step {
        Step {
            instruction: instruction.into(),
            target: None,
            action_hint: None,
            success_check: String::new(),
            why: String::new(),
            note: None,
            screenshot: None,
            raw: vec![],
        }
    }

    fn labels() -> DocLabels {
        DocLabels {
            steps: "steps".into(),
            why: "Why:".into(),
            note: "Note:".into(),
            footer: "Made with Nudgy".into(),
            lang: "en".into(),
        }
    }

    #[test]
    fn renders_steps_escaped_with_notes_and_screenshots() {
        let mut a = step("Click <Save>");
        a.note = Some("Use the \"Q3\" folder".into());
        a.screenshot = Some("data:image/jpeg;base64,AAAA".into());
        let mut b = step("Close it");
        b.why = "So others can open it".into();
        b.screenshot = Some("javascript:alert(1)".into()); // never trusted
        let w = Walkthrough {
            format: crate::walkthrough::FORMAT.into(),
            version: 1,
            id: "w".into(),
            title: "Expenses & receipts".into(),
            app: "SAP".into(),
            summary: String::new(),
            platform: String::new(),
            created_at: 0,
            steps: vec![a, b],
        };
        let html = to_html(&w, &labels());
        assert!(html.contains("<title>Expenses &amp; receipts</title>"));
        assert!(html.contains("<h2>Click &lt;Save&gt;</h2>"));
        assert!(html.contains("Use the &quot;Q3&quot; folder"));
        assert!(html.contains("<b>Why:</b> So others can open it"));
        assert!(html.contains("src=\"data:image/jpeg;base64,AAAA\""));
        assert!(!html.contains("javascript:"));
        assert!(html.contains("SAP · 2 steps"));
        assert_eq!(html.matches("<li>").count(), 2);
    }
}
