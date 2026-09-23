import { useEffect } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { SettingsPage } from "./features/settings/SettingsPage";
import type { Settings } from "./lib/settings";
import { useSettings } from "./stores/settings";

export default function App() {
  const { loaded, load, replace } = useSettings();

  useEffect(() => {
    load();
    if (!isTauri()) return;
    // The tray's "Pause" item changes settings from Rust; keep the UI in sync.
    const unlisten = listen<Settings>("settings-changed", (e) => replace(e.payload));
    return () => {
      unlisten.then((f) => f());
    };
  }, [load, replace]);

  if (!loaded) return null;
  return <SettingsPage />;
}
