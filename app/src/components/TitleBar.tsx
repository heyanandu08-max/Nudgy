import { useEffect, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { useTranslation } from "react-i18next";
import logo from "../assets/logo.svg";
import { useHealth } from "../features/settings/useHealth";
import { useSettings } from "../stores/settings";
import { Hotkey, StatusDot } from "./ui";

export interface Tab {
  id: string;
  labelKey: string;
}

/** 46px paper title bar: logo · tabs · status, hotkey keycaps, avatar. Native window controls stay native. */
export function TitleBar({ tabs, active, onChange, onAccount }: { tabs: Tab[]; active: string; onChange: (id: string) => void; onAccount: () => void }) {
  const { t } = useTranslation();
  const { settings } = useSettings();
  const { health } = useHealth(settings.backendUrl);
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    if (!isTauri()) return;
    const load = () => invoke<{ email: string } | null>("auth_state").then((s) => setEmail(s?.email || null)).catch(() => {});
    load();
    const off = listen("auth-changed", load);
    return () => void off.then((f) => f());
  }, []);

  const status = settings.paused
    ? { tone: "wait" as const, text: t("titlebar.paused") }
    : health.state === "ok"
      ? { tone: "good" as const, text: t("titlebar.ready") }
      : health.state === "down"
        ? { tone: "bad" as const, text: t("titlebar.offline") }
        : { tone: "wait" as const, text: t("titlebar.checking") };

  return (
    <header className="flex h-[46px] shrink-0 items-center border-b border-line bg-paper px-4">
      <img src={logo} alt={t("app.name")} className="h-[22px]" />
      <nav className="ml-7 flex gap-1" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={tab.id === active}
            onClick={() => onChange(tab.id)}
            className={`rounded-lg px-3 py-1.5 text-[13px] ${
              tab.id === active ? "border border-line-2 bg-white text-ink shadow-[0_1px_0_rgba(0,0,0,.04)]" : "border border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {t(tab.labelKey)}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center gap-2.5 text-xs text-ink-2">
        <StatusDot tone={status.tone} />
        <span>{status.text} ·</span>
        <Hotkey accelerator={settings.hotkey} />
        <button
          type="button"
          onClick={onAccount}
          aria-label={t("titlebar.account")}
          className="ml-1 grid h-7 w-7 place-items-center rounded-full bg-ink text-xs font-semibold text-white"
        >
          {(email?.[0] ?? "·").toUpperCase()}
        </button>
      </div>
    </header>
  );
}
