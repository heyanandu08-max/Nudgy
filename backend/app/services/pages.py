"""Shared look for the few web pages the backend serves (sign-in hand-off, shared links, billing)."""

from html import escape

# Tokens from design/tokens (ink on white, 10px buttons). No web fonts: system fallbacks only.
CSS = """body{font:16px/1.55 Poppins,system-ui,sans-serif;max-width:600px;margin:64px auto;padding:0 16px;
color:#0A0A0A;background:#FFFFFF}h1{font-weight:600;font-size:26px;letter-spacing:-.01em;margin:0 0 8px}
a.btn{display:inline-block;background:#0A0A0A;color:#fff;padding:10px 18px;border-radius:10px;text-decoration:none;
font-weight:500}p.meta{color:#55544F}ol{padding-left:20px}li{margin:4px 0}
small{font:12px ui-monospace,"JetBrains Mono",monospace;color:#9A988F}"""


def page(title: str, body: str) -> str:
    """Wraps trusted `body` HTML; `title` is escaped here."""
    return (
        f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{escape(title)}</title>'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><style>{CSS}</style>'
        f"</head><body><small>nudgy</small>{body}</body></html>"
    )
