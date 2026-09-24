# Design audit — nudgy-kit redesign

Applied `nudgy-kit/prompts/2-redesign-existing-app.md` and `3-no-ai-look-rules.md`.
Reference mockups: `design/previews/*.png`, CSS values from `design/nudgy-app-screens.html`.
Brand assets: `brand/` (logo, app icon, BRAND.md).

## Foundations
- **Tokens** (`app/src/index.css` `@theme`, mirrored in `app/src/overlay/overlay.css`): bg `#FFFFFF`,
  paper `#FAFAF7`, ink `#0A0A0A`, ink-2 `#55544F`, ink-3 `#9A988F`, line `#ECEAE4`, line-2 `#DAD7CF`,
  accent `#FF4A1C` (only: review-due dot, record dot, speaking wave, save errors), good `#1F9D55`.
  The old orange/slate palette is gone everywhere, including the backend web pages.
- **Fonts** bundled locally via @fontsource (`app/src/fonts.ts`): Poppins 500/600, Lora Italic 500,
  JetBrains Mono 400. No font CDN.
- **Radii**: cards 14px, buttons 10px. Hard offset shadow (`4px 4px 0 ink`) only on the ask box and lesson card.
- **Motion**: 120–250 ms entrances; the only loops are while something is actually happening
  (listening dots, speaking wave, recording dot). `prefers-reduced-motion` turns animation off.
- **Dark mode**: TODO (noted in `index.css`).
- **Window**: 980×780 default, min width 760; two-column layouts stack below 900px.
- **Icons**: regenerated all Tauri icons from `brand/app-icon/nudgy-icon-1024.png`; `.icns`/`.ico` from the kit.

## Main window
- New title bar (`components/TitleBar.tsx`): logo, Home / Walkthroughs / Settings tabs, Ready/Offline
  status dot, hotkey keycaps (⌃ ⌥ on macOS), avatar → Account. Replaces `Shell.tsx`.
- **Home** (`features/home/HomePage.tsx`) rebuilt to match `0-home-dashboard.png`: date + greeting line,
  "What should we *learn* today?", ask box with "Teach me →", hotkey hint, example chips with app codes,
  skill cards with big Lora percentage + review-due dot, empty "+" card, Needs practice, Recent
  (lessons and quick questions, Q&A tag), black "Record a walkthrough" banner, mono footer.
  Replaces `Dashboard.tsx` and `StartLesson.tsx`.
- **Settings** (`features/settings/*`) rebuilt to match `4-settings.png`: sidebar (Cursor & voice,
  Hotkey, Privacy, Account, About), auto-saving rows. **Cursor color** swatches and **cursor size**
  S/M/L replace the old emoji/companion picker. Voice select, speak toggle, answer length, "Never look
  at these apps" chips (+N more, add/remove), hide-when-idle. Hotkey capture, language, server URL
  and version moved to their own sections. `HealthBadge.tsx` removed (status lives in the title bar).
- **Walkthroughs** and **Account** restyled with the same tokens and components (`components/ui.tsx`).

## Overlay (the Nudgy cursor)
- The emoji companion (`Companion.tsx`) is replaced by the **Nudgy cursor** (`overlay/NudgyCursor.tsx`):
  black arrow, white outline, tilted 16°, trailing the real pointer. Color and size come from Settings.
  Fades out after 5 s idle, or stays hidden unless called when "hide when idle" is on.
- **State labels** in mono next to the cursor: listening (red dot) / thinking… / talking / watching /
  checking… / nice ✓ (green, with a small hop, when a lesson step passes).
- **Pointing** (`Pointer.tsx`): the cursor itself flies to the target on an arc with a dashed trail
  and draws a black ring around the element (was: orange arrow + glow).
- **Caption** (`CaptionBubble.tsx`): black bubble with a mono "NUDGY" header.
- **Status pill** (`StatusPill.tsx`, new): "speaking · Esc to stop" with a wave, "your turn · I'm
  watching this window only", "open <app>", "planning…". Esc is registered globally only while
  audio plays (`escape_listen` command) and stops the answer.
- **Lesson card** (`LessonCard.tsx`, replaces `LessonPanel.tsx`): white card, 1.5px ink border, hard
  shadow, "LESSON · APP  n / N", instruction, step bars, Show me / Skip, "I did it · stop" links.
- **Review nudge** and **recorder bar** restyled (`.nudge`, `.recbar`).

## Guide inside the user's own app
- New `apps.rs`: `focus_app` brings the lesson's app to the front (macOS `open -a`; Windows
  `SetForegroundWindow` on a matching window, else launch by exe name); `wait_for_app` polls for it.
- Lessons hide the Nudgy main window when they start. If the app can't be brought up, the tutor
  enters `waiting_app`, says "Open <app> and I'll take it from there." and continues when it appears.

