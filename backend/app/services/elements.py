"""Shortens the on-screen element list for small (local) models, keeping what can be clicked."""

from __future__ import annotations

from typing import Any

INTERACTIVE = {
    "button", "menuitem", "tab", "link", "checkbox", "radio", "combobox", "edit", "textfield",
    "listitem", "treeitem", "menu", "splitbutton", "spinbutton", "slider", "cell",
}  # fmt: skip


def trim(elements: list[Any], limit: int) -> list[Any]:
    """At most `limit` elements: clickable ones first, then the rest, each in screen order.
    Ids are kept, so a model's answer still points at the same element."""
    if len(elements) <= limit:
        return elements
    keep = [e for e in elements if e.role in INTERACTIVE and e.name.strip()]
    if len(keep) < limit:
        chosen = {id(e) for e in keep}
        keep += [e for e in elements if id(e) not in chosen][: limit - len(keep)]
    chosen = {id(e) for e in keep[:limit]}
    return [e for e in elements if id(e) in chosen]


def apply(ctx: Any) -> Any:
    """Trims `ctx.elements` (and a verify context's before/after lists) to the configured size."""
    from app.config import get_settings

    limit = get_settings().max_elements
    for holder in (ctx, getattr(ctx, "before", None), getattr(ctx, "after", None)):
        if isinstance(getattr(holder, "elements", None), list):
            holder.elements = trim(holder.elements, limit)
    return ctx
