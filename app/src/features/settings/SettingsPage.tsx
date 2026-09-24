import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { AccountPage } from "../account/AccountPage";
import { AboutSection } from "./AboutSection";
import { CursorSection } from "./CursorSection";
import { HotkeySection } from "./HotkeySection";
import { PrivacySection } from "./PrivacySection";

export type SettingsSection = "cursor" | "hotkey" | "privacy" | "account" | "about";
const SECTIONS: SettingsSection[] = ["cursor", "hotkey", "privacy", "account", "about"];

export function SettingsPage({ section: initial = "cursor" }: { section?: SettingsSection }) {
  const { t } = useTranslation();
  const [section, setSection] = useState<SettingsSection>(initial);
  useEffect(() => setSection(initial), [initial]);

  return (
    <div className="grid gap-10 px-14 pt-9 pb-10 min-[900px]:grid-cols-[200px_1fr]">
      <nav aria-label={t("nav.settings")} className="flex gap-1 min-[900px]:flex-col">
        {SECTIONS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSection(s)}
            aria-current={s === section ? "page" : undefined}
            className={`rounded-lg px-3 py-2 text-left text-[13px] ${
              s === section ? "border border-line bg-paper font-medium text-ink" : "border border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {t(`settings.sections.${s}`)}
          </button>
        ))}
      </nav>
      <div className="min-w-0">
        {section === "cursor" && <CursorSection />}
        {section === "hotkey" && <HotkeySection />}
        {section === "privacy" && <PrivacySection />}
        {section === "account" && <AccountPage />}
        {section === "about" && <AboutSection />}
      </div>
    </div>
  );
}