## Copy (no-AI-look rules)
- `en.json` rewritten in the brand voice: short, concrete, no exclamation marks (0 left), no emoji,
  none of unlock / supercharge / seamless / effortless / AI-powered / Certainly / Great question /
  happy to help / dive in / delve. "First," → "First step:" (fixed "First, Click…" capitalisation).
- `backend/prompts/talk.md` v3: persona is "calm, direct and kind" (was "warm, a little witty"),
  1–3 sentences, no filler openers or exclamation marks, never mention being an AI / model / assistant.
- `lesson_plan.md` v2, `verify_step.md` v2, `walkthrough_clean.md` v2: plain sentences, no exclamation
  marks, praise without hype.
- Fake LLM strings ("Let's do it together!", "Nice work, that's exactly it!", "happy to explain it")
  rewritten. Billing page "Thanks! …" → "Thanks. …".
- Backend web pages (sign-in hand-off, shared link, billing return) share one ink-on-white style
  (`backend/app/services/pages.py`) instead of orange buttons.

## Not changed
- All logic (ask pipeline, tutor state machine, SM-2, recorder, accounts/billing) is untouched apart
  from the guide-in-app additions; all tests pass (backend 85, Rust 78, vitest 17).

## Billing — launch date, free year, capped free tier

### How it behaves
| When | Free account | Paid account |
|------|--------------|--------------|
| Before FREE_UNTIL − 30 days | Unlimited. No plan, price, counter or upgrade text anywhere. | Same |
| Last 30 days before FREE_UNTIL | Unlimited. One mono line under the Settings sidebar: "free access changes on Oct 10, 2026 · you'll keep 2 lessons a month, unlimited if you subscribe". | Nothing |
| From FREE_UNTIL (and every signup after it) | N new lessons per calendar month (UTC). Questions, step checks, reviews and walkthrough replays stay unlimited. "1 lesson left this month · resets Oct 1" under the Home ask box and on the lesson card. At 0: one dismissable screen. | Unlimited, nothing shown |

- FREE_UNTIL = `NUDGY_LAUNCH_DATE` + 365 days, one date for everyone (admin override:
  `NUDGY_FREE_UNTIL_OVERRIDE` or `PUT /v1/admin/access`). The cap N is the
  `app_settings.free_tier_lessons_per_month` row (seeded from `NUDGY_FREE_TIER_LESSONS_PER_MONTH`,
  changed live via the admin API). No launch date = no free window (dev default).
- The server decides everything (`services/access.py`) using its own clock. The app only shows
  what `/v1/access` returns, and the backend returns nothing about caps before the notice window.
- Enforced server-side on `POST /v1/lessons/plan` (402 `limit_reached` with used/limit/resets_at).
  A plan that fails is refunded. Lessons run during the free window never count toward the first
  capped month.
- Usage is logged quietly the whole time (`usage_events`: kind, tokens, latency, STT audio ms,
  TTS characters), for every call type. `GET /v1/admin/usage` gives monthly totals and
  lessons-per-user p50/p90/max, to help pick the cap.
- Subscribe is one stub (`features/billing/subscribe.ts`, `TODO: connect billing provider`) that
  says "subscriptions aren't open yet". A paid plan (set by the Stripe webhook, or by hand with
  `PUT /v1/admin/users/{email}/plan` for QA) removes the cap, and the tests cover that.
- Copy: no exclamation marks, no "unlock"/"premium", no countdowns, no red. The notice and notes
  are ink-3 mono meta lines. The upgrade screen uses the standard heading with a Lora accent,
  plain paragraphs, a primary Subscribe button and an always-enabled Not now that goes back to
  where you were.

### Files touched
Backend
- `backend/app/config.py`: `launch_date`, `free_until_override`, `free_tier_lessons_per_month`,
  `admin_token` (blank env values count as unset). Production check for the admin token length.
- `backend/app/models/app_setting.py` (new): the `app_settings` key/value table.
- `backend/app/models/account.py`: `UsageEvent.audio_ms`, `UsageEvent.tts_chars`.
- `backend/app/models/__init__.py`: registers `AppSetting`.
- `backend/app/db.py`: `_add_missing_columns` adds new columns to existing databases.
- `backend/app/services/access.py` (new): FREE_UNTIL, the cap, quota and the `/v1/access` shape.
- `backend/app/services/usage.py`: rewritten as a quiet usage log (`record`, `refund`,
  `finish` with cost fields, `wav_ms`). Plan limits removed.
- `backend/app/services/plans.py`, `backend/config/plans.yaml`: plans are `paid` or not. Per-kind
  limits removed.
- `backend/app/deps.py`: `get_clock` (overridable). `metered` logs every kind and enforces only
  the lesson cap.
- `backend/app/routers/lessons.py`: refund on failed plans, tokens/latency recorded for plan,
  verify and locate, `quota` in the plan response, `speak` logged.
