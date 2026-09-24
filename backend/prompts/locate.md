---
name: locate
version: 1
---
Find a UI element on the user's screen. You see a screenshot and an element list (`id | role | name | x,y,w,h` in screenshot pixels).

Looking for: {{description}}

Prefer an `element_id` from the list. If none matches but you can see it in the screenshot, give its center as `x`,`y` in screenshot pixels. If it is not visible at all, use null.

Reply with exactly one JSON object and nothing else:
{"target": {"element_id": "e12"} | {"x": 812, "y": 64} | null}
