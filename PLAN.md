# Nudgy — Build Plan

Nudgy is a cross-platform (Windows + macOS) desktop AI tutor that lives next to the
cursor. Hold a hotkey, ask out loud; Nudgy looks at the screen, answers out loud, and
flies a pointer to the exact UI element you need. It also runs verified step-by-step
lessons, tracks skills, and records/replays shareable walkthroughs.

See `DECISIONS.md` for the reasoning behind choices and `CLAUDE.md` for how to work
in this repo.

---

## 1. Architecture

```
┌──────────────────────────── Desktop app (Tauri v2) ────────────────────────────┐
│                                                                                 │
│  Rust core (app/src-tauri)                     React UI (app/src)               │
│  ─────────────────────────                     ─────────────────                │
│  hotkey   (global-shortcut plugin)             windows:                         │
│  audio    (cpal → 16 kHz mono PCM/WAV)           • main  (settings, dashboard,  │
│  capture  (xcap → JPEG ≤1280px)                           onboarding, debug)    │
│  uitree   (trait UiTree)                         • overlay-<monitor> (one per   │
│     ├─ windows.rs  (UI Automation)                 monitor: companion, pointer, │
│     └─ macos.rs    (AXUIElement)                   captions, highlight ring)    │
│  geometry (screenshot ↔ screen coords,         state: zustand stores           │
│            DPI, Retina, multi-monitor,         i18n: react-i18next (en)         │
│            macOS origin flip)                  api client: fetch + SSE parser   │
│  overlay  (create/position windows,                                             │
│            click-through, cursor poll)                                          │
│  privacy  (blocklist, password-field check,                                     │
│            capture indicator)                                                   │
│  store    (SQLite via rusqlite: settings,                                       │
│            skills, lessons, reviews, walkthroughs)                              │
│  tray     (Open / Pause / Settings / Quit)                                      │
│                                                                                 │
└──────────────────────────────┬──────────────────────────────────────────────────┘
                               │ HTTPS, JWT, multipart upload → SSE stream back
                               ▼
┌──────────────────────────── Backend (FastAPI) ──────────────────────────────────┐
│  routers:  /health  /v1/ask  /v1/lessons/*  /v1/verify  /v1/walkthroughs/*      │
│            /v1/auth/*  /v1/billing/*  /v1/me (export / delete)                  │
│  services: ask pipeline, prompt builder, JSON parse/repair, usage metering,     │
│            lesson planner, step verifier, walkthrough cleaner                   │
│  providers (interfaces + registry, chosen via config):                          │
│     LLM:  anthropic (default) | fake                                            │
│     STT:  deepgram (default)  | openai_whisper | fake                           │
│     TTS:  elevenlabs (default)| openai_tts     | fake                           │
│  db:      SQLAlchemy 2 (SQLite dev / Postgres prod) — users, usage, plans,      │
│           shared walkthroughs. NEVER screenshots.                               │
│  prompts: backend/prompts/*.md (versioned)                                      │
└─────────────────────────────────────────────────────────────────────────────────┘
```

### Ask flow (Phase 3)
1. Hotkey down → Rust starts mic capture, shows capture indicator.
2. Hotkey up → Rust grabs screenshot of the monitor under the cursor + UI element list of
   the foreground window (unless blocklisted / password field focused).
3. App POSTs multipart to `/v1/ask`: `audio` (wav), `screenshot` (jpeg), `context` (JSON:
   elements, screenshot size, monitor info, settings, history).
4. Backend streams Server-Sent Events: `transcript` → `speech_text` (deltas) → `target`
   → `audio` (base64 chunks) → `done` (+ `timings`), or `error`.
5. Rust/TS resolves `target` → real screen rect (element bbox or screenshot-space point
   → screen coords) → overlay flies the pointer and pulses the highlight ring.

