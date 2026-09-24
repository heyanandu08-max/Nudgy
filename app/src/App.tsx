import { useEffect, useState } from "react";
import { isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { Footer } from "./components/Footer";
import { TitleBar, type Tab } from "./components/TitleBar";
import { AskBox } from "./features/ask/AskBox";
import { Onboarding } from "./features/onboarding/Onboarding";
import { HomePage, startRecording } from "./features/home/HomePage";
import { SettingsPage, type SettingsSection } from "./features/settings/SettingsPage";
import { getTutor } from "./features/tutor/host";
import { finishRecording } from "./features/walkthroughs/recording";
import { WalkthroughsPage } from "./features/walkthroughs/WalkthroughsPage";
import type { Settings } from "./lib/settings";
import { useSettings } from "./stores/settings";

const TABS: Tab[] = [
  { id: "home", labelKey: "nav.home" },
  { id: "walkthroughs", labelKey: "nav.walkthroughs" },
  { id: "settings", labelKey: "nav.settings" },
];

export default function App() {
  if (window.location.hash === "#ask") return <AskBox />;
  return <MainWindow />;
}

function MainWindow() {
  const { settings, loaded, load, replace } = useSettings();
  const [tab, setTab] = useState("home");
  const [section, setSection] = useState<SettingsSection>("cursor");

  // "account", "privacy"… open Settings on that section; others are tabs.
  const navigate = (to: string) => {
    if (["cursor", "hotkey", "privacy", "account", "about"].includes(to)) {
      setSection(to as SettingsSection);
      setTab("settings");
    } else {
      setTab(to);
    }
  };

  useEffect(() => {
    void load();
    if (!isTauri()) return;
    getTutor(); // the main window hosts the lesson runner, even while hidden
    const subs = [
      listen<Settings>("settings-changed", (e) => replace(e.payload)),
      listen<string>("navigate", (e) => navigate(e.payload)),
      listen("recorder-stop", () => void finishRecording(navigate)),
    ];
    return () => subs.forEach((p) => p.then((f) => f()));
  }, [load, replace]);

  if (!loaded) return null;
  if (!settings.onboarded) return <Onboarding />;
  return (
    <div className="flex h-full min-w-[760px] flex-col bg-bg">
      <TitleBar tabs={TABS} active={tab} onChange={setTab} onAccount={() => navigate("account")} />
      <main className="flex-1 overflow-auto">
        {tab === "home" && <HomePage onRecord={() => void startRecording()} />}
        {tab === "walkthroughs" && <WalkthroughsPage />}
        {tab === "settings" && <SettingsPage section={section} />}
      </main>
      <Footer />
    </div>
  );
}
