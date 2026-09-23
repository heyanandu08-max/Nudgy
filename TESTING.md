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
