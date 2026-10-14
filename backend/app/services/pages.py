"""Shared look for the web pages the backend serves (sign-in hand-off, shared links, billing,
legal pages). Every page carries the business details and legal links in its footer."""

import json
from html import escape

from app.config import Settings, get_settings

# Tokens from design/tokens (ink on white, 10px buttons). No web fonts: system fallbacks only.
# Meta grey #706E67 keeps 4.9:1 contrast (WCAG AA).
CSS = """body{font:16px/1.55 Poppins,system-ui,sans-serif;max-width:680px;margin:64px auto;padding:0 16px;
color:#0A0A0A;background:#FFFFFF}h1{font-weight:600;font-size:26px;letter-spacing:-.01em;margin:0 0 8px}
h2{font-size:18px;margin:28px 0 6px}h3{font-size:16px;margin:20px 0 4px}
a{color:#0A0A0A}a.btn{display:inline-block;background:#0A0A0A;color:#fff;padding:10px 18px;border-radius:10px;
text-decoration:none;font-weight:500}a:focus-visible,button:focus-visible{outline:2px solid #0A0A0A;outline-offset:2px}
p.meta{color:#55544F}ol,ul{padding-left:20px}li{margin:4px 0}
table{border-collapse:collapse;width:100%;font-size:14px;margin:8px 0}th,td{border:1px solid #DAD7CF;padding:6px 8px;
text-align:left;vertical-align:top}th{background:#FAFAF7}code{font:13px ui-monospace,monospace}
small{font:12px ui-monospace,"JetBrains Mono",monospace;color:#706E67}
footer{margin-top:48px;border-top:1px solid #ECEAE4;padding-top:16px;font-size:13px;color:#55544F}
footer a{color:#55544F;margin-right:12px}
#consent{position:fixed;left:16px;right:16px;bottom:16px;max-width:640px;margin:auto;background:#0A0A0A;color:#fff;
border-radius:14px;padding:14px 16px;font-size:14px}#consent button{margin:8px 8px 0 0;padding:8px 14px;
border-radius:10px;border:1px solid #fff;background:#0A0A0A;color:#fff;font:inherit;cursor:pointer}"""

LEGAL_LINKS = (
    ("/privacy", "Privacy"),
    ("/terms", "Terms"),
    ("/cookies", "Cookies"),
    ("/delete-account", "Delete your account"),
    ("/licenses", "Licenses"),
)


def _footer(s: Settings) -> str:
    who = escape(s.company_name or "Nudgy")
    parts = [who]
    if s.company_address:
        parts.append(escape(s.company_address))
    if s.contact_email:
        e = escape(s.contact_email)
        parts.append(f'<a href="mailto:{e}">{e}</a>')
    links = "".join(f'<a href="{href}">{label}</a>' for href, label in LEGAL_LINKS)
    return f"<footer><p>{' · '.join(parts)}</p><p>{links}</p></footer>"


def _consent_banner(s: Settings) -> str:
    """Only when site analytics is configured: nothing non-essential loads until the visitor
    says yes, and "No" is as easy as "Yes"."""
    src = s.analytics_src
    if not src:
        return ""
    safe_src = json.dumps(src).replace("</", "<\\/")  # can't close the <script>
    return (
        '<div id="consent" role="dialog" aria-label="Cookies" hidden><p>We use analytics cookies '
        "to see which pages help people. They load only if you agree. "
        '<a style="color:#fff" href="/cookies">Cookie policy</a></p>'
        '<button type="button" data-v="yes">Accept</button>'
        '<button type="button" data-v="no">Decline</button></div>'
        "<script>(function(){var k='nudgy-consent',b=document.getElementById('consent');"
        f"var src={safe_src};"
        "function load(){var s=document.createElement('script');s.src=src;s.async=true;"
        "document.head.appendChild(s);}"
        "var v=null;try{v=localStorage.getItem(k)}catch(e){}"
        "if(v==='yes')load();else if(v!=='no')b.hidden=false;"
        "b.addEventListener('click',function(e){var a=e.target.getAttribute('data-v');if(!a)return;"
        "try{localStorage.setItem(k,a)}catch(x){}b.hidden=true;if(a==='yes')load();});})();</script>"
    )


def page(title: str, body: str, settings: Settings | None = None) -> str:
    """Wraps trusted `body` HTML; `title` is escaped here."""
    s = settings or get_settings()
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>'
        f"</head><body><main><small>nudgy</small>{body}</main>{_footer(s)}{_consent_banner(s)}"
        "</body></html>"
    )
