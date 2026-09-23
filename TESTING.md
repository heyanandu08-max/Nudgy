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
