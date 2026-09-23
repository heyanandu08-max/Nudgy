import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Shell, type Tab } from "./components/Shell";
import { AskBox } from "./features/ask/AskBox";
import { HomePage } from "./features/home/HomePage";
import { SettingsPage } from "./features/settings/SettingsPage";
import { WalkthroughsPage } from "./features/walkthroughs/WalkthroughsPage";
import { getTutor } from "./features/tutor/host";
import { finishRecording } from "./features/walkthroughs/recording";
import type { Settings } from "./lib/settings";
import { useSettings } from "./stores/settings";

const TABS: Tab[] = [
  { id: "home", labelKey: "nav.home", render: () => <HomePage /> },
  { id: "walkthroughs", labelKey: "nav.walkthroughs", render: () => <WalkthroughsPage /> },
  { id: "settings", labelKey: "nav.settings", render: () => <SettingsPage /> },
];

export default function App() {
  if (window.location.hash === "#ask") return <AskBox />;
  return <MainWindow />;
}

function MainWindow() {
  const { loaded, load, replace } = useSettings();
  const [tab, setTab] = useState("home");

  useEffect(() => {
    load();
    if (!isTauri()) return;
    getTutor(); // the main window hosts the lesson runner, even while hidden
    const subs = [
      // The tray's "Pause" item changes settings from Rust; keep the UI in sync.
      listen<Settings>("settings-changed", (e) => replace(e.payload)),
      listen<string>("navigate", (e) => setTab(e.payload)),
      listen("recorder-stop", () => void finishRecording(setTab)),
    ];
    return () => subs.forEach((p) => p.then((f) => f()));
  }, [load, replace]);

  if (!loaded) return null;
  return <Shell tabs={TABS} active={tab} onChange={setTab} />;
}
