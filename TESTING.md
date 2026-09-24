# Manual test checklist

Automated tests cover the backend and Rust logic. Everything below needs real
Windows/macOS hardware. Record OS version, scaling and monitor setup for each run.

## Phase 1 — Skeleton
| Check | Win 10/11 | macOS 13+ |
|-------|-----------|-----------|
| App launches with no window; tray / menu-bar icon appears | | |
| No Dock icon on macOS | – | |
| Tray: Open and Settings… show the settings window | | |
| Tray: Pause toggles its checkmark; settings window shows the "paused" note | | |
| Closing the settings window hides it; app keeps running | | |
| Tray: Quit exits the process | | |
| Change every setting, Save, quit, relaunch → values persisted | | |
| Backend running → green badge with version; stop backend → red within 15 s; "Check again" works | | |
| Voice list populates from the backend | | |

## Phase 2 — Overlay + companion
Trigger pointing from the tray (**Debug → Point at screen center**) or launch with
`NUDGY_DEBUG_POINT=1` (fires ~4 s after start on the monitor under the cursor).

| Check | Win 100% | Win 125% | Win 150% | Win dual (mixed DPI) | Mac Retina | Mac + external |
|-------|----------|----------|----------|----------------------|------------|----------------|
| Companion follows the cursor with slight lag, bounces and blinks | | | | | | |
| Companion moves to the other monitor when the cursor does | | | | | | |
| Clicks and scrolls pass through the overlay to apps underneath | | | | | | |
| Overlay does not appear in the taskbar / Alt-Tab / Mission Control | | | | | | |
| Debug point: arrow flies on an upward arc, tip lands on the exact center pixel | | | | | | |
| Highlight ring is centered on the target and pulses, fades after ~6 s | | | | | | |
| Monitor with negative coordinates (left of / above primary) | | | | | | |
| Plug/unplug a monitor → overlays rebuilt within ~2 s | | | | | | |
| Change scaling while running → overlays rebuilt, pointing still exact | | | | | | |

## Phase 3 — Talk mode
Backend with real keys in `.env` (`NUDGY_LLM_PROVIDER=anthropic`, `NUDGY_STT_PROVIDER=deepgram`,
`NUDGY_TTS_PROVIDER=elevenlabs`). First run `python scripts/smoke_test.py --save-audio /tmp/nudgy`
and listen to the clips.

| Check | Win | Mac |
|-------|-----|-----|
| Hold hotkey → companion shows "listening" ring; release → "thinking" dots | | |
| Tap once quickly → nothing is sent | | |
| Double-tap → text box under the cursor; Enter sends, Esc closes | | |
| Notepad / TextEdit: "How do I change the font?" → points at Format/Font menu, speaks correct steps | | |
| Chrome: "How do I open a new incognito window?" → points at the ⋮ menu | | |
| Excel: "How do I make this bold?" → points at the Bold button | | |
| Captions stream while speaking; audio sentences play in order without gaps > 0.5 s | | |
| First audio within ~2.5 s of release (Debug panel timings) | | |
| No mic / mic denied → friendly caption, no crash | | |
| Backend stopped → "can't reach my server" caption | | |
| Password field focused → caption says screen was skipped; answer still arrives | | |
| macOS without Accessibility permission → still answers (points by pixel) | | |

## Phase 4 — Tutor mode
| Check | Win | Mac |
|-------|-----|-----|
| Home → "Add up a column and format it as currency in Excel" starts a lesson; panel appears on the cursor's monitor | | |
| Hold hotkey: "teach me to make a bulleted list in Word" starts a lesson | | |
| Each step is spoken, captioned, and the pointer lands on the right control | | |
| Doing the step (click/typing, then pausing ~1.5 s) advances without saying anything | | |
| Wrong action → quiet the first time, then hint 1 (verbal) → 2 (points) → 3 (points + why) | | |
| "Show me" explains + points; "Skip" moves on; "Stop" ends and says goodbye | | |
| Saying "done" / "skip" / "show me" by voice works like the buttons | | |
| Panel buttons are clickable; everything else on screen stays click-through | | |
| Completed lesson appears in the local DB (`nudgy.db`: lessons, lesson_steps, mistakes) | | |
| macOS without Accessibility permission: activity detection off → learner uses Done | – | |