### Coordinate model
All UI element rects are stored in **physical screen pixels, top-left origin, virtual
desktop space** (the Windows convention). macOS AX rects (points, top-left of primary
display in Cocoa's flipped global space) are converted to that space at collection
time. The screenshot is scaled to ≤1280 px wide; the LLM's `x,y` are in screenshot
pixels and are mapped back with `geometry::screenshot_to_screen`. The overlay converts
screen pixels → its own logical (CSS) pixels using its monitor's scale factor.

### Event schema (SSE, `event:` name + JSON `data:`)
| event        | data                                                        |
|--------------|-------------------------------------------------------------|
| `transcript` | `{ "text": str }`                                           |
| `speech_text`| `{ "delta": str }`                                          |
| `target`     | `{ "element_id": str } \| { "x": int, "y": int } \| null`, `action_hint` |
| `audio`      | `{ "seq": int, "mime": "audio/mpeg", "b64": str }`          |
| `done`       | `{ "timings": {stage: ms}, "usage": {...} }`                |
| `error`      | `{ "code": str, "message": str }`                           |

---

## 2. Folder structure

```
nudgy/
  app/                      Tauri + React
    src/
      windows/              main/, overlay/ entry components
      components/           shared UI
      features/             settings, dashboard, tutor, walkthroughs, onboarding, debug
      lib/                  api client, sse parser, tauri bridge, geometry helpers
      i18n/                 index.ts, locales/en.json
      stores/               zustand stores
    src-tauri/
      src/
        main.rs lib.rs      app bootstrap, tray, commands registry
        settings.rs         persisted settings
        geometry.rs         coordinate conversion (+ unit tests)
        capture/            screenshot (xcap)
        audio/              mic (cpal)
        uitree/             mod.rs (trait), windows.rs, macos.rs, stub.rs
        overlay.rs          overlay windows per monitor
        privacy.rs          blocklist, secure-field detection
        store/              SQLite (rusqlite)
      tauri.conf.json  capabilities/
  backend/
    app/
      main.py config.py deps.py
      routers/  providers/  services/  models/  schemas/
    prompts/  talk.md lesson_plan.md verify_step.md walkthrough_clean.md
    config/   plans.yaml languages.yaml
    tests/
    pyproject.toml
  docs/        privacy-policy.md, architecture.md
  scripts/     smoke_test.py, fixtures/
  PLAN.md DECISIONS.md CLAUDE.md TESTING.md README.md .env.example
```

---

## 3. Phase checklist

Legend: `[x]` done & verified · `[~]` implemented, needs verification on real
Windows/macOS hardware (the dev container is Linux) · `[ ]` not started.

### Phase 0 — Planning
- [x] Read the brief; write `PLAN.md`, `DECISIONS.md`, `CLAUDE.md`
- [x] `.gitignore`, `.env.example`

### Phase 1 — Skeleton
- [x] Scaffold Tauri v2 + React + Vite + TS + Tailwind in `app/`
- [~] Tray / menu-bar icon with Open, Pause, Settings, Quit; app starts hidden in tray
- [x] Settings model (Rust, persisted JSON in app config dir) + Tauri commands get/set
- [x] Settings UI: backend URL, voice on/off, voice choice, hotkey, response length, language
- [x] i18n via `react-i18next`, `en.json` only; language list from backend config
- [x] FastAPI backend: `/health`, `/v1/config` (languages, voices), config via env, pytest
- [x] Health indicator in settings (green/red)
- [~] **Done when:** app starts in tray, settings persist, health check shows green
  (verified on Linux/Xvfb + unit tests; Windows/macOS tray per `TESTING.md`)

### Phase 2 — Overlay + companion
- [x] One transparent, borderless, always-on-top, click-through overlay per monitor (rebuilt on layout change)
- [x] Cursor position polling in Rust → emitted to the overlay of the monitor under it
- [x] Companion character (idle/listening/thinking/talking/pointing; bounce, blink, nudge)
- [x] Pointer arc animation + highlight ring around a bbox
- [x] `geometry.rs` with unit tests (DPI 100/125/150%, Retina, dual monitor, negative offsets, macOS flip)
- [x] Debug menu: "Point at screen center" (tray → Debug; or `NUDGY_DEBUG_POINT=1`)
- [~] **Done when:** debug pointing lands precisely at all scalings / monitor setups
  (verified pixel-exact on Linux/Xvfb 1600×900 via screenshot; code type-checks for Windows + macOS;
  real-hardware matrix in `TESTING.md`)

### Phase 3 — Talk mode
- [x] Global push-to-talk hotkey (hold) + double-tap → text input (decision logic unit-tested)
- [x] Mic capture (cpal) → 16 kHz WAV; screenshot (xcap) → JPEG ≤1280px @80% (captured on key-down)
- [~] UI tree: Windows UIA impl (cached `find_all`), macOS AX impl (depth-first walk), Linux stub; cap 300, prune
  (both type-check against the real target APIs; need hardware runs)
- [x] Backend provider interfaces + registry; Anthropic, Deepgram, Whisper, ElevenLabs, OpenAI TTS, fakes
- [x] `/v1/ask` pipeline with SSE, per-sentence TTS, JSON parse → repair retry → speech-only fallback
- [x] `prompts/talk.md` (+ `repair_json.md`)
- [x] Overlay: live captions, ordered audio playback, pointer to target, friendly error captions
- [x] `scripts/smoke_test.py` against saved screenshot + audio (`scripts/fixtures/`)
- [~] **Done when:** "how do I change the font?" works in Notepad/TextEdit, Chrome, Excel
  (verified end to end on Linux/Xvfb with typed input + fake providers, and via the smoke test;
  real vendors and real apps need keys + Windows/macOS — see `TESTING.md`)

### Phase 4 — Tutor mode
- [x] `/v1/lessons/plan` (`prompts/lesson_plan.md`), `/v1/lessons/verify` (`prompts/verify_step.md`),
      `/v1/lessons/locate` (`prompts/locate.md`), `/v1/speak`; talk prompt v2 returns lesson intents
- [x] Lesson runner state machine (`app/src/features/tutor/tutor.ts`, 8 unit tests): instruct →
      wait for activity/"done" → verify → praise | hint 1 verbal / 2 point / 3 point + why; "show me", "skip", "stop"
- [x] Input activity detection (device_query; reports *that* input happened, never what)
- [x] Local SQLite (rusqlite, migrations): skills, lessons, steps, attempts, hints, mistakes, durations
- [x] Overlay lesson panel (progress, Done / Show me / Skip / Stop) with click-through carve-out
- [x] Start from Home tab, suggestions, or by saying "teach me…"
- [~] **Done when:** 5-step Excel lesson (SUM + currency) runs with verification and hints
  (ran end to end on Linux/Xvfb with fake providers: typed "teach me…", clicked Done through all
  5 steps with a hint on each, lesson + steps + mistakes recorded in SQLite; real Excel run pending)

### Phase 5 — Learning memory
- [x] Skills dashboard (per-app cards with % mastery, lesson count, due badge; recent lessons; weak spots)
- [x] SM-2 scheduler (`store/reviews.rs`): lessons graded 0–5 from hints/skips/abandonment
- [x] Review nudges: companion toast every ≤4 h when a skill is due; never while paused, in a lesson,
      snoozed, or over a full-screen app (UIA/AX check); "Later" snoozes 4 h, ignoring auto-snoozes
- [x] Review = quiz replay of the stored plan (no pointing until hint level 2)
- [~] **Done when:** lessons update dashboard + schedule; a due review can be run
  (verified on Linux/Xvfb: completed lesson → skill card + review due → "Review now" replays the plan
  without planning or locating; full-screen suppression needs hardware)

### Phase 6 — Record & Replay
- [ ] Recorder: clicks/keys + element info + per-step screenshot + notes (local only)
- [ ] `/v1/walkthroughs/clean` (`prompts/walkthrough_clean.md`)
- [ ] `.nudgy` JSON export/import; share links via backend (no screenshots uploaded unless user opts in per walkthrough)
- [ ] Player = Tutor-mode lesson with element matching by role+name (fuzzy), coords as last resort
- [ ] **Done when:** recorded on one machine, replays on another (incl. Win ↔ macOS in Chrome)

### Phase 7 — Accounts, limits, billing
- [ ] Magic-link email, Google, Apple sign-in → JWT; app deep link `nudgy://auth`
- [ ] Plans in `config/plans.yaml`; per-request usage metering + limits
- [ ] Stripe Checkout + webhooks (signature verified); student coupon
- [ ] Team plan: org + shared walkthrough library
- [ ] **Done when:** signup → hit free limit → pay (test mode) → auto-upgrade

### Phase 8 — Privacy & safety
- [ ] Capture only while hotkey held / step verifying (enforced in Rust)
- [ ] Screenshots processed in memory only; metadata-only logging (enforced + tested)
- [ ] App/window blocklist + password-field auto-skip
- [ ] Visible capture indicator (overlay + tray icon state)
- [ ] Privacy page in settings; "Delete my data"; `/v1/me/export`, `DELETE /v1/me`
- [ ] `docs/privacy-policy.md` draft

### Phase 9 — Polish & release
- [ ] First-run onboarding (Nudgy teaches Nudgy) + permission walkthrough (macOS: mic, screen recording, accessibility)
- [ ] Friendly error states (no mic, offline, backend down, provider error, permissions)
- [ ] Debug panel with per-stage timings; target first audio ≤2.5 s
- [ ] Signed installers (MSI/NSIS, notarized DMG) via CI + Tauri updater
- [ ] README with setup, env vars, run, build, architecture diagram
- [ ] `TESTING.md` manual checklist

---

## 4. Verification limits of the dev environment

Development happens in a Linux container. Everything that can be verified here will be
(backend tests, Rust unit tests, TypeScript build, `cargo check` of the shared code).
OS-specific behaviour — Windows UIA, macOS AX, overlay click-through, DPI scaling,
tray on real desktops, signing — compiles behind `cfg(target_os)` and is marked `[~]`
until checked on real hardware using `TESTING.md`.
