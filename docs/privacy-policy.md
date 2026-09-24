# Nudgy privacy policy (draft)

_Draft for review by counsel before release. Last updated: 2026-09-24._

Nudgy is a desktop tutor. To answer a question about what's on your screen it has to look at
your screen, so this page says exactly when it looks, what it sends, where, and for how long.

## When Nudgy looks at your screen
- **Only when you ask**: while you hold the hotkey, or open the question box with a double tap.
- **During a lesson you started**: each time you pause, to check whether you did the step.
- **While you record a walkthrough**: a small picture per click, kept on your computer.

Nudgy does not watch your screen in the background. Every time it captures, a "looking at your
screen" tag appears at the top right of that screen and the tray/menu-bar tooltip changes.

It never captures when a password field has focus, or when an app on your "Never look at these
apps" list is in front (password managers are on it by default). In those cases your question
is still answered, without the screenshot.

## What is sent, and to whom
For each question or lesson check, the app sends to **your Nudgy server** (shown in
Settings → Privacy):

| Data | Why |
|------|-----|
| One screenshot of the monitor your cursor is on (downscaled JPEG) | so the answer matches your screen |
| Names, roles and positions of buttons and fields in the app in front | so Nudgy can point exactly |
| The app name and window title | context |
| Your recorded question (audio) or typed text | the question |
| Your language, voice and answer-length settings | how to answer |

The server forwards the screenshot, element list and question to the AI providers it is
configured with (speech-to-text, a vision language model, text-to-speech). With the default
configuration these are: an STT provider, Anthropic (Claude) for the answer, and a TTS provider.
Their own data-use terms apply; review them before release (see DECISIONS.md).

**Not stored.** Screenshots and audio are processed in memory for that one request and then
discarded. They are never written to disk or logs, on your computer or on the server. Server
logs contain metadata only (request type, sizes, timings, error codes).

## What is stored
**On your computer** (SQLite in the app data folder): lessons, skills and review schedule,
the text of your recent questions (last 200), recorded walkthroughs, and your settings.
Nothing here is uploaded unless you share it.

**On the server, only if you create an account:** your email and name, plan and billing
status (payments are handled by Stripe; we never see card numbers), a count of questions and
lessons with token counts and timings for plan limits, your team membership, and walkthroughs
you chose to share. Shared links are unlisted but anyone with the link can open them; shared
copies leave out screenshots unless you choose to include them.

## Your controls
- **Export**: Settings → Privacy → Export my data saves one JSON file with everything above
  (local data plus, if signed in, `GET /v1/me/export`).
- **Delete**: "Delete learning history" wipes local data. "Delete my account" also deletes
  your account, usage records, shared links and (for team owners) the team, and cancels any
  subscription (`DELETE /v1/me`). This cannot be undone.
- **Pause**: the tray menu's Pause turns off the hotkey entirely.
- **Blocklist**: add any app in Settings → Cursor & voice → "Never look at these apps".

## Children
Nudgy is not directed at children under 13 (or the minimum age in your country) and does
not knowingly collect their data.

## Contact
Questions or requests: privacy@nudgy.app (placeholder).