- `backend/app/schemas/lessons.py`: `LessonQuota`, `PlannedLesson`.
- `backend/app/routers/ask.py`: STT audio ms and TTS characters recorded.
- `backend/app/routers/walkthroughs.py`: tokens for clean. `transcribe` logged.
- `backend/app/routers/auth.py`: `/v1/me` returns `paid` + `access` instead of usage counters.
  New `GET /v1/access`.
- `backend/app/routers/admin.py` (new), `backend/app/main.py`: admin API.
- `backend/tests/test_access.py` (new, 13 tests), `backend/tests/test_accounts.py` (updated to
  the new policy).
- `.env.example`: the four new variables.

Desktop app (shared by both OS builds)
- `app/src/features/billing/` (new): `access.ts` (store, UTC date formatting), `QuotaNote.tsx`,
  `AccessNotice.tsx`, `UpgradePrompt.tsx`, `SubscribeButton.tsx` (`useSubscribe`), `subscribe.ts` (stub).
- `app/src/App.tsx`: refreshes access at launch, on focus, sign-in and after lessons. The
  upgrade screen replaces the page content and Not now returns to it.
- `app/src/features/home/HomePage.tsx`: quota note under the ask box. Opens the explanation
  instead of starting a lesson it knows will be refused.
- `app/src/features/settings/SettingsPage.tsx`: the notice line under the sidebar.
- `app/src/features/account/AccountPage.tsx`: plan picker, usage meters and checkout removed.
  Shows the plan only when paid, or the monthly allowance + Subscribe when capped.
- `app/src/features/tutor/{tutor.ts,types.ts,host.ts,tutor.test.ts}`: `limit_reached` →
  short spoken line + explanation screen (not "failed"). Quota carried into the lesson view.
- `app/src/overlay/LessonCard.tsx`: quota note on the first step.
- `app/src/tokens.css` (new), `app/src/index.css`, `app/src/overlay/overlay.css`: one token
  file for both windows (the overlay's variables now alias it), plus thin scrollbars styled
  the same on both OSes.
- `app/src/i18n/locales/en.json`: `billing.*`, `tutor.say.limitReached`, the new
  `errors.limit_reached`. Old plan/usage strings removed.
- `app/src-tauri/src/account.rs`, `app/src-tauri/src/lib.rs`: `access_get` command.
- `scripts/ui_parity.mjs`, `scripts/ui_parity.sh` (new): Windows vs macOS render and diff.

### Windows vs macOS
All billing and cap screens are single shared React components. The app's UI code has two
OS branches, both on the allowed list: keyboard symbols (`components/ui.tsx` `hotkeyParts`) and
the macOS permission step in onboarding.

Checked with `scripts/ui_parity.sh`: the same build rendered as Windows and as macOS, with the
Tauri IPC mocked in the capped, cap-reached and notice states.

| Screen | Pixels that differ | Where |
|--------|--------------------|-------|
| Upgrade screen | 1,845 | title-bar keycaps only (Ctrl Alt vs ⌃ ⌥) |
| Account (capped) | 1,845 | title-bar keycaps only |
| Settings with notice | 1,845 | title-bar keycaps only |
| Home (1 lesson left) | 4,395 | title-bar keycaps + the "or just hold …" keycaps and the text they push along |

Engine check: the upgrade screen and Account in the real app on WebKitGTK (the same engine
family as macOS's WKWebView) against Chromium (the engine of Windows' WebView2). Layout,
line wraps and sizes match. Glyph rasterization differs, and blocks shift by up to 2 px from
line-box rounding.

Known differences, left as they are:
- Native: window title-bar controls, the voice `<select>`'s open list, file save/open dialogs,
  and OS permission prompts.
- `-webkit-font-smoothing: antialiased` only affects macOS, so text is slightly lighter there.
  Windows draws text with DirectWrite.
- Text rasterization (CoreText vs DirectWrite) can move lines by a pixel or two.

Fixed while checking: scrollbars were the OS default (classic grey on Windows, overlay on macOS).
Both OSes now get the same thin styled scrollbar (`tokens.css`).

Not verified: real Windows and macOS binaries weren't run side by side, because this was done in
a Linux container. Both targets compile (`scripts/check_targets.sh`). The side-by-side hardware
check is in `TESTING.md` → Billing.

### Payments update (D44)
Subscribe now opens **PayPal** (Nudgy Pro: $20 a month or $40 a year) instead of the stub /
Stripe. Same shared components on both OSes: one button per price on the cap screen and in
Account ("Subscribe · $20 a month", "$40 a year"), a mono status line under them, and
"Manage in PayPal" for subscribers. Files: `backend/app/services/paypal_api.py` (new),
`backend/app/services/billing.py`, `backend/app/routers/billing.py`, `backend/app/routers/auth.py`,
`backend/app/models/account.py`, `backend/app/services/{plans,usage,account_data}.py`,
`backend/config/plans.yaml`, `app/src/features/billing/{subscribe.ts,SubscribeButton.tsx}`,
`app/src-tauri/src/account.rs`, `app/src/i18n/locales/en.json`.