## Phase 5 — Learning memory
| Check | Win | Mac |
|-------|-----|-----|
| After a lesson, Home shows the skill card (app, name, % mastered, lessons) and the lesson under Recent | | |
| Steps that needed hints/skips show under Weak spots | | |
| Set a review due (or wait a day) → within ~10 min a "Quick review?" card appears bottom-right | | |
| No card while a full-screen video/game/slideshow is in front | | |
| "Later" hides it for 4 h; ignoring it auto-snoozes | | |
| "Let's do it" / "Review now" runs the quiz: no pointing until you ask or fail twice | | |
| Finishing the review updates % mastered and the next review date | | |

## Phase 6 — Record & Replay
| Check | Win | Mac |
|-------|-----|-----|
| Walkthroughs → Record new: main window hides, red "Recording" bar appears top-center | | |
| Clicks in Chrome/Word are logged with the right element names (Show steps after stopping) | | |
| Typing is captured as whole words; Ctrl/Cmd shortcuts appear as "Press Control plus S" | | |
| Typing into a password field shows only "type your password", never the text | | |
| Clicking the recorder bar itself is not recorded | | |
| Hold hotkey during recording → spoken note attaches to the last step; "Add note" box too | | |
| Stop → spoken "Turning your recording…" → walkthrough appears with title + clean steps + thumbnails | | |
| Export (with/without screenshots) → .nudgy file opens in a text editor as JSON | | |
| Import file on another machine → Play → pointer finds the same buttons by name | | |
| Share → link copied; opening it in a browser shows the steps and "Open in Nudgy" | | |
| Import the link on a **Mac** that was recorded on **Windows** (Chrome): steps match and point correctly | | |

## Phase 7 — Accounts, limits, billing
Backend with Stripe **test-mode** keys and `stripe listen --forward-to localhost:8787/v1/billing/webhook`.

| Check | Win | Mac |
|-------|-----|-----|
| Account → email link → click it in the mail → browser page opens Nudgy → Account shows signed in | | |
| Continue with Google / Apple → same hand-off | | |
| Relaunch after a day → still signed in (token rotated) | | |
| Free plan: 31st question → caption says the free questions are used up | | |
| Choose Pro → Stripe Checkout (card 4242 4242 4242 4242) → back in Nudgy, plan shows Pro within seconds | | |
| Student discount applies the coupon in Checkout | | |
| Manage billing → cancel → plan returns to Free when the period ends | | |
| Team (3 seats) → invite 2 people → they sign in with those emails → appear as members; 4th invite refused | | |
| Share a walkthrough with "Share with my team" → teammates see it under Team library → Import | | |

## Phase 8 — Privacy & safety

| Check | Win | Mac |
|-------|-----|-----|
| Hold the hotkey → "looking at your screen" tag at top right of the screen under the cursor, gone ~1 s after | | |
| Tray/menu-bar tooltip reads "Nudgy · looking at your screen" while capturing | | |
| Focus a password field (browser login) → ask → answer says it didn't look; no screenshot in the request | | |
| 1Password/Bitwarden in front → same | | |
| Add "Notes" to the list → ask over Notes → withheld; remove it → works again | | |
| Idle for 10 min with network monitor open → no requests to the Nudgy server | | |
| Settings → Privacy → Export → JSON contains lessons, asks, walkthroughs, settings (+ account if signed in) | | |
| Delete learning history → Home shows the empty state | | |
| Delete my account (signed in, Pro test subscription) → Stripe dashboard shows it cancelled; signed out | | |
| Server log after a session: no base64, no question text | | |
