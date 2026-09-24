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
