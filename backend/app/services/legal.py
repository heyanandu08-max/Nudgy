"""Legal pages (privacy, terms, cookies, deletion, licenses) from Markdown in backend/legal/,
filled with the business details from settings.

The Markdown is ours, but it is still escaped first and only a small, known subset is turned
into HTML: headings, paragraphs, lists, pipe tables, bold, inline code and links.
"""

from __future__ import annotations

import re
from functools import lru_cache
from html import escape
from pathlib import Path

from app.config import BACKEND_DIR, Settings

LEGAL_DIR = BACKEND_DIR / "legal"
# Bump when the Terms or Privacy Policy change in substance: sign-ins record the version agreed to.
TERMS_VERSION = "2026-10-14"
PAGES = {
    "privacy": "Privacy Policy",
    "terms": "Terms of Service",
    "cookies": "Cookie Policy",
    "delete-account": "Delete your account",
    "licenses": "Open-source licenses",
}

_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_LINK = re.compile(r"\[([^\]]+)\]\(((?:https?://|mailto:|/)[^)\s]*)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`([^`]+)`")


def details(s: Settings) -> dict[str, str]:
    """Placeholders available in the Markdown as {{name}}."""
    missing = "[not set]"
    return {
        "company": s.company_name or "Nudgy",
        "address": s.company_address or missing,
        "country": s.company_country or missing,
        "email": s.contact_email or missing,
        "updated": TERMS_VERSION,
        "site": s.public_url.rstrip("/"),
    }


def _inline(text: str) -> str:
    out = escape(text, quote=False)
    out = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", out)
    return _LINK.sub(lambda m: f'<a href="{escape(m.group(2))}">{m.group(1)}</a>', out)


def to_html(md: str) -> str:
    lines = _COMMENT.sub("", md).splitlines()
    html: list[str] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            html.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i].rstrip()
        if not line.strip():
            flush()
        elif m := re.match(r"(#{1,3}) (.+)", line):
            flush()
            level = len(m.group(1))
            html.append(f"<h{level}>{_inline(m.group(2))}</h{level}>")
        elif line.lstrip().startswith(("- ", "* ")):
            flush()
            items = []
            while i < len(lines) and lines[i].lstrip().startswith(("- ", "* ")):
                items.append(f"<li>{_inline(lines[i].lstrip()[2:])}</li>")
                i += 1
            html.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):
                    tag = "th" if not rows else "td"
                    rows.append(
                        "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"
                    )
                i += 1
            html.append("<table>" + "".join(rows) + "</table>")
            continue
        else:
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(html)


@lru_cache
def _source(name: str) -> str:
    return (LEGAL_DIR / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, s: Settings) -> str:
    """The page body for `name` with {{placeholders}} filled."""
    text = _source(name)
    for key, value in details(s).items():
        text = text.replace("{{" + key + "}}", value)
    return to_html(text)


def source_path(name: str) -> Path:
    return LEGAL_DIR / f"{name}.md"
